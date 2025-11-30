from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, update

from app.db.models import Player
from app.db.session import async_session
from app.filters.is_admin import IsAdmin
from app.keyboards.inline import (
    get_paginated_players_management_kb,
    admin_menu_kb,
    player_management_menu_kb,
    player_management_back_kb,
    enter_rating_fsm_kb,
    add_global_player_success_kb
)
from app.states.player_management import PlayerManagement
from app.states.tournament_management import TournamentManagement

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

async def show_players_list(message_or_cb: types.Message | types.CallbackQuery, state: FSMContext, page: int = 0, view_mode: str = "active"):
    """Helper to show the list of players."""
    async with async_session() as session:
        result = await session.execute(select(Player))
        players = result.scalars().all()

    kb = get_paginated_players_management_kb(players, view_mode=view_mode, page=page)
    
    title = "👤 Активные игроки" if view_mode == "active" else "🗄 Архив игроков"
    text = f"<b>{title}</b>\n\nВыберите игрока для редактирования или добавьте нового."
    
    if isinstance(message_or_cb, types.Message):
        await message_or_cb.answer(text, reply_markup=kb)
    else:
        await message_or_cb.message.edit_text(text, reply_markup=kb)

async def show_player_details(callback: types.CallbackQuery, player_id: int):
    """Helper to show player details and menu."""
    async with async_session() as session:
        player = await session.get(Player, player_id)
        if not player:
            await callback.answer("Игрок не найден.", show_alert=True)
            return

        status = "Активен" if (player.is_active if player.is_active is not None else True) else "Архивирован"
        text = (
            f"<b>👤 Игрок: {player.full_name}</b>\n"
            f"⭐ Рейтинг: {player.current_rating if player.current_rating is not None else 'Нет'}\n"
            f"📊 Статус: {status}\n\n"
            "Выберите действие:"
        )
        await callback.message.edit_text(text, reply_markup=player_management_menu_kb(player))


@router.message(Command("players"))
async def cmd_players(message: types.Message, state: FSMContext):
    """Entry point via command."""
    await state.clear()
    await show_players_list(message, state, page=0, view_mode="active")


@router.callback_query(F.data.startswith("pm_list_players:"))
async def cq_list_players(callback: types.CallbackQuery, state: FSMContext):
    """Entry point via admin menu or back button."""
    parts = callback.data.split(":")
    page = int(parts[1])
    # Default to active if not specified (backward compatibility)
    view_mode = parts[2] if len(parts) > 2 else "active"
    
    await state.clear()
    await show_players_list(callback, state, page=page, view_mode=view_mode)


@router.callback_query(F.data.startswith("pm_paginate:"))
async def cq_paginate_players(callback: types.CallbackQuery, state: FSMContext):
    """Handle pagination."""
    parts = callback.data.split(":")
    view_mode = parts[1]
    page = int(parts[2])
    await show_players_list(callback, state, page=page, view_mode=view_mode)

@router.callback_query(F.data.startswith("pm_switch:"))
async def cq_switch_view_mode(callback: types.CallbackQuery, state: FSMContext):
    """Handle switching between active and archived."""
    view_mode = callback.data.split(":")[1]
    await show_players_list(callback, state, page=0, view_mode=view_mode)


@router.callback_query(F.data == "pm_back_list")
async def cq_back_to_list(callback: types.CallbackQuery, state: FSMContext):
    """Back to list from detail view."""
    # Ideally we should remember the previous view_mode, but defaulting to active is safe for now
    await state.clear()
    await show_players_list(callback, state, page=0, view_mode="active")


@router.callback_query(F.data == "admin_back_main")
async def cq_back_to_admin_main(callback: types.CallbackQuery, state: FSMContext):
    """Back to main admin menu."""
    await state.clear()
    # Restore the state required for the admin dashboard to work
    await state.set_state(TournamentManagement.choosing_tournament)
    await callback.message.edit_text("<b>🔧 Панель администратора</b>", reply_markup=admin_menu_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("pm_select:"))
async def cq_select_player(callback: types.CallbackQuery, state: FSMContext):
    """Show details for a selected player."""
    player_id = int(callback.data.split(":")[1])
    await show_player_details(callback, player_id)


# --- Add New Player ---
@router.callback_query(F.data == "pm_add_new")
async def cq_add_new_player(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PlayerManagement.adding_new_player_name)
    await callback.message.edit_text(
        "Введите имя и фамилию нового игрока:", reply_markup=player_management_back_kb()
    )

@router.message(PlayerManagement.adding_new_player_name)
async def msg_add_player_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    await state.update_data(new_player_name=name)
    await state.set_state(PlayerManagement.adding_new_player_rating)
    
    # Create a custom simple KB for skipping rating
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="Пропустить (без рейтинга)", callback_data="pm_skip_rating")
    builder.button(text="↩️ Отмена", callback_data="pm_back_list")
    builder.adjust(1)
    
    await message.answer(
        f"Имя: <b>{name}</b>\nТеперь введите рейтинг игрока (число) или нажмите кнопку 'Пропустить':",
        reply_markup=builder.as_markup()
    )

@router.callback_query(PlayerManagement.adding_new_player_rating, F.data == "pm_skip_rating")
async def cq_skip_rating(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data.get("new_player_name")
    
    async with async_session() as session:
        # Check for duplicates
        existing = await session.execute(select(Player).where(Player.full_name == name))
        if existing.scalar_one_or_none():
             await callback.message.edit_text(f"❌ Игрок с именем {name} уже существует!", reply_markup=player_management_back_kb())
             await state.clear()
             return

        new_player = Player(full_name=name, current_rating=None, is_active=True)
        session.add(new_player)
        await session.commit()
        await callback.message.edit_text(f"✅ Игрок <b>{name}</b> успешно добавлен!", reply_markup=add_global_player_success_kb())
    
    await state.clear()

@router.message(PlayerManagement.adding_new_player_rating)
async def msg_add_player_rating(message: types.Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("Пожалуйста, введите целое число для рейтинга.")
        return
    
    rating = int(message.text.strip())
    data = await state.get_data()
    name = data.get("new_player_name")
    
    async with async_session() as session:
        # Check for duplicates
        existing = await session.execute(select(Player).where(Player.full_name == name))
        if existing.scalar_one_or_none():
             await message.answer(f"❌ Игрок с именем {name} уже существует!", reply_markup=player_management_back_kb())
             await state.clear()
             return

        new_player = Player(full_name=name, current_rating=rating, is_active=True)
        session.add(new_player)
        await session.commit()
        await message.answer(f"✅ Игрок <b>{name}</b> с рейтингом {rating} успешно добавлен!", reply_markup=add_global_player_success_kb())
    
    await state.clear()


# --- Edit Name ---
@router.callback_query(F.data.startswith("pm_edit_name:"))
async def cq_edit_name_start(callback: types.CallbackQuery, state: FSMContext):
    player_id = int(callback.data.split(":")[1])
    await state.update_data(player_id=player_id)
    await state.set_state(PlayerManagement.editing_player_name)
    await callback.message.edit_text(
        "Введите новое имя игрока:", reply_markup=player_management_back_kb()
    )

@router.message(PlayerManagement.editing_player_name)
async def msg_edit_name_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    player_id = data.get("player_id")
    new_name = message.text.strip()

    async with async_session() as session:
        player = await session.get(Player, player_id)
        if player:
            player.full_name = new_name
            await session.commit()
            await message.answer(f"✅ Имя изменено на <b>{new_name}</b>.")
            # Re-fetch to get fresh state
            await session.refresh(player)
            status = "Активен" if (player.is_active if player.is_active is not None else True) else "Архивирован"
            text = (
                f"<b>👤 Игрок: {player.full_name}</b>\n"
                f"⭐ Рейтинг: {player.current_rating if player.current_rating is not None else 'Нет'}\n"
                f"📊 Статус: {status}\n\n"
                "Выберите действие:"
            )
            await message.answer(text, reply_markup=player_management_menu_kb(player))
        else:
            await message.answer("Ошибка: игрок не найден.")
    
    await state.clear()


# --- Edit Rating ---
@router.callback_query(F.data.startswith("pm_edit_rating:"))
async def cq_edit_rating_start(callback: types.CallbackQuery, state: FSMContext):
    player_id = int(callback.data.split(":")[1])
    await state.update_data(player_id=player_id)
    await state.set_state(PlayerManagement.editing_player_rating)
    await callback.message.edit_text(
        "Введите новый рейтинг (целое число):", reply_markup=player_management_back_kb()
    )

@router.message(PlayerManagement.editing_player_rating)
async def msg_edit_rating_process(message: types.Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("Пожалуйста, введите целое число.")
        return

    data = await state.get_data()
    player_id = data.get("player_id")
    new_rating = int(message.text.strip())

    async with async_session() as session:
        player = await session.get(Player, player_id)
        if player:
            player.current_rating = new_rating
            await session.commit()
            await message.answer(f"✅ Рейтинг обновлен: <b>{new_rating}</b>.")
            
            await session.refresh(player)
            status = "Активен" if (player.is_active if player.is_active is not None else True) else "Архивирован"
            text = (
                f"<b>👤 Игрок: {player.full_name}</b>\n"
                f"⭐ Рейтинг: {player.current_rating if player.current_rating is not None else 'Нет'}\n"
                f"📊 Статус: {status}\n\n"
                "Выберите действие:"
            )
            await message.answer(text, reply_markup=player_management_menu_kb(player))
        else:
            await message.answer("Ошибка: игрок не найден.")
    
    await state.clear()


# --- Delete (Archive) ---
@router.callback_query(F.data.startswith("pm_delete:"))
async def cq_delete_player(callback: types.CallbackQuery, state: FSMContext):
    player_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        player = await session.get(Player, player_id)
        if player:
            player.is_active = False
            await session.commit()
            await callback.answer("✅ Игрок архивирован (удален из списка выбора).", show_alert=True)
            await show_player_details(callback, player_id)
        else:
            await callback.answer("Игрок не найден.", show_alert=True)


# --- Restore ---
@router.callback_query(F.data.startswith("pm_restore:"))
async def cq_restore_player(callback: types.CallbackQuery, state: FSMContext):
    player_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        player = await session.get(Player, player_id)
        if player:
            player.is_active = True
            await session.commit()
            await callback.answer("✅ Игрок восстановлен!", show_alert=True)
            await show_player_details(callback, player_id)
        else:
            await callback.answer("Игрок не найден.", show_alert=True)
