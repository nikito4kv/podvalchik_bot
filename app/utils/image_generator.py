import io
import logging
from time import perf_counter

from PIL import Image, ImageDraw

from app.utils.render_assets import load_font, resolve_logo_path


LOGGER = logging.getLogger(__name__)


WIDTH = 1000
BG_COLOR = (20, 24, 35)
CARD_BG = (30, 36, 50)
ACCENT_GOLD = (212, 175, 55)
ACCENT_CYAN = (0, 255, 255)
TEXT_WHITE = (240, 240, 240)
TEXT_GREY = (170, 170, 180)
BORDER_COLOR = (255, 255, 255)
ROW_ALT_COLOR = (35, 40, 60)


def _load_fonts():
    return {
        "title": load_font("arialbd.ttf", 64, "leaderboard.title"),
        "header": load_font("arialbd.ttf", 36, "leaderboard.header"),
        "row": load_font("arial.ttf", 32, "leaderboard.row"),
        "row_bold": load_font("arialbd.ttf", 32, "leaderboard.row_bold"),
        "profile_name": load_font("arialbd.ttf", 60, "profile.name"),
        "profile_rank": load_font("arial.ttf", 36, "profile.rank"),
        "stat_label": load_font("arialbd.ttf", 24, "profile.stat_label"),
        "stat_value": load_font("arialbd.ttf", 48, "profile.stat_value"),
    }


def _draw_logo_overlay(
    base_img: Image.Image, opacity: float = 0.15, center_y: int | None = None
):
    """
    Draws a centered logo watermark on top of the generated image.
    """

    logo_path = resolve_logo_path()
    if logo_path is None:
        return

    try:
        logo = Image.open(logo_path).convert("RGBA")
        target_width = int(base_img.width * 0.5)
        ratio = target_width / logo.width
        target_height = int(logo.height * ratio)
        logo = logo.resize((target_width, target_height), Image.Resampling.LANCZOS)

        overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
        x = (base_img.width - target_width) // 2
        if center_y is None:
            y = (base_img.height - target_height) // 2
        else:
            y = center_y - (target_height // 2)

        overlay.paste(logo, (x, y))
        _, _, _, alpha_channel = overlay.split()
        alpha_channel = alpha_channel.point(lambda value: int(value * opacity))
        overlay.putalpha(alpha_channel)
        base_img.paste(overlay, (0, 0), mask=overlay)
    except Exception:
        LOGGER.exception(
            "render.logo_overlay.failed logo=%s opacity=%.2f",
            logo_path.name,
            opacity,
        )


def draw_table_row(draw, y, col_data, fonts):
    for x, text, font_key, color, anchor in col_data:
        draw.text((x, y), str(text), font=fonts[font_key], fill=color, anchor=anchor)


def generate_leaderboard_image(season_name: str, leaders: list) -> io.BytesIO:
    started = perf_counter()
    try:
        header_height = 160
        row_height = 80
        padding = 20

        num_rows = min(len(leaders), 10)
        height = header_height + (num_rows * row_height) + padding + 20

        img = Image.new("RGBA", (WIDTH, height), color=BG_COLOR)
        draw = ImageDraw.Draw(img)
        fonts = _load_fonts()

        draw.text(
            (WIDTH // 2, 60),
            season_name,
            font=fonts["title"],
            fill=TEXT_WHITE,
            anchor="mm",
        )

        table_top = 120
        table_bottom = height - 20
        table_left = 20
        table_right = WIDTH - 20
        draw.rectangle(
            [(table_left, table_top), (table_right, table_bottom)],
            outline=BORDER_COLOR,
            width=3,
        )
        draw.rectangle(
            [(table_left, table_top), (table_right, table_top + 60)], fill=CARD_BG
        )
        draw.line(
            [(table_left, table_top + 60), (table_right, table_top + 60)],
            fill=BORDER_COLOR,
            width=2,
        )

        col_rank_x = 80
        col_name_x = 180
        col_games_x = 650
        col_perf_x = 780
        col_pts_x = 900
        header_y = table_top + 30
        headers = [
            (col_rank_x, "#", "header", ACCENT_GOLD, "mm"),
            (col_name_x, "Игрок", "header", ACCENT_GOLD, "lm"),
            (col_games_x, "Игр", "header", ACCENT_GOLD, "mm"),
            (col_perf_x, "Идеал", "header", ACCENT_GOLD, "mm"),
            (col_pts_x, "Очки", "header", ACCENT_GOLD, "mm"),
        ]
        draw_table_row(draw, header_y, headers, fonts)

        start_y = table_top + 60
        for index, user in enumerate(leaders[:10]):
            y = start_y + (index * row_height)
            row_center_y = y + row_height // 2
            if index % 2 == 1:
                draw.rectangle(
                    [(table_left + 2, y), (table_right - 2, y + row_height)],
                    fill=ROW_ALT_COLOR,
                )

            rank = index + 1
            name = user.get("name", "Unknown")
            points = user.get("points", 0)
            played = user.get("played", 0)
            perfects = user.get("perfects", 0)

            rank_color = TEXT_WHITE
            if rank == 1:
                rank_color = ACCENT_GOLD
            elif rank == 2:
                rank_color = (192, 192, 192)
            elif rank == 3:
                rank_color = (205, 127, 50)

            row_data = [
                (col_rank_x, str(rank), "row_bold", rank_color, "mm"),
                (col_name_x, name, "row_bold", TEXT_WHITE, "lm"),
                (col_games_x, str(played), "row", TEXT_GREY, "mm"),
                (
                    col_perf_x,
                    str(perfects) if perfects > 0 else "-",
                    "row",
                    ACCENT_CYAN if perfects > 0 else TEXT_GREY,
                    "mm",
                ),
                (col_pts_x, str(points), "row_bold", ACCENT_GOLD, "mm"),
            ]
            draw_table_row(draw, row_center_y, row_data, fonts)

            if index < len(leaders) - 1:
                draw.line(
                    [(table_left, y + row_height), (table_right, y + row_height)],
                    fill=(255, 255, 255, 30),
                    width=1,
                )

        visual_center_y = (table_top + (height - 20)) // 2
        _draw_logo_overlay(img, opacity=0.15, center_y=visual_center_y)
        bio = _save_img(img)
    except Exception:
        LOGGER.exception(
            "render.leaderboard.failed season=%s rows=%s", season_name, len(leaders)
        )
        raise

    duration_ms = (perf_counter() - started) * 1000
    LOGGER.info(
        "render.leaderboard.complete season=%s rows=%s duration_ms=%.3f",
        season_name,
        min(len(leaders), 10),
        duration_ms,
    )
    return bio


def generate_user_profile_image(user_data: dict) -> io.BytesIO:
    started = perf_counter()
    try:
        height = 700
        img = Image.new("RGBA", (WIDTH, height), color=BG_COLOR)
        draw = ImageDraw.Draw(img)
        fonts = _load_fonts()

        margin = 20
        draw.rectangle(
            [(margin, margin), (WIDTH - margin, height - margin)],
            outline=BORDER_COLOR,
            width=4,
        )

        cy_name = 100
        full_name = user_data.get("full_name", "Player")
        draw.text(
            (WIDTH // 2, cy_name),
            full_name,
            font=fonts["profile_name"],
            fill=TEXT_WHITE,
            anchor="mm",
        )

        cy_rank = 160
        rank_title = user_data.get("rank_title", "Novice").upper()
        draw.text(
            (WIDTH // 2, cy_rank),
            f"- {rank_title} -",
            font=fonts["profile_rank"],
            fill=ACCENT_GOLD,
            anchor="mm",
        )
        draw.line(
            [(WIDTH // 2 - 150, 200), (WIDTH // 2 + 150, 200)],
            fill=TEXT_GREY,
            width=2,
        )

        y_start = 260
        y_gap = 100

        def draw_stat_pair(x, y, label, value, value_color=TEXT_WHITE):
            draw.text(
                (x, y),
                label,
                font=fonts["stat_label"],
                fill=TEXT_GREY,
                anchor="mm",
            )
            draw.text(
                (x, y + 40),
                str(value),
                font=fonts["stat_value"],
                fill=value_color,
                anchor="mm",
            )

        col1 = WIDTH // 3
        col2 = WIDTH * 2 // 3

        y1 = y_start
        draw_stat_pair(col1, y1, "ОЧКИ", user_data.get("total_points", 0), ACCENT_GOLD)
        draw_stat_pair(col2, y1, "РЕЙТИНГ", f"#{user_data.get('rank_pos', '-')}")

        y2 = y1 + y_gap
        draw_stat_pair(col1, y2, "ТУРНИРОВ", user_data.get("played", 0))
        draw_stat_pair(col2, y2, "СРЕДНИЙ БАЛЛ", user_data.get("avg_score", 0.0))

        y3 = y2 + y_gap
        current_streak = user_data.get("current_streak", 0)
        max_streak = user_data.get("max_streak", 0)
        streak_color = (255, 100, 100) if current_streak > 0 else TEXT_WHITE
        draw_stat_pair(col1, y3, "СЕРИЯ", current_streak, streak_color)
        draw_stat_pair(col2, y3, "МАКС. СЕРИЯ", max_streak)

        y4 = y3 + y_gap
        draw_stat_pair(col1, y4, "ИДЕАЛЬНО", user_data.get("perfects", 0), ACCENT_CYAN)
        draw_stat_pair(col2, y4, "В ЯБЛОЧКО", user_data.get("exacts", 0), ACCENT_CYAN)

        _draw_logo_overlay(img, opacity=0.15)
        bio = _save_img(img)
    except Exception:
        LOGGER.exception(
            "render.profile.failed user=%s", user_data.get("full_name", "unknown")
        )
        raise

    duration_ms = (perf_counter() - started) * 1000
    LOGGER.info(
        "render.profile.complete user=%s duration_ms=%.3f",
        user_data.get("full_name", "unknown"),
        duration_ms,
    )
    return bio


def _save_img(img):
    final_img = img.convert("RGB")
    bio = io.BytesIO()
    final_img.save(bio, format="PNG")
    bio.seek(0)
    return bio
