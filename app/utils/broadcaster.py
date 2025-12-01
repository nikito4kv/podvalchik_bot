import asyncio
import logging
from typing import List, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

async def broadcast_message(
    bot: Bot,
    user_ids: List[int],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    sleep_time: float = 0.1
) -> int:
    """
    Safe broadcaster that respects Telegram limits.
    
    :param bot: Bot instance
    :param user_ids: List of user IDs to send message to
    :param text: Message text
    :param reply_markup: Optional keyboard
    :param sleep_time: Sleep time between messages (default 0.1s = 10 msgs/sec)
    :return: Count of successfully sent messages
    """
    count = 0
    try:
        for user_id in user_ids:
            try:
                await bot.send_message(user_id, text, reply_markup=reply_markup)
                count += 1
            except TelegramForbiddenError:
                # User blocked the bot
                logging.debug(f"User {user_id} blocked the bot. Skipping.")
            except TelegramRetryAfter as e:
                # We hit a limit, sleep for the requested time
                logging.warning(f"Flood limit exceeded. Sleeping for {e.retry_after} seconds.")
                await asyncio.sleep(e.retry_after)
                # Try once more
                try:
                    await bot.send_message(user_id, text, reply_markup=reply_markup)
                    count += 1
                except Exception:
                    pass
            except Exception as e:
                logging.error(f"Failed to send message to {user_id}: {e}")
            
            # Sleep to respect limits (approx 10-20 messages per second safe limit for bulk)
            await asyncio.sleep(sleep_time)
            
    except Exception as e:
        logging.error(f"Broadcaster critical error: {e}")
        
    return count
