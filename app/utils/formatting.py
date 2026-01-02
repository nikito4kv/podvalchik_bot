from typing import List, Dict

# Need to import User model? No, to avoid circular imports, we'll pass attributes or a duck-typed object.
# But typing is good. We can use 'Any' or just expect attributes.

def get_medal_str(rank: int) -> str:
    """Returns a medal icon or the rank number formatted."""
    if rank == 1: return "🥇"
    if rank == 2: return "🥈"
    if rank == 3: return "🥉"
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
    if points < 50: return "👶 Новичок"
    if points < 200: return "🧢 Любитель"
    if points < 500: return "🎱 Профи"
    if points < 1000: return "🧠 Эксперт"
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
