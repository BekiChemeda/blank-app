from typing import List, Optional, Dict, Any
from pymongo.database import Database


class ChannelsRepository:
    def __init__(self, db: Database) -> None:
        self.collection = db["channels"]

    def add_channel(self, user_id: int, chat_id: int, title: str, username: str | None, can_post: bool) -> None:
        self.collection.update_one(
            {"user_id": user_id, "chat_id": chat_id},
            {"$set": {"title": title, "username": username, "can_post": can_post}},
            upsert=True,
        )

    def remove_channel(self, user_id: int, chat_id: int) -> None:
        self.collection.delete_one({"user_id": user_id, "chat_id": chat_id})

    def list_channels(self, user_id: int) -> List[Dict[str, Any]]:
        return list(self.collection.find({"user_id": user_id}))

    def get_channel(self, user_id: int, chat_id: int) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"user_id": user_id, "chat_id": chat_id})