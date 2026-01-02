from aiogram import Router, types, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.session import async_session
from app.db.models import BugReport
from app.db import crud
from app.states.user_states import BugReportState
from app.config import config
from app.utils.formatting import format_user_name

router = Router()

# --- Cancel Handler ---
@router.message(StateFilter(BugReportState), Command("cancel"))
@router.callback_query(StateFilter(BugReportState), F.data == "fsm_cancel")
async def cancel_bug_report(message_or_cb: types.Message | types.CallbackQuery, state: FSMContext):
    """Cancels the bug reporting process."""
    await state.clear()
    text = "❌ Отправка баг-репорта отменена."
    
    if isinstance(message_or_cb, types.CallbackQuery):
        await message_or_cb.message.edit_text(text)
        await message_or_cb.answer()
    else:
        await message_or_cb.answer(text)


# --- Step 1: Start ---
@router.message(Command("bug"))
async def cmd_bug_start(message: types.Message, state: FSMContext):
    """Starts the bug reporting process."""
    print(f"DEBUG: /bug command received from {message.from_user.id}")
    await state.set_state(BugReportState.entering_description)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="fsm_cancel")
    
    await message.answer(
        "🐛 <b>Сообщение об ошибке</b>\n\n"
        "Пожалуйста, опишите, что произошло. Укажите:\n"
        "1. Какие действия вы выполняли?\n"
        "2. Что пошло не так?\n"
        "3. Какой результат вы ожидали?\n\n"
        "Напишите описание одним сообщением.",
        reply_markup=builder.as_markup()
    )


# --- Step 2: Description -> Screenshot ---
@router.message(BugReportState.entering_description, F.text)
async def process_bug_description(message: types.Message, state: FSMContext):
    """Saves description and asks for screenshot."""
    # Check for commands (like /start) to allow exit implicitly
    if message.text.startswith("/"):
        return 
    
    # Validation: Telegram caption limit is 1024 chars. 
    # We reserve ~200 chars for headers, so max description is ~800.
    if len(message.text) > 800:
        await message.answer(
            f"⚠️ <b>Слишком длинное описание!</b>\n"
            f"Телеграм ограничивает длину подписи к фото.\n\n"
            f"Текущая длина: {len(message.text)} символов.\n"
            f"Максимум: 800 символов.\n\n"
            "Пожалуйста, сократите текст и отправьте его снова."
        )
        return
        
    await state.update_data(description=message.text)
    await state.set_state(BugReportState.entering_screenshot)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="➡️ Пропустить", callback_data="bug:skip_photo")
    builder.button(text="❌ Отмена", callback_data="fsm_cancel")
    builder.adjust(1)
    
    await message.answer(
        "📷 <b>Скриншот (по желанию)</b>\n\n"
        "Пришлите скриншот ошибки (как фото) или нажмите кнопку «Пропустить».",
        reply_markup=builder.as_markup()
    )


# --- Shared Finish Logic ---
async def save_and_send_report(message_or_cb: types.Message | types.CallbackQuery, state: FSMContext, photo_id: str | None):
    data = await state.get_data()
    description = data.get("description")
    user = message_or_cb.from_user
    
    # Save to DB
    async with async_session() as session:
        report = BugReport(
            user_id=user.id,
            description=description,
            photo_id=photo_id
        )
        await crud.create_bug_report(session, report)
        await session.commit()
        await session.refresh(report)
        report_id = report.id

    # Send success message to User
    success_text = f"✅ <b>Спасибо! Ваш отчёт #{report_id} отправлен.</b>\nМы постараемся исправить ошибку как можно скорее."
    
    if isinstance(message_or_cb, types.Message):
        await message_or_cb.answer(success_text)
    else:
        try:
            await message_or_cb.message.edit_text(success_text)
        except Exception:
            await message_or_cb.message.answer(success_text)

    # Send notification to Bug Chat
    if config.bug_report_chat_id:
        # Use utility for name
        display_name = format_user_name(user)
        
        report_text = (
            f"🐛 <b>Новый баг-репорт #{report_id}</b>\n\n"
            f"👤 <b>От:</b> {display_name}\n"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n\n"
            f"📝 <b>Описание:</b>\n{description}"
        )
        
        try:
            bot: Bot = message_or_cb.bot
            if photo_id:
                await bot.send_photo(chat_id=config.bug_report_chat_id, photo=photo_id, caption=report_text)
            else:
                await bot.send_message(chat_id=config.bug_report_chat_id, text=report_text)
        except Exception as e:
            print(f"Error sending bug report to chat: {e}")
    
    await state.clear()


# --- Step 3: Handle Screenshot ---
@router.message(BugReportState.entering_screenshot, F.photo)
async def process_bug_screenshot(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await save_and_send_report(message, state, photo_id)


# --- Step 3: Handle Skip ---
@router.callback_query(BugReportState.entering_screenshot, F.data == "bug:skip_photo")
async def process_bug_skip_photo(callback: types.CallbackQuery, state: FSMContext):
    await save_and_send_report(callback, state, None)
    await callback.answer()
