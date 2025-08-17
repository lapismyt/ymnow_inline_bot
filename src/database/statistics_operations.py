from ..models.statistics import Statistics
from ..database.session import get_session
from sqlmodel import select
from typing import Optional
from datetime import datetime


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
        stats = Statistics(
            total_requests=total_requests,
            successful_requests=successful_requests,
            users=users,
            daily_requests=daily_requests
        )
        session.add(stats)
        session.commit()
        session.refresh(stats)
        return stats


async def update_statistics(total_requests: int = 0, successful_requests: int = 0, users: int = 0, daily_requests: int = 0) -> Statistics:
    """Update or create statistics."""
    stats = await get_latest_statistics()
    if not stats:
        stats = await create_statistics(total_requests, successful_requests, users, daily_requests)
    else:
        with next(get_session()) as session:
            stats.total_requests += total_requests
            stats.successful_requests += successful_requests
            stats.users += users
            stats.daily_requests += daily_requests
            session.add(stats)
            session.commit()
            session.refresh(stats)
    return stats
