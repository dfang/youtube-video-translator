#!/usr/bin/env python3
"""
Deduplicate YouTube highlight-style subtitles and generate clean SRT.
Usage: python3 dedup_subtitle.py <input.vtt> <output.srt>
"""

import re
import sys

def time_to_ms(t):
    """Convert VTT/SRT time to milliseconds"""
    h, m, s = t.replace(',', '.').split(':')
    return int(h)*3600000 + int(m)*60000 + int(float(s)*1000)

def ms_to_time(ms):
    """Convert milliseconds to SRT time format"""
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def parse_vtt(content):
    """Parse VTT content into segments"""
    # Remove WEBVTT header and style tags
    content = re.sub(r'WEBVTT[^ ]*', '', content)
    content = re.sub(r'Kind:[^ ]*', '', content)
    content = re.sub(r'Default:[^ ]*', '', content)
    # Remove intra-word timestamp tags like <00:00:00.448><c>text</c>
    content = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', content)
    content = re.sub(r'</?c>', '', content)
    content = re.sub(r'<[^>]+>', '', content)  # Remove any remaining HTML-like tags

    blocks = re.split(r'\n\n+', content.strip())
    parsed = []

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue
        try:
            time_code = lines[0]
            text = ' '.join(lines[1:]).strip()
        except:
            continue
        # Match VTT time format (uses . instead of ,)
        time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', time_code)
        if not time_match:
            # Try VTT format with dots
            time_match = re.match(r'(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})', time_code)
        if time_match:
            start, end = time_match.groups()
            # Normalize to SRT format (with comma)
            start = start.replace('.', ',', 1) if ',' not in start else start
            end = end.replace('.', ',', 1) if ',' not in end else end
            parsed.append({
                'start': start, 'end': end,
                'start_ms': time_to_ms(start), 'end_ms': time_to_ms(end),
                'text': text
            })

    return parsed

def deduplicate(parsed):
    """
    Deduplicate YouTube highlight-style subtitles.

    YouTube highlight subtitles have cumulative text like:
    - "Hello"
    - "Hello everyone"
    - "Hello everyone welcome"

    We only keep the longest unique segments.
    """
    all_texts = [block['text'].strip() for block in parsed]

    # Build deduped list: skip if current text starts with previous non-skipped text
    deduped = []
    for text in all_texts:
        if not deduped:
            deduped.append(text)
        elif text.startswith(deduped[-1]) and len(text) > len(deduped[-1]):
            # Replace previous with this longer version
            deduped[-1] = text
        elif not text.startswith(deduped[-1]):
            # Completely new text
            deduped.append(text)
        # else: skip, this is a partial/shorter version

    return ' '.join(deduped)


def deduplicate_blocks(parsed):
    """
    Deduplicate YouTube highlight-style subtitles.

    YouTube highlight subtitles have cumulative text like:
    - "Hello"
    - "Hello everyone"
    - "Hello everyone welcome"

    We extract only the new text from each block by removing the prefix from previous block.
    Then we deduplicate consecutive blocks with identical text.
    """
    if not parsed:
        return []

    # Step 1: Extract new text from cumulative subtitles
    extracted = []
    prev_text = ""

    for block in parsed:
        text = block['text'].strip()
        if not text:
            continue

        # Check if current text starts with previous text (cumulative format)
        if prev_text and text.startswith(prev_text):
            # Extract only the new part
            new_text = text[len(prev_text):].strip()
            if new_text:
                # Create a new block with updated text
                new_block = block.copy()
                new_block['text'] = new_text
                extracted.append(new_block)
        elif prev_text and prev_text.startswith(text):
            # Current text is a prefix of previous, skip (partial repeat)
            pass
        elif text != prev_text:
            # Completely new text
            extracted.append(block)

        prev_text = text

    # Step 2: Deduplicate consecutive blocks with identical text
    if not extracted:
        return []

    deduped = []
    prev_block = extracted[0]

    for i in range(1, len(extracted)):
        block = extracted[i]
        if block['text'].strip() == prev_block['text'].strip():
            # Same text, merge time range
            prev_block['end'] = block['end']
            prev_block['end_ms'] = block['end_ms']
        else:
            deduped.append(prev_block)
            prev_block = block.copy()

    deduped.append(prev_block)
    return deduped

def split_sentences(full_text):
    """Split text by sentence punctuation"""
    # Clean up spaces around Chinese punctuation (use raw string for regex)
    full_text = re.sub(r'\s*([.!?.!?，，,,;:""''())])\s*', r'\1', full_text)
    full_text = re.sub(r'\s+', ' ', full_text).strip()

    # Split by sentence punctuation
    sentences = re.split(r'([.!?.!?])', full_text)
    clean_sentences = []
    for i in range(0, len(sentences)-1, 2):
        sentence = sentences[i].strip()
        punct = sentences[i+1] if i+1 < len(sentences) else ''
        if sentence or punct:
            clean_sentences.append(sentence + punct)

    # Remove very short sentences
    clean_sentences = [s for s in clean_sentences if len(s.strip()) > 3]

    return clean_sentences, full_text

def generate_srt(parsed, clean_sentences, full_text, output_file):
    """Generate SRT file with calculated timing"""
    video_start_ms = parsed[0]['start_ms']
    video_end_ms = parsed[-1]['end_ms']
    video_duration = video_end_ms - video_start_ms
    total_chars = len(full_text)

    output_srt = []
    for i, sentence in enumerate(clean_sentences):
        search = sentence[:min(20, len(sentence))]
        pos = full_text.find(search)

        if pos >= 0:
            progress = pos / total_chars
            start_ms = int(video_start_ms + progress * video_duration)
            duration_ms = max(1500, int(len(sentence) * 220))
            end_ms = start_ms + duration_ms
        else:
            start_ms = video_start_ms
            duration_ms = max(1500, int(len(sentence) * 220))
            end_ms = start_ms + duration_ms

        start_time = ms_to_time(start_ms)
        end_time = ms_to_time(end_ms)

        output_srt.append(str(i+1))
        output_srt.append(f"{start_time} --> {end_time}")
        output_srt.append(sentence)
        output_srt.append('')

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_srt))

    return len(clean_sentences)

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 dedup_subtitle.py <input.vtt> <output.srt>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    parsed = parse_vtt(content)

    if not parsed:
        print(f"  VTT 解析失败：{input_file}")
        sys.exit(1)

    # Deduplicate by keeping only first occurrence of each unique text
    deduped = deduplicate_blocks(parsed)

    if not deduped:
        print(f"  去重后无内容：{input_file}")
        sys.exit(1)

    # Generate SRT with deduped blocks, preserving original timing
    output_srt = []
    for i, block in enumerate(deduped):
        output_srt.append(str(i + 1))
        output_srt.append(f"{block['start']} --> {block['end']}")
        output_srt.append(block['text'].strip())
        output_srt.append('')

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_srt))

    print(f"  已清理 YouTube 字幕格式：{len(parsed)} -> {len(deduped)} 条字幕")

if __name__ == '__main__':
    main()
