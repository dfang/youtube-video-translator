import sys
import os
import re
import json
from collections import Counter
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = _dev_root
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/core"))

def extract_terms(srt_path, top_n=20):
    """
    从 SRT 文件中提取潜在的术语（专有名词、高频名词）。
    这是一个简单的实现，主要依赖正则匹配连续的大写字母或特定模式。
    """
    if not os.path.exists(srt_path):
        print(f"文件不存在: {srt_path}")
        return []

    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 移除序号和时间轴
    text = re.sub(r'\d+\n\d{2}:\d{2}:\d{2}[,.]\d{3} --> \d{2}:\d{2}:\d{2}[,.]\d{3}\n', '', content)
    
    # 匹配可能的术语：
    # 1. 连续的大写字母（如 AWS, SQL）
    # 2. 首字母大写的单词序列（如 Google Cloud Platform）
    # 3. 包含数字或特殊字符的标识符（如 React18, node.js）
    
    # 模式 1: 首字母大写的单词序列
    proper_nouns = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
    
    # 模式 2: 全大写缩写
    acronyms = re.findall(r'\b[A-Z]{2,}\b', text)
    
    # 合并并计数
    all_candidates = proper_nouns + acronyms
    counter = Counter(all_candidates)
    
    # 过滤掉一些常见的停用词（简单列表）
    stopwords = {'The', 'This', 'That', 'With', 'From', 'They', 'There', 'When', 'What', 'Where', 'Which'}
    filtered_terms = [(term, count) for term, count in counter.most_common(top_n * 2) if term not in stopwords and len(term) > 2]
    
    return filtered_terms[:top_n]

def save_terms_to_file(terms, output_path):
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# 自动提取的潜在术语 (格式: Term -> Translation)\n")
        f.write("# 请手动编辑翻译部分\n\n")
        for term, count in terms:
            f.write(f"{term} -> \n")
    print(f"术语表已保存至: {output_path}，请手动编辑后合并到 references/terms.txt")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python terminology_extractor.py [InputSrt] [OptionalOutputPath]")
        sys.exit(1)
    
    input_srt = sys.argv[1]
    output_txt = sys.argv[2] if len(sys.argv) > 2 else "extracted_terms.txt"
    
    print(f"正在从 {input_srt} 提取术语...")
    terms = extract_terms(input_srt)
    if terms:
        print("提取到的潜在术语：")
        for term, count in terms:
            print(f"- {term} ({count} 次)")
        save_terms_to_file(terms, output_txt)
    else:
        print("未提取到明显的术语。")
