class LexiconRU:
    NO_OPEN_TOURNAMENTS = "Сейчас нет турниров, открытых для прогнозов, или вы уже сделали прогноз на все доступные. Загляните позже!"
    CHOOSE_TOURNAMENT = "Выберите турнир для создания прогноза:"
    TOURNAMENT_NOT_FOUND = "Турнир не найден."
    TOURNAMENT_TITLE = "<b>Турнир: «{name}»</b>\nДата: {date}\n\nВыберите действие:"
    PARTICIPANTS_TITLE = "<b>Участники турнира «{name}»</b>\n\n"
    NO_PARTICIPANTS = "В этом турнире пока нет зарегистрированных участников."
    NO_PARTICIPANTS_FORECAST_IMPOSSIBLE = "В этом турнире пока нет участников. Прогноз невозможен."
    STEP_1 = "<b>Шаг 1/5:</b> Выберите, кто, по-вашему, займет <b>1 место</b>:"
    STEP_N = "<b>Шаг {next_place}/5:</b> Выберите, кто займет <b>{next_place} место</b>:"
    PLAYER_ALREADY_SELECTED = "Этот игрок уже в вашем прогнозе!"
    FINAL_FORECAST_HEADER = "<b>Ваш итоговый прогноз:</b>\n"
    CONFIRM_CHOICE = "\nПодтверждаете свой выбор?"
    FORECAST_ERROR = "Произошла ошибка, не вся информация для прогноза найдена. Попробуйте снова."
    FORECAST_UPDATED = "✅ Ваш прогноз обновлен!"
    FORECAST_ACCEPTED = "✅ Ваш прогноз принят!"
    YOUR_CHOICE = "\n\n<b>Ваш выбор:</b>\n"
    FORECAST_CANCELLED = "❌ Прогноз отменен."
    EDIT_CANCELLED = "Редактирование отменено."
    ERROR_CANCEL = "Ошибка отмены."
    TOURNAMENT_NOT_FOUND_FOR_FORECAST = "Турнир для этого прогноза не найден."
    EDIT_FORBIDDEN = "⚠️ Редактирование запрещено! Турнир уже начался или завершен."
    NO_FORECASTS_YET = "Пока нет прогнозов на этот турнир."
    ANALYTICS_TITLE = "📊 <b>Аналитика прогнозов «{name}»</b>\n"
    TOTAL_PARTICIPANTS = "Всего участников: <b>{count}</b>\n\n"
    POPULAR_TOP = "🧠 <b>Народный ТОП (мнение большинства):</b>\n<i>(на основе суммы баллов за места)</i>\n"
    FAVORITES_GOLD = "🥇 Золото"
    FAVORITES_SILVER = "🥈 Серебро"
    FAVORITES_BRONZE = "🥉 Бронза"
    FAVORITES_HEADER = "\n<b>{medal} (Фавориты):</b>\n"
    NO_DATA = "• Нет данных\n"
    CLICK_BELOW = "\n👇 Нажмите кнопку ниже, чтобы увидеть прогнозы каждого участника."
    FORECAST_LIST_TITLE = "📋 <b>Список прогнозистов</b>\nНажмите на участника, чтобы увидеть его прогноз:"
    FORECAST_DETAIL_TITLE = "👤 <b>Прогноз {name}</b>\n\n"
    POINTS_EARNED = "\n💰 Очки: <b>{points}</b>"
    UNKNOWN_PLAYER = "Неизвестный"
    BACK_BUTTON = "◀️ Назад к меню турнира"
    ALL_FORECASTS_HEADER = "📜 <b>Лента прогнозов на турнир «{name}»</b>:\n\n"
    ALL_FORECASTS_USER_HEADER = "👤 <b>{username}</b>{points_str}:\n"
    ALL_FORECASTS_LINE_ITEM = "{rank} {player}\n"
    ADMIN_PANEL_TEXT = "<b>🔧 Панель администратора</b>\n\nВыберите действие в меню ниже:"

# Backward compatibility dict (optional, but good for incremental refactor)
LEXICON_RU = {
    "no_open_tournaments": LexiconRU.NO_OPEN_TOURNAMENTS,
    "choose_tournament": LexiconRU.CHOOSE_TOURNAMENT,
    "tournament_not_found": LexiconRU.TOURNAMENT_NOT_FOUND,
    "tournament_title": LexiconRU.TOURNAMENT_TITLE,
    "participants_title": LexiconRU.PARTICIPANTS_TITLE,
    "no_participants": LexiconRU.NO_PARTICIPANTS,
    "no_participants_forecast_impossible": LexiconRU.NO_PARTICIPANTS_FORECAST_IMPOSSIBLE,
    "step_1": LexiconRU.STEP_1,
    "step_n": LexiconRU.STEP_N,
    "player_already_selected": LexiconRU.PLAYER_ALREADY_SELECTED,
    "final_forecast_header": LexiconRU.FINAL_FORECAST_HEADER,
    "confirm_choice": LexiconRU.CONFIRM_CHOICE,
    "forecast_error": LexiconRU.FORECAST_ERROR,
    "forecast_updated": LexiconRU.FORECAST_UPDATED,
    "forecast_accepted": LexiconRU.FORECAST_ACCEPTED,
    "your_choice": LexiconRU.YOUR_CHOICE,
    "forecast_cancelled": LexiconRU.FORECAST_CANCELLED,
    "edit_cancelled": LexiconRU.EDIT_CANCELLED,
    "error_cancel": LexiconRU.ERROR_CANCEL,
    "tournament_not_found_for_forecast": LexiconRU.TOURNAMENT_NOT_FOUND_FOR_FORECAST,
    "edit_forbidden": LexiconRU.EDIT_FORBIDDEN,
    "no_forecasts_yet": LexiconRU.NO_FORECASTS_YET,
    "analytics_title": LexiconRU.ANALYTICS_TITLE,
    "total_participants": LexiconRU.TOTAL_PARTICIPANTS,
    "popular_top": LexiconRU.POPULAR_TOP,
    "favorites_gold": LexiconRU.FAVORITES_GOLD,
    "favorites_silver": LexiconRU.FAVORITES_SILVER,
    "favorites_bronze": LexiconRU.FAVORITES_BRONZE,
    "favorites_header": LexiconRU.FAVORITES_HEADER,
    "no_data": LexiconRU.NO_DATA,
    "click_below": LexiconRU.CLICK_BELOW,
    "forecast_list_title": LexiconRU.FORECAST_LIST_TITLE,
    "forecast_detail_title": LexiconRU.FORECAST_DETAIL_TITLE,
    "points_earned": LexiconRU.POINTS_EARNED,
    "unknown_player": LexiconRU.UNKNOWN_PLAYER,
    "back_button": LexiconRU.BACK_BUTTON,
    "all_forecasts_header": LexiconRU.ALL_FORECASTS_HEADER,
    "all_forecasts_user_header": LexiconRU.ALL_FORECASTS_USER_HEADER,
    "all_forecasts_line_item": LexiconRU.ALL_FORECASTS_LINE_ITEM,
    "admin_panel_text": LexiconRU.ADMIN_PANEL_TEXT,
}