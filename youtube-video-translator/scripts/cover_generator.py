import sys
import os
from PIL import Image, ImageDraw, ImageFont

def find_font(preferred_font_name="PingFang.ttc"):
    # 1. Check local assets/fonts
    local_path = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts", preferred_font_name)
    if os.path.exists(local_path):
        return local_path
    
    # 2. Check Common System Paths
    system_paths = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf", # macOS
        "/System/Library/Fonts/PingFang.ttc",                  # macOS
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", # Linux
        "C:\\Windows\\Fonts\\msyh.ttc"                         # Windows
    ]
    for p in system_paths:
        if os.path.exists(p):
            return p
    return None

def get_optimal_font_size(draw, text, font_path, max_width, initial_size):
    size = initial_size
    if not font_path:
        font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        return font, bbox[2] - bbox[0], bbox[3] - bbox[1]

    font = ImageFont.truetype(font_path, size)
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    
    while w > max_width and size > 20:
        size -= 5
        font = ImageFont.truetype(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
    return font, w, (bbox[3] - bbox[1])

def create_cover(bg_path, output_path, title, subtitle):
    if not os.path.exists(bg_path):
        print(f"Error: BG image not found at {bg_path}")
        return

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    img = Image.open(bg_path).convert('RGB')
    width, height = img.size
    draw = ImageDraw.Draw(img)

    font_path = find_font()
    if not font_path:
        print("Warning: No suitable Chinese font found. Using default.")

    max_w = int(width * 0.88)
    title_font, title_w, title_h = get_optimal_font_size(draw, title, font_path, max_w, 130)
    subtitle_font, sub_w, sub_h = get_optimal_font_size(draw, subtitle, font_path, max_w, 55)

    spacing = 40
    padding = 60
    overlay_h = title_h + spacing + sub_h + (padding * 2)
    top_y = (height - overlay_h) // 2

    overlay = Image.new('RGBA', img.size, (0,0,0,0))
    d = ImageDraw.Draw(overlay)
    d.rectangle([0, top_y, width, top_y + overlay_h], fill=(0, 0, 0, 165)) 
    img = Image.alpha_composite(img.convert('RGBA'), overlay)
    draw = ImageDraw.Draw(img)

    draw.text(((width - title_w) // 2, top_y + padding), title, font=title_font, fill=(255, 230, 0))
    draw.text(((width - sub_w) // 2, top_y + padding + title_h + spacing), subtitle, font=subtitle_font, fill=(255, 255, 255))

    img.convert('RGB').save(output_path, "JPEG", quality=95)
    print(f"Cover generated: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python cover_generator.py [BgPath] [OutPath] [Title] [Subtitle]")
        sys.exit(1)
    create_cover(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
