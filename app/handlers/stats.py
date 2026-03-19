import asyncio
import logging
from datetime import date, datetime, timedelta
from time import perf_counter

from aiogram import Bot, F, Router, types
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
from app.utils.detailed_stats_generator import generate_detailed_season_image
from app.utils.formatting import format_breadcrumbs, get_user_rank
from app.utils.image_generator import (
    generate_leaderboard_image,
    generate_user_profile_image,
)
from app.utils.leaderboard_data import (
    build_daily_leaderboard_snapshot,
    build_detailed_season_snapshot,
)
from app.utils.stats_calculator import calculate_user_tournament_streaks
from app.utils.telegram_media import send_or_update_photo


LOGGER = logging.getLogger(__name__)
router = Router()


async def render_photo_bytes(renderer, *args, filename: str) -> tuple[bytes, float]:
    started = perf_counter()
    img_buffer = await asyncio.to_thread(renderer, *args)
    photo_bytes = img_buffer.getvalue()
    render_ms = (perf_counter() - started) * 1000
    LOGGER.info(
        "stats.image.render.complete renderer=%s filename=%s size_bytes=%s duration_ms=%.3f",
        renderer.__name__,
        filename,
        len(photo_bytes),
        render_ms,
    )
    return photo_bytes, render_ms


def leaderboard_kb(current_view: str = "season"):
    builder = InlineKeyboardBuilder()

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
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="fsm_cancel"))
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
    builder.button(text="↩️ Назад к сезону", callback_data="leaderboard:season")
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
            text="↩️ Назад к рейтингу", callback_data="leaderboard:season"
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
            session, user.id
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

        tournaments_played = user.tournaments_played or 0
        avg_score = (
            round(user.total_points / tournaments_played, 1)
            if tournaments_played > 0
            else 0.0
        )
        rank_title_full = get_user_rank(user.total_points)
        parts = rank_title_full.split()
        rank_title = parts[-1] if len(parts) > 1 else rank_title_full

        return {
            "full_name": display_name or user.full_name,
            "rank_title": rank_title,
            "league_emoji": "",
            "total_points": user.total_points,
            "rank_pos": current_rank,
            "played": tournaments_played,
            "avg_score": avg_score,
            "perfects": user.perfect_tournaments or 0,
            "exacts": user.exact_guesses or 0,
            "current_streak": current_streak,
            "max_streak": max_streak,
        }


@router.message(F.text == "📊 Моя статистика")
async def handle_my_stats(message: types.Message):
    started = perf_counter()
    loading_message = await message.answer("⏳ Собираю статистику...")

    user_data = await build_user_profile_data(
        message.from_user.id, message.from_user.full_name
    )
    if user_data is None:
        await loading_message.edit_text(
            "Не удалось найти вашу статистику. Попробуйте /start"
        )
        LOGGER.warning("stats.request.user_missing user_id=%s", message.from_user.id)
        return

    photo_bytes, render_ms = await render_photo_bytes(
        generate_user_profile_image,
        user_data,
        filename="my_stats.png",
    )

    await send_or_update_photo(
        bot=message.bot,
        chat_id=message.chat.id,
        photo_bytes=photo_bytes,
        filename="my_stats.png",
        caption=f"📊 Статистика игрока <b>{message.from_user.full_name}</b>",
        message_to_edit=loading_message,
    )

    duration_ms = (perf_counter() - started) * 1000
    LOGGER.info(
        "stats.request.complete user_id=%s duration_ms=%.3f db_writes=0 current_streak=%s max_streak=%s render_ms=%.3f image_size_bytes=%s",
        message.from_user.id,
        duration_ms,
        user_data["current_streak"],
        user_data["max_streak"],
        render_ms,
        len(photo_bytes),
    )


@router.message(F.text == "🏆 Рейтинг клуба")
async def handle_leaderboard(message: types.Message):
    await show_seasonal_leaderboard(message)


async def send_leaderboard_image(
    chat_id: int,
    photo_bytes: bytes,
    filename: str,
    caption: str,
    reply_markup: types.InlineKeyboardMarkup,
    bot: Bot,
    message_to_edit: types.Message | None = None,
):
    await send_or_update_photo(
        bot=bot,
        chat_id=chat_id,
        photo_bytes=photo_bytes,
        filename=filename,
        caption=caption,
        reply_markup=reply_markup,
        message_to_edit=message_to_edit,
    )


async def show_seasonal_leaderboard(message_or_cb: types.Message | types.CallbackQuery):
    is_callback = isinstance(message_or_cb, types.CallbackQuery)
    chat_id = (
        message_or_cb.chat.id if not is_callback else message_or_cb.message.chat.id
    )
    bot_instance = message_or_cb.bot

    target_message = None
    if is_callback:
        await message_or_cb.answer()
        if message_or_cb.message.content_type == types.ContentType.PHOTO:
            target_message = message_or_cb.message
            await target_message.edit_caption(
                caption="⏳ Загружаю рейтинг...", reply_markup=None
            )
        else:
            target_message = await bot_instance.send_message(
                chat_id, "⏳ Загружаю рейтинг..."
            )
    else:
        target_message = await message_or_cb.answer("⏳ Загружаю рейтинг...")

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

    photo_bytes, _ = await render_photo_bytes(
        generate_leaderboard_image,
        f"СЕЗОН #{season_number}",
        leaders_data,
        filename="season_top.png",
    )
    caption_breadcrumbs = format_breadcrumbs(
        ["Главная", "Рейтинг клуба", "Текущий сезон"]
    )
    caption = (
        f"{caption_breadcrumbs}\n\n"
        f"<b>📅 Текущий сезон #{season_number}</b>\n"
        f"<i>{start_date.strftime('%d.%m')} — {end_date.strftime('%d.%m')}</i>\n\n"
        "Рейтинг обновляется в реальном времени после каждого турнира."
    )
    await send_leaderboard_image(
        chat_id=chat_id,
        photo_bytes=photo_bytes,
        filename="season_top.png",
        caption=caption,
        reply_markup=leaderboard_kb("season"),
        bot=bot_instance,
        message_to_edit=target_message,
    )


@router.callback_query(F.data == "leaderboard:season")
async def cq_leaderboard_season(callback: types.CallbackQuery):
    await show_seasonal_leaderboard(callback)


@router.callback_query(F.data == "leaderboard:global")
async def cq_leaderboard_global(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    bot_instance = callback.bot
    await callback.answer()

    if callback.message.content_type == types.ContentType.PHOTO:
        target_message = callback.message
        await target_message.edit_caption(
            caption="⏳ Загружаю рейтинг...", reply_markup=None
        )
    else:
        target_message = await bot_instance.send_message(
            chat_id, "⏳ Загружаю рейтинг..."
        )

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
        rank_str = get_user_rank(user.total_points)
        league_emoji = rank_str.split()[0] if rank_str else ""
        leaders_data.append(
            {
                "user_id": user.id,
                "name": name,
                "points": user.total_points,
                "played": user.tournaments_played,
                "perfects": user.perfect_tournaments,
                "league_emoji": league_emoji,
            }
        )

    photo_bytes, _ = await render_photo_bytes(
        generate_leaderboard_image,
        "ЗА ВСЕ ВРЕМЯ",
        leaders_data,
        filename="global_top.png",
    )
    caption_breadcrumbs = format_breadcrumbs(
        ["Главная", "Рейтинг клуба", "За все время"]
    )
    caption = (
        f"{caption_breadcrumbs}\n\n"
        "<b>🌍 Глобальный рейтинг клуба</b>\nСумма очков за всю историю."
    )
    await send_leaderboard_image(
        chat_id=chat_id,
        photo_bytes=photo_bytes,
        filename="global_top.png",
        caption=caption,
        reply_markup=leaderboard_kb("global"),
        bot=bot_instance,
        message_to_edit=target_message,
    )


@router.callback_query(F.data == "leaderboard:history:list")
async def cq_leaderboard_history_list(callback: types.CallbackQuery):
    await callback.answer()
    await show_history_list(callback, page=0)


@router.callback_query(F.data.startswith("leaderboard:history:page:"))
async def cq_leaderboard_history_page(callback: types.CallbackQuery):
    await callback.answer()
    await show_history_list(callback, int(callback.data.split(":")[-1]))


async def show_history_list(callback: types.CallbackQuery, page: int):
    if callback.message.content_type == types.ContentType.PHOTO:
        await callback.message.delete()

    async with async_session() as session:
        seasons = (
            (await session.execute(select(Season).order_by(Season.number.desc())))
            .scalars()
            .all()
        )

    if not seasons:
        await callback.message.answer("История сезонов пуста.")
        return

    text = (
        f"{format_breadcrumbs(['Главная', 'Рейтинг клуба', 'История сезонов'])}\n\n"
        "<b>📜 Архив сезонов</b>\nВыберите сезон для просмотра итогов:"
    )
    if callback.message.content_type == types.ContentType.TEXT:
        await callback.message.edit_text(
            text, reply_markup=season_history_kb(seasons, page)
        )
    else:
        await callback.message.answer(
            text, reply_markup=season_history_kb(seasons, page)
        )


@router.callback_query(F.data.startswith("leaderboard:history:view:"))
async def cq_leaderboard_history_view(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    bot_instance = callback.bot
    await callback.answer()

    if callback.message.content_type == types.ContentType.TEXT:
        target_message = await callback.message.edit_text("⏳ Загружаю архив...")
    else:
        target_message = await callback.message.edit_caption(
            caption="⏳ Загружаю архив..."
        )

    season_id = int(callback.data.split(":")[-1])
    async with async_session() as session:
        season = await session.get(Season, season_id)
        if season is None:
            await callback.message.answer("❌ Сезон не найден.")
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
        if result.user_snapshot and isinstance(result.user_snapshot, dict):
            name = (
                result.user_snapshot.get("full_name")
                or result.user_snapshot.get("username")
                or name
            )
        if result.user is not None:
            name = result.user.full_name or result.user.username or name

        rank_str = get_user_rank(result.points)
        league_emoji = rank_str.split()[0] if rank_str else ""
        leaders_data.append(
            {
                "user_id": result.user_id,
                "name": name,
                "points": result.points,
                "played": result.tournaments_played,
                "perfects": 0,
                "league_emoji": league_emoji,
            }
        )

    filename = f"season_{season.number}.png"
    photo_bytes, _ = await render_photo_bytes(
        generate_leaderboard_image,
        f"СЕЗОН #{season.number}",
        leaders_data,
        filename=filename,
    )
    caption_breadcrumbs = format_breadcrumbs(
        ["Главная", "Рейтинг клуба", "История сезонов", f"Сезон #{season.number}"]
    )
    caption = (
        f"{caption_breadcrumbs}\n\n"
        f"<b>📜 Итоги сезона #{season.number}</b>\n"
        f"<i>{season.start_date.strftime('%d.%m.%Y')} — {season.end_date.strftime('%d.%m.%Y')}</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(
        text="📊 Подробная таблица",
        callback_data=f"leaderboard:history:detailed:{season.id}",
    )
    builder.button(text="↩️ К списку сезонов", callback_data="leaderboard:history:list")
    builder.adjust(1)

    await send_leaderboard_image(
        chat_id=chat_id,
        photo_bytes=photo_bytes,
        filename=filename,
        caption=caption,
        reply_markup=builder.as_markup(),
        bot=bot_instance,
        message_to_edit=target_message,
    )


@router.callback_query(F.data == "leaderboard:daily:menu")
async def cq_leaderboard_daily_menu(callback: types.CallbackQuery):
    await cq_daily_today(callback)


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
        caption_breadcrumbs = format_breadcrumbs(
            ["Главная", "Рейтинг клуба", "Рейтинг дня"]
        )
        text = (
            f"{caption_breadcrumbs}\n\n"
            f"📅 <b>Нет данных за {target_date.strftime('%d.%m.%Y')}</b>\n"
            "В этот день турниров не проводилось или прогнозы отсутствуют."
        )
        if message_to_edit and message_to_edit.content_type == types.ContentType.TEXT:
            await message_to_edit.edit_text(text, reply_markup=kb)
        else:
            await bot_instance.send_message(chat_id, text, reply_markup=kb)
        return

    filename = f"daily_{target_date}.png"
    photo_bytes, _ = await render_photo_bytes(
        generate_leaderboard_image,
        f"РЕЙТИНГ {target_date.strftime('%d.%m')}",
        snapshot["leaders"],
        filename=filename,
    )
    caption_breadcrumbs = format_breadcrumbs(
        ["Главная", "Рейтинг клуба", "Рейтинг дня"]
    )
    caption = (
        f"{caption_breadcrumbs}\n\n"
        f"<b>📆 Рейтинг за {target_date.strftime('%d.%m.%Y')}</b>\n"
        f"Турниров: {snapshot['tournament_count']}\n"
        f"Участников: {len(snapshot['leaders'])}"
    )

    await send_leaderboard_image(
        chat_id=chat_id,
        photo_bytes=photo_bytes,
        filename=filename,
        caption=caption,
        reply_markup=kb,
        bot=bot_instance,
        message_to_edit=message_to_edit,
    )


@router.callback_query(F.data == "leaderboard:daily:today")
async def cq_daily_today(callback: types.CallbackQuery):
    await callback.answer()
    import pytz

    tz = pytz.timezone("Asia/Tbilisi")
    today = datetime.now(tz).date()
    if callback.message.content_type == types.ContentType.TEXT:
        target_message = await callback.message.edit_text(
            "⏳ Считаю очки за сегодня..."
        )
    else:
        target_message = callback.message
        await target_message.edit_caption("⏳ Считаю очки за сегодня...")
    await generate_and_send_daily_stats(
        callback.message.chat.id, callback.bot, today, target_message
    )


@router.callback_query(F.data == "leaderboard:daily:yesterday")
async def cq_daily_yesterday(callback: types.CallbackQuery):
    await callback.answer()
    import pytz

    tz = pytz.timezone("Asia/Tbilisi")
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    if callback.message.content_type == types.ContentType.TEXT:
        target_message = await callback.message.edit_text("⏳ Считаю очки за вчера...")
    else:
        target_message = callback.message
        await target_message.edit_caption("⏳ Считаю очки за вчера...")
    await generate_and_send_daily_stats(
        callback.message.chat.id, callback.bot, yesterday, target_message
    )


@router.callback_query(F.data == "leaderboard:daily:select")
async def cq_daily_select(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    text = (
        f"{format_breadcrumbs(['Главная', 'Рейтинг клуба', 'Рейтинг дня'])}\n\n"
        "📅 Выберите день или введите дату вручную:"
    )
    if callback.message.content_type == types.ContentType.TEXT:
        await callback.message.edit_text(text, reply_markup=daily_date_selection_kb())
    else:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=daily_date_selection_kb())


@router.callback_query(F.data.startswith("leaderboard:daily:date_pick:"))
async def cq_daily_date_picked(callback: types.CallbackQuery):
    await callback.answer()
    picked_date = date.fromisoformat(callback.data.split(":")[3])
    target_message = await callback.message.edit_text(
        f"⏳ Считаю очки за {picked_date.strftime('%d.%m.%Y')}..."
    )
    await generate_and_send_daily_stats(
        callback.message.chat.id, callback.bot, picked_date, target_message
    )


@router.callback_query(F.data == "leaderboard:daily:date_input_manual")
async def cq_daily_date_input_manual(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text(
        (
            f"{format_breadcrumbs(['Главная', 'Рейтинг клуба', 'Рейтинг дня', 'Ввод даты'])}\n\n"
            "✍️ Введите дату в формате <b>ДД.ММ.ГГГГ</b> (например, 13.12.2025):"
        ),
        reply_markup=cancel_fsm_kb(),
    )
    await state.set_state(LeaderboardState.waiting_for_date)


@router.message(LeaderboardState.waiting_for_date)
async def process_date_input(message: types.Message, state: FSMContext):
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
        )
        return

    await state.clear()
    loading_message = await message.answer(f"⏳ Считаю очки за {text}...")
    await generate_and_send_daily_stats(
        message.chat.id, message.bot, target_date, loading_message
    )


@router.callback_query(F.data == "fsm_cancel", LeaderboardState.waiting_for_date)
async def cancel_date_input(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Ввод отменен")
    await callback.message.edit_text(
        (
            f"{format_breadcrumbs(['Главная', 'Рейтинг клуба', 'Рейтинг дня'])}\n\n"
            "<b>📆 Рейтинг дня</b>\nВыберите, за какой день вы хотите посмотреть статистику:"
        ),
        reply_markup=leaderboard_daily_modes_kb(),
    )


@router.callback_query(F.data.startswith("leaderboard:history:detailed:"))
async def cq_leaderboard_history_detailed(callback: types.CallbackQuery):
    season_id = int(callback.data.split(":")[-1])
    chat_id = callback.message.chat.id
    bot_instance = callback.bot
    await callback.answer()

    try:
        target_message = await callback.message.edit_caption(
            caption="⏳ Генерирую детальную статистику..."
        )
    except Exception:
        target_message = callback.message

    async with async_session() as session:
        snapshot = await build_detailed_season_snapshot(session, season_id)

    if snapshot is None:
        await callback.message.answer("❌ Сезон не найден.")
        return
    if not snapshot["tournaments"]:
        await callback.message.edit_caption(
            caption="⚠ В этом сезоне не было завершенных турниров."
        )
        return

    season = snapshot["season"]
    title_dates = (
        f"{season.start_date.day}.{season.start_date.month} - "
        f"{season.end_date.day}.{season.end_date.month}"
    )
    filename = f"season_{season.number}_detailed.png"
    photo_bytes, _ = await render_photo_bytes(
        generate_detailed_season_image,
        f"Сезон {season.number} ({title_dates})",
        snapshot["columns"],
        snapshot["rows"],
        filename=filename,
    )
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅ Назад к сезону", callback_data=f"leaderboard:history:view:{season.id}"
    )
    await send_leaderboard_image(
        chat_id=chat_id,
        photo_bytes=photo_bytes,
        filename=filename,
        caption=f"<b>Детальная статистика сезона #{season.number}</b>",
        reply_markup=builder.as_markup(),
        bot=bot_instance,
        message_to_edit=target_message,
    )
