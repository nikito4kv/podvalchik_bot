import logging
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FONTS_DIR = PROJECT_ROOT / "fonts"


@lru_cache(maxsize=None)
def resolve_font_path(filename: str) -> Path | None:
    candidates = [FONTS_DIR / filename, PROJECT_ROOT / filename]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    LOGGER.warning("render.asset_missing asset=%s", filename)
    return None


def load_font(filename: str, size: int, role: str):
    font_path = resolve_font_path(filename)
    if font_path is None:
        LOGGER.warning(
            "render.font_fallback role=%s font=%s size=%s reason=missing",
            role,
            filename,
            size,
        )
        return ImageFont.load_default()

    try:
        return ImageFont.truetype(str(font_path), size)
    except OSError:
        LOGGER.exception(
            "render.font_fallback role=%s font=%s size=%s reason=load_error",
            role,
            filename,
            size,
        )
        return ImageFont.load_default()


@lru_cache(maxsize=None)
def resolve_logo_path() -> Path | None:
    for filename in ("logo.png", "logo.jpg"):
        candidate = PROJECT_ROOT / filename
        if candidate.exists():
            return candidate
    LOGGER.warning("render.asset_missing asset=logo")
    return None
