from sqlmodel import SQLModel, Field
from typing import Optional
from sqlalchemy import BigInteger


class User(SQLModel, table=True):
    id: int = Field(primary_key=True, sa_type=BigInteger)
    ym_id: Optional[str] = Field(default=None)
    ym_token: Optional[str] = Field(default=None)
