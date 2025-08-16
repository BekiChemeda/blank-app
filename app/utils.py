from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List
from .config import get_config
from .services.settings_service import SettingsService
from .db import get_db


def is_admin(user_doc: dict) -> bool:
    return (user_doc or {}).get("role") == "admin"


def is_subscribed(bot: TeleBot, user_id: int) -> bool:
    # Prefer DB settings; fallback to env
    db = get_db()
    ss = SettingsService(db)
    force = ss.get_bool("force_subscription", default=get_config().force_subscription)
    if not force:
        return True
    channels = ss.get_list_str("force_channels", default=get_config().force_channels)
    for channel in channels:
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