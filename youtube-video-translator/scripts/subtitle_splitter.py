import re
import sys
from datetime import timedelta


def srt_time_to_delta(srt_time):
    srt_time = srt_time.replace(".", ",")
    h, m, s_ms = srt_time.split(":")
    s, ms = s_ms.split(",")
    return timedelta(hours=int(h), minutes=int(m), seconds=int(s), milliseconds=int(ms))


def delta_to_srt_time(delta):
    total_seconds = int(delta.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    milliseconds = int(delta.microseconds / 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def protect_abbreviations(text):
    abbreviations = [
        r"Mr\.",
        r"Mrs\.",
        r"Dr\.",
        r"St\.",
        r"U\.S\.",
        r"U\.K\.",
        r"i\.e\.",
        r"e\.g\.",
    ]
    protected = text
    placeholders = {}
    for i, pattern in enumerate(abbreviations):
        token = f"__ABBR_{i}__"
        protected = re.sub(pattern, token, protected)
        placeholders[token] = pattern.replace("\\", "")
    return protected, placeholders


def restore_abbreviations(text, placeholders):
    restored = text
    for token, value in placeholders.items():
        restored = restored.replace(token, value)
    return restored


def split_into_clauses(text):
    protected, placeholders = protect_abbreviations(text)
    parts = re.split(r"(?<=[.!?;:])\s+|(?<=[,，;；:：])\s*", protected)
    clauses = []
    for part in parts:
        normalized = restore_abbreviations(part, placeholders).strip()
        if normalized:
            clauses.append(normalized)
    return clauses


def has_meaningful_clause_boundaries(clauses):
    if len(clauses) <= 1:
        return False
    for clause in clauses:
        words = clause.split()
        if len(words) >= 2 or len(clause) >= 12:
            return True
    return False


def balanced_word_chunks(text, target_parts, min_words_per_chunk=3):
    words = text.split()
    if not words:
        return [""]
    if len(words) < target_parts * min_words_per_chunk:
        return [" ".join(words)]

    chunk_size = max(min_words_per_chunk, round(len(words) / target_parts))
    chunks = []
    cursor = 0
    remaining_parts = target_parts
    while cursor < len(words):
        remaining_words = len(words) - cursor
        if remaining_parts <= 1:
            chunks.append(" ".join(words[cursor:]))
            break

        current_size = min(chunk_size, remaining_words - min_words_per_chunk * (remaining_parts - 1))
        current_size = max(min_words_per_chunk, current_size)
        chunks.append(" ".join(words[cursor:cursor + current_size]))
        cursor += current_size
        remaining_parts -= 1

    return chunks


def merge_clauses_balanced(clauses, target_parts):
    if not clauses:
        return [""]
    if len(clauses) <= target_parts:
        return clauses

    total_chars = sum(len(clause) for clause in clauses)
    target_chars = max(1, total_chars // target_parts)
    merged = []
    current = []
    current_chars = 0
    remaining_clauses = len(clauses)
    remaining_parts = target_parts

    for clause in clauses:
        remaining_clauses -= 1
        candidate_chars = current_chars + len(clause) + (1 if current else 0)
        must_flush = (
            current
            and candidate_chars >= target_chars
            and remaining_clauses >= (remaining_parts - 1)
        )
        if must_flush:
            merged.append(" ".join(current))
            current = [clause]
            current_chars = len(clause)
            remaining_parts -= 1
        else:
            current.append(clause)
            current_chars = candidate_chars

    if current:
        merged.append(" ".join(current))
    return merged


def split_text_naturally(text, target_parts):
    if target_parts <= 1:
        return [text.strip()]

    normalized = " ".join(text.split())
    if not normalized:
        return [""]

    clauses = split_into_clauses(normalized)
    if has_meaningful_clause_boundaries(clauses):
        return merge_clauses_balanced(clauses, target_parts)

    return balanced_word_chunks(normalized, target_parts)


def audit_and_split_srt(input_path, output_path, max_duration=8.0, max_chars_per_line=80):
    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        print("警告: 输入文件为空。")
        return

    blocks = re.split(r"\n\s*\n", content)
    new_blocks = []
    index = 1

    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        if len(lines) < 3:
            continue

        time_match = re.match(
            r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})",
            lines[1],
        )
        if not time_match:
            continue

        start_str, end_str = time_match.groups()
        start_delta = srt_time_to_delta(start_str)
        end_delta = srt_time_to_delta(end_str)
        duration = (end_delta - start_delta).total_seconds()
        text = " ".join(lines[2:]).strip()

        needs_split = duration > max_duration or len(text) > max_chars_per_line
        if not needs_split:
            new_blocks.append(f"{index}\n{start_str} --> {end_str}\n{text}")
            index += 1
            continue

        num_by_duration = int(duration // 4.5) + (1 if duration % 4.5 > 2.0 else 0)
        num_by_chars = int(len(text) // 45) + (1 if len(text) % 45 > 15 else 0)
        target_parts = max(2, num_by_duration, num_by_chars)

        sub_texts = [part for part in split_text_naturally(text, target_parts) if part.strip()]
        actual_parts = max(1, len(sub_texts))
        if actual_parts == 1:
            new_blocks.append(f"{index}\n{start_str} --> {end_str}\n{sub_texts[0]}")
            index += 1
            continue

        sub_duration = duration / actual_parts
        for i, sub_text in enumerate(sub_texts):
            sub_start = start_delta + timedelta(seconds=i * sub_duration)
            sub_end = start_delta + timedelta(seconds=(i + 1) * sub_duration)
            if i == actual_parts - 1:
                sub_end = end_delta
            new_blocks.append(
                f"{index}\n{delta_to_srt_time(sub_start)} --> {delta_to_srt_time(sub_end)}\n{sub_text}"
            )
            index += 1

        print(
            f"审计发现超长或过密片段 ({duration:.2f}s, {len(text)} chars)，"
            f"已自然拆分为 {actual_parts} 段。"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(new_blocks))
    print(f"审计完成，生成优化后的字幕: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python subtitle_splitter.py [InputSrt] [OutputSrt]")
        sys.exit(1)
    audit_and_split_srt(sys.argv[1], sys.argv[2])
