import logging
from datetime import date, datetime, timedelta
from html import escape
from time import perf_counter
from typing import cast

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.core.seasonal import get_current_season_number, get_season_dates
from app.db.models import (
    Forecast,
    Season,
    SeasonResult,
    Tournament,
    TournamentStatus,
    User,
)
from app.db.session import async_session
from app.keyboards.inline import cancel_fsm_kb
from app.states.user_states import LeaderboardState
from app.utils.formatting import (
    format_breadcrumbs,
    format_detailed_season_rows,
    format_leaderboard_entries,
    format_user_profile_text,
    get_user_rank,
    split_text_chunks,
)
from app.utils.leaderboard_data import (
    build_daily_leaderboard_snapshot,
    build_detailed_season_snapshot,
)
from app.utils.stats_calculator import calculate_user_tournament_streaks


LOGGER = logging.getLogger(__name__)
router = Router()


async def delete_message_safe(bot: Bot, chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as exc:
        LOGGER.warning(
            "stats.text.cleanup_failed chat_id=%s message_id=%s error=%s",
            chat_id,
            message_id,
            exc,
        )


async def answer_callback_safe(callback: types.CallbackQuery, *args, **kwargs) -> bool:
    try:
        await callback.answer(*args, **kwargs)
        return True
    except TelegramBadRequest as exc:
        error_text = str(exc).lower()
        if "query is too old" in error_text or "query id is invalid" in error_text:
            LOGGER.info(
                "stats.callback.answer_skipped callback_data=%s error=%s",
                callback.data,
                exc,
            )
            return False
        raise
    except TelegramNetworkError as exc:
        error_text = str(exc).lower()
        if "timeout" not in error_text:
            raise
        LOGGER.warning(
            "stats.callback.answer_failed callback_data=%s error=%s",
            callback.data,
            exc,
        )
        return False


def require_message(callback: types.CallbackQuery) -> types.Message:
    message = callback.message
    if not isinstance(message, types.Message):
        raise RuntimeError("Callback message is unavailable")
    return message


def require_bot(bot: Bot | None) -> Bot:
    if bot is None:
        raise RuntimeError("Bot instance is unavailable")
    return bot


def require_callback_data(callback: types.CallbackQuery) -> str:
    data = callback.data
    if data is None:
        raise RuntimeError("Callback data is unavailable")
    return data


async def prepare_loading_message(
    message_or_cb: types.Message | types.CallbackQuery, loading_text: str
) -> types.Message:
    if isinstance(message_or_cb, types.CallbackQuery):
        await answer_callback_safe(message_or_cb)
        return require_message(message_or_cb)

    return await message_or_cb.answer(loading_text)


async def send_or_update_text(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    message_to_edit: types.Message | None = None,
) -> types.Message:
    chunks = split_text_chunks(text)

    if (
        message_to_edit is not None
        and message_to_edit.content_type == types.ContentType.TEXT
    ):
        await message_to_edit.edit_text(
            chunks[0],
            reply_markup=reply_markup if len(chunks) == 1 else None,
            parse_mode="HTML",
        )
        anchor_message = message_to_edit
    else:
        anchor_message = await bot.send_message(
            chat_id,
            chunks[0],
            reply_markup=reply_markup if len(chunks) == 1 else None,
            parse_mode="HTML",
        )
        if message_to_edit is not None:
            await delete_message_safe(bot, chat_id, message_to_edit.message_id)

    last_message = anchor_message
    for index, chunk in enumerate(chunks[1:], start=1):
        last_message = await bot.send_message(
            chat_id,
            chunk,
            reply_markup=reply_markup if index == len(chunks) - 1 else None,
            parse_mode="HTML",
        )

    return last_message


def build_leaderboard_text(
    breadcrumbs: list[str],
    title: str,
    leaders: list[dict],
    subtitle_lines: list[str] | None = None,
) -> str:
    sections = [format_breadcrumbs(breadcrumbs), f"<b>{escape(title)}</b>"]
    if subtitle_lines:
        sections.append("\n".join(subtitle_lines))
    sections.append(format_leaderboard_entries(leaders))
    return "\n\n".join(section for section in sections if section)


def build_detailed_season_text(
    season_number: int,
    date_range: str,
    columns: list[str],
    rows: list[dict],
) -> str:
    header = "\n\n".join(
        [
            format_breadcrumbs(
                [
                    "Главная",
                    "Рейтинг клуба",
                    "История сезонов",
                    f"Сезон #{season_number}",
                    "Детально",
                ]
            ),
            f"<b>📊 Детальная статистика сезона #{season_number}</b>",
            f"<i>{escape(date_range)}</i>",
        ]
    )
    blocks = format_detailed_season_rows(columns, rows)
    if not blocks:
        return header
    return "\n\n".join([header, *blocks])


def leaderboard_kb(current_view: str = "season"):
    builder = InlineKeyboardBuilder()

    if current_view == "menu":
        builder.button(text="📅 Текущий сезон", callback_data="leaderboard:season")
        builder.button(text="🌍 За все время", callback_data="leaderboard:global")
        builder.button(text="📆 Рейтинг дня", callback_data="leaderboard:daily:menu")
        builder.button(
            text="📜 История сезонов", callback_data="leaderboard:history:list"
        )
        builder.adjust(1)
        return builder.as_markup()

    if current_view == "season":
        builder.button(text="🌍 За все время", callback_data="leaderboard:global")
        builder.button(text="📆 Рейтинг дня", callback_data="leaderboard:daily:menu")
        builder.button(
            text="📜 История сезонов", callback_data="leaderboard:history:list"
        )
    elif current_view == "global":
        builder.button(text="📅 Текущий сезон", callback_data="leaderboard:season")
        builder.button(text="📆 Рейтинг дня", callback_data="leaderboard:daily:menu")
        builder.button(
            text="📜 История сезонов", callback_data="leaderboard:history:list"
        )

    builder.button(text="↩️ К выбору рейтинга", callback_data="leaderboard:menu")
    builder.adjust(2)
    return builder.as_markup()


def daily_date_selection_kb():
    builder = InlineKeyboardBuilder()

    import pytz

    tz = pytz.timezone("Asia/Tbilisi")
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    day_before_yesterday = today - timedelta(days=2)

    builder.button(
        text=f"Сегодня ({today.strftime('%d.%m')})",
        callback_data=f"leaderboard:daily:date_pick:{today.isoformat()}",
    )
    builder.button(
        text=f"Вчера ({yesterday.strftime('%d.%m')})",
        callback_data=f"leaderboard:daily:date_pick:{yesterday.isoformat()}",
    )
    builder.button(
        text=f"Позавчера ({day_before_yesterday.strftime('%d.%m')})",
        callback_data=f"leaderboard:daily:date_pick:{day_before_yesterday.isoformat()}",
    )

    builder.row(
        InlineKeyboardButton(
            text="✍️ Ввести дату вручную",
            callback_data="leaderboard:daily:date_input_manual",
        )
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="leaderboard:daily:menu")
    )
    builder.adjust(1)
    return builder.as_markup()


def leaderboard_daily_modes_kb(viewing_mode: str = "other"):
    builder = InlineKeyboardBuilder()

    if viewing_mode != "today":
        builder.button(
            text="📅 Топ за сегодня", callback_data="leaderboard:daily:today"
        )
    if viewing_mode != "yesterday":
        builder.button(
            text="⏮ Топ за вчера", callback_data="leaderboard:daily:yesterday"
        )

    builder.button(text="📆 Выбрать дату", callback_data="leaderboard:daily:select")
    builder.button(text="↩️ К выбору рейтинга", callback_data="leaderboard:menu")
    builder.adjust(1)
    return builder.as_markup()


def season_history_kb(seasons: list, page: int = 0):
    builder = InlineKeyboardBuilder()
    items_per_page = 5

    start = page * items_per_page
    end = start + items_per_page
    current_page_seasons = seasons[start:end]
    for season in current_page_seasons:
        dates = f"{season.start_date.strftime('%d.%m')} - {season.end_date.strftime('%d.%m')}"
        builder.button(
            text=f"Сезон {season.number} ({dates})",
            callback_data=f"leaderboard:history:view:{season.id}",
        )

    builder.adjust(1)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            types.InlineKeyboardButton(
                text="⬅️", callback_data=f"leaderboard:history:page:{page - 1}"
            )
        )
    if end < len(seasons):
        nav_buttons.append(
            types.InlineKeyboardButton(
                text="➡️", callback_data=f"leaderboard:history:page:{page + 1}"
            )
        )

    if nav_buttons:
        builder.row(*nav_buttons)
    builder.row(
        types.InlineKeyboardButton(
            text="↩️ Назад к рейтингу", callback_data="leaderboard:menu"
        )
    )
    return builder.as_markup()


async def build_user_profile_data(
    user_id: int, display_name: str | None = None
) -> dict | None:
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            return None

        current_streak, max_streak = await calculate_user_tournament_streaks(
            session, user_id
        )
        rank_subquery = select(
            User.id,
            func.rank()
            .over(
                order_by=[
                    User.total_points.desc(),
                    User.perfect_tournaments.desc(),
                    User.exact_guesses.desc(),
                    User.tournaments_played.asc(),
                    User.id.asc(),
                ]
            )
            .label("rank_val"),
        ).subquery()
        current_rank = await session.scalar(
            select(rank_subquery.c.rank_val).where(rank_subquery.c.id == user.id)
        )

        tournaments_played = cast(int, user.tournaments_played or 0)
        total_points = cast(int, user.total_points or 0)
        perfect_tournaments = cast(int, user.perfect_tournaments or 0)
        exact_guesses = cast(int, user.exact_guesses or 0)
        avg_score = (
            round(total_points / tournaments_played, 1)
            if tournaments_played > 0
            else 0.0
        )
        rank_title_full = get_user_rank(total_points)
        parts = rank_title_full.split()
        rank_title = parts[-1] if len(parts) > 1 else rank_title_full

        return {
            "full_name": display_name or user.full_name,
            "rank_title": rank_title,
            "league_emoji": "",
            "total_points": total_points,
            "rank_pos": current_rank,
            "played": tournaments_played,
            "avg_score": avg_score,
            "perfects": perfect_tournaments,
            "exacts": exact_guesses,
            "current_streak": current_streak,
            "max_streak": max_streak,
        }


@router.message(F.text == "📊 Моя статистика")
async def handle_my_stats(message: types.Message):
    started = perf_counter()
    from_user = message.from_user
    if from_user is None:
        return

    user_data = await build_user_profile_data(from_user.id, from_user.full_name)
    if user_data is None:
        await message.answer("Не удалось найти вашу статистику. Попробуйте /start")
        LOGGER.warning("stats.request.user_missing user_id=%s", from_user.id)
        return

    text = "\n\n".join(
        [
            format_breadcrumbs(["Главная", "Моя статистика"]),
            format_user_profile_text(user_data),
        ]
    )
    await send_or_update_text(
        bot=require_bot(message.bot),
        chat_id=message.chat.id,
        text=text,
    )

    duration_ms = (perf_counter() - started) * 1000
    LOGGER.info(
        "stats.request.complete user_id=%s duration_ms=%.3f db_writes=0 current_streak=%s max_streak=%s output=text",
        from_user.id,
        duration_ms,
        user_data["current_streak"],
        user_data["max_streak"],
    )


@router.message(F.text == "🏆 Рейтинг клуба")
async def handle_leaderboard(message: types.Message):
    await show_leaderboard_menu(message)


async def show_leaderboard_menu(
    message_or_cb: types.Message | types.CallbackQuery,
) -> None:
    is_callback = isinstance(message_or_cb, types.CallbackQuery)
    bot_instance = require_bot(message_or_cb.bot)
    if is_callback:
        source_message = require_message(message_or_cb)
        chat_id = source_message.chat.id
        target_message = source_message
        await answer_callback_safe(message_or_cb)
    else:
        chat_id = message_or_cb.chat.id
        target_message = None

    text = (
        f"{format_breadcrumbs(['Главная', 'Рейтинг клуба'])}\n\n"
        "<b>🏆 Рейтинг клуба</b>\n"
        "Выберите, какой рейтинг хотите посмотреть:"
    )
    await send_or_update_text(
        bot=bot_instance,
        chat_id=chat_id,
        text=text,
        reply_markup=leaderboard_kb("menu"),
        message_to_edit=target_message,
    )


@router.callback_query(F.data == "leaderboard:menu")
async def cq_leaderboard_menu(callback: types.CallbackQuery):
    await show_leaderboard_menu(callback)


async def show_seasonal_leaderboard(message_or_cb: types.Message | types.CallbackQuery):
    is_callback = isinstance(message_or_cb, types.CallbackQuery)
    bot_instance = require_bot(message_or_cb.bot)
    if is_callback:
        source_message = require_message(message_or_cb)
        chat_id = source_message.chat.id
    else:
        chat_id = message_or_cb.chat.id

    target_message = await prepare_loading_message(
        message_or_cb, "⏳ Загружаю рейтинг..."
    )

    async with async_session() as session:
        season_number = get_current_season_number()
        start_date, end_date = get_season_dates(season_number)
        tournament_ids = (
            (
                await session.execute(
                    select(Tournament.id).where(
                        Tournament.date >= start_date,
                        Tournament.date <= end_date,
                    )
                )
            )
            .scalars()
            .all()
        )

        leaders_data = []
        if tournament_ids:
            stats_stmt = (
                select(
                    Forecast.user_id,
                    func.sum(Forecast.points_earned).label("total_points"),
                    func.count(Forecast.id).label("played"),
                    User.full_name,
                    User.username,
                )
                .join(User, Forecast.user_id == User.id)
                .where(Forecast.tournament_id.in_(tournament_ids))
                .group_by(Forecast.user_id, User.full_name, User.username)
                .order_by(func.sum(Forecast.points_earned).desc())
                .limit(10)
            )
            for row in (await session.execute(stats_stmt)).all():
                name = row.full_name or row.username or f"id:{row.user_id}"
                rank_str = get_user_rank(row.total_points or 0)
                league_emoji = rank_str.split()[0] if rank_str else ""
                leaders_data.append(
                    {
                        "user_id": row.user_id,
                        "name": name,
                        "points": row.total_points or 0,
                        "played": row.played,
                        "perfects": 0,
                        "league_emoji": league_emoji,
                    }
                )

    text = build_leaderboard_text(
        ["Главная", "Рейтинг клуба", "Текущий сезон"],
        f"📅 Текущий сезон #{season_number}",
        leaders_data,
        subtitle_lines=[
            f"<i>{start_date.strftime('%d.%m')} — {end_date.strftime('%d.%m')}</i>",
            "Рейтинг обновляется в реальном времени после каждого турнира.",
        ],
    )
    await send_or_update_text(
        bot=bot_instance,
        chat_id=chat_id,
        text=text,
        reply_markup=leaderboard_kb("season"),
        message_to_edit=target_message,
    )


@router.callback_query(F.data == "leaderboard:season")
async def cq_leaderboard_season(callback: types.CallbackQuery):
    await show_seasonal_leaderboard(callback)


@router.callback_query(F.data == "leaderboard:global")
async def cq_leaderboard_global(callback: types.CallbackQuery):
    message = require_message(callback)
    chat_id = message.chat.id
    bot_instance = require_bot(callback.bot)
    target_message = await prepare_loading_message(callback, "⏳ Загружаю рейтинг...")

    async with async_session() as session:
        top_users = (
            (
                await session.execute(
                    select(User)
                    .order_by(User.total_points.desc(), User.perfect_tournaments.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )

    leaders_data = []
    for user in top_users:
        name = user.full_name or user.username or f"id:{user.id}"
        total_points = cast(int, user.total_points or 0)
        rank_str = get_user_rank(total_points)
        league_emoji = rank_str.split()[0] if rank_str else ""
        leaders_data.append(
            {
                "user_id": user.id,
                "name": name,
                "points": total_points,
                "played": cast(int, user.tournaments_played or 0),
                "perfects": cast(int, user.perfect_tournaments or 0),
                "league_emoji": league_emoji,
            }
        )

    text = build_leaderboard_text(
        ["Главная", "Рейтинг клуба", "За все время"],
        "🌍 Глобальный рейтинг клуба",
        leaders_data,
        subtitle_lines=["Сумма очков за всю историю."],
    )
    await send_or_update_text(
        bot=bot_instance,
        chat_id=chat_id,
        text=text,
        reply_markup=leaderboard_kb("global"),
        message_to_edit=target_message,
    )


@router.callback_query(F.data == "leaderboard:history:list")
async def cq_leaderboard_history_list(callback: types.CallbackQuery):
    await answer_callback_safe(callback)
    await show_history_list(callback, page=0)


@router.callback_query(F.data.startswith("leaderboard:history:page:"))
async def cq_leaderboard_history_page(callback: types.CallbackQuery):
    await answer_callback_safe(callback)
    callback_data = require_callback_data(callback)
    await show_history_list(callback, int(callback_data.split(":")[-1]))


async def show_history_list(callback: types.CallbackQuery, page: int):
    message = require_message(callback)
    if message.content_type == types.ContentType.PHOTO:
        await delete_message_safe(
            require_bot(callback.bot), message.chat.id, message.message_id
        )

    async with async_session() as session:
        seasons = (
            (await session.execute(select(Season).order_by(Season.number.desc())))
            .scalars()
            .all()
        )

    if not seasons:
        await message.answer("История сезонов пуста.", parse_mode="HTML")
        return

    text = (
        f"{format_breadcrumbs(['Главная', 'Рейтинг клуба', 'История сезонов'])}\n\n"
        "<b>📜 Архив сезонов</b>\nВыберите сезон для просмотра итогов:"
    )
    seasons_list = list(seasons)
    if message.content_type == types.ContentType.TEXT:
        await message.edit_text(
            text, reply_markup=season_history_kb(seasons_list, page), parse_mode="HTML"
        )
    else:
        await message.answer(
            text,
            reply_markup=season_history_kb(seasons_list, page),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("leaderboard:history:view:"))
async def cq_leaderboard_history_view(callback: types.CallbackQuery):
    message = require_message(callback)
    chat_id = message.chat.id
    bot_instance = require_bot(callback.bot)
    target_message = await prepare_loading_message(callback, "⏳ Загружаю архив...")

    callback_data = require_callback_data(callback)
    season_id = int(callback_data.split(":")[-1])
    async with async_session() as session:
        season = await session.get(Season, season_id)
        if season is None:
            await send_or_update_text(
                bot=bot_instance,
                chat_id=chat_id,
                text="❌ Сезон не найден.",
                message_to_edit=target_message,
            )
            return

        results = (
            (
                await session.execute(
                    select(SeasonResult)
                    .options(joinedload(SeasonResult.user))
                    .where(SeasonResult.season_id == season_id)
                    .order_by(SeasonResult.rank.asc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )

    leaders_data = []
    for result in results:
        name = "Unknown"
        if isinstance(result.user_snapshot, dict):
            name = (
                result.user_snapshot.get("full_name")
                or result.user_snapshot.get("username")
                or name
            )
        if result.user is not None:
            name = result.user.full_name or result.user.username or name

        points = cast(int, result.points or 0)
        rank_str = get_user_rank(points)
        league_emoji = rank_str.split()[0] if rank_str else ""
        leaders_data.append(
            {
                "user_id": result.user_id,
                "name": name,
                "points": points,
                "played": cast(int, result.tournaments_played or 0),
                "perfects": 0,
                "league_emoji": league_emoji,
            }
        )

    text = build_leaderboard_text(
        ["Главная", "Рейтинг клуба", "История сезонов", f"Сезон #{season.number}"],
        f"📜 Итоги сезона #{season.number}",
        leaders_data,
        subtitle_lines=[
            f"<i>{season.start_date.strftime('%d.%m.%Y')} — {season.end_date.strftime('%d.%m.%Y')}</i>"
        ],
    )

    builder = InlineKeyboardBuilder()
    builder.button(
        text="📊 Подробная таблица",
        callback_data=f"leaderboard:history:detailed:{season.id}",
    )
    builder.button(text="↩️ К списку сезонов", callback_data="leaderboard:history:list")
    builder.adjust(1)

    await send_or_update_text(
        bot=bot_instance,
        chat_id=chat_id,
        text=text,
        reply_markup=builder.as_markup(),
        message_to_edit=target_message,
    )


@router.callback_query(F.data == "leaderboard:daily:menu")
async def cq_leaderboard_daily_menu(callback: types.CallbackQuery):
    await answer_callback_safe(callback)
    message = require_message(callback)
    text = (
        f"{format_breadcrumbs(['Главная', 'Рейтинг клуба', 'Рейтинг дня'])}\n\n"
        "<b>📆 Рейтинг дня</b>\n"
        "Выберите, за какой день вы хотите посмотреть статистику:"
    )
    await send_or_update_text(
        bot=require_bot(callback.bot),
        chat_id=message.chat.id,
        text=text,
        reply_markup=leaderboard_daily_modes_kb(),
        message_to_edit=message,
    )


async def generate_and_send_daily_stats(
    chat_id: int,
    bot_instance: Bot,
    target_date: date,
    message_to_edit: types.Message | None = None,
):
    import pytz

    tz = pytz.timezone("Asia/Tbilisi")
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    viewing_mode = "other"
    if target_date == today:
        viewing_mode = "today"
    elif target_date == yesterday:
        viewing_mode = "yesterday"

    async with async_session() as session:
        snapshot = await build_daily_leaderboard_snapshot(session, target_date)

    kb = leaderboard_daily_modes_kb(viewing_mode=viewing_mode)
    if not snapshot["leaders"]:
        text = build_leaderboard_text(
            ["Главная", "Рейтинг клуба", "Рейтинг дня"],
            f"📅 Нет данных за {target_date.strftime('%d.%m.%Y')}",
            [],
            subtitle_lines=[
                "В этот день турниров не проводилось или прогнозы отсутствуют."
            ],
        )
        await send_or_update_text(
            bot=bot_instance,
            chat_id=chat_id,
            text=text,
            reply_markup=kb,
            message_to_edit=message_to_edit,
        )
        return

    text = build_leaderboard_text(
        ["Главная", "Рейтинг клуба", "Рейтинг дня"],
        f"📆 Рейтинг за {target_date.strftime('%d.%m.%Y')}",
        snapshot["leaders"],
        subtitle_lines=[
            f"Турниров: <b>{snapshot['tournament_count']}</b>",
            f"Участников: <b>{len(snapshot['leaders'])}</b>",
        ],
    )
    await send_or_update_text(
        bot=bot_instance,
        chat_id=chat_id,
        text=text,
        reply_markup=kb,
        message_to_edit=message_to_edit,
    )


@router.callback_query(F.data == "leaderboard:daily:today")
async def cq_daily_today(callback: types.CallbackQuery):
    import pytz

    message = require_message(callback)
    tz = pytz.timezone("Asia/Tbilisi")
    today = datetime.now(tz).date()
    target_message = await prepare_loading_message(
        callback, "⏳ Считаю очки за сегодня..."
    )
    await generate_and_send_daily_stats(
        message.chat.id, require_bot(callback.bot), today, target_message
    )


@router.callback_query(F.data == "leaderboard:daily:yesterday")
async def cq_daily_yesterday(callback: types.CallbackQuery):
    import pytz

    message = require_message(callback)
    tz = pytz.timezone("Asia/Tbilisi")
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    target_message = await prepare_loading_message(
        callback, "⏳ Считаю очки за вчера..."
    )
    await generate_and_send_daily_stats(
        message.chat.id, require_bot(callback.bot), yesterday, target_message
    )


@router.callback_query(F.data == "leaderboard:daily:select")
async def cq_daily_select(callback: types.CallbackQuery, state: FSMContext):
    message = require_message(callback)
    await answer_callback_safe(callback)
    text = (
        f"{format_breadcrumbs(['Главная', 'Рейтинг клуба', 'Рейтинг дня'])}\n\n"
        "📅 Выберите день или введите дату вручную:"
    )
    if message.content_type == types.ContentType.TEXT:
        await message.edit_text(text, reply_markup=daily_date_selection_kb())
    else:
        await delete_message_safe(
            require_bot(callback.bot), message.chat.id, message.message_id
        )
        await message.answer(text, reply_markup=daily_date_selection_kb())


@router.callback_query(F.data.startswith("leaderboard:daily:date_pick:"))
async def cq_daily_date_picked(callback: types.CallbackQuery):
    message = require_message(callback)
    callback_data = require_callback_data(callback)
    picked_date = date.fromisoformat(callback_data.split(":")[3])
    target_message = await prepare_loading_message(
        callback, f"⏳ Считаю очки за {picked_date.strftime('%d.%m.%Y')}..."
    )
    await generate_and_send_daily_stats(
        message.chat.id, require_bot(callback.bot), picked_date, target_message
    )


@router.callback_query(F.data == "leaderboard:daily:date_input_manual")
async def cq_daily_date_input_manual(callback: types.CallbackQuery, state: FSMContext):
    message = require_message(callback)
    await answer_callback_safe(callback)
    text = (
        f"{format_breadcrumbs(['Главная', 'Рейтинг клуба', 'Рейтинг дня', 'Ввод даты'])}\n\n"
        "✍️ Введите дату в формате <b>ДД.ММ.ГГГГ</b> (например, 13.12.2025):"
    )
    if message.content_type == types.ContentType.TEXT:
        await message.edit_text(text, reply_markup=cancel_fsm_kb(), parse_mode="HTML")
    else:
        await delete_message_safe(
            require_bot(callback.bot), message.chat.id, message.message_id
        )
        await message.answer(text, reply_markup=cancel_fsm_kb(), parse_mode="HTML")
    await state.set_state(LeaderboardState.waiting_for_date)


@router.message(LeaderboardState.waiting_for_date)
async def process_date_input(message: types.Message, state: FSMContext):
    if message.text is None:
        return

    text = message.text.strip()
    try:
        target_date = datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        await message.answer(
            (
                f"{format_breadcrumbs(['Главная', 'Рейтинг клуба', 'Рейтинг дня', 'Ввод даты'])}\n\n"
                "❌ Неверный формат. Попробуйте еще раз (ДД.ММ.ГГГГ):"
            ),
            reply_markup=cancel_fsm_kb(),
            parse_mode="HTML",
        )
        return

    await state.clear()
    loading_message = await message.answer(
        f"⏳ Считаю очки за {text}...",
        parse_mode="HTML",
    )
    await generate_and_send_daily_stats(
        message.chat.id, require_bot(message.bot), target_date, loading_message
    )


@router.callback_query(F.data == "fsm_cancel", LeaderboardState.waiting_for_date)
async def cancel_date_input(callback: types.CallbackQuery, state: FSMContext):
    message = require_message(callback)
    await state.clear()
    await answer_callback_safe(callback, "Ввод отменен")
    await message.edit_text(
        (
            f"{format_breadcrumbs(['Главная', 'Рейтинг клуба', 'Рейтинг дня'])}\n\n"
            "<b>📆 Рейтинг дня</b>\nВыберите, за какой день вы хотите посмотреть статистику:"
        ),
        reply_markup=leaderboard_daily_modes_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("leaderboard:history:detailed:"))
async def cq_leaderboard_history_detailed(callback: types.CallbackQuery):
    message = require_message(callback)
    callback_data = require_callback_data(callback)
    season_id = int(callback_data.split(":")[-1])
    chat_id = message.chat.id
    bot_instance = require_bot(callback.bot)
    target_message = await prepare_loading_message(
        callback, "⏳ Генерирую детальную статистику..."
    )

    async with async_session() as session:
        snapshot = await build_detailed_season_snapshot(session, season_id)

    if snapshot is None:
        await send_or_update_text(
            bot=bot_instance,
            chat_id=chat_id,
            text="❌ Сезон не найден.",
            message_to_edit=target_message,
        )
        return
    if not snapshot["tournaments"]:
        await send_or_update_text(
            bot=bot_instance,
            chat_id=chat_id,
            text="⚠ В этом сезоне не было завершенных турниров.",
            message_to_edit=target_message,
        )
        return

    season = snapshot["season"]
    title_dates = (
        f"{season.start_date.day}.{season.start_date.month} - "
        f"{season.end_date.day}.{season.end_date.month}"
    )
    text = build_detailed_season_text(
        season.number,
        title_dates,
        snapshot["columns"],
        snapshot["rows"],
    )
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅ Назад к сезону", callback_data=f"leaderboard:history:view:{season.id}"
    )
    await send_or_update_text(
        bot=bot_instance,
        chat_id=chat_id,
        text=text,
        reply_markup=builder.as_markup(),
        message_to_edit=target_message,
    )
