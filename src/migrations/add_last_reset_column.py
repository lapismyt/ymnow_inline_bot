#!/usr/bin/env python3
"""
Migration script to add the last_reset column to the statistics table.
This script adds the last_reset column to track when daily requests were last reset.
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Add src to path so we can import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.database.session import engine

load_dotenv()

def add_last_reset_column():
    """Add last_reset column to statistics table."""
    try:
        # Get database connection details from engine
        # The engine URL is in the format: postgresql://user:password@host:port/database
        db_url = str(engine.url)
        
        # Parse the database URL
        # Example: postgresql://user:password@localhost:5432/dbname
        parts = db_url.split('://')[1].split('@')
        user_pass = parts[0].split(':')
        host_port_db = parts[1].split('/')
        
        user = user_pass[0]
        password = user_pass[1] if len(user_pass) > 1 else ''
        host_port = host_port_db[0].split(':')
        host = host_port[0]
        port = host_port[1] if len(host_port) > 1 else '5432'
        database = host_port_db[1]
        
        # Connect to the database
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Check if the column already exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='statistics' AND column_name='last_reset'
        """)
        
        if cursor.fetchone():
            print("Column 'last_reset' already exists in 'statistics' table.")
            cursor.close()
            conn.close()
            return True
        
        # Add the last_reset column with default value
        print("Adding 'last_reset' column to 'statistics' table...")
        cursor.execute("""
            ALTER TABLE statistics 
            ADD COLUMN last_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """)
        
        # Update existing rows to have the current timestamp as last_reset
        print("Setting last_reset timestamp for existing records...")
        cursor.execute("""
            UPDATE statistics 
            SET last_reset = CURRENT_TIMESTAMP 
            WHERE last_reset IS NULL
        """)
        
        cursor.close()
        conn.close()
        
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
