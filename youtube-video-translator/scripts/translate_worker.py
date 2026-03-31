import sys
import os
import re
import json
from datetime import datetime, timedelta

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

def check_cps(srt_block, max_cps=15):
    """
    校验单段 SRT 的 CPS。
    """
    lines = srt_block.strip().split('\n')
    if len(lines) < 3: return True, 0

    time_match = re.search(r'(\d+:\d+:\d+[,.]\d+) --> (\d+:\d+:\d+[,.]\d+)', lines[1])
    if not time_match: return True, 0

    start = srt_time_to_seconds(time_match.group(1))
    end = srt_time_to_seconds(time_match.group(2))
    duration = max(0.5, end - start)

    # 提取文本内容
    text = " ".join(lines[2:])
    # 如果有 \N，取后面部分（中文）
    zh_text = text.split('\\N')[-1] if '\\N' in text else text
    # 过滤掉非中文字符进行计数
    zh_len = len(re.sub(r'[^\u4e00-\u9fa5]', '', zh_text))

    cps = zh_len / duration
    return (cps <= max_cps), cps

def verify_translated_srt(original_path, translated_path):
    """
    验证翻译后的 SRT 是否与原版行数对应，并检查 CPS。
    """
    with open(original_path, 'r', encoding='utf-8') as f:
        orig_blocks = re.split(r'\n\s*\n', f.read().strip())
    
    with open(translated_path, 'r', encoding='utf-8') as f:
        trans_blocks = re.split(r'\n\s*\n', f.read().strip())
    
    if len(orig_blocks) != len(trans_blocks):
        print(f"警告：块数量不匹配！原版: {len(orig_blocks)}, 翻译版: {len(trans_blocks)}")
    
    issues = []
    for i, block in enumerate(trans_blocks):
        is_ok, cps = check_cps(block)
        if not is_ok:
            issues.append(f"块 {i+1} CPS 过高: {cps:.1f}")
    
    return issues

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python translate_worker.py [prepare|verify] [args...]")
        sys.exit(1)
        
    cmd = sys.argv[1]
    if cmd == "prepare":
        batches = prepare_batches(sys.argv[2])
        for i, b in enumerate(batches):
            with open(f"batch_{i+1}.txt", "w", encoding="utf-8") as f:
                f.write(b)
        print(f"已生成 {len(batches)} 个批次文件。")
    elif cmd == "verify":
        issues = verify_translated_srt(sys.argv[2], sys.argv[3])
        if issues:
            print("发现以下问题：")
            for iss in issues: print(iss)
        else:
            print("校验通过，未发现 CPS 异常。")
