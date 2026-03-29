import os
import sys
import subprocess

def transcribe_with_whisperx(video_path, output_dir):
    """
    1. 从视频中提取音频 (WAV)
    2. 使用 WhisperX 进行转录
    """
    audio_path = os.path.join(output_dir, "original_audio.wav")
    
    # 提取音频
    print("正在提取音频...")
    subprocess.run([
        "ffmpeg", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path, "-y"
    ], check=True)

    # 运行 WhisperX 转录
    # 默认模型 large-v3, 自动检测语言 (英), MPS 加速
    print("正在使用 WhisperX 转录音频 ( large-v3 )...")
    subprocess.run([
        "whisperx", audio_path, "--model", "large-v3", "--language", "en",
        "--output_dir", output_dir, "--output_format", "srt", "--compute_type", "int8"
    ], check=True)

    # 重命名生成的字幕为 en_original.srt
    # WhisperX 会生成 original_audio.srt
    generated_srt = os.path.join(output_dir, "original_audio.srt")
    final_srt = os.path.join(output_dir, "en_original.srt")
    if os.path.exists(generated_srt):
        os.rename(generated_srt, final_srt)
        print(f"转录完成: {final_srt}")
    else:
        print("WhisperX 未能生成字幕。")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python whisperx_transcriber.py [VideoPath] [OutputDir]")
        sys.exit(1)

    v_path = sys.argv[1]
    o_dir = sys.argv[2]
    transcribe_with_whisperx(v_path, o_dir)
