import html
from collections.abc import Container, Mapping, Sequence

from app.utils.formatting import get_medal_str


def build_forecast_card_text(
    tournament_name: str,
    tournament_date_str: str,
    player_ids: Sequence[int],
    players_map: Mapping[int, object],
    *,
    escape_html: bool = True,
) -> str:
    safe_tournament_name = (
        html.escape(tournament_name) if escape_html else tournament_name
    )
    text = (
        f"<b>Ваш прогноз на турнир «{safe_tournament_name}» "
        f"от {tournament_date_str}:</b>\n\n"
    )

    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, player_id in enumerate(player_ids):
        place = medals.get(i, f" {i + 1}.")
        player = players_map.get(player_id)
        if player:
            player_name = getattr(player, "full_name", "Неизвестный игрок")
            safe_player_name = html.escape(player_name) if escape_html else player_name
            rating = getattr(player, "current_rating", None)
            rating_str = f" ({rating})" if rating is not None else ""
            name_str = f"{safe_player_name}{rating_str}"
        else:
            name_str = "Неизвестный игрок"
        text += f"{place} {name_str}\n"

    return text


def get_forecast_view_flags(
    tournament_status: object, user_id: int, admin_ids: Container[int]
) -> tuple[bool, bool, bool]:
    status_name = getattr(tournament_status, "name", None)
    status_str = status_name if isinstance(status_name, str) else str(tournament_status)
    allow_edit = status_str == "OPEN"
    is_admin = user_id in admin_ids
    show_others = (status_str != "OPEN") or is_admin
    return allow_edit, is_admin, show_others


def build_history_details_text(
    tournament_name: str,
    tournament_date_str: str,
    pred_ids: Sequence[int],
    results: Mapping[str, int] | Mapping[int, int],
    players_map: Mapping[int, object],
    points_earned: int | None,
) -> str:
    normalized_results = {int(k): int(v) for k, v in results.items()}
    sorted_results = sorted(normalized_results.items(), key=lambda item: item[1])

    safe_t_name = html.escape(tournament_name)
    results_text = (
        f"<b>🏆 Итоги турнира «{safe_t_name}» ({tournament_date_str})</b>\n\n"
    )
    for pid, rank in sorted_results:
        p_obj = players_map.get(pid)
        p_name = html.escape(getattr(p_obj, "full_name", "Неизвестный"))
        medal = get_medal_str(rank)
        results_text += f"{medal} {p_name}\n"

    prediction_text = "\n<b>📜 Ваш прогноз:</b>\n"
    current_hits = 0

    for i, pid in enumerate(pred_ids):
        predicted_rank = i + 1
        p_obj = players_map.get(pid)
        p_name = html.escape(getattr(p_obj, "full_name", "Неизвестный"))

        line_points = 0
        extra_info = ""
        if pid in normalized_results:
            actual_rank = normalized_results[pid]
            diff = abs(predicted_rank - actual_rank)
            if diff == 0:
                line_points = 5
                extra_info = " (🎯 Точно!)"
                current_hits += 1
            else:
                line_points = 1
                extra_info = f" (факт: {actual_rank})"
        else:
            extra_info = " (не в топе)"

        prediction_text += (
            f"{predicted_rank}. {p_name}{extra_info} — <b>+{line_points}</b>\n"
        )

    if current_hits == len(pred_ids) and len(pred_ids) > 0:
        prediction_text += "\n🎉 <b>БОНУС: +15 очков за идеальный прогноз!</b>\n"

    return (
        results_text
        + prediction_text
        + f"\n<b>💰 Итого очков:</b> {points_earned or 0}"
    )
