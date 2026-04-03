import os
import sys
import asyncio
import edge_tts
import re
import subprocess
import shutil
import tempfile
from utils import get_ffmpeg_path, get_ffprobe_path

FFMPEG = get_ffmpeg_path()
FFPROBE = get_ffprobe_path()

def srt_time_to_seconds(srt_time):
    srt_time = srt_time.replace('.', ',')
    h, m, s_ms = srt_time.split(':')
    s, ms = s_ms.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

def get_audio_duration(file_path):
    if not FFPROBE:
        raise RuntimeError("ffprobe not found")
    cmd = [
        FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', file_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return float(result.stdout)

def extract_voice_text(text):
    parts = [part.strip() for part in text.split('\\N') if part.strip()]
    if not parts:
        return ""

    for part in parts:
        if re.search(r'[\u4e00-\u9fa5]', part):
            return part

    return parts[0]

async def process_segment(index, text, start_time, end_time, temp_dir, voice="zh-CN-XiaoxiaoNeural"):
    target_duration = end_time - start_time
    raw_path = os.path.join(temp_dir, f"seg_{index}_raw.mp3")
    aligned_path = os.path.join(temp_dir, f"seg_{index}_aligned.mp3")
    
    # 1. Generate TTS
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(raw_path)
    
    if not FFMPEG:
        raise RuntimeError("ffmpeg not found")

    if not os.path.exists(raw_path) or os.path.getsize(raw_path) == 0:
        # Fallback for empty text segments
        subprocess.run([FFMPEG, '-f', 'lavfi', '-i', f'anullsrc=r=44100:cl=mono', '-t', str(target_duration), '-y', aligned_path], check=True, capture_output=True)
        return aligned_path

    # 2. Get duration
    actual_duration = get_audio_duration(raw_path)
    
    # 3. Align with target duration
    if actual_duration > target_duration:
        speed = min(1.25, actual_duration / target_duration)
        print(f"Segment {index}: Speeding up by {speed:.2f}x")
        subprocess.run([FFMPEG, '-i', raw_path, '-filter:a', f"atempo={speed}", '-y', aligned_path], check=True, capture_output=True)
    else:
        # Pad with silence
        pad_dur = target_duration - actual_duration
        print(f"Segment {index}: Padding with {pad_dur:.2f}s silence")
        subprocess.run([FFMPEG, '-i', raw_path, '-af', f"apad=pad_dur={pad_dur}", '-y', aligned_path], check=True, capture_output=True)
    
    return aligned_path

async def generate_voiceover(srt_path, output_audio_path):
    output_dir = os.path.dirname(os.path.abspath(output_audio_path)) or "."
    os.makedirs(output_dir, exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix="voice_segments_", dir=output_dir)

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read().strip()

        blocks = re.split(r'\n\s*\n', content)
        aligned_files = []

        print(f"开始处理 {len(blocks)} 个字幕片段...")

        for i, block in enumerate(blocks):
            lines = block.split('\n')
            if len(lines) < 3:
                continue

            time_match = re.search(r'(\d+:\d+:\d+[,.]\d+) --> (\d+:\d+:\d+[,.]\d+)', lines[1])
            if not time_match:
                continue

            start_time = srt_time_to_seconds(time_match.group(1))
            end_time = srt_time_to_seconds(time_match.group(2))

            # Extract text (handling bilingual \N)
            text = " ".join(lines[2:])
            zh_text = extract_voice_text(text)

            aligned_path = await process_segment(i, zh_text, start_time, end_time, temp_dir)
            aligned_files.append(aligned_path)

        if not aligned_files:
            raise RuntimeError("No valid subtitle segments found for TTS generation.")

        # 4. Concatenate all segments
        concat_list_path = os.path.join(temp_dir, "concat.txt")
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for fpath in aligned_files:
                # Use absolute path for safety with ffmpeg concat
                f.write(f"file '{os.path.abspath(fpath)}'\n")

        print(f"正在合并音频到: {output_audio_path}...")
        if not FFMPEG:
            raise RuntimeError("ffmpeg not found")
        subprocess.run([FFMPEG, '-f', 'concat', '-safe', '0', '-i', concat_list_path, '-c', 'libmp3lame', '-q:a', '2', '-y', output_audio_path], check=True, capture_output=True)
        print("语音合成与对齐完成。")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python voiceover_tts.py [SrtPath] [OutputAudioPath]")
        sys.exit(1)

    s_path = sys.argv[1]
    o_path = sys.argv[2]
    asyncio.run(generate_voiceover(s_path, o_path))
