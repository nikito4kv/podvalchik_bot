from html import escape
from typing import Dict, Iterable, List

# Need to import User model? No, to avoid circular imports, we'll pass attributes or a duck-typed object.
# But typing is good. We can use 'Any' or just expect attributes.


def get_medal_str(rank: int) -> str:
    """Returns a medal icon or the rank number formatted."""
    if rank == 1:
        return "🥇"
    if rank == 2:
        return "🥈"
    if rank == 3:
        return "🥉"
    return f"{rank}."


def format_player_list(player_ids: List[int], player_names_map: Dict[int, str]) -> str:
    """
    Generates a formatted list of players with ranks.
    Example:
    🥇 Ma Long
    🥈 Fan Zhendong
    """
    lines = []
    for i, pid in enumerate(player_ids):
        rank = i + 1
        name = player_names_map.get(pid, "Неизвестный")
        medal = get_medal_str(rank)
        lines.append(f"{medal} {name}")
    return "\n".join(lines)


def get_user_rank(points: int) -> str:
    """Returns the user's rank title based on points."""
    if points < 50:
        return "👶 Новичок"
    if points < 200:
        return "🧢 Любитель"
    if points < 500:
        return "🎱 Профи"
    if points < 1000:
        return "🧠 Эксперт"
    return "🔮 Оракул"


def format_user_name(user: object) -> str:
    """
    Returns a formatted user name with username if available.
    Format: "Full Name (@username)" or "Full Name" or "@username" or "id:123".
    Accepts a User model object or any object with full_name, username, id attributes.
    """
    full_name = getattr(user, "full_name", None)
    username = getattr(user, "username", None)
    user_id = getattr(user, "id", "?")

    if full_name and username:
        return f"{full_name} (@{username})"
    if full_name:
        return full_name
    if username:
        return f"@{username}"
    return f"id:{user_id}"


def format_breadcrumbs(path_elements: List[str]) -> str:
    """
    Formats a list of path elements into a breadcrumb string.
    Example: ["Главная", "Рейтинг клуба", "Текущий сезон"] -> "🏠 Главная > Рейтинг клуба > Текущий сезон"
    """
    if not path_elements:
        return ""

    # Always start with Home emoji for the first element
    elements_with_emoji = []
    if path_elements[0] == "Главная":
        elements_with_emoji.append("🏠 Главная")
        remaining_elements = path_elements[1:]
    else:
        # If the first element is not "Главная", we still might want to prepend "🏠"
        # Or just use the element as is. For now, let's just use it as is.
        elements_with_emoji.append(path_elements[0])
        remaining_elements = path_elements[1:]

    # Add other elements
    elements_with_emoji.extend(remaining_elements)

    return " > ".join(elements_with_emoji)


def format_user_profile_text(user_data: dict) -> str:
    full_name = escape(str(user_data.get("full_name") or "Игрок"))
    rank_title = escape(str(user_data.get("rank_title") or "Без ранга"))
    total_points = user_data.get("total_points", 0)
    rank_pos = user_data.get("rank_pos") or "-"
    played = user_data.get("played", 0)
    avg_score = user_data.get("avg_score", 0.0)
    perfects = user_data.get("perfects", 0)
    exacts = user_data.get("exacts", 0)
    current_streak = user_data.get("current_streak", 0)
    max_streak = user_data.get("max_streak", 0)

    return "\n".join(
        [
            f"<b>📊 Статистика игрока {full_name}</b>",
            f"<i>{rank_title}</i>",
            "",
            f"🏅 Очки: <b>{total_points}</b>",
            f"📈 Рейтинг: <b>#{rank_pos}</b>",
            f"🏓 Турниров: <b>{played}</b>",
            f"📊 Средний балл: <b>{avg_score}</b>",
            f"🎯 Идеально: <b>{perfects}</b>",
            f"🎲 В яблочко: <b>{exacts}</b>",
            f"🔥 Серия: <b>{current_streak}</b>",
            f"🏆 Макс. серия: <b>{max_streak}</b>",
        ]
    )


def format_leaderboard_entries(leaders: List[dict], limit: int = 10) -> str:
    if not leaders:
        return "Пока нет данных."

    lines = []
    for index, user in enumerate(leaders[:limit], start=1):
        medal = get_medal_str(index)
        name = escape(str(user.get("name") or "Неизвестный игрок"))
        points = user.get("points", 0)
        played = user.get("played", 0)
        perfects = user.get("perfects", 0)

        details = [f"🏅 {points}", f"🏓 {played}"]
        if perfects:
            details.append(f"🎯 {perfects}")

        lines.append(f"{medal} <b>{name}</b> — {' • '.join(details)}")

    return "\n".join(lines)


def _wrap_tokens(tokens: Iterable[str], max_line_length: int = 56) -> List[str]:
    lines: List[str] = []
    current_line = ""

    for token in tokens:
        if not current_line:
            current_line = token
            continue

        candidate = f"{current_line} • {token}"
        if len(candidate) <= max_line_length:
            current_line = candidate
            continue

        lines.append(current_line)
        current_line = token

    if current_line:
        lines.append(current_line)

    return lines


def format_detailed_season_rows(
    columns: List[str], rows: List[dict], max_line_length: int = 56
) -> List[str]:
    blocks: List[str] = []

    for index, row in enumerate(rows, start=1):
        name = escape(str(row.get("name") or "Неизвестный игрок"))
        total = row.get("total", 0)
        header = f"{get_medal_str(index)} <b>{name}</b> — <b>{total}</b>"

        score_tokens = []
        for column_name, score in zip(columns, row.get("scores", [])):
            value = "-" if score is None else str(score)
            score_tokens.append(f"{escape(column_name)}: {value}")

        wrapped_lines = _wrap_tokens(score_tokens, max_line_length=max_line_length)
        if wrapped_lines:
            blocks.append("\n".join([header, *wrapped_lines]))
        else:
            blocks.append(header)

    return blocks


def split_text_chunks(text: str, limit: int = 4000) -> List[str]:
    if len(text) <= limit:
        return [text]

    parts = text.split("\n\n")
    chunks: List[str] = []
    current = ""

    for part in parts:
        if not current:
            candidate = part
        else:
            candidate = f"{current}\n\n{part}"

        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(part) <= limit:
            current = part
            continue

        lines = part.split("\n")
        for line in lines:
            if not current:
                candidate = line
            else:
                candidate = f"{current}\n{line}"

            if len(candidate) <= limit:
                current = candidate
                continue

            if current:
                chunks.append(current)
            current = line

    if current:
        chunks.append(current)

    return chunks
