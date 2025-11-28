from typing import List, Dict

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

def draw_progress_bar(percent: int, length: int = 8) -> str:
    """
    Draws a text progress bar.
    Example:
    [■■■■□□□□]
    """
    filled_len = int(length * percent / 100)
    bar = "■" * filled_len + "□" * (length - filled_len)
    return f"<code>[{bar}]</code>"