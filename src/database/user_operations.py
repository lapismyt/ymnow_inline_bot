from ..models.user import User
from ..database.session import get_session
from sqlmodel import select
from typing import Optional, List


async def get_user(user_id: int) -> Optional[User]:
    """Get a user by ID."""
    with next(get_session()) as session:
        statement = select(User).where(User.id == user_id)
        result = session.exec(statement)
        return result.first()


async def get_all_users() -> List[User]:
    """Get all users from the database."""
    with next(get_session()) as session:
        statement = select(User)
        result = session.exec(statement)
        return result.all()


async def create_user(user_id: int) -> User:
    """Create a new user."""
    with next(get_session()) as session:
        user = User(id=user_id)
        session.add(user)
        session.commit()
        session.refresh(user)
        
        # Update statistics when a new user is created
        from src.database.statistics_operations import update_statistics
        import asyncio
        asyncio.create_task(update_statistics(users=1))
        
        return user


async def update_user(user_id: int, update_fields: dict) -> Optional[User]:
    """Update user fields."""
    with next(get_session()) as session:
        statement = select(User).where(User.id == user_id)
        result = session.exec(statement)
        user = result.first()
        
        if user:
            for field, value in update_fields.items():
                setattr(user, field, value)
            session.add(user)
            session.commit()
            session.refresh(user)
            return user
        return None


async def handle_user(user_id: int) -> User:
    """Handle user - get or create if not exists."""
    user = await get_user(user_id)
    if not user:
        user = await create_user(user_id)
    return user
