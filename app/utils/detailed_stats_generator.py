from PIL import Image, ImageDraw, ImageFont
import io
import os

# --- CONSTANTS & CONFIG ---
WIDTH = 1200 # Wider than standard for more columns
MIN_HEIGHT = 600
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
        # Try loading from fonts/ directory first
        path_bold = "fonts/arialbd.ttf"
        path_reg = "fonts/arial.ttf"
        
        # Fallback for local testing if fonts are in root (optional, but good for safety)
        if not os.path.exists(path_bold):
             path_bold = "arialbd.ttf"
        if not os.path.exists(path_reg):
             path_reg = "arial.ttf"
        
        fonts["title"] = ImageFont.truetype(path_bold, 48)
        fonts["header"] = ImageFont.truetype(path_bold, 24)
        fonts["row_name"] = ImageFont.truetype(path_bold, 24)
        fonts["row_val"] = ImageFont.truetype(path_reg, 24)
        fonts["row_total"] = ImageFont.truetype(path_bold, 26)
        
    except IOError:
        d = ImageFont.load_default()
        return {k: d for k in ["title", "header", "row_name", "row_val", "row_total"]}
    return fonts

def generate_detailed_season_image(season_title: str, columns: list, rows: list) -> io.BytesIO:
    """
    columns: list of tournament names (strings)
    rows: list of dicts {'name': str, 'scores': [int, int...], 'total': int}
          scores length must match columns length.
    """
    
    # Calculate dynamic width/height
    # Base layout:
    # Name column: 250px
    # Data columns: 100px each
    # Total column: 100px
    
    NAME_COL_WIDTH = 250
    DATA_COL_WIDTH = 100
    TOTAL_COL_WIDTH = 100
    PADDING = 20
    TABLE_TOP = 100
    HEADER_HEIGHT = 150
    ROW_HEIGHT = 50
    
    num_data_cols = len(columns)
    calculated_width = NAME_COL_WIDTH + (num_data_cols * DATA_COL_WIDTH) + TOTAL_COL_WIDTH + (PADDING * 2)
    final_width = max(WIDTH, calculated_width)
    
    final_height = TABLE_TOP + HEADER_HEIGHT + (len(rows) * ROW_HEIGHT) + PADDING + 20
    
    img = Image.new('RGBA', (final_width, final_height), color=BG_COLOR)
    draw = ImageDraw.Draw(img)
    fonts = _load_fonts()
    
    # 1. Title
    draw.text((final_width // 2, 40), season_title, font=fonts["title"], fill=TEXT_WHITE, anchor="mm")
    
    # 2. Table Header
    # Draw header background
    draw.rectangle([(PADDING, TABLE_TOP), (final_width - PADDING, TABLE_TOP + HEADER_HEIGHT)], fill=CARD_BG)
    
    # Name Header (Horizontal)
    curr_x = PADDING + 10
    draw.text((curr_x, TABLE_TOP + HEADER_HEIGHT - 30), "Игрок", font=fonts["header"], fill=ACCENT_GOLD, anchor="lm")
    
    curr_x += NAME_COL_WIDTH
    
    # Tournament Headers (Horizontal with Wrap)
    for col_name in columns:
        # Wrap text logic
        words = col_name.split()
        lines = []
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=fonts["header"])
            w = bbox[2] - bbox[0]
            if w <= (DATA_COL_WIDTH - 5): # 5px padding
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                else:
                    # Single word is too long, force split or just add it (it will overflow slightly but better than empty)
                    lines.append(word)
                    current_line = []
        if current_line:
            lines.append(' '.join(current_line))
            
        # Draw lines from bottom up or top down? 
        # Let's draw bottom aligned to match other headers
        
        # Calculate total block height
        line_height = 0
        if lines:
             bbox = draw.textbbox((0, 0), "Aj", font=fonts["header"])
             line_height = bbox[3] - bbox[1] + 5 # +5 line spacing
             
        total_text_h = len(lines) * line_height
        
        # Start Y position
        # TABLE_TOP + HEADER_HEIGHT is bottom of header box
        # - 20 padding
        # - total_text_h
        start_y = (TABLE_TOP + HEADER_HEIGHT - 20) - total_text_h + line_height
        
        for i, line in enumerate(lines):
            draw.text((curr_x + DATA_COL_WIDTH//2, start_y + (i * line_height)), line, font=fonts["header"], fill=ACCENT_GOLD, anchor="ms") # ms = middle baseline
        
        curr_x += DATA_COL_WIDTH
        
    # Total Header
    draw.text((curr_x + TOTAL_COL_WIDTH//2, TABLE_TOP + HEADER_HEIGHT - 30), "ИТОГ", font=fonts["header"], fill=ACCENT_GOLD, anchor="mm")
    
    # 3. Rows
    y = TABLE_TOP + HEADER_HEIGHT
    
    for i, row in enumerate(rows):
        row_center_y = y + ROW_HEIGHT // 2
        
        # Zebra
        if i % 2 == 1:
            draw.rectangle([(PADDING, y), (final_width - PADDING, y + ROW_HEIGHT)], fill=ROW_ALT_COLOR)
            
        # Name
        curr_x = PADDING + 10
        draw.text((curr_x, row_center_y), row['name'], font=fonts["row_name"], fill=TEXT_WHITE, anchor="lm")
        curr_x += NAME_COL_WIDTH
        
        # Scores
        for score in row['scores']:
            val_str = str(score) if score is not None else "-"
            color = TEXT_WHITE if score is not None else TEXT_GREY
            if score == 0: color = TEXT_GREY
            
            draw.text((curr_x + DATA_COL_WIDTH//2, row_center_y), val_str, font=fonts["row_val"], fill=color, anchor="mm")
            curr_x += DATA_COL_WIDTH
            
        # Total
        draw.text((curr_x + TOTAL_COL_WIDTH//2, row_center_y), str(row['total']), font=fonts["row_total"], fill=ACCENT_CYAN, anchor="mm")
        
        # Separator
        draw.line([(PADDING, y + ROW_HEIGHT), (final_width - PADDING, y + ROW_HEIGHT)], fill=(255,255,255,30), width=1)
        
        y += ROW_HEIGHT

    # Overlay Logo
    from app.utils.image_generator import _draw_logo_overlay
    visual_center_y = (TABLE_TOP + (final_height - 20)) // 2
    _draw_logo_overlay(img, opacity=0.10, center_y=visual_center_y)

    # Save
    bio = io.BytesIO()
    img.save(bio, format='PNG')
    bio.seek(0)
    return bio
