import sys
import os
from PIL import Image, ImageDraw, ImageFont

def get_optimal_font_size(draw, text, font_path, max_width, initial_size):
    size = initial_size
    font = ImageFont.truetype(font_path, size)
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    
    # 如果标题太宽，逐步减小字号
    while w > max_width and size > 20:
        size -= 5
        font = ImageFont.truetype(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
    return font, w, (bbox[3] - bbox[1])

def create_cover(bg_path, output_path, title, subtitle):
    if not os.path.exists(bg_path):
        print(f"错误: 找不到底图 {bg_path}")
        return

    img = Image.open(bg_path).convert('RGB')
    width, height = img.size
    draw = ImageDraw.Draw(img)

    # 字体路径适配 (优先使用高清系统字体)
    font_path = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
    if not os.path.exists(font_path):
        font_path = "/System/Library/Fonts/PingFang.ttc"
    if not os.path.exists(font_path):
        print("警告: 未找到系统级中文字体，可能导致文字显示异常。")

    # 计算自适应字号
    max_w = int(width * 0.88) # 留出边距
    title_font, title_w, title_h = get_optimal_font_size(draw, title, font_path, max_w, 130)
    subtitle_font, sub_w, sub_h = get_optimal_font_size(draw, subtitle, font_path, max_w, 55)

    # 计算垂直居中布局
    spacing = 40
    padding = 60
    overlay_h = title_h + spacing + sub_h + (padding * 2)
    top_y = (height - overlay_h) // 2

    # 绘制半透明遮罩
    overlay = Image.new('RGBA', img.size, (0,0,0,0))
    d = ImageDraw.Draw(overlay)
    d.rectangle([0, top_y, width, top_y + overlay_h], fill=(0, 0, 0, 165)) 
    img = Image.alpha_composite(img.convert('RGBA'), overlay)
    draw = ImageDraw.Draw(img)

    # 写入文字
    draw.text(((width - title_w) // 2, top_y + padding), title, font=title_font, fill=(255, 230, 0))
    draw.text(((width - sub_w) // 2, top_y + padding + title_h + spacing), subtitle, font=subtitle_font, fill=(255, 255, 255))

    # 保存
    img.convert('RGB').save(output_path, "JPEG", quality=95)
    print(f"封面生成成功: {output_path} (字号: {title_font.size})")

if __name__ == "__main__":
    # 用法: python cover_generator.py [背景图] [输出路径] [标题] [副标题]
    if len(sys.argv) < 5:
        print("用法说明:")
        print("python cover_generator.py [BgPath] [OutPath] [Title] [Subtitle]")
        sys.exit(1)

    bg = sys.argv[1]
    out = sys.argv[2]
    t = sys.argv[3]
    st = sys.argv[4]

    create_cover(bg, out, t, st)
