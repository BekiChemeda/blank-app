from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime


class QuizQuestion(BaseModel):
    question: str
    choices: List[str]
    answer_index: int
    explanation: str = ""


class User(BaseModel):
    id: int
    username: Optional[str] = None
    type: Literal["regular", "premium"] = "regular"
    role: Literal["user", "admin"] = "user"
    premium_since: Optional[datetime] = None
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    total_notes: int = 0
    notes_today: int = 0
    last_note_time: Optional[datetime] = None
    default_question_type: Literal["text", "poll"] = "text"
    questions_per_note: int = 5


class Setting(BaseModel):
    key: str
    value: object


class Payment(BaseModel):
    user_id: int
    method: str
    amount: int
    photo_file_id: Optional[str] = None
    status: Literal["pending", "accepted", "declined"] = "pending"
    time: datetime = Field(default_factory=datetime.utcnow)


class UserChannel(BaseModel):
    user_id: int
    chat_id: int
    title: str
    username: Optional[str] = None
    can_post: bool = True


class Schedule(BaseModel):
    user_id: int
    target_chat_id: int
    target_label: str
    note: str
    num_questions: int
    question_type: Literal["text", "poll"] = "text"
    delay_seconds: int = 5
    scheduled_at: datetime
    status: Literal["pending", "sent", "failed"] = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)