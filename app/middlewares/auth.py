from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select

from app.db.session import async_session
from app.db.models import User

class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        
        user_id = event.from_user.id
        
        # Skip check for /start command
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            return await handler(event, data)

        async with async_session() as session:
            user = await session.get(User, user_id)
            
            if not user:
                text = "⚠️ Вы не зарегистрированы в системе.\nПожалуйста, нажмите /start для регистрации."
                if isinstance(event, Message):
                    await event.answer(text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
                return # Stop execution here
            
        return await handler(event, data)
