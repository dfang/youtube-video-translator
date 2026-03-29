import sys
import re
from datetime import datetime, timedelta

def srt_time_to_delta(srt_time):
    # 00:00:10,894 -> timedelta
    h, m, s_ms = srt_time.split(':')
    s, ms = s_ms.split(',')
    return timedelta(hours=int(h), minutes=int(m), seconds=int(s), milliseconds=int(ms))

def delta_to_srt_time(delta):
    # timedelta -> 00:00:10,894
    total_seconds = int(delta.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    milliseconds = int(delta.microseconds / 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"

def split_text_by_words(text, num_parts):
    words = text.split()
    avg_len = len(words) // num_parts
    parts = []
    for i in range(num_parts):
        if i == num_parts - 1:
            parts.append(" ".join(words[i*avg_len:]))
        else:
            parts.append(" ".join(words[i*avg_len:(i+1)*avg_len]))
    return parts

def audit_and_split_srt(input_path, output_path, max_duration=8.0):
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()

    blocks = re.split(r'\n\s*\n', content)
    new_blocks = []
    index = 1

    for block in blocks:
        lines = block.split('\n')
        if len(lines) < 3:
            continue

        time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', lines[1])
        if not time_match:
            continue

        start_str, end_str = time_match.groups()
        start_delta = srt_time_to_delta(start_str)
        end_delta = srt_time_to_delta(end_str)
        duration = (end_delta - start_delta).total_seconds()
        text = " ".join(lines[2:])

        if duration > max_duration:
            # 需要拆分的段数
            num_segments = int(duration // 5.0) + (1 if duration % 5.0 > 2.0 else 0)
            if num_segments < 2: num_segments = 2

            sub_duration = duration / num_segments
            sub_texts = split_text_by_words(text, num_segments)

            for i in range(num_segments):
                sub_start = start_delta + timedelta(seconds=i * sub_duration)
                sub_end = start_delta + timedelta(seconds=(i + 1) * sub_duration)

                # 确保最后一段的时间戳精准闭合
                if i == num_segments - 1: sub_end = end_delta

                new_blocks.append(f"{index}\n{delta_to_srt_time(sub_start)} --> {delta_to_srt_time(sub_end)}\n{sub_texts[i]}")
                index += 1
            print(f"审计发现超长片段 ({duration}s)，已拆分为 {num_segments} 段。")
        else:
            new_blocks.append(f"{index}\n{start_str} --> {end_str}\n{text}")
            index += 1

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("\n\n".join(new_blocks))
    print(f"审计完成，生成优化后的字幕: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python subtitle_splitter.py [InputSrt] [OutputSrt]")
        sys.exit(1)
    audit_and_split_srt(sys.argv[1], sys.argv[2])
