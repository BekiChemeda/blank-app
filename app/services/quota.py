from datetime import datetime, timedelta
from pymongo.database import Database
from ..config import get_config
from ..repositories.users import UsersRepository


def is_premium(user_doc: dict) -> bool:
    return (user_doc or {}).get("type") == "premium"


def has_quota(db: Database, user_id: int) -> bool:
    cfg = get_config()
    users_repo = UsersRepository(db)
    user = users_repo.get(user_id) or {}
    max_notes = cfg.max_notes_premium if is_premium(user) else cfg.max_notes_regular
    return int(user.get("notes_today", 0)) < int(max_notes)


def increment_quota(db: Database, user_id: int) -> None:
    UsersRepository(db).bump_notes_today(user_id)


def increase_total_notes(db: Database, user_id: int) -> None:
    UsersRepository(db).bump_total_notes(user_id)


def can_submit_note_now(db: Database, user_id: int, cooldown_seconds: int = 10) -> bool:
    users_repo = UsersRepository(db)
    user = users_repo.get(user_id) or {}
    last = user.get("last_note_time")
    if not last:
        return True
    if isinstance(last, str):
        try:
            last = datetime.fromisoformat(last)
        except Exception:
            return True
    return datetime.utcnow() - last >= timedelta(seconds=cooldown_seconds)


def update_last_note_time(db: Database, user_id: int) -> None:
    UsersRepository(db).set_last_note_time(user_id)


def reset_notes_if_new_day(db: Database, user_id: int) -> None:
    UsersRepository(db).reset_notes_if_new_day(user_id)