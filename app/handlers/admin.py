from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from app.filters.is_admin import IsAdmin
from app.keyboards.inline import admin_menu_kb
from app.states.tournament_management import TournamentManagement
from app.lexicon.ru import LexiconRU

router = Router()
router.message.filter(IsAdmin())

@router.message(Command("admin"))
async def cmd_admin_panel(message: types.Message, state: FSMContext):
    """Shows the main admin interactive dashboard."""
    await state.clear()
    # Set initial state just in case
    await state.set_state(TournamentManagement.choosing_tournament)
    
    await message.answer(LexiconRU.ADMIN_PANEL_TEXT, reply_markup=admin_menu_kb())