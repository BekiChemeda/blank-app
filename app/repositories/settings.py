from typing import Any, Optional
from pymongo.database import Database


class SettingsRepository:
    def __init__(self, db: Database) -> None:
        self.collection = db["settings"]

    def get(self, key: str, default: Any | None = None) -> Any:
        doc = self.collection.find_one({"key": key})
        if not doc:
            return default
        return doc.get("value", default)

    def set(self, key: str, value: Any) -> None:
        self.collection.update_one({"key": key}, {"$set": {"value": value}}, upsert=True)

    def all(self) -> list[dict]:
        return list(self.collection.find({}))