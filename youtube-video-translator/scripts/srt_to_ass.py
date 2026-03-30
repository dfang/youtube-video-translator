import sys
import os
import pysubs2

def convert_srt_to_ass(srt_path, ass_path):
    # 1. 加载 SRT
    subs = pysubs2.load(srt_path, encoding="utf-8")
    
    # 2. 设置 ASS 画布大小 (与视频 1080p 比例一致)
    subs.info["PlayResX"] = 640
    subs.info["PlayResY"] = 360

    # 3. 定义全局样式 (基于您的要求)
    # 字体: PingFang SC Semibold
    # 颜色: 纯黑 (&H00000000)
    # 描边: 纯白 (&H00FFFFFF), 宽度 1.5
    style = pysubs2.SSAStyle()
    style.fontname = "PingFang SC Semibold"
    style.fontsize = 16
    style.primarycolor = pysubs2.Color(0, 0, 0)      # 文字黑色
    style.outlinecolor = pysubs2.Color(255, 255, 255) # 描边白色
    style.backcolor = pysubs2.Color(0, 0, 0, 128)    # 阴影透明
    style.outline = 1.5
    style.shadow = 0
    style.alignment = pysubs2.Alignment.BOTTOM_CENTER # 底部居中
    style.marginv = 15 # 距离底部边距
    
    subs.styles["Default"] = style

    # 4. 遍历并重组文本
    for line in subs:
        # 原始文本清理
        raw_text = line.text.strip()
        
        # 识别中英内容
        # 逻辑：假设 SRT 块中第一行是英文，第二行是中文（这是之前脚本生成的格式）
        # 或者是以 \N 分隔的格式
        parts = raw_text.split(r'\N')
        if len(parts) >= 2:
            eng = parts[0].strip()
            zh = parts[1].strip()
            # 标准：中文在上 (16号)，英文在下 (14号)
            # pysubs2 内部换行使用 \N
            line.text = f"{zh}\\N{{\\fs14}}{eng}"
        elif '\n' in raw_text:
            # 处理直接带有换行符的原始 SRT
            parts = raw_text.split('\n')
            eng = parts[0].strip()
            zh = parts[1].strip()
            line.text = f"{zh}\\N{{\\fs14}}{eng}"
        
    # 5. 自动修复：排序、解决微小重叠
    subs.sort()
    
    # 6. 保存
    subs.save(ass_path)
    print(f"pysubs2 转换成功: {ass_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python srt_to_ass.py [SrtPath] [AssPath]")
        sys.exit(1)
    convert_srt_to_ass(sys.argv[1], sys.argv[2])
