import sys
import re

def srt_time_to_ass(srt_time):
    # SRT: 00:00:10,894 -> ASS: 0:00:10.89
    srt_time = srt_time.replace(',', '.')
    # Remove leading 0 if hours < 10
    if srt_time.startswith('0'):
        srt_time = srt_time[1:]
    # ASS uses 2 digits for centiseconds
    return srt_time[:-1]

def convert_srt_to_ass(srt_path, ass_path):
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split by double newline to get blocks
    blocks = re.split(r'\n\s*\n', content.strip())
    
    header = """[Script Info]
Title: YouTube-Video-Translator Subtitles
ScriptType: v4.00+
Collisions: Normal
PlayResX: 640
PlayResY: 360

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,16,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,1,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write(header)
        for block in blocks:
            lines = block.split('\n')
            if len(lines) >= 3:
                # Line 0: ID, Line 1: Time, Line 2+: Text
                time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', lines[1])
                if time_match:
                    start = srt_time_to_ass(time_match.group(1))
                    end = srt_time_to_ass(time_match.group(2))
                    
                    text_lines = lines[2:]
                    if len(text_lines) >= 2:
                        eng = text_lines[0].strip()
                        zh = text_lines[1].strip()
                        # Visual balance: English on top, Chinese on bottom
                        text = f"{eng}\\N{{\\fs14}}{zh}"
                        f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")
                    elif len(text_lines) == 1:
                        # Fallback if no split happened or translation missing
                        f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text_lines[0]}\n")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python srt_to_ass.py [SrtPath] [AssPath]")
        sys.exit(1)
    convert_srt_to_ass(sys.argv[1], sys.argv[2])
