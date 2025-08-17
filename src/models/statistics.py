from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class Statistics(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    total_requests: int = Field(default=0)
    successful_requests: int = Field(default=0)
    users: int = Field(default=0)
    daily_requests: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
