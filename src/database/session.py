from sqlmodel import create_engine, Session
from typing import Generator
import os
from dotenv import load_dotenv

load_dotenv()

# Database URL for PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/dbname")

# Create engine
engine = create_engine(DATABASE_URL, echo=True)


def get_session() -> Generator[Session, None, None]:
    """Get a database session."""
    with Session(engine) as session:
        yield session
