import sys
import os
import re
import json
from datetime import datetime, timedelta


TRANSLATION_PROMPT_TEMPLATE = '''你是专业字幕翻译器。请把下面 SRT 批次翻译为中文。

硬性要求：
1) 保留每个字幕块的序号与时间轴原样不变。
2) 每个块可输出单语中文，或双语格式 `英文\\N中文`。
3) 不要删块、并块、拆块。
4) 不要输出任何解释，只输出合法 SRT 内容。

待翻译批次：
{batch_content}
'''


def srt_time_to_seconds(srt_time):
    # Handle both , and . for milliseconds
    srt_time = srt_time.replace('.', ',')
    h, m, s_ms = srt_time.split(':')
    s, ms = s_ms.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def load_glossary(path):
    glossary = {}
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                if '->' in line:
                    en, zh = line.split('->')
                    glossary[en.strip()] = zh.strip()
    return glossary


def prepare_batches(srt_path, batch_size=50):
    """
    将 SRT 文件拆分为多个批次供 Agent 翻译。
    """
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()

    blocks = re.split(r'\n\s*\n', content)
    batches = []
    for i in range(0, len(blocks), batch_size):
        batch = blocks[i:i + batch_size]
        batches.append("\n\n".join(batch))
    return batches


def write_batches(srt_path, output_dir='.', batch_size=50):
    os.makedirs(output_dir, exist_ok=True)
    batches = prepare_batches(srt_path, batch_size=batch_size)
    batch_files = []
    for i, batch in enumerate(batches, start=1):
        path = os.path.join(output_dir, f'batch_{i}.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(batch)
        batch_files.append(path)

    manifest = {
        'source_srt': os.path.abspath(srt_path),
        'batch_size': batch_size,
        'total_batches': len(batch_files),
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'batches': [os.path.abspath(p) for p in batch_files],
    }

    manifest_path = os.path.join(output_dir, 'translation_manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return batch_files, manifest_path


def generate_prompt_for_batch(batch_file, output_prompt_path=None):
    with open(batch_file, 'r', encoding='utf-8') as f:
        batch_content = f.read().strip()

    prompt = TRANSLATION_PROMPT_TEMPLATE.format(batch_content=batch_content)
    if output_prompt_path:
        with open(output_prompt_path, 'w', encoding='utf-8') as f:
            f.write(prompt)
    return prompt


def merge_translated_batches(translated_dir, output_srt_path):
    files = []
    for name in os.listdir(translated_dir):
        m = re.fullmatch(r'batch_(\d+)\.translated\.srt', name)
        if m:
            files.append((int(m.group(1)), os.path.join(translated_dir, name)))

    if not files:
        raise RuntimeError('未找到 batch_*.translated.srt 文件，无法合并。')

    files.sort(key=lambda x: x[0])
    merged_blocks = []
    expected = 1
    for idx, path in files:
        if idx != expected:
            raise RuntimeError(f'批次不连续：期望 batch_{expected}.translated.srt，实际是 batch_{idx}.translated.srt')
        expected += 1
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if content:
                merged_blocks.append(content)

    with open(output_srt_path, 'w', encoding='utf-8') as out:
        out.write('\n\n'.join(merged_blocks) + '\n')

    return len(files)


def check_cps(srt_block, max_cps=15):
    """
    校验单段 SRT 的 CPS。
    """
    lines = srt_block.strip().split('\n')
    if len(lines) < 3:
        return True, 0

    time_match = re.search(r'(\d+:\d+:\d+[,.]\d+) --> (\d+:\d+:\d+[,.]\d+)', lines[1])
    if not time_match:
        return True, 0

    start = srt_time_to_seconds(time_match.group(1))
    end = srt_time_to_seconds(time_match.group(2))
    duration = max(0.5, end - start)

    # 提取文本内容
    text = ' '.join(lines[2:])
    # 如果有 \N，取后面部分（中文）
    zh_text = text.split('\\N')[-1] if '\\N' in text else text
    # 过滤掉非中文字符进行计数
    zh_len = len(re.sub(r'[^\u4e00-\u9fa5]', '', zh_text))

    cps = zh_len / duration
    return cps <= max_cps, cps


def verify_translated_srt(original_path, translated_path):
    """
    验证翻译后的 SRT 是否与原版行数对应，并检查 CPS。
    """
    with open(original_path, 'r', encoding='utf-8') as f:
        orig_blocks = re.split(r'\n\s*\n', f.read().strip())

    with open(translated_path, 'r', encoding='utf-8') as f:
        trans_blocks = re.split(r'\n\s*\n', f.read().strip())

    if len(orig_blocks) != len(trans_blocks):
        print(f'警告：块数量不匹配！原版: {len(orig_blocks)}, 翻译版: {len(trans_blocks)}')

    issues = []
    for i, block in enumerate(trans_blocks):
        is_ok, cps = check_cps(block)
        if not is_ok:
            issues.append(f'块 {i+1} CPS 过高: {cps:.1f}')

    return issues


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python translate_worker.py [prepare|prompt|merge|verify] [args...]')
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == 'prepare':
        if len(sys.argv) < 3:
            print('用法: python translate_worker.py prepare [SourceSrtPath] [OutputDir可选]')
            sys.exit(1)
        source_srt = sys.argv[2]
        out_dir = sys.argv[3] if len(sys.argv) >= 4 else '.'
        batch_files, manifest_path = write_batches(source_srt, out_dir)
        print(f'已生成 {len(batch_files)} 个批次文件。')
        print(f'manifest: {manifest_path}')
    elif cmd == 'prompt':
        if len(sys.argv) < 3:
            print('用法: python translate_worker.py prompt [BatchFile] [OutputPromptPath可选]')
            sys.exit(1)
        batch_file = sys.argv[2]
        output_prompt_path = sys.argv[3] if len(sys.argv) >= 4 else None
        prompt = generate_prompt_for_batch(batch_file, output_prompt_path)
        if output_prompt_path:
            print(f'已写入翻译提示词: {output_prompt_path}')
        else:
            print(prompt)
    elif cmd == 'merge':
        if len(sys.argv) < 4:
            print('用法: python translate_worker.py merge [TranslatedDir] [OutputSrtPath]')
            sys.exit(1)
        translated_dir = sys.argv[2]
        output_srt = sys.argv[3]
        count = merge_translated_batches(translated_dir, output_srt)
        print(f'已合并 {count} 个批次到: {output_srt}')
    elif cmd == 'verify':
        if len(sys.argv) < 4:
            print('用法: python translate_worker.py verify [OriginalSrtPath] [TranslatedSrtPath]')
            sys.exit(1)
        issues = verify_translated_srt(sys.argv[2], sys.argv[3])
        if issues:
            print('发现以下问题：')
            for issue in issues:
                print(issue)
        else:
            print('校验通过，未发现 CPS 异常。')
    else:
        print(f'未知命令: {cmd}')
        print('Usage: python translate_worker.py [prepare|prompt|merge|verify] [args...]')
        sys.exit(1)
