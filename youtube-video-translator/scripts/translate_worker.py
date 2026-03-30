import sys
import os
import re
import json
from datetime import datetime, timedelta

def srt_time_to_seconds(srt_time):
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

def translate_batch(segments, glossary, model_proxy_func):
    """
    发送一批段落给 LLM 翻译，并强制要求返回符合 CPS 标准的精简中文。
    """
    prompt = f"""你是一名专业的医学视频翻译专家。请翻译以下由英文 SRT 拆分出的片段。

【核心指令】
1. 必须保留原有的序号和时间轴。
2. 中文翻译必须极其精炼，严禁直译长句。
3. 视觉控制：单行中文字数建议在 10-15 字之间。
4. 格式：
序号
时间戳
英文原文\\N中文翻译

【术语表应用】
{json.dumps(glossary, ensure_ascii=False, indent=2)}

【待翻译片段】
{segments}
"""
    # 模拟调用逻辑，实际由外部 Agent 填入翻译结果
    return prompt

def check_cps(srt_block, max_cps=15):
    lines = srt_block.strip().split('\n')
    if len(lines) < 3: return True

    time_match = re.search(r'(\d+:\d+:\d+,\d+) --> (\d+:\d+:\d+,\d+)', lines[1])
    if not time_match: return True

    start = srt_time_to_seconds(time_match.group(1))
    end = srt_time_to_seconds(time_match.group(2))
    duration = max(0.5, end - start)

    # 提取中文部分 (假设在 \N 之后)
    text = lines[2]
    zh_text = text.split('\\N')[-1] if '\\N' in text else text
    zh_len = len(re.sub(r'[^\u4e00-\u9fa5]', '', zh_text)) # 仅计算汉字

    cps = zh_len / duration
    if cps > max_cps:
        print(f"警告：序号 {lines[0]} CPS 过高 ({cps:.1f})，中文字数: {zh_len}, 时长: {duration:.1f}s")
        return False
    return True

if __name__ == "__main__":
    print("翻译执行官已就绪。请调用 Agent 进行批量翻译，并使用 check_cps 函数进行实时校验。")
