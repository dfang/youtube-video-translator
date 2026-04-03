import sys
import os
import pysubs2

def convert_srt_to_ass(srt_path, ass_path):
    subs = pysubs2.load(srt_path, encoding="utf-8")
    subs.info["PlayResX"] = 640
    subs.info["PlayResY"] = 360

    style = pysubs2.SSAStyle()
    # Check if we should fallback if PingFang is missing?
    # For now, let's keep the name and assume font-config/OS handles it.
    style.fontname = "PingFang SC Semibold"
    style.fontsize = 16
    style.primarycolor = pysubs2.Color(0, 0, 0)
    style.outlinecolor = pysubs2.Color(255, 255, 255)
    style.outline = 1
    style.shadow = 0
    style.alignment = pysubs2.Alignment.BOTTOM_CENTER
    style.marginv = 15

    subs.styles["Default"] = style

    for line in subs:
        raw_text = line.text.strip()
        # SRT format: first line = Chinese (top), second line = English (bottom)
        # \N in the original file is a literal string, not an escape sequence
        # After fix, SRT should have actual newlines between Chinese and English
        if r'\N' in raw_text:
            parts = raw_text.split(r'\N')
            if len(parts) >= 2:
                zh = parts[0].strip()
                eng = parts[1].strip()
                line.text = f"{zh}\\N{{\\fs14}}{eng}"
        elif '\n' in raw_text:
            parts = raw_text.split('\n')
            if len(parts) >= 2:
                # parts[0] = Chinese (top), parts[1] = English (bottom)
                zh = parts[0].strip()
                eng = parts[1].strip()
                line.text = f"{zh}\\N{{\\fs14}}{eng}"

    subs.sort()
    subs.save(ass_path)
    print(f"pysubs2 conversion complete: {ass_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)
    convert_srt_to_ass(sys.argv[1], sys.argv[2])
