import sys
import os
import re
import json
from datetime import datetime


TRANSLATION_PROMPT_TEMPLATE = '''你是专业字幕翻译器。请把下面 SRT 批次翻译为简体中文。

硬性要求：
1) 保留每个字幕块的序号与时间轴原样不变。
2) 每个块只输出中文译文，不要保留英文原文，不要输出双语格式。
3) 不要删块、并块、拆块。
4) 不要输出任何解释，只输出合法 SRT 内容。
{glossary_section}{context_section}
待翻译批次：
{batch_content}
'''

TIME_RE = re.compile(r'(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})')


def normalize_timecode(ts):
    return ts.replace('.', ',')


def srt_time_to_seconds(srt_time):
    srt_time = normalize_timecode(srt_time)
    h, m, s_ms = srt_time.split(':')
    s, ms = s_ms.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def load_glossary(path=None):
    """
    加载术语表。支持两种格式：
    1) en -> zh (显式映射)
    2) term1, term2 (仅提示词)
    """
    # 默认路径：references/terms.txt
    if path is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base_dir, "references", "terms.txt")

    glossary = {}
    plain_terms = []

    if not path or not os.path.exists(path):
        return glossary, plain_terms

    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if '->' in line:
                parts = line.split('->', 1)
                en, zh = parts[0].strip(), parts[1].strip()
                glossary[en] = zh
            else:
                # 处理逗号分隔的术语
                for t in line.split(','):
                    t = t.strip()
                    if t:
                        plain_terms.append(t)

    return glossary, plain_terms


def parse_srt(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read().strip()

    if not content:
        return [], [f'{path}: 文件为空']

    blocks = re.split(r'\n\s*\n', content)
    parsed = []
    errors = []

    for pos, block in enumerate(blocks, start=1):
        lines = [line.rstrip('\r') for line in block.split('\n') if line.strip() != '']
        if len(lines) < 3:
            errors.append(f'块 {pos}: 行数不足(至少3行)')
            continue

        try:
            idx = int(lines[0].strip())
        except ValueError:
            errors.append(f'块 {pos}: 序号非法: {lines[0]!r}')
            continue

        tm = TIME_RE.search(lines[1])
        if not tm:
            errors.append(f'块 {pos}: 时间轴格式非法: {lines[1]!r}')
            continue

        text = '\n'.join(lines[2:]).strip()
        parsed.append(
            {
                'pos': pos,
                'index': idx,
                'start': normalize_timecode(tm.group(1)),
                'end': normalize_timecode(tm.group(2)),
                'text': text,
            }
        )

    return parsed, errors


def extract_zh_text(text):
    parts = [part.strip() for part in text.split('\\N') if part.strip()]
    if not parts:
        return ''

    for part in parts:
        if re.search(r'[\u4e00-\u9fff]', part):
            return part

    return parts[-1]


def is_likely_untranslated(text):
    zh_text = extract_zh_text(text)
    has_cjk = bool(re.search(r'[\u4e00-\u9fff]', zh_text))
    has_letters = bool(re.search(r'[A-Za-z]', zh_text))
    return (not has_cjk) and has_letters


def check_cps(srt_block, max_cps=15):
    lines = srt_block.strip().split('\n')
    if len(lines) < 3:
        return True, 0.0

    time_match = TIME_RE.search(lines[1])
    if not time_match:
        return True, 0.0

    start = srt_time_to_seconds(time_match.group(1))
    end = srt_time_to_seconds(time_match.group(2))
    duration = max(0.5, end - start)

    text = ' '.join(lines[2:])
    zh_text = extract_zh_text(text)
    zh_len = len(re.sub(r'[^\u4e00-\u9fff]', '', zh_text))

    cps = zh_len / duration
    return cps <= max_cps, cps


def prepare_batches(srt_path, batch_size=50):
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()

    blocks = re.split(r'\n\s*\n', content)
    batches = []
    for i in range(0, len(blocks), batch_size):
        batch = blocks[i:i + batch_size]
        batches.append('\n\n'.join(batch))
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


def generate_prompt_for_batch(batch_file, output_prompt_path=None, context_file=None):
    with open(batch_file, 'r', encoding='utf-8') as f:
        batch_content = f.read().strip()

    glossary, plain_terms = load_glossary()
    glossary_section = ""
    if glossary or plain_terms:
        glossary_section = "\n参考术语 (Glossary/Reference)：\n"
        if glossary:
            for en, zh in glossary.items():
                glossary_section += f"- {en} -> {zh}\n"
        if plain_terms:
            glossary_section += f"- {', '.join(plain_terms)}\n"

    context_section = ""
    if context_file and os.path.exists(context_file):
        try:
            with open(context_file, 'r', encoding='utf-8') as f:
                context_content = f.read().strip()
                if context_content:
                    # 只取最后几块作为上下文，避免超出 token 限制
                    context_blocks = re.split(r'\n\s*\n', context_content)
                    last_blocks = context_blocks[-5:] # 取最后 5 块
                    context_section = "\n前文参考 (Context from previous blocks):\n"
                    context_section += "\n\n".join(last_blocks).strip() + "\n"
        except Exception as e:
            print(f"警告: 读取上下文文件失败: {e}")

    prompt = TRANSLATION_PROMPT_TEMPLATE.format(
        glossary_section=glossary_section,
        context_section=context_section,
        batch_content=batch_content
    )
    if output_prompt_path:
        with open(output_prompt_path, 'w', encoding='utf-8') as f:
            f.write(prompt)
    return prompt


def detect_batch_completeness(translated_dir, manifest_path=None):
    if manifest_path is None:
        candidate = os.path.join(translated_dir, 'translation_manifest.json')
        manifest_path = candidate if os.path.exists(candidate) else None

    files = []
    for name in os.listdir(translated_dir):
        m = re.fullmatch(r'batch_(\d+)\.translated\.srt', name)
        if m:
            files.append(int(m.group(1)))

    found = sorted(files)
    if not found:
        return {'ok': False, 'expected': [], 'found': [], 'missing': ['all']}

    expected = list(range(1, max(found) + 1))
    if manifest_path and os.path.exists(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        total = int(manifest.get('total_batches', max(found)))
        expected = list(range(1, total + 1))

    missing = [i for i in expected if i not in found]
    extra = [i for i in found if i not in expected]

    return {
        'ok': not missing and not extra,
        'expected': expected,
        'found': found,
        'missing': missing,
        'extra': extra,
    }


def merge_translated_batches(translated_dir, output_srt_path, manifest_path=None):
    completeness = detect_batch_completeness(translated_dir, manifest_path)
    if not completeness['found']:
        raise RuntimeError('未找到 batch_*.translated.srt 文件，无法合并。')
    if completeness['missing'] or completeness['extra']:
        raise RuntimeError(
            f"批次不完整: missing={completeness['missing']}, extra={completeness['extra']}"
        )

    merged_blocks = []
    for idx in completeness['expected']:
        path = os.path.join(translated_dir, f'batch_{idx}.translated.srt')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if content:
                merged_blocks.append(content)

    with open(output_srt_path, 'w', encoding='utf-8') as out:
        out.write('\n\n'.join(merged_blocks) + '\n')

    return len(completeness['expected'])


def verify_translated_srt(original_path, translated_path, glossary_path=None, max_cps=15):
    orig_blocks, orig_errors = parse_srt(original_path)
    trans_blocks, trans_errors = parse_srt(translated_path)
    glossary, plain_terms = load_glossary(glossary_path)

    issues = []

    for err in orig_errors:
        issues.append(f'[原文格式错误] {err}')
    for err in trans_errors:
        issues.append(f'[译文格式错误] {err}')

    if len(orig_blocks) != len(trans_blocks):
        issues.append(
            f'[数量不匹配] 原文块数={len(orig_blocks)}, 译文块数={len(trans_blocks)}'
        )

    pair_count = min(len(orig_blocks), len(trans_blocks))
    for i in range(pair_count):
        ob = orig_blocks[i]
        tb = trans_blocks[i]

        if ob['index'] != tb['index']:
            issues.append(
                f"[序号不一致] 第{i+1}对: 原={ob['index']} 译={tb['index']}"
            )

        if ob['start'] != tb['start'] or ob['end'] != tb['end']:
            issues.append(
                f"[时间轴不一致] 块{ob['index']}: 原={ob['start']} --> {ob['end']} 译={tb['start']} --> {tb['end']}"
            )

        if not tb['text'].strip():
            issues.append(f"[空翻译] 块{tb['index']} 译文为空")

        if '\\N' in tb['text']:
            issues.append(f"[输出格式错误] 块{tb['index']} 含有双语或 ASS 换行标记 \\N；权威译文应为纯中文 SRT")

        if is_likely_untranslated(tb['text']):
            issues.append(f"[疑似漏翻] 块{tb['index']} 主要为英文/非中文")

        block_text = f"{tb['index']}\n{tb['start']} --> {tb['end']}\n{tb['text']}"
        is_ok, cps = check_cps(block_text, max_cps=max_cps)
        if not is_ok:
            issues.append(f"[CPS过高] 块{tb['index']} CPS={cps:.1f} (阈值 {max_cps})")

        if glossary:
            orig_text_lower = ob['text'].lower()
            zh_text = extract_zh_text(tb['text'])
            for en, zh in glossary.items():
                if en.lower() in orig_text_lower and zh and zh not in zh_text:
                    issues.append(
                        f"[术语不一致] 块{tb['index']}: 检测到术语 {en!r}，期望包含 {zh!r}"
                    )
        if plain_terms:
            orig_text_lower = ob['text'].lower()
            zh_text = extract_zh_text(tb['text'])
            for term in plain_terms:
                if term.lower() in orig_text_lower and term not in zh_text and term.lower() not in zh_text.lower():
                    issues.append(
                        f"[术语可疑] 块{tb['index']}: 原文包含术语 {term!r}，译文中未显式保留，请人工复核"
                    )

    return issues


def verify_all_batches(translated_dir, glossary_path=None, max_cps=15):
    """
    逐批校验：batch_N.txt vs batch_N.translated.srt
    返回 (has_error, reports)
    """
    reports = []
    has_error = False

    originals = []
    for name in os.listdir(translated_dir):
        m = re.fullmatch(r'batch_(\d+)\.txt', name)
        if m:
            originals.append((int(m.group(1)), os.path.join(translated_dir, name)))

    if not originals:
        return True, ['未找到 batch_*.txt，无法执行逐批校验。']

    originals.sort(key=lambda x: x[0])

    for idx, original_path in originals:
        translated_path = os.path.join(translated_dir, f'batch_{idx}.translated.srt')
        if not os.path.exists(translated_path):
            has_error = True
            reports.append(f'[批次缺失] batch_{idx}.translated.srt 不存在')
            continue

        issues = verify_translated_srt(
            original_path,
            translated_path,
            glossary_path=glossary_path,
            max_cps=max_cps,
        )
        if issues:
            has_error = True
            reports.append(f'--- batch_{idx} 校验失败 ---')
            reports.extend(issues)
        else:
            reports.append(f'[OK] batch_{idx} 校验通过')

    return has_error, reports


def print_usage():
    print('Usage: python translate_worker.py [prepare|prompt|merge|verify|verify-batches|check-batches] [args...]')


def _parse_verify_optional_args(args):
    """
    解析 verify / verify-batches 的可选参数。
    兼容：
      1) 旧位置参数: [GlossaryPath可选] [MaxCPS可选]
      2) 新 flag 参数: [--glossary PATH] [--max-cps N]
      3) 仅传 MaxCPS: [15]
    """
    glossary_path = None
    max_cps = 15

    i = 0
    positional = []
    while i < len(args):
        token = args[i]
        if token == '--glossary':
            if i + 1 >= len(args):
                raise ValueError('参数错误: --glossary 需要路径值')
            glossary_path = args[i + 1]
            i += 2
            continue
        if token == '--max-cps':
            if i + 1 >= len(args):
                raise ValueError('参数错误: --max-cps 需要数值')
            max_cps = int(args[i + 1])
            i += 2
            continue
        positional.append(token)
        i += 1

    if positional:
        if len(positional) > 2:
            raise ValueError('参数错误: 可选参数最多 2 个（GlossaryPath, MaxCPS）')
        if len(positional) >= 1:
            first = positional[0]
            if first.isdigit():
                max_cps = int(first)
            else:
                glossary_path = first
        if len(positional) == 2:
            max_cps = int(positional[1])

    return glossary_path, max_cps


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'prepare':
        if len(sys.argv) < 3:
            print('用法: python translate_worker.py prepare [SourceSrtPath] [OutputDir可选] [BatchSize可选]')
            sys.exit(1)
        source_srt = sys.argv[2]
        out_dir = sys.argv[3] if len(sys.argv) >= 4 else '.'
        batch_size = int(sys.argv[4]) if len(sys.argv) >= 5 else 50
        batch_files, manifest_path = write_batches(source_srt, out_dir, batch_size=batch_size)
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

    elif cmd == 'check-batches':
        if len(sys.argv) < 3:
            print('用法: python translate_worker.py check-batches [TranslatedDir] [ManifestPath可选]')
            sys.exit(1)
        translated_dir = sys.argv[2]
        manifest_path = sys.argv[3] if len(sys.argv) >= 4 else None
        result = detect_batch_completeness(translated_dir, manifest_path)
        if result['ok']:
            print('批次完整性检查通过。')
        else:
            print('批次完整性检查失败。')
            print(f"missing: {result['missing']}")
            print(f"extra: {result['extra']}")
            sys.exit(2)

    elif cmd == 'merge':
        if len(sys.argv) < 4:
            print('用法: python translate_worker.py merge [TranslatedDir] [OutputSrtPath] [ManifestPath可选]')
            sys.exit(1)
        translated_dir = sys.argv[2]
        output_srt = sys.argv[3]
        manifest_path = sys.argv[4] if len(sys.argv) >= 5 else None
        count = merge_translated_batches(translated_dir, output_srt, manifest_path)
        print(f'已合并 {count} 个批次到: {output_srt}')

    elif cmd == 'verify':
        if len(sys.argv) < 4:
            print('用法: python translate_worker.py verify [OriginalSrtPath] [TranslatedSrtPath] [GlossaryPath可选] [MaxCPS可选]')
            print('   或: python translate_worker.py verify [Original] [Translated] [--glossary PATH] [--max-cps N]')
            sys.exit(1)
        try:
            glossary_path, max_cps = _parse_verify_optional_args(sys.argv[4:])
        except ValueError as e:
            print(str(e))
            sys.exit(1)
        issues = verify_translated_srt(sys.argv[2], sys.argv[3], glossary_path=glossary_path, max_cps=max_cps)
        if issues:
            print('发现以下问题：')
            for issue in issues:
                print(issue)
            sys.exit(2)
        else:
            print('校验通过：数量/序号/时间轴/CPS/术语一致性正常。')

    elif cmd == 'verify-batches':
        if len(sys.argv) < 3:
            print('用法: python translate_worker.py verify-batches [BatchDir] [GlossaryPath可选] [MaxCPS可选]')
            print('   或: python translate_worker.py verify-batches [BatchDir] [--glossary PATH] [--max-cps N]')
            sys.exit(1)
        batch_dir = sys.argv[2]
        try:
            glossary_path, max_cps = _parse_verify_optional_args(sys.argv[3:])
        except ValueError as e:
            print(str(e))
            sys.exit(1)
        has_error, reports = verify_all_batches(batch_dir, glossary_path=glossary_path, max_cps=max_cps)
        for line in reports:
            print(line)
        if has_error:
            sys.exit(2)
        print('逐批校验全部通过。')

    else:
        print(f'未知命令: {cmd}')
        print_usage()
        sys.exit(1)
