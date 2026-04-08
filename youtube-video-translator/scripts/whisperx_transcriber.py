import os
import sys
import subprocess
import json
from utils import get_ffmpeg_path

# 尝试导入 state_manager 以支持状态更新
try:
    from state_manager import update_phase
except ImportError:
    # 如果不在同一目录下或环境不对，退化为无状态模式
    update_phase = None

# 优先使用具有完整能力的 ffmpeg
FFMPEG = get_ffmpeg_path()


def _safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def build_word_timing_sidecar_payload(whisperx_json_path, srt_path):
    if not os.path.exists(whisperx_json_path):
        return None

    try:
        with open(whisperx_json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        print(f"读取 WhisperX JSON 失败，跳过词级时间戳 sidecar: {e}")
        return None

    segments = []
    for idx, seg in enumerate(payload.get("segments", []), start=1):
        text = (seg.get("text") or "").strip()
        start = _safe_float(seg.get("start"))
        end = _safe_float(seg.get("end"))
        if not text or start is None or end is None:
            continue

        words = []
        for word in seg.get("words", []) or []:
            token = (word.get("word") or word.get("text") or "").strip()
            if not token:
                continue
            words.append({
                "text": token,
                "start": _safe_float(word.get("start")),
                "end": _safe_float(word.get("end")),
                "score": _safe_float(word.get("score")),
            })

        item = {
            "index": idx,
            "start": start,
            "end": end,
            "text": text,
            "words": words,
        }
        speaker = seg.get("speaker")
        if speaker:
            item["speaker"] = speaker
        segments.append(item)

    return {
        "source_srt": os.path.abspath(srt_path),
        "language": payload.get("language", "en"),
        "segments": segments,
    }

def _get_initial_prompt():
    """
    生成初始提示词（Initial Prompt），用于引导 WhisperX 识别专业术语。
    优先级：外部术语文件 (references/terms.txt) > 环境变量 > 默认内置术语
    注意：Whisper 的 initial_prompt 有长度限制（约 224 tokens），过长会被截断。
    因此，自定义术语会被放在前面，以确保它们具有更高的权重。
    """
    custom_terms = []

    # 1. 尝试从 references/terms.txt 加载自定义术语（优先级最高）
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    terms_file = os.path.join(base_dir, "references", "terms.txt")

    if os.path.exists(terms_file):
        try:
            with open(terms_file, "r", encoding="utf-8") as f:
                # 支持按行、逗号分隔
                lines = f.readlines()
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # 再次按逗号分割
                        for part in line.split(","):
                            p = part.strip()
                            if p:
                                custom_terms.append(p)
                if custom_terms:
                    print(f"加载自定义术语文件: {terms_file} ({len(custom_terms)} 个术语)")
        except Exception as e:
            print(f"读取术语文件失败: {e}")

    # 2. 支持通过环境变量扩展
    extra = os.environ.get("WHISPERX_INITIAL_PROMPT", "")
    if extra:
        for part in extra.split(","):
            p = part.strip()
            if p:
                custom_terms.append(p)

    # 合并、去重且保持顺序 (Python 3.7+ dict.fromkeys 可保持顺序)
    all_terms = list(dict.fromkeys(custom_terms))

    # 将术语重新组合成字符串
    # Whisper 提示词通常建议以逗号或空格分隔
    # 我们使用逗号空格分隔，使其看起来像一个自然的列表
    full_prompt = ", ".join(all_terms)

    # 如果总长度过长，虽然 Whisper 会自动截断，但我们可以在这里打个日志提醒
    if len(full_prompt.split()) > 200:
        print(f"警告: 初始提示词可能过长 ({len(full_prompt.split())} 单词)，Whisper 可能会截断末尾部分。")

    return full_prompt

def transcribe_with_whisperx(video_path, output_dir):
    """
    1. 从视频中提取音频 (WAV)
    2. 使用 WhisperX 进行转录
    """
    audio_path = os.path.join(output_dir, "original_audio.wav")

    # 尝试识别 video_id 以便更新全局状态
    # 路径通常是 ./translations/[video_id]/temp
    video_id = None
    if "translations" in output_dir:
        parts = os.path.normpath(output_dir).split(os.sep)
        try:
            idx = parts.index("translations")
            if idx + 1 < len(parts):
                video_id = parts[idx + 1]
        except ValueError:
            pass

    if update_phase and video_id:
        update_phase(video_id, 4, "running")

    if not FFMPEG:
        if update_phase and video_id:
            update_phase(video_id, 4, "failed", error="FFmpeg not found")
        raise RuntimeError("FFmpeg not found. Please install ffmpeg/ffmpeg-full and retry.")

    # 提取音频
    print("正在提取音频...")
    subprocess.run([
        FFMPEG, "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path, "-y"
    ], check=True)

    # 运行 WhisperX 转录
    # 默认模型 medium, 自动检测语言 (英), MPS 加速
    # initial_prompt 注入 ICU 术语词典，提升医疗术语识别率
    initial_prompt = _get_initial_prompt()
    print("正在使用 WhisperX 转录音频 ( medium )...")

    try:
        subprocess.run([
            "whisperx", audio_path,
            "--model", "medium",
            "--language", "en",
            "--initial_prompt", initial_prompt,
            "--output_dir", output_dir,
            "--output_format", "all",
            "--compute_type", "int8"
        ], check=True)
    except subprocess.CalledProcessError as e:
        if update_phase and video_id:
            update_phase(video_id, 4, "failed", error=f"WhisperX failed: {str(e)}")
        raise

    # 重命名生成的字幕为 en_original.srt
    # WhisperX 会生成 original_audio.srt
    generated_srt = os.path.join(output_dir, "original_audio.srt")
    generated_json = os.path.join(output_dir, "original_audio.json")
    final_srt = os.path.join(output_dir, "en_original.srt")
    final_sidecar = os.path.join(output_dir, "en_original.word_timestamps.json")
    if os.path.exists(generated_srt):
        os.rename(generated_srt, final_srt)
        sidecar_payload = build_word_timing_sidecar_payload(generated_json, final_srt)
        if sidecar_payload:
            with open(final_sidecar, "w", encoding="utf-8") as f:
                json.dump(sidecar_payload, f, ensure_ascii=False, indent=2)
            print(f"词级时间戳 sidecar 已生成: {final_sidecar}")
        elif os.path.exists(final_sidecar):
            os.remove(final_sidecar)
        print(f"转录完成: {final_srt}")
        if update_phase and video_id:
            update_phase(video_id, 4, "done", artifact=final_srt)
    else:
        print("WhisperX 未能生成字幕。")
        if update_phase and video_id:
            update_phase(video_id, 4, "failed", error="SRT not generated")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python whisperx_transcriber.py [VideoPath] [OutputDir]")
        sys.exit(1)

    v_path = sys.argv[1]
    o_dir = sys.argv[2]
    transcribe_with_whisperx(v_path, o_dir)
