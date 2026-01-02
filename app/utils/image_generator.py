from PIL import Image, ImageDraw, ImageFont
import io
import os

# --- CONSTANTS & CONFIG ---
WIDTH = 1000
# Theme Colors
BG_COLOR = (20, 24, 35)        # Dark Navy
CARD_BG = (30, 36, 50)         # Card Background
ACCENT_GOLD = (212, 175, 55)   # Gold
ACCENT_CYAN = (0, 255, 255)    # Cyan
TEXT_WHITE = (240, 240, 240)
TEXT_GREY = (170, 170, 180)
BORDER_COLOR = (255, 255, 255) # White border
ROW_ALT_COLOR = (35, 40, 60)   # Zebra striping

def _load_fonts():
    fonts = {}
    try:
        path_bold = "fonts/arialbd.ttf"
        path_reg = "fonts/arial.ttf"
        
        # Fallback
        if not os.path.exists(path_bold):
             path_bold = "arialbd.ttf"
        if not os.path.exists(path_reg):
             path_reg = "arial.ttf"
        
        fonts["title"] = ImageFont.truetype(path_bold, 64)
        fonts["header"] = ImageFont.truetype(path_bold, 36)
        fonts["row"] = ImageFont.truetype(path_reg, 32)
        fonts["row_bold"] = ImageFont.truetype(path_bold, 32)
        
        # Profile specific
        fonts["profile_name"] = ImageFont.truetype(path_bold, 60)
        fonts["profile_rank"] = ImageFont.truetype(path_reg, 36)
        fonts["stat_label"] = ImageFont.truetype(path_bold, 24)
        fonts["stat_value"] = ImageFont.truetype(path_bold, 48)
        
    except IOError:
        d = ImageFont.load_default()
        return {k: d for k in ["title", "header", "row", "row_bold", "profile_name", "profile_rank", "stat_label", "stat_value"]}
    return fonts

def _draw_logo_overlay(base_img: Image.Image, opacity: float = 0.15, center_y: int = None):
    """
    Draws logo.jpg/png center watermark ON TOP.
    center_y: Optional Y coordinate for the center of the logo. 
              If None, centers vertically in the image.
    """
    logo_path = "logo.png"
    if not os.path.exists(logo_path):
        logo_path = "logo.jpg"
        if not os.path.exists(logo_path):
            return

    try:
        logo = Image.open(logo_path).convert("RGBA")
        
        # Resize to 50% width
        target_width = int(base_img.width * 0.5)
        ratio = target_width / logo.width
        target_height = int(logo.height * ratio)
        logo = logo.resize((target_width, target_height), Image.Resampling.LANCZOS)
        
        # Create transparent canvas
        overlay = Image.new('RGBA', base_img.size, (0,0,0,0))
        
        x = (base_img.width - target_width) // 2
        
        if center_y is not None:
            y = center_y - (target_height // 2)
        else:
            y = (base_img.height - target_height) // 2
            
        overlay.paste(logo, (x, y))
        
        # Apply opacity
        r, g, b, a = overlay.split()
        a = a.point(lambda p: int(p * opacity))
        overlay.putalpha(a)
        
        # Paste overlay ON TOP
        base_img.paste(overlay, (0, 0), mask=overlay)
    except Exception as e:
        print(f"Overlay error: {e}")

# --- HELPERS FOR ALIGNMENT ---
def draw_table_row(draw, y, col_data, fonts):
    for x, text, f_key, color, anc in col_data:
        draw.text((x, y), str(text), font=fonts[f_key], fill=color, anchor=anc)

# --- GENERATORS ---

def generate_leaderboard_image(season_name: str, leaders: list) -> io.BytesIO:
    HEADER_HEIGHT = 160
    ROW_HEIGHT = 80
    PADDING = 20
    
    num_rows = min(len(leaders), 10)
    HEIGHT = HEADER_HEIGHT + (num_rows * ROW_HEIGHT) + PADDING + 20 
    
    img = Image.new('RGBA', (WIDTH, HEIGHT), color=BG_COLOR)
    draw = ImageDraw.Draw(img)
    fonts = _load_fonts()

    # 1. Header
    draw.text((WIDTH // 2, 60), season_name, font=fonts["title"], fill=TEXT_WHITE, anchor="mm")

    # 2. Table Structure
    table_top = 120
    table_bottom = HEIGHT - 20
    table_left = 20
    table_right = WIDTH - 20
    
    # Outer Border (White)
    draw.rectangle([(table_left, table_top), (table_right, table_bottom)], outline=BORDER_COLOR, width=3)
    
    # Header Row Background
    draw.rectangle([(table_left, table_top), (table_right, table_top + 60)], fill=CARD_BG)
    draw.line([(table_left, table_top + 60), (table_right, table_top + 60)], fill=BORDER_COLOR, width=2)
    
    # Columns Config
    col_rank_x = 80
    col_name_x = 180
    col_games_x = 650
    col_perf_x = 780
    col_pts_x = 900
    
    # Table Headers
    header_y = table_top + 30
    headers = [
        (col_rank_x, "#", "header", ACCENT_GOLD, "mm"),
        (col_name_x, "Игрок", "header", ACCENT_GOLD, "lm"),
        (col_games_x, "Игр", "header", ACCENT_GOLD, "mm"),
        (col_perf_x, "Идеал", "header", ACCENT_GOLD, "mm"),
        (col_pts_x, "Очки", "header", ACCENT_GOLD, "mm"),
    ]
    draw_table_row(draw, header_y, headers, fonts)

    # Rows
    start_y = table_top + 60
    for i, user in enumerate(leaders[:10]):
        y = start_y + (i * ROW_HEIGHT)
        row_center_y = y + ROW_HEIGHT // 2
        
        # Zebra Striping
        if i % 2 == 1:
            draw.rectangle([(table_left + 2, y), (table_right - 2, y + ROW_HEIGHT)], fill=ROW_ALT_COLOR)
        
        # Data
        rank = i + 1
        name = user.get('name', 'Unknown')
        points = user.get('points', 0)
        played = user.get('played', 0)
        perfects = user.get('perfects', 0)
        
        r_color = TEXT_WHITE
        if rank == 1: r_color = ACCENT_GOLD
        elif rank == 2: r_color = (192, 192, 192)
        elif rank == 3: r_color = (205, 127, 50)
        
        row_data = [
            (col_rank_x, str(rank), "row_bold", r_color, "mm"),
            (col_name_x, name, "row_bold", TEXT_WHITE, "lm"),
            (col_games_x, str(played), "row", TEXT_GREY, "mm"),
            (col_perf_x, str(perfects) if perfects > 0 else "-", "row", ACCENT_CYAN if perfects > 0 else TEXT_GREY, "mm"),
            (col_pts_x, str(points), "row_bold", ACCENT_GOLD, "mm"),
        ]
        draw_table_row(draw, row_center_y, row_data, fonts)
        
        # Separator line
        if i < len(leaders) - 1:
            draw.line([(table_left, y + ROW_HEIGHT), (table_right, y + ROW_HEIGHT)], fill=(255, 255, 255, 30), width=1)

    # 3. Logo Overlay (LAST STEP)
    # Calculate visual center of the TABLE (excluding title)
    # Table starts at table_top (120) and ends at HEIGHT-20
    visual_center_y = (table_top + (HEIGHT - 20)) // 2
    
    _draw_logo_overlay(img, opacity=0.15, center_y=visual_center_y)

    return _save_img(img)

def generate_user_profile_image(user_data: dict) -> io.BytesIO:
    HEIGHT = 700
    img = Image.new('RGBA', (WIDTH, HEIGHT), color=BG_COLOR)
    draw = ImageDraw.Draw(img)
    fonts = _load_fonts()
    
    # 1. Main Frame
    m = 20
    draw.rectangle([(m, m), (WIDTH - m, HEIGHT - m)], outline=BORDER_COLOR, width=4)

    # CENTER ALIGNED CONTENT
    
    # 2. NAME
    cy_name = 100
    full_name = user_data.get("full_name", "Player")
    draw.text((WIDTH // 2, cy_name), full_name, font=fonts["profile_name"], fill=TEXT_WHITE, anchor="mm")
    
    # 3. RANK TITLE
    cy_rank = 160
    rank_title = user_data.get("rank_title", "Novice").upper()
    draw.text((WIDTH // 2, cy_rank), f"— {rank_title} —", font=fonts["profile_rank"], fill=ACCENT_GOLD, anchor="mm")
    
    # SEPARATOR LINE
    draw.line([(WIDTH // 2 - 150, 200), (WIDTH // 2 + 150, 200)], fill=TEXT_GREY, width=2)
    
    # 4. STATS BLOCKS
    y_start = 260
    y_gap = 100
    
    def draw_stat_pair(x, y, label, value, val_color=TEXT_WHITE):
        draw.text((x, y), label, font=fonts["stat_label"], fill=TEXT_GREY, anchor="mm")
        draw.text((x, y + 40), str(value), font=fonts["stat_value"], fill=val_color, anchor="mm")

    col1 = WIDTH // 3
    col2 = WIDTH * 2 // 3
    
    # ROW 1
    y1 = y_start
    draw_stat_pair(col1, y1, "ОЧКИ", user_data.get("total_points", 0), ACCENT_GOLD)
    draw_stat_pair(col2, y1, "РЕЙТИНГ", f"#{user_data.get('rank_pos', '-')}")
    
    # ROW 2
    y2 = y1 + y_gap
    draw_stat_pair(col1, y2, "ТУРНИРОВ", user_data.get("played", 0))
    draw_stat_pair(col2, y2, "СРЕДНИЙ БАЛЛ", user_data.get("avg_score", 0.0))
    
    # ROW 3
    y3 = y2 + y_gap
    curr_str = user_data.get("current_streak", 0)
    max_str = user_data.get("max_streak", 0)
    
    str_color = (255, 100, 100) if curr_str > 0 else TEXT_WHITE
    draw_stat_pair(col1, y3, "СЕРИЯ", curr_str, str_color)
    draw_stat_pair(col2, y3, "МАКС. СЕРИЯ", max_str)

    # ROW 4
    y4 = y3 + y_gap
    draw_stat_pair(col1, y4, "ИДЕАЛЬНО", user_data.get("perfects", 0), ACCENT_CYAN)
    draw_stat_pair(col2, y4, "В ЯБЛОЧКО", user_data.get("exacts", 0), ACCENT_CYAN)

    # 5. Logo Overlay (LAST STEP)
    # Center relative to content block (approx 100 to 600) -> 350
    # Or just default center which is 350.
    _draw_logo_overlay(img, opacity=0.15)

    return _save_img(img)

def _save_img(img):
    final_img = img.convert("RGB")
    bio = io.BytesIO()
    final_img.save(bio, format='PNG')
    bio.seek(0)
    return bio