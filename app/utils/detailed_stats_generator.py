import io
import logging
from time import perf_counter

from PIL import Image, ImageDraw

from app.utils.image_generator import _draw_logo_overlay
from app.utils.render_assets import load_font


LOGGER = logging.getLogger(__name__)


WIDTH = 1200
MIN_HEIGHT = 600
BG_COLOR = (20, 24, 35)
CARD_BG = (30, 36, 50)
ACCENT_GOLD = (212, 175, 55)
ACCENT_CYAN = (0, 255, 255)
TEXT_WHITE = (240, 240, 240)
TEXT_GREY = (170, 170, 180)
ROW_ALT_COLOR = (35, 40, 60)


def _load_fonts():
    return {
        "title": load_font("arialbd.ttf", 48, "season_detail.title"),
        "header": load_font("arialbd.ttf", 24, "season_detail.header"),
        "row_name": load_font("arialbd.ttf", 24, "season_detail.row_name"),
        "row_val": load_font("arial.ttf", 24, "season_detail.row_val"),
        "row_total": load_font("arialbd.ttf", 26, "season_detail.row_total"),
    }


def generate_detailed_season_image(
    season_title: str, columns: list, rows: list
) -> io.BytesIO:
    started = perf_counter()
    try:
        name_col_width = 250
        data_col_width = 100
        total_col_width = 100
        padding = 20
        table_top = 100
        header_height = 150
        row_height = 50

        calculated_width = (
            name_col_width
            + (len(columns) * data_col_width)
            + total_col_width
            + (padding * 2)
        )
        final_width = max(WIDTH, calculated_width)
        final_height = max(
            MIN_HEIGHT,
            table_top + header_height + (len(rows) * row_height) + padding + 20,
        )

        img = Image.new("RGBA", (final_width, final_height), color=BG_COLOR)
        draw = ImageDraw.Draw(img)
        fonts = _load_fonts()

        draw.text(
            (final_width // 2, 40),
            season_title,
            font=fonts["title"],
            fill=TEXT_WHITE,
            anchor="mm",
        )
        draw.rectangle(
            [(padding, table_top), (final_width - padding, table_top + header_height)],
            fill=CARD_BG,
        )

        curr_x = padding + 10
        draw.text(
            (curr_x, table_top + header_height - 30),
            "Игрок",
            font=fonts["header"],
            fill=ACCENT_GOLD,
            anchor="lm",
        )
        curr_x += name_col_width

        for column_name in columns:
            words = column_name.split()
            lines = []
            current_line = []
            for word in words:
                test_line = " ".join(current_line + [word])
                bbox = draw.textbbox((0, 0), test_line, font=fonts["header"])
                width = bbox[2] - bbox[0]
                if width <= (data_col_width - 5):
                    current_line.append(word)
                    continue
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)
            if current_line:
                lines.append(" ".join(current_line))

            bbox = draw.textbbox((0, 0), "Aj", font=fonts["header"])
            line_height = (bbox[3] - bbox[1]) + 5
            total_text_height = len(lines) * line_height
            start_y = (table_top + header_height - 20) - total_text_height + line_height
            for index, line in enumerate(lines):
                draw.text(
                    (curr_x + data_col_width // 2, start_y + (index * line_height)),
                    line,
                    font=fonts["header"],
                    fill=ACCENT_GOLD,
                    anchor="ms",
                )
            curr_x += data_col_width

        draw.text(
            (curr_x + total_col_width // 2, table_top + header_height - 30),
            "ИТОГ",
            font=fonts["header"],
            fill=ACCENT_GOLD,
            anchor="mm",
        )

        y = table_top + header_height
        for index, row in enumerate(rows):
            row_center_y = y + row_height // 2
            if index % 2 == 1:
                draw.rectangle(
                    [(padding, y), (final_width - padding, y + row_height)],
                    fill=ROW_ALT_COLOR,
                )

            curr_x = padding + 10
            draw.text(
                (curr_x, row_center_y),
                row["name"],
                font=fonts["row_name"],
                fill=TEXT_WHITE,
                anchor="lm",
            )
            curr_x += name_col_width

            for score in row["scores"]:
                value = str(score) if score is not None else "-"
                color = TEXT_WHITE if score is not None else TEXT_GREY
                if score == 0:
                    color = TEXT_GREY
                draw.text(
                    (curr_x + data_col_width // 2, row_center_y),
                    value,
                    font=fonts["row_val"],
                    fill=color,
                    anchor="mm",
                )
                curr_x += data_col_width

            draw.text(
                (curr_x + total_col_width // 2, row_center_y),
                str(row["total"]),
                font=fonts["row_total"],
                fill=ACCENT_CYAN,
                anchor="mm",
            )
            draw.line(
                [(padding, y + row_height), (final_width - padding, y + row_height)],
                fill=(255, 255, 255, 30),
                width=1,
            )
            y += row_height

        visual_center_y = (table_top + (final_height - 20)) // 2
        _draw_logo_overlay(img, opacity=0.10, center_y=visual_center_y)

        bio = io.BytesIO()
        img.convert("RGB").save(bio, format="PNG")
        bio.seek(0)
    except Exception:
        LOGGER.exception(
            "render.season_detail.failed title=%s columns=%s rows=%s",
            season_title,
            len(columns),
            len(rows),
        )
        raise

    duration_ms = (perf_counter() - started) * 1000
    LOGGER.info(
        "render.season_detail.complete title=%s columns=%s rows=%s duration_ms=%.3f",
        season_title,
        len(columns),
        len(rows),
        duration_ms,
    )
    return bio
