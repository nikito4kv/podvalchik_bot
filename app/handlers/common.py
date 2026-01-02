import asyncio
import logging
import html
from datetime import datetime, date, timedelta
from typing import List, Dict # ADDED
from aiogram import Bot, Router, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, InlineKeyboardButton # ADDED InlineKeyboardButton
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.keyboards.reply import main_menu
from app.keyboards.inline import (
    my_forecasts_menu_kb,
    active_tournaments_kb,
    view_forecast_kb,
    forecast_history_kb,
    confirmation_kb,
    help_menu_kb,
    help_back_kb,
    cancel_fsm_kb
)
from app.db.models import User, Tournament, Forecast, TournamentStatus, Player, Season, SeasonResult
from app.db.session import async_session
from app.db.crud import get_forecasts_by_date
from app.utils.formatting import get_medal_str, get_user_rank, format_breadcrumbs
from app.utils.image_generator import generate_leaderboard_image, generate_user_profile_image # UPDATED
from app.utils.stats_calculator import recalculate_user_streaks # UPDATED
from app.core.seasonal import get_current_season_number, get_season_dates
from app.config import config
from app.states.user_states import LeaderboardState
from app.core.scoring import calculate_forecast_points

import io

router = Router()


from aiogram.utils.keyboard import InlineKeyboardBuilder

def leaderboard_kb(current_view: str = "season"):
    """
    Keyboard for switching between leaderboard views.
    current_view: 'season', 'global', 'history', 'daily'
    """
    builder = InlineKeyboardBuilder()
    
    # Row 1: Main Switches
    if current_view == "season":
        builder.button(text="🌍 За все время", callback_data="leaderboard:global")
        builder.button(text="📆 Рейтинг дня", callback_data="leaderboard:daily:menu")
        builder.button(text="📜 История сезонов", callback_data="leaderboard:history:list")
    elif current_view == "global":
        builder.button(text="📅 Текущий сезон", callback_data="leaderboard:season")
        builder.button(text="📆 Рейтинг дня", callback_data="leaderboard:daily:menu")
        builder.button(text="📜 История сезонов", callback_data="leaderboard:history:list")
    
    builder.adjust(2)
    return builder.as_markup()

def daily_date_selection_kb():
    """Keyboard for quick daily date selection."""
    builder = InlineKeyboardBuilder()
    
    import pytz
    tz = pytz.timezone('Asia/Tbilisi')
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    day_before_yesterday = today - timedelta(days=2)
    
    builder.button(text=f"Сегодня ({today.strftime('%d.%m')})", callback_data=f"leaderboard:daily:date_pick:{today.isoformat()}")
    builder.button(text=f"Вчера ({yesterday.strftime('%d.%m')})", callback_data=f"leaderboard:daily:date_pick:{yesterday.isoformat()}")
    builder.button(text=f"Позавчера ({day_before_yesterday.strftime('%d.%m')})", callback_data=f"leaderboard:daily:date_pick:{day_before_yesterday.isoformat()}")
    
    builder.row(InlineKeyboardButton(text="✍️ Ввести дату вручную", callback_data="leaderboard:daily:date_input_manual"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="fsm_cancel"))
    builder.adjust(1)
    return builder.as_markup()

def leaderboard_daily_modes_kb(viewing_mode: str = "other"):
    """
    Keyboard for Daily Leaderboard modes.
    viewing_mode: 'today', 'yesterday', 'other' (determines which buttons to hide/show)
    """
    builder = InlineKeyboardBuilder()
    
    # If viewing today, don't show "Today" button
    if viewing_mode != "today":
        builder.button(text="📅 Топ за сегодня", callback_data="leaderboard:daily:today")
        
    # If viewing yesterday, don't show "Yesterday" button? 
    # Actually user requested specific buttons: "Today" and "Select Date".
    # So if viewing yesterday, we show "Today" and "Select".
    if viewing_mode != "yesterday":
        builder.button(text="⏮ Топ за вчера", callback_data="leaderboard:daily:yesterday")
        
    builder.button(text="📆 Выбрать дату", callback_data="leaderboard:daily:select")
    builder.button(text="↩️ Назад к сезону", callback_data="leaderboard:season")
    builder.adjust(1)
    return builder.as_markup()

def season_history_kb(seasons: list, page: int = 0):
    """
    Paginated list of past seasons.
    seasons: list of Season objects
    """
    builder = InlineKeyboardBuilder()
    ITEMS_PER_PAGE = 5
    
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    current_page_seasons = seasons[start:end]
    
    for season in current_page_seasons:
        dates = f"{season.start_date.strftime('%d.%m')} - {season.end_date.strftime('%d.%m')}"
        builder.button(text=f"Сезон {season.number} ({dates})", callback_data=f"leaderboard:history:view:{season.id}")
        
    builder.adjust(1)
    
    # Navigation
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(text="⬅️", callback_data=f"leaderboard:history:page:{page-1}"))
    if end < len(seasons):
        nav_buttons.append(types.InlineKeyboardButton(text="➡️", callback_data=f"leaderboard:history:page:{page+1}"))
        
    if nav_buttons:
        builder.row(*nav_buttons)
        
    builder.row(types.InlineKeyboardButton(text="↩️ Назад к рейтингу", callback_data="leaderboard:season"))
    return builder.as_markup()


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    """
    Стартовый хэндлер. Проверяет, есть ли пользователь в базе,
    добавляет его, если нет, и показывает главное меню.
    """
    async with async_session() as session:
        # Проверяем, есть ли пользователь в базе
        user = await session.get(User, message.from_user.id)
        if not user:
            # Если пользователя нет, создаем нового
            new_user = User(
                id=message.from_user.id,
                username=message.from_user.username or "unknown",
                full_name=message.from_user.full_name
            )
            session.add(new_user)
            await session.commit()
            await message.answer(
                "Добро пожаловать! Я бот для прогнозов на настольный теннис. "
                "Я зарегистрировал вас в системе. Вот главное меню:",
                reply_markup=main_menu,
            )
        else:
            await message.answer(
                f"С возвращением, {message.from_user.first_name}! Вот главное меню:",
                reply_markup=main_menu,
            )



@router.message(F.text == "📊 Моя статистика")
async def handle_my_stats(message: types.Message):
    msg = await message.answer("⏳ Собираю статистику...")
    
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            await msg.edit_text("Не удалось найти вашу статистику. Попробуйте /start")
            return
        
        # 1. Recalculate Streaks (Ensure data is fresh)
        current_streak, max_streak = await recalculate_user_streaks(session, user.id)
        
        # 2. Calculate Rank
        rank_subquery = select(
            User.id,
            func.rank().over(
                order_by=[
                    User.total_points.desc(),
                    User.perfect_tournaments.desc(),
                    User.exact_guesses.desc(),
                    User.tournaments_played.asc(),
                    User.id.asc()
                ]
            ).label("rank_val")
        ).subquery()
        
        current_rank = await session.scalar(
            select(rank_subquery.c.rank_val).where(rank_subquery.c.id == user.id)
        )

    rank_title_full = get_user_rank(user.total_points)
    # Split by space and take the last part (the name) if possible, or the whole string
    # "👶 Новичок" -> "Новичок"
    parts = rank_title_full.split()
    rank_title = parts[-1] if len(parts) > 1 else rank_title_full
    
    league_emoji = "" # Removed emoji display as requested
    
    tournaments = user.tournaments_played or 0
    avg_score = round(user.total_points / tournaments, 1) if tournaments > 0 else 0.0

    # Prepare data for image
    user_data = {
        "full_name": message.from_user.full_name,
        "rank_title": rank_title,
        "league_emoji": league_emoji,
        "total_points": user.total_points,
        "rank_pos": current_rank,
        "played": tournaments,
        "avg_score": avg_score,
        "perfects": user.perfect_tournaments or 0,
        "exacts": user.exact_guesses or 0,
        "current_streak": current_streak,
        "max_streak": max_streak
    }
    
    # Generate Image
    img_buffer = generate_user_profile_image(user_data)
    photo = BufferedInputFile(img_buffer.read(), filename="my_stats.png")
    
    await msg.delete()
    await message.answer_photo(photo, caption=f"📊 Статистика игрока <b>{message.from_user.full_name}</b>")


@router.message(F.text == "🏆 Рейтинг клуба")
async def handle_leaderboard(message: types.Message):
    # Default to current season view
    await show_seasonal_leaderboard(message)

async def send_leaderboard_image(
    chat_id: int,
    photo: BufferedInputFile,
    caption: str,
    reply_markup: types.InlineKeyboardMarkup,
    bot: Bot,
    message_to_edit: types.Message | None = None
):
    """
    Helper function to send a leaderboard image.
    If message_to_edit is a PHOTO, it edits the media.
    If message_to_edit is TEXT (loading msg), it deletes it and sends a new photo.
    """
    if message_to_edit and message_to_edit.content_type == types.ContentType.PHOTO:
        # We can edit the photo directly
        await bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_to_edit.message_id,
            media=types.InputMediaPhoto(media=photo, caption=caption, parse_mode="HTML"),
            reply_markup=reply_markup
        )
    else:
        # If it was text (loading...), delete it and send new photo
        if message_to_edit:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_to_edit.message_id)
            except Exception as e:
                logging.warning(f"Failed to delete loading message: {e}")
        
        await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )

async def show_seasonal_leaderboard(message_or_cb: types.Message | types.CallbackQuery):
    is_cb = isinstance(message_or_cb, types.CallbackQuery)
    chat_id = message_or_cb.chat.id if not is_cb else message_or_cb.message.chat.id
    bot_instance = message_or_cb.bot

    # Loading State Handling
    target_message = None
    
    if is_cb:
        await message_or_cb.answer() # Stop spinner
        if message_or_cb.message.content_type == types.ContentType.PHOTO:
            # Edit Caption of existing photo to "Loading"
            target_message = message_or_cb.message
            await target_message.edit_caption(caption="⏳ Загружаю рейтинг...", reply_markup=None)
        else:
            # It was a text message (shouldn't happen for these buttons usually, but fallback)
            # Or if we came from a menu command. 
            # Send new loading message
            target_message = await bot_instance.send_message(chat_id, "⏳ Загружаю рейтинг...")
    else:
        # Command /leaderboard
        target_message = await message_or_cb.answer("⏳ Загружаю рейтинг...")

    async with async_session() as session:
        # 2. Get current season info
        s_num = get_current_season_number()
        start_date, end_date = get_season_dates(s_num)
        
        # 3. Calculate scores dynamically for active season
        t_stmt = select(Tournament.id).where(
            Tournament.date >= start_date, 
            Tournament.date <= end_date
        )
        t_res = await session.execute(t_stmt)
        t_ids = t_res.scalars().all()
        
        leaders_data = []

        if t_ids:
            stats_stmt = (
                select(
                    Forecast.user_id,
                    func.sum(Forecast.points_earned).label("total_points"),
                    func.count(Forecast.id).label("played"),
                    User.full_name,
                    User.username,
                    User.streak_days # ADDED
                )
                .join(User, Forecast.user_id == User.id)
                .where(Forecast.tournament_id.in_(t_ids))
                .group_by(Forecast.user_id, User.full_name, User.username, User.streak_days) # ADDED
                .order_by(func.sum(Forecast.points_earned).desc())
                .limit(10)
            )
            stats_res = await session.execute(stats_stmt)
            stats_rows = stats_res.all()
            
            leaders_data = []
            for row in stats_rows:
                name = row.full_name or row.username or f"id:{row.user_id}"
                rank_str = get_user_rank(row.total_points or 0)
                league_emoji = rank_str.split()[0] if rank_str else ""
            
                streak_emoji = "🔥" if row.streak_days and row.streak_days > 0 else "" # Conditional streak emoji
                leaders_data.append({
                    "user_id": row.user_id,
                    "name": name,
                    "points": row.total_points or 0,
                    "played": row.played,
                    "perfects": 0,
                    "league_emoji": league_emoji,
                    "streak_emoji": streak_emoji # ADDED
                })
                    # 4. Generate Image
        season_name = f"СЕЗОН #{s_num}"
        img_buffer = generate_leaderboard_image(season_name, leaders_data) # Pass avatars
        photo = BufferedInputFile(img_buffer.read(), filename="season_top.png")
        
        caption_breadcrumbs = format_breadcrumbs(["Главная", "Рейтинг клуба", "Текущий сезон"])
        caption = (
            f"{caption_breadcrumbs}\n\n"
            f"<b>📅 Текущий сезон #{s_num}</b>\n"
            f"<i>{start_date.strftime('%d.%m')} — {end_date.strftime('%d.%m')}</i>\n\n"
            "Рейтинг обновляется в реальном времени после каждого турнира."
        )
        
        kb = leaderboard_kb("season")
        
        await send_leaderboard_image(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            reply_markup=kb,
            bot=bot_instance,
            message_to_edit=target_message
        )

@router.callback_query(F.data == "leaderboard:season")
async def cq_leaderboard_season(callback: types.CallbackQuery):
    await show_seasonal_leaderboard(callback)

@router.callback_query(F.data == "leaderboard:global")
async def cq_leaderboard_global(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    bot_instance = callback.bot
    
    await callback.answer()
    
    target_message = None
    if callback.message.content_type == types.ContentType.PHOTO:
        target_message = callback.message
        await target_message.edit_caption(caption="⏳ Загружаю рейтинг...", reply_markup=None)
    else:
        target_message = await bot_instance.send_message(chat_id, "⏳ Загружаю рейтинг...")

    async with async_session() as session:
        top_users_stmt = (
            select(User)
            .order_by(
                User.total_points.desc(),
                User.perfect_tournaments.desc()
            )
            .limit(10)
        )
        res = await session.execute(top_users_stmt)
        top_users = res.scalars().all()
        
        leaders_data = []
        for u in top_users:
            name = u.full_name or u.username or f"id:{u.id}"
            rank_str = get_user_rank(u.total_points)
            league_emoji = rank_str.split()[0] if rank_str else ""
            
            streak_emoji = "🔥" if u.streak_days and u.streak_days > 0 else "" # Conditional streak emoji
            leaders_data.append({
                "user_id": u.id,
                "name": name,
                "points": u.total_points,
                "played": u.tournaments_played,
                "perfects": u.perfect_tournaments,
                "league_emoji": league_emoji,
                "streak_emoji": streak_emoji # ADDED
            })
            
    img_buffer = generate_leaderboard_image("ЗА ВСЕ ВРЕМЯ", leaders_data) # Pass avatars
    photo = BufferedInputFile(img_buffer.read(), filename="global_top.png")
    
    caption_breadcrumbs = format_breadcrumbs(["Главная", "Рейтинг клуба", "За все время"])
    caption = f"{caption_breadcrumbs}\n\n" + "<b>🌍 Глобальный рейтинг клуба</b>\nСумма очков за всю историю."
    kb = leaderboard_kb("global")
    
    await send_leaderboard_image(
        chat_id=chat_id,
        photo=photo,
        caption=caption,
        reply_markup=kb,
        bot=bot_instance,
        message_to_edit=target_message
    )

@router.callback_query(F.data == "leaderboard:history:list")
async def cq_leaderboard_history_list(callback: types.CallbackQuery):
    # This switches to TEXT mode, so we must send a new message
    await callback.answer()
    await show_history_list(callback, page=0)

@router.callback_query(F.data.startswith("leaderboard:history:page:"))
async def cq_leaderboard_history_page(callback: types.CallbackQuery):
    await callback.answer()
    page = int(callback.data.split(":")[-1])
    await show_history_list(callback, page)

async def show_history_list(callback: types.CallbackQuery, page: int):
    # If we are coming from a Photo view (like Season/Global), we should delete it and send text
    # Or just send text.
    
    if callback.message.content_type == types.ContentType.PHOTO:
        await callback.message.delete()
        
    async with async_session() as session:
        stmt = select(Season).order_by(Season.number.desc())
        res = await session.execute(stmt)
        seasons = res.scalars().all()
        
    if not seasons:
        # Need to send message since we might have deleted the photo
        await callback.message.answer("История сезонов пуста.")
        return
    
    # Check if we are editing an existing text message (pagination) or sending new
    if callback.message.content_type == types.ContentType.TEXT:
        await callback.message.edit_text(
            f"{format_breadcrumbs(['Главная', 'Рейтинг клуба', 'История сезонов'])}\n\n"
            "<b>📜 Архив сезонов</b>\nВыберите сезон для просмотра итогов:",
            reply_markup=season_history_kb(seasons, page)
        )
    else:
        # Just deleted photo, send new text
        await callback.message.answer(
            f"{format_breadcrumbs(['Главная', 'Рейтинг клуба', 'История сезонов'])}\n\n"
            "<b>📜 Архив сезонов</b>\nВыберите сезон для просмотра итогов:",
            reply_markup=season_history_kb(seasons, page)
        )

@router.callback_query(F.data.startswith("leaderboard:history:view:"))
async def cq_leaderboard_history_view(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    bot_instance = callback.bot
    
    await callback.answer()
    
    # We are coming from TEXT list OR from DETAILED view (Photo).
    # If Text -> Edit Text. If Photo -> Edit Caption.
    if callback.message.content_type == types.ContentType.TEXT:
        target_message = await callback.message.edit_text("⏳ Загружаю архив...")
    else:
        target_message = await callback.message.edit_caption(caption="⏳ Загружаю архив...")

    season_id = int(callback.data.split(":")[-1])
    
    async with async_session() as session:
        season = await session.get(Season, season_id)
        results_stmt = (
            select(SeasonResult)
            .where(SeasonResult.season_id == season_id)
            .order_by(SeasonResult.rank)
            .limit(10)
        )
        res = await session.execute(results_stmt)
        results = res.scalars().all()
        
        leaders_data = []
        for r in results:
            name = "Unknown"
            if r.user_snapshot and isinstance(r.user_snapshot, dict):
                name = r.user_snapshot.get('full_name') or r.user_snapshot.get('username')
            
            user_obj = await session.get(User, r.user_id) # Ensure User object is fetched
            if user_obj:
                name = user_obj.full_name or user_obj.username or name # Use user_obj for name if snapshot is missing
                streak_emoji = "🔥" if user_obj.streak_days and user_obj.streak_days > 0 else ""
            else:
                streak_emoji = ""
            
            rank_str = get_user_rank(r.points)
            league_emoji = rank_str.split()[0] if rank_str else ""
            
            leaders_data.append({
                "user_id": r.user_id,
                "name": name,
                "points": r.points,
                "played": r.tournaments_played,
                "perfects": 0,
                "league_emoji": league_emoji,
                "streak_emoji": streak_emoji # ADDED
            })
            
    img_buffer = generate_leaderboard_image(f"СЕЗОН #{season.number}", leaders_data) # Pass avatars
    photo = BufferedInputFile(img_buffer.read(), filename=f"season_{season.number}.png")
    
    caption_breadcrumbs = format_breadcrumbs(["Главная", "Рейтинг клуба", "История сезонов", f"Сезон #{season.number}"])
    caption = (
        f"{caption_breadcrumbs}\n\n"
        f"<b>📜 Итоги сезона #{season.number}</b>\n"
        f"<i>{season.start_date.strftime('%d.%m.%Y')} — {season.end_date.strftime('%d.%m.%Y')}</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Подробная таблица", callback_data=f"leaderboard:history:detailed:{season.id}")
    builder.button(text="↩️ К списку сезонов", callback_data="leaderboard:history:list")
    builder.adjust(1)
    
    await send_leaderboard_image(
        chat_id=chat_id,
        photo=photo,
        caption=caption,
        reply_markup=builder.as_markup(),
        bot=bot_instance,
        message_to_edit=target_message
    )

@router.callback_query(F.data == "leaderboard:daily:menu")
async def cq_leaderboard_daily_menu(callback: types.CallbackQuery):
    """
    Immediately shows 'Yesterday' stats as the entry point for daily ratings.
    """
    # Redirect to today logic
    await cq_daily_today(callback)

async def generate_and_send_daily_stats(
    chat_id: int,
    bot_instance: Bot,
    target_date: date,
    message_to_edit: types.Message | None = None
):
    """
    Core logic to calculate daily stats and send the image.
    """
    import pytz
    tz = pytz.timezone('Asia/Tbilisi')
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    
    # Determine mode for keyboard
    mode = "other"
    if target_date == today:
        mode = "today"
    elif target_date == yesterday:
        mode = "yesterday"

    async with async_session() as session:
        # 1. Get forecasts for this date
        forecasts = await get_forecasts_by_date(session, target_date)
        
        kb = leaderboard_daily_modes_kb(viewing_mode=mode)
        
        if not forecasts:
            caption_breadcrumbs = format_breadcrumbs(["Главная", "Рейтинг клуба", "Рейтинг дня"])
            text = (
                f"{caption_breadcrumbs}\n\n"
                f"📅 <b>Нет данных за {target_date.strftime('%d.%m.%Y')}</b>\nВ этот день турниров не проводилось или прогнозы отсутствуют."
            )
            if message_to_edit:
                # If we are editing a loading text message
                if message_to_edit.content_type == types.ContentType.TEXT:
                    await message_to_edit.edit_text(text, reply_markup=kb)
                else:
                    await bot_instance.send_message(chat_id, text, reply_markup=kb)
            else:
                await bot_instance.send_message(chat_id, text, reply_markup=kb)
            return

        # 2. Process Stats manually
        # Structure: user_id -> {name, points, played, perfects, exacts}
        user_stats = {}
        
        for f in forecasts:
            uid = f.user_id
            if uid not in user_stats:
                u_name = f.user.full_name or f.user.username or f"User {uid}"
                user_stats[uid] = {
                    "name": u_name,
                    "points": 0,
                    "played": 0,
                    "perfects": 0
                }
            
            user_stats[uid]["played"] += 1
            user_stats[uid]["points"] += (f.points_earned or 0)
            
            # Recalculate if it was perfect
            # We need results to be accurate. 
            # If points_earned is None, we skip (tournament not finished?)
            if f.points_earned is not None and f.tournament.results:
                results_map = {int(k): int(v) for k, v in f.tournament.results.items()}
                # Re-run scoring strictly for perfect check
                _, _, exact_hits = calculate_forecast_points(f.prediction_data, results_map)
                
                # Check for perfect bonus condition
                # If exact_hits == len(prediction_data) -> Perfect
                if exact_hits == len(f.prediction_data) and len(f.prediction_data) > 0:
                    user_stats[uid]["perfects"] += 1

        # 3. Sort
        leaders_list = []
        for uid, data in user_stats.items():
            rank_str = get_user_rank(data["points"]) # Rank based on daily points? Or global? 
            # Usually rank is global, but here we might want to show how good they performed today.
            # But get_user_rank checks thresholds (0-50, etc). It's meaningless for daily points.
            # Let's fetch the user's GLOBAL rank to show their league emoji?
            # Or just show no emoji. Or calculate global rank separately.
            # For simplicity, let's skip league emoji or fetch user global points.
            # Optimally: We already fetched 'User' in joinedload.
            # We can access f.user.total_points.
            # Let's find one forecast for this user to get global points.
            
            user_global_points = 0
            # Find any forecast for this user
            for ff in forecasts: # Iterate through forecasts to find the user's global points
                if ff.user_id == uid:
                    user_global_points = ff.user.total_points
                    break
            
            rank_str = get_user_rank(user_global_points)
            league_emoji = rank_str.split()[0] if rank_str else ""

            streak_emoji = "🔥" if ff.user.streak_days and ff.user.streak_days > 0 else "" # Conditional streak emoji
            leaders_list.append({
                "user_id": uid,
                "name": data["name"],
                "points": data["points"],
                "played": data["played"],
                "perfects": data["perfects"],
                "league_emoji": league_emoji,
                "streak_emoji": streak_emoji # ADDED
            })
        
        # Sort by Points Desc, then Perfects Desc
        leaders_list.sort(key=lambda x: (x["points"], x["perfects"]), reverse=True)
        
        # 4. Generate Image
        title = f"РЕЙТИНГ {target_date.strftime('%d.%m')}"
        img_buffer = generate_leaderboard_image(title, leaders_list) # Pass avatars
        photo = BufferedInputFile(img_buffer.read(), filename=f"daily_{target_date}.png")
        
        caption_breadcrumbs = format_breadcrumbs(["Главная", "Рейтинг клуба", "Рейтинг дня"])
        caption = (
            f"{caption_breadcrumbs}\n\n"
            f"<b>📆 Рейтинг за {target_date.strftime('%d.%m.%Y')}</b>\n"
            f"Турниров: {len(set(f.tournament_id for f in forecasts))}\n"
            f"Участников: {len(leaders_list)}"
        )
        
        await send_leaderboard_image(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            reply_markup=kb,
            bot=bot_instance,
            message_to_edit=message_to_edit
        )

@router.callback_query(F.data == "leaderboard:daily:today")
async def cq_daily_today(callback: types.CallbackQuery):
    await callback.answer()
    import pytz
    tz = pytz.timezone('Asia/Tbilisi')
    today = datetime.now(tz).date()
    
    # Check if we can edit existing message or send new
    target_message = None
    if callback.message.content_type == types.ContentType.TEXT:
        target_message = await callback.message.edit_text("⏳ Считаю очки за сегодня...")
    else:
         target_message = callback.message
         await target_message.edit_caption("⏳ Считаю очки за сегодня...")
         
    await generate_and_send_daily_stats(callback.message.chat.id, callback.bot, today, target_message)

@router.callback_query(F.data == "leaderboard:daily:yesterday")
async def cq_daily_yesterday(callback: types.CallbackQuery):
    await callback.answer()
    import pytz
    tz = pytz.timezone('Asia/Tbilisi')
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    
    target_message = None
    if callback.message.content_type == types.ContentType.TEXT:
        target_message = await callback.message.edit_text("⏳ Считаю очки за вчера...")
    else:
         target_message = callback.message
         await target_message.edit_caption("⏳ Считаю очки за вчера...")

    await generate_and_send_daily_stats(callback.message.chat.id, callback.bot, yesterday, target_message)

@router.callback_query(F.data == "leaderboard:daily:select")
async def cq_daily_select(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    breadcrumbs = format_breadcrumbs(["Главная", "Рейтинг клуба", "Рейтинг дня"])
    text = f"{breadcrumbs}\n\n📅 Выберите день или введите дату вручную:"
    
    if callback.message.content_type == types.ContentType.TEXT:
        await callback.message.edit_text(text, reply_markup=daily_date_selection_kb())
    else:
        # If coming from a photo view (e.g. daily stats image), we must delete and send new text
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=daily_date_selection_kb())
    # Don't set state yet, wait for manual input or selection

@router.callback_query(F.data.startswith("leaderboard:daily:date_pick:"))
async def cq_daily_date_picked(callback: types.CallbackQuery):
    await callback.answer()
    date_str = callback.data.split(":")[3]
    picked_date = date.fromisoformat(date_str)
    
    target_message = await callback.message.edit_text(f"⏳ Считаю очки за {picked_date.strftime('%d.%m.%Y')}...")
    await generate_and_send_daily_stats(callback.message.chat.id, callback.bot, picked_date, target_message)

@router.callback_query(F.data == "leaderboard:daily:date_input_manual")
async def cq_daily_date_input_manual(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    breadcrumbs = format_breadcrumbs(["Главная", "Рейтинг клуба", "Рейтинг дня", "Ввод даты"])
    await callback.message.edit_text(
        f"{breadcrumbs}\n\n✍️ Введите дату в формате <b>ДД.ММ.ГГГГ</b> (например, 13.12.2025):",
        reply_markup=cancel_fsm_kb()
    )
    await state.set_state(LeaderboardState.waiting_for_date)

@router.message(LeaderboardState.waiting_for_date)
async def process_date_input(message: types.Message, state: FSMContext):
    text = message.text.strip()
    try:
        dt = datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        breadcrumbs = format_breadcrumbs(["Главная", "Рейтинг клуба", "Рейтинг дня", "Ввод даты"])
        await message.answer(
            f"{breadcrumbs}\n\n❌ Неверный формат. Попробуйте еще раз (ДД.ММ.ГГГГ):", reply_markup=cancel_fsm_kb()
        )
        return
        
    await state.clear()
    msg = await message.answer(f"⏳ Считаю очки за {text}...")
    await generate_and_send_daily_stats(message.chat.id, message.bot, dt, msg)

@router.callback_query(F.data == "fsm_cancel", LeaderboardState.waiting_for_date)
async def cancel_date_input(callback: types.CallbackQuery, state: FSMContext):
    """Cancels the date input process."""
    await state.clear()
    await callback.answer("Ввод отменен")
    # Return to daily menu
    breadcrumbs = format_breadcrumbs(["Главная", "Рейтинг клуба", "Рейтинг дня"])
    await callback.message.edit_text(
        f"{breadcrumbs}\n\n<b>📆 Рейтинг дня</b>\nВыберите, за какой день вы хотите посмотреть статистику:",
        reply_markup=leaderboard_daily_modes_kb()
    )

@router.message(F.text == "ℹ️ Правила")
async def handle_rules(message: types.Message): # ADDED async
    text = "<b>📚 Справочный центр</b>\n\nВыберите интересующий вас раздел:"
    await message.answer(text, reply_markup=help_menu_kb())

@router.callback_query(F.data == "help:main")
async def cq_help_main(callback: types.CallbackQuery):
    text = "<b>📚 Справочный центр</b>\n\nВыберите интересующий вас раздел:"
    await callback.message.edit_text(text, reply_markup=help_menu_kb())
    await callback.answer()

@router.callback_query(F.data == "help:scoring")
async def cq_help_scoring(callback: types.CallbackQuery):
    text = """
    <b>📈 Система начисления очков (РТТФ)</b>

    Мы используем справедливую систему оценки прогнозов:

    🔸 <b>+1 балл:</b> Вы угадали, что игрок займет призовое место, но ошиблись с точной позицией.
    <i>Пример: Поставили на 1-е, а он занял 3-е.</i>

    🎯 <b>+5 баллов:</b> Вы угадали игрока и его точное место.
    <i>Пример: Поставили на 1-е, и он занял 1-е.</i>

    💎 <b>БОНУС +15 баллов:</b> Вы угадали <b>всех</b> призеров и их места в точности.
    <i>Это высшее мастерство!</i>
    """
    await callback.message.edit_text(text, reply_markup=help_back_kb())
    await callback.answer()

@router.callback_query(F.data == "help:ranks")
async def cq_help_ranks(callback: types.CallbackQuery):
    text = """
    <b>🏅 Ранги и Достижения</b>

    Ваш статус зависит от суммы очков:
    👶 <b>Новичок</b>: 0 - 50
    🧢 <b>Любитель</b>: 51 - 200
    🎱 <b>Профи</b>: 201 - 500
    🧠 <b>Эксперт</b>: 501 - 1000
    🔮 <b>Оракул</b>: 1000+

    <b>Специальные отметки:</b>
    💎 — Количество "Идеальных турниров" (с бонусом +15).
    🎯 — Количество точных попаданий в место (+5 баллов).
    """
    await callback.message.edit_text(text, reply_markup=help_back_kb())
    await callback.answer()

@router.callback_query(F.data == "help:how_to")
async def cq_help_howto(callback: types.CallbackQuery):
    text = """
    <b>📝 Как сделать прогноз</b>

    1. Нажмите кнопку <b>"🏁 Актуальные турниры"</b>.
    2. Выберите турнир из списка (если есть открытые).
    3. Нажмите <b>"🔮 Сделать прогноз"</b>.
    4. Выберите игроков последовательно для каждого места (1-е, 2-е, и т.д.).
    5. Подтвердите выбор.

    Вы можете изменить прогноз в любой момент до начала турнира!
    """
    await callback.message.edit_text(text, reply_markup=help_back_kb())
    await callback.answer()


@router.message(F.text == "🗂 Архив прогнозов")
async def handle_my_forecasts(message: types.Message): # ADDED async
    """
    Shows the menu for viewing active or past forecasts.
    """
    await message.answer(
        "Выберите, какие прогнозы вы хотите посмотреть:",
        reply_markup=my_forecasts_menu_kb(),
    )


@router.callback_query(F.data == "back_to_forecasts_menu")
async def back_to_forecasts_menu(callback_query: types.CallbackQuery): # ADDED async
    """
    Returns the user to the main forecasts menu.
    """
    await callback_query.message.edit_text(
        "Выберите, какие прогнозы вы хотите посмотреть:",
        reply_markup=my_forecasts_menu_kb(),
    )
    await callback_query.answer()


@router.callback_query(F.data == "forecasts:active")
async def show_active_forecasts(callback_query: types.CallbackQuery): # ADDED async
    """
    Shows a list of tournaments for which the user has an active forecast.
    """
    await callback_query.answer()
    user_id = callback_query.from_user.id
    async with async_session() as session:
        active_forecasts_stmt = (
            select(Forecast)
            .options(joinedload(Forecast.tournament))
            .join(Tournament, Forecast.tournament_id == Tournament.id)
            .where(
                Forecast.user_id == user_id,
                Tournament.status.in_([TournamentStatus.OPEN, TournamentStatus.LIVE]),
            )
            .order_by(Tournament.date.desc())
        )
        result = await session.execute(active_forecasts_stmt)
        forecasts = result.scalars().all()

        if not forecasts:
            breadcrumbs = format_breadcrumbs(["Главная", "Мои прогнозы", "Активные"])
            builder = InlineKeyboardBuilder()
            builder.button(text="🏁 Посмотреть доступные турниры", callback_data="predict_back_to_list") # Callback to show active tournaments
            builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_forecasts_menu"))
            
            await callback_query.message.edit_text(
                f"{breadcrumbs}\n\nУ вас пока нет активных прогнозов. Сделайте первый!",
                reply_markup=builder.as_markup()
            )
            return

        breadcrumbs = format_breadcrumbs(["Главная", "Мои прогнозы", "Активные"])
        await callback_query.message.edit_text(
            f"{breadcrumbs}\n\nВыберите турнир, чтобы посмотреть ваш прогноз:",
            reply_markup=active_tournaments_kb([f.tournament for f in forecasts]),
        )


@router.callback_query(F.data.startswith("view_forecast:"))
async def show_specific_forecast(callback_query: types.CallbackQuery): # ADDED async
    """
    Shows the user's specific forecast for a selected tournament.
    """
    await callback_query.answer()
    tournament_id = int(callback_query.data.split(":")[1])
    user_id = callback_query.from_user.id

    async with async_session() as session:
        # Fetch the forecast with tournament info
        forecast_stmt = (
            select(Forecast)
            .options(joinedload(Forecast.tournament))
            .where(
                Forecast.user_id == user_id, Forecast.tournament_id == tournament_id
            )
        )
        result = await session.execute(forecast_stmt)
        forecast = result.scalar_one_or_none()

        if not forecast:
            await callback_query.message.answer("Прогноз не найден.")
            return

        # Fetch player objects
        player_ids = forecast.prediction_data
        if not player_ids:
            await callback_query.message.answer(
                "В этом прогнозе нет данных об игроках."
            )
            return

        players_stmt = select(Player).where(Player.id.in_(player_ids))
        result = await session.execute(players_stmt)
        players_map = {p.id: p for p in result.scalars()}

        # Format the message
        tournament_date = forecast.tournament.date.strftime("%d.%m.%Y")
        t_name = html.escape(forecast.tournament.name)
        text = f"<b>Ваш прогноз на турнир «{t_name}» от {tournament_date}:</b>\n\n"

        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        for i, player_id in enumerate(player_ids):
            place = medals.get(i, f" {i + 1}.")
            player = players_map.get(player_id)
            if player:
                rating_str = f" ({player.current_rating})" if player.current_rating is not None else ""
                name_str = f"{html.escape(player.full_name)}{rating_str}"
            else:
                name_str = "Неизвестный игрок"
            text += f"{place} {name_str}\n"

        # Show 'Edit' button only for OPEN tournaments
        allow_edit = (forecast.tournament.status == TournamentStatus.OPEN)
        
        # Show 'Other Forecasts' only if NOT OPEN or if admin (based on rules from tournament_user_menu_kb)
        is_admin = user_id in config.admin_ids
        status_str = forecast.tournament.status.name if hasattr(forecast.tournament.status, "name") else str(forecast.tournament.status)
        _show_others = (status_str != "OPEN") or is_admin # Recalc as it's passed directly

        kb = view_forecast_kb(
            back_callback="forecasts:active", 
            forecast_id=forecast.id,
            tournament_id=tournament_id,
            allow_edit=allow_edit,
            show_others=_show_others,
            is_admin=is_admin, # Pass for consistency check in KB
            tournament_status=forecast.tournament.status # Pass for consistency check in KB
        )

        await callback_query.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("edit_forecast_start:"))
async def cq_edit_forecast_start(callback_query: types.CallbackQuery): # ADDED async
    """Asks for confirmation to edit a forecast."""
    await callback_query.answer()
    forecast_id = int(callback_query.data.split(":")[1])
    text = "Вы уверены, что хотите изменить прогноз? Ваш старый прогноз будет заменен только <b>после сохранения нового</b>."
    await callback_query.message.edit_text(
        text,
        reply_markup=confirmation_kb(action_prefix=f"edit_confirm:{forecast_id}"),
    )


import logging

# ... imports

@router.callback_query(F.data.startswith("forecasts:history:"))
async def show_forecast_history(callback_query: types.CallbackQuery): # ADDED async
    """
    Shows a paginated list of the user's past forecasts.
    """
    await callback_query.answer()
    page = int(callback_query.data.split(":")[2])
    user_id = callback_query.from_user.id
    logging.info(f"DEBUG: Fetching history for user {user_id}, page {page}")

    async with async_session() as session:
        # Debug: Check if user exists and has any forecasts
        total_forecasts = await session.scalar(select(func.count(Forecast.id)).where(Forecast.user_id == user_id))
        logging.info(f"DEBUG: Total forecasts for user {user_id}: {total_forecasts}")

        history_stmt = (
            select(Forecast)
            .options(joinedload(Forecast.tournament))
            .join(Tournament, Forecast.tournament_id == Tournament.id)
            .where(
                Forecast.user_id == user_id,
                Tournament.status == TournamentStatus.FINISHED,
            )
            .order_by(Tournament.date.desc())
        )
        result = await session.execute(history_stmt)
        forecasts = result.scalars().all()
        
        logging.info(f"DEBUG: Found {len(forecasts)} FINISHED forecasts.")

        if not forecasts:
            # Fallback: Check if we have string mismatch for Enum
            # This is a hack, but helpful for debugging SQLite
            logging.info("DEBUG: Forecasts list is empty. Checking raw statuses...")
            
            debug_res = await session.execute(select(Forecast).where(Forecast.user_id == user_id))
            debug_forecasts = debug_res.scalars().all()
            
            if debug_forecasts:
                t_ids = [f.tournament_id for f in debug_forecasts]
                all_t_res = await session.execute(select(Tournament).where(Tournament.id.in_(t_ids)))
                all_t = all_t_res.scalars().all()
                for t in all_t:
                    logging.info(f"DEBUG: Tournament {t.id} status: {t.status} (type: {type(t.status)})")
            else:
                logging.info("DEBUG: No forecasts found for user at all (even ignoring status).")

            await callback_query.message.answer("У вас нет прошлых прогнозов.")
            return

        await callback_query.message.edit_text(
            "История ваших прогнозов:",
            reply_markup=forecast_history_kb(forecasts, page),
        )


@router.callback_query(F.data.startswith("view_history:"))
async def show_specific_history(callback_query: types.CallbackQuery): # ADDED async
    """
    Shows a detailed comparison for a past forecast.
    """
    await callback_query.answer()
    parts = callback_query.data.split(":")
    forecast_id, page = int(parts[1]), int(parts[2])

    async with async_session() as session:
        # Fetch the forecast with tournament info
        forecast_stmt = (
            select(Forecast)
            .options(joinedload(Forecast.tournament))
            .where(Forecast.id == forecast_id)
        )
        result = await session.execute(forecast_stmt)
        forecast = result.scalar_one_or_none()

        if not forecast or not forecast.tournament.results:
            await callback_query.message.answer(
                "История для этого прогноза не найдена."
            )
            return

        # Get all player IDs from prediction and results to fetch names in one query
        pred_ids = forecast.prediction_data
        res_ids = [int(k) for k in forecast.tournament.results.keys()]
        all_player_ids = list(set(pred_ids) | set(res_ids))

        players_stmt = select(Player).where(Player.id.in_(all_player_ids))
        result = await session.execute(players_stmt)
        players_map = {p.id: p for p in result.scalars()}

        # Format message
        tournament_date = forecast.tournament.date.strftime("%d.%m.%Y")
        
        # 1. Actual Results Block
        results_dict = {int(k): int(v) for k, v in forecast.tournament.results.items()}
        sorted_results = sorted(results_dict.items(), key=lambda item: item[1])
        
        t_name = html.escape(forecast.tournament.name)
        results_text = f"<b>🏆 Итоги турнира «{t_name}» ({tournament_date})</b>\n\n"
        for pid, rank in sorted_results:
            p_obj = players_map.get(pid)
            p_name = html.escape(p_obj.full_name) if p_obj else "Неизвестный"
            medal = get_medal_str(rank)
            results_text += f"{medal} {p_name}\n"
            
        # 2. User Forecast Block (Detailed)
        prediction_text = f"\n<b>📜 Ваш прогноз:</b>\n"
        
        current_hits = 0
        for i, pid in enumerate(pred_ids):
            predicted_rank = i + 1
            p_obj = players_map.get(pid)
            p_name = html.escape(p_obj.full_name) if p_obj else "Неизвестный"
            
            line_points = 0
            extra_info = ""
            
            if pid in results_dict:
                actual_rank = results_dict[pid]
                diff = abs(predicted_rank - actual_rank)
                
                if diff == 0:
                    line_points = 5
                    extra_info = " (🎯 Точно!)"
                    current_hits += 1
                else:
                    line_points = 1
                    extra_info = f" (факт: {actual_rank})"
            else:
                 line_points = 0
                 extra_info = " (не в топе)"
            
            prediction_text += f"{i+1}. {p_name}{extra_info} — <b>+{line_points}</b>\n"

        if current_hits == len(pred_ids) and len(pred_ids) > 0:
            prediction_text += "\n🎉 <b>БОНУС: +15 очков за идеальный прогноз!</b>\n"

        final_text = results_text + prediction_text + f"\n<b>💰 Итого очков:</b> {forecast.points_earned or 0}"

        # Pass tournament_id to enable 'Other Forecasts' button
        # History implies finished, so show_others=True
        await callback_query.message.edit_text(
            final_text, reply_markup=view_forecast_kb(
                back_callback=f"forecasts:history:{page}",
                forecast_id=forecast.id,
                tournament_id=forecast.tournament_id,
                allow_edit=False,
                show_others=True,
                is_admin=False,
                tournament_status=TournamentStatus.FINISHED
            )
        )
@router.callback_query(F.data.startswith("leaderboard:history:detailed:"))
async def cq_leaderboard_history_detailed(callback: types.CallbackQuery):
    from app.utils.detailed_stats_generator import generate_detailed_season_image
    
    season_id = int(callback.data.split(":")[-1])
    chat_id = callback.message.chat.id
    bot_instance = callback.bot
    
    await callback.answer()
    
    # Send loading state. Since we are on a photo, we can try to edit caption
    # But usually generation takes time, so a clear 'Loading' message is better.
    # However, we can't delete the photo easily and restore it if we fail.
    # Best UX: Edit caption to "Generating...", then replace photo.
    try:
        target_message = await callback.message.edit_caption(caption="⏳ Генерирую детальную статистику...")
    except Exception:
        # If caption is same or other error, just ignore
        target_message = callback.message

    async with async_session() as session:
        season = await session.get(Season, season_id)
        if not season:
            await callback.message.answer("❌ Сезон не найден.")
            return

        # 1. Fetch Tournaments in Season range (FINISHED only)
        tournaments_stmt = (
            select(Tournament)
            .where(
                Tournament.date >= season.start_date,
                Tournament.date <= season.end_date,
                Tournament.status == TournamentStatus.FINISHED
            )
            .order_by(Tournament.date)
        )
        t_res = await session.execute(tournaments_stmt)
        tournaments = t_res.scalars().all()
        
        if not tournaments:
            await callback.message.edit_caption(caption="⚠ В этом сезоне не было завершенных турниров.")
            return

        t_ids = [t.id for t in tournaments]
        
        # 2. Fetch Forecasts
        forecasts_stmt = (
            select(Forecast)
            .options(joinedload(Forecast.user))
            .where(Forecast.tournament_id.in_(t_ids))
        )
        f_res = await session.execute(forecasts_stmt)
        forecasts = f_res.scalars().all()
        
        # 3. Aggregate Data
        user_map = {}
        
        for f in forecasts:
            uid = f.user_id
            if uid not in user_map:
                name = f.user.username or f"User {uid}"
                if f.user.full_name: name = f.user.full_name
                
                user_map[uid] = {
                    "name": name,
                    "scores": {},
                    "total": 0
                }
            
            points = f.points_earned or 0
            user_map[uid]["scores"][f.tournament_id] = points
            user_map[uid]["total"] += points
            
        # 4. Sort by Total Points Desc
        sorted_users = sorted(user_map.values(), key=lambda x: x["total"], reverse=True)
        
        # 5. Prepare data for Generator
        columns = [t.name for t in tournaments]
        rows = []
        for u in sorted_users:
            scores_list = []
            for t in tournaments:
                scores_list.append(u["scores"].get(t.id, None)) # None means didn't play
            
            rows.append({
                "name": u["name"],
                "scores": scores_list,
                "total": u["total"]
            })
            
        # 6. Generate Image
        title_dates = f"{season.start_date.day}.{season.start_date.month} - {season.end_date.day}.{season.end_date.month}"
        img_buffer = await asyncio.to_thread(
            generate_detailed_season_image, 
            f"Сезон {season.number} ({title_dates})", 
            columns, 
            rows
        )
        
        photo = BufferedInputFile(img_buffer.read(), filename=f"season_{season.number}_detailed.png")
        
        caption = f"<b>Детальная статистика сезона #{season.number}</b>"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅ Назад к сезону", callback_data=f"leaderboard:history:view:{season.id}")
        
        await send_leaderboard_image(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            reply_markup=builder.as_markup(),
            bot=bot_instance,
            message_to_edit=target_message
        )
