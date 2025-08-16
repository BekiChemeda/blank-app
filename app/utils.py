from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List
from .config import get_config


def is_admin(user_doc: dict) -> bool:
    return (user_doc or {}).get("role") == "admin"


def is_subscribed(bot: TeleBot, user_id: int) -> bool:
    cfg = get_config()
    if not cfg.force_subscription:
        return True
    for channel in cfg.force_channels:
        try:
            status = bot.get_chat_member(channel, user_id).status
            if status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            return False
    return True


def home_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔙home", callback_data="home"))
    return kb