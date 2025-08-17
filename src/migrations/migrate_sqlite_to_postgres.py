import sqlite3
import os
import sys

# Add the parent directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ..models.user import User
from ..models.statistics import Statistics
from ..database.session import engine
from sqlmodel import Session, select


def migrate_users(db_path: str = "db.sqlite3"):
    """Migrate users from SQLite to PostgreSQL."""
    # Create tables
    User.metadata.create_all(engine)
    Statistics.metadata.create_all(engine)
    
    # Connect to SQLite database
    sqlite_conn = sqlite3.connect(db_path)
    sqlite_cursor = sqlite_conn.cursor()
    
    # Get users from SQLite
    sqlite_cursor.execute("SELECT id, ym_id, ym_token FROM users")
    users = sqlite_cursor.fetchall()
    
    # Insert users into PostgreSQL
    with Session(engine) as session:
        for user in users:
            user_id, ym_id, ym_token = user
            # Check if user already exists
            statement = select(User).where(User.id == user_id)
            result = session.exec(statement).first()
            
            if not result:
                new_user = User(id=user_id, ym_id=ym_id, ym_token=ym_token)
                session.add(new_user)
        
        session.commit()
    
    # Close SQLite connection
    sqlite_conn.close()
    print(f"Migrated {len(users)} users from SQLite to PostgreSQL")


def migrate_statistics(stats_file: str = "stats.json"):
    """Migrate statistics from JSON file to PostgreSQL."""
    import json
    
    # Read statistics from JSON file
    if os.path.exists(stats_file):
        with open(stats_file, "r") as f:
            stats_data = json.load(f)
        
        total_requests = stats_data.get("total_requests", 0)
        
        # Insert statistics into PostgreSQL
        with Session(engine) as session:
            # Check if statistics already exist
            statement = select(Statistics)
            result = session.exec(statement)
            stats = result.all()
            
            if not stats:
                # Get actual user count from the users table
                user_statement = select(User)
                user_result = session.exec(user_statement)
                user_count = len(user_result.all())
                
                stats = Statistics(
                    total_requests=total_requests,
                    successful_requests=total_requests,  # Assume all requests were successful for migration
                    users=user_count,
                    daily_requests=0  # Reset daily requests for migration
                )
                session.add(stats)
                session.commit()
                print(f"Migrated statistics: {total_requests} requests, {user_count} users")
            else:
                print("Statistics already exist in PostgreSQL, skipping migration")


if __name__ == "__main__":
    migrate_users()
    migrate_statistics()
