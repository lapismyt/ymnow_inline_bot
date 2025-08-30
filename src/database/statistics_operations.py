from ..models.statistics import Statistics
from ..models.user import User
from ..database.session import get_session
from sqlmodel import select
from typing import Optional
from datetime import datetime, date


async def get_user_count() -> int:
    """Get the total number of users from the database."""
    with next(get_session()) as session:
        statement = select(User)
        result = session.exec(statement)
        return len(result.all())


async def get_latest_statistics() -> Optional[Statistics]:
    """Get the latest statistics record."""
    with next(get_session()) as session:
        statement = select(Statistics)
        result = session.exec(statement)
        # Get all results and find the one with the highest ID
        stats = result.all()
        if stats:
            return max(stats, key=lambda x: x.id or 0)
        return None


async def create_statistics(total_requests: int = 0, successful_requests: int = 0, users: int = 0, daily_requests: int = 0) -> Statistics:
    """Create a new statistics record."""
    with next(get_session()) as session:
        # Get actual user count from database
        user_count = await get_user_count()
        stats = Statistics(
            total_requests=total_requests,
            successful_requests=successful_requests,
            users=user_count,
            daily_requests=daily_requests,
            last_reset=datetime.utcnow()
        )
        session.add(stats)
        session.commit()
        session.refresh(stats)
        return stats


async def reset_daily_if_needed(stats: Statistics) -> bool:
    """Reset daily requests if the day has changed. Returns True if reset was performed."""
    if not stats.last_reset:
        return False
    
    # Check if the last reset was today
    last_reset_date = stats.last_reset.date()
    today = date.today()
    
    if last_reset_date < today:
        # Reset daily requests
        with next(get_session()) as session:
            stats.daily_requests = 0
            stats.last_reset = datetime.utcnow()
            session.add(stats)
            session.commit()
            session.refresh(stats)
        return True
    return False


async def update_statistics(total_requests: int = 0, successful_requests: int = 0, users: int = 0, daily_requests: int = 0) -> Statistics:
    """Update or create statistics."""
    stats = await get_latest_statistics()
    if not stats:
        stats = await create_statistics(total_requests, successful_requests, users, daily_requests)
    else:
        with next(get_session()) as session:
            # Check if we need to reset daily requests
            await reset_daily_if_needed(stats)
            
            stats.total_requests += total_requests
            stats.successful_requests += successful_requests
            # Only update user count when a new user is added
            if users > 0:
                stats.users += users
            stats.daily_requests += daily_requests
            session.add(stats)
            session.commit()
            session.refresh(stats)
    return stats
