import os
from PIL import Image, ImageDraw

icons_dir = os.path.join(os.path.dirname(__file__), 'static', 'icons')
os.makedirs(icons_dir, exist_ok=True)

def generate_icon(size: int, filename: str, is_maskable: bool = False):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Margin
    pad = int(size * 0.12) if is_maskable else int(size * 0.05)
    box = [pad, pad, size - pad, size - pad]
    radius = int(size * 0.22)
    
    # Pink rounded box with border
    draw.rounded_rectangle(box, radius=radius, fill="#FF4F93", outline="#1B1B3A", width=max(4, int(size * 0.04)))
    
    # White Play Triangle
    cx = size // 2
    cy = size // 2
    tw = int(size * 0.32)
    th = int(size * 0.36)
    
    # Centered play button points
    p1 = (cx - tw // 3, cy - th // 2)
    p2 = (cx + tw * 2 // 3, cy)
    p3 = (cx - tw // 3, cy + th // 2)
    draw.polygon([p1, p2, p3], fill="#FFFFFF", outline="#1B1B3A", width=max(2, int(size * 0.03)))
    
    # Sparkle / Star in corner
    star_x = int(size * 0.76)
    star_y = int(size * 0.24)
    sr = int(size * 0.08)
    # Diamond star
    draw.polygon([
        (star_x, star_y - sr),
        (star_x + sr // 2, star_y),
        (star_x, star_y + sr),
        (star_x - sr // 2, star_y)
    ], fill="#FFD93D", outline="#1B1B3A", width=max(1, int(size * 0.02)))
    
    out_path = os.path.join(icons_dir, filename)
    img.save(out_path, "PNG")
    print(f"Generated {out_path} ({size}x{size})")

generate_icon(192, 'icon-192.png')
generate_icon(512, 'icon-512.png')
generate_icon(512, 'icon-maskable-512.png', is_maskable=True)
