#!/usr/bin/env python3
"""
Migration script to add the last_reset column to the statistics table.
This script adds the last_reset column to track when daily requests were last reset.
Uses SQLModel/SQLAlchemy instead of raw SQL.
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add src to path so we can import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from src.database.session import engine
from src.models.statistics import Statistics

load_dotenv()

def add_last_reset_column():
    """Add last_reset column to statistics table using SQLModel/SQLAlchemy."""
    try:
        # Create a session
        with Session(engine) as session:
            # Check if the column already exists by trying to query it
            try:
                # Try to query the last_reset column
                result = session.execute(text("SELECT last_reset FROM statistics LIMIT 1"))
                print("Column 'last_reset' already exists in 'statistics' table.")
                return True
            except OperationalError as e:
                if "column" in str(e).lower() and "last_reset" in str(e).lower():
                    # Column doesn't exist, we need to add it
                    pass
                else:
                    # Some other error
                    raise e
            
            # Add the last_reset column
            print("Adding 'last_reset' column to 'statistics' table...")
            
            # Using raw SQL through SQLAlchemy to add the column
            session.execute(text("""
                ALTER TABLE statistics 
                ADD COLUMN last_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            """))
            
            # Update existing rows to have the current timestamp as last_reset
            print("Setting last_reset timestamp for existing records...")
            session.execute(text("""
                UPDATE statistics 
                SET last_reset = CURRENT_TIMESTAMP 
                WHERE last_reset IS NULL
            """))
            
            # Commit the changes
            session.commit()
            
        print("Successfully added 'last_reset' column to 'statistics' table.")
        return True
        
    except Exception as e:
        print(f"Error adding 'last_reset' column: {e}")
        return False

def main():
    """Main function to run the migration."""
    print("Starting migration to add last_reset column...")
    
    if add_last_reset_column():
        print("Migration completed successfully!")
        return 0
    else:
        print("Migration failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
