import sys
import re
from datetime import timedelta

def srt_time_to_delta(srt_time):
    # 00:00:10,894 or 00:00:10.894 -> timedelta
    srt_time = srt_time.replace('.', ',')
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

def split_text_naturally(text, num_parts):
    parts = []
    
    # Simple strategy: find split points that result in relatively even segments
    # For now, let's use a more robust split that tries to keep sentences together
    sentences = re.split(r'(\.|\?|!|;)\s*', text)
    # Reconstruct sentences from the split (retaining the punctuation)
    combined_sentences = []
    for i in range(0, len(sentences)-1, 2):
        combined_sentences.append(sentences[i] + sentences[i+1])
    if len(sentences) % 2 != 0 and sentences[-1]:
        combined_sentences.append(sentences[-1])

    if len(combined_sentences) >= num_parts:
        # Distribute sentences into num_parts
        avg = len(combined_sentences) // num_parts
        for i in range(num_parts):
            if i == num_parts - 1:
                parts.append(" ".join(combined_sentences[i*avg:]))
            else:
                parts.append(" ".join(combined_sentences[i*avg:(i+1)*avg]))
        return parts
    
    # Fallback to word-based splitting if not enough sentences
    words = text.split()
    avg_len = len(words) // num_parts
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

        time_match = re.match(r'(\d{2}:\d{2}:\d{2}[,.]\d{3}) --> (\d{2}:\d{2}:\d{2}[,.]\d{3})', lines[1])
        if not time_match:
            continue

        start_str, end_str = time_match.groups()
        start_delta = srt_time_to_delta(start_str)
        end_delta = srt_time_to_delta(end_str)
        duration = (end_delta - start_delta).total_seconds()
        text = " ".join(lines[2:])

        if duration > max_duration:
            # Calculate how many segments we need based on a target 4-5s per segment
            num_segments = max(2, int(duration // 4.5))
            
            sub_duration = duration / num_segments
            sub_texts = split_text_naturally(text, num_segments)

            for i in range(num_segments):
                sub_start = start_delta + timedelta(seconds=i * sub_duration)
                sub_end = start_delta + timedelta(seconds=(i + 1) * sub_duration)

                if i == num_segments - 1: sub_end = end_delta

                new_blocks.append(f"{index}\n{delta_to_srt_time(sub_start)} --> {delta_to_srt_time(sub_end)}\n{sub_texts[i]}")
                index += 1
            print(f"审计发现超长片段 ({duration:.2f}s)，已自然拆分为 {num_segments} 段。")
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
