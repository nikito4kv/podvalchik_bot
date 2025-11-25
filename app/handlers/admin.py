from aiogram import Router, types
from aiogram.filters import Command
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.filters.is_admin import IsAdmin
from app.db.models import Player
from app.db.session import async_session

router = Router()
router.message.filter(IsAdmin())

@router.message(Command("admin"))
async def cmd_admin_panel(message: types.Message):
    """Shows the main admin help message."""
    text = (
        "<b>Админ-панель</b>\n\n"
        "Для управления турнирами (создание, настройка участников, ввод результатов) используйте новую интерактивную команду:\n"
        "➡️ /manage_tournaments\n\n"
        "<b>Глобальное управление игроками:</b>\n"
        "/add_player [ФИО] - Добавить игрока в общую базу\n"
        "/list_players - Показать всех игроков в общей базе"
    )
    await message.answer(text)


@router.message(Command("add_player"))
async def cmd_add_player(message: types.Message):
    """Adds a new player to the global database."""
    player_name_parts = message.text.split(maxsplit=1)[1:]
    if not player_name_parts:
        await message.answer("Пожалуйста, укажите ФИО игрока. Пример:\n/add_player Иванов Иван")
        return

    player_name = player_name_parts[0]
    async with async_session() as session:
        try:
            new_player = Player(full_name=player_name)
            session.add(new_player)
            await session.commit()
            await message.answer(f"✅ Игрок '{player_name}' успешно добавлен в глобальную базу. ID: {new_player.id}")
        except IntegrityError:
            await session.rollback()
            await message.answer(f"⚠️ Игрок '{player_name}' уже существует в базе.")
        except Exception as e:
            await session.rollback()
            await message.answer(f"❌ Произошла ошибка при добавлении игрока: {e}")

@router.message(Command("list_players"))
async def cmd_list_players(message: types.Message):
    """Shows a list of all global players."""
    async with async_session() as session:
        players = await session.execute(select(Player).order_by(Player.full_name))
        player_list = [f"{p.id}: {p.full_name}" for p in players.scalars().all()]
        if not player_list:
            await message.answer("В глобальной базе нет ни одного игрока.")
            return
        await message.answer("<b>Глобальный список игроков:</b>\n\n" + "\n".join(player_list))
