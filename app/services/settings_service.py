from typing import Any, List
from pymongo.database import Database
from ..config import get_config
from ..repositories.settings import SettingsRepository


class SettingsService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.repo = SettingsRepository(db)
        self.cfg = get_config()

    def get_bool(self, key: str, default: bool | None = None) -> bool:
        if default is None:
            default = bool(getattr(self.cfg, key, False))
        val = self.repo.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("1", "true", "yes", "on")
        return bool(val)

    def get_int(self, key: str, default: int | None = None) -> int:
        if default is None:
            default = int(getattr(self.cfg, key, 0))
        val = self.repo.get(key, default)
        try:
            return int(val)
        except Exception:
            return int(default)

    def get_str(self, key: str, default: str | None = None) -> str:
        if default is None:
            default = str(getattr(self.cfg, key, ""))
        val = self.repo.get(key, default)
        return str(val) if val is not None else (default or "")

    def get_list_str(self, key: str, default: List[str] | None = None) -> List[str]:
        if default is None:
            default = list(getattr(self.cfg, key, []) or [])
        val = self.repo.get(key, default)
        if isinstance(val, list):
            return [str(x) for x in val]
        if isinstance(val, str):
            return [x.strip() for x in val.split(",") if x.strip()]
        return default