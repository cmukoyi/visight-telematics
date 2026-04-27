#!/usr/bin/env python3
"""
ONE-TIME MIGRATION SCRIPT (COMPLETED - March 1, 2026)
=====================================================
This script was used to migrate data from SQLite to PostgreSQL.
Migration completed successfully with 9 users, 16 PINs, and 3 tags.

⚠️  DO NOT RUN THIS SCRIPT AGAIN - It's kept for historical reference only.
⚠️  The application now uses PostgreSQL exclusively.

Original Purpose: Migrate data from SQLite to PostgreSQL
"""
import sqlite3
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import models to ensure they're registered with Base
from app.models import User, VerificationPIN, BLETag
from app.database import Base

def migrate_data():
    """Migrate data from SQLite to PostgreSQL"""
    
    # SQLite connection
    sqlite_db = 'ble_tracker.db'
    print(f"📂 Connecting to SQLite: {sqlite_db}")
    sqlite_conn = sqlite3.connect(sqlite_db)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()
    
    # PostgreSQL connection
    postgres_url = 'postgresql://ble_user:ble_dev_password_123@localhost:5432/ble_tracker'
    print(f"🐘 Connecting to PostgreSQL...")
    pg_engine = create_engine(postgres_url)
    
    # Create all tables
    print("📋 Creating tables in PostgreSQL...")
    Base.metadata.create_all(bind=pg_engine)
    print("✅ Tables created successfully")
    
    # Create session
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)
    pg_session = SessionLocal()
    
    try:
        # Migrate Users
        print("\n👤 Migrating users...")
        sqlite_cursor.execute("SELECT * FROM users")
        users = sqlite_cursor.fetchall()
        
        for row in users:
            user = User(
                id=row['id'],
                email=row['email'],
                hashed_password=row['hashed_password'],
                first_name=row['first_name'],
                last_name=row['last_name'],
                phone=row['phone'],
                is_active=bool(row['is_active']),
                is_admin=bool(row['is_admin']),
                created_at=row['created_at']
            )
            pg_session.add(user)
        
        pg_session.commit()
        print(f"   ✅ Migrated {len(users)} users")
        
        # Migrate Verification PINs
        print("\n🔢 Migrating verification PINs...")
        sqlite_cursor.execute("SELECT * FROM verification_pins")
        pins = sqlite_cursor.fetchall()
        
        for row in pins:
            # Create with exact model field names
            pin = VerificationPIN(
                id=row['id'],
                user_id=row['user_id'],
                email=row['email'],
                pin=row['pin'],
                created_at=row['created_at'],
                expires_at=row['expires_at'],
                is_used=bool(row['is_used'])
            )
            pg_session.add(pin)
        
        pg_session.commit()
        print(f"   ✅ Migrated {len(pins)} verification PINs")
        
        # Migrate BLE Tags
        print("\n🏷️  Migrating BLE tags...")
        sqlite_cursor.execute("SELECT * FROM ble_tags")
        tags = sqlite_cursor.fetchall()
        
        for row in tags:
            tag = BLETag(
                id=row['id'],
                user_id=row['user_id'],
                imei=row['imei'],
                device_name=row['device_name'],
                device_model=row['device_model'],
                mac_address=row['mac_address'],
                is_active=bool(row['is_active']),
                added_at=row['added_at']
            )
            pg_session.add(tag)
        
        pg_session.commit()
        print(f"   ✅ Migrated {len(tags)} BLE tags")
        
        print("\n" + "="*50)
        print("🎉 Migration completed successfully!")
        print("="*50)
        print(f"📊 Summary:")
        print(f"   - Users: {len(users)}")
        print(f"   - Verification PINs: {len(pins)}")
        print(f"   - BLE Tags: {len(tags)}")
        print("\n💡 Next steps:")
        print("   1. Verify data in PostgreSQL")
        print("   2. Restart the backend: ./start.sh")
        print("   3. Test the application")
        
    except Exception as e:
        print(f"\n❌ Error during migration: {e}")
        pg_session.rollback()
        sys.exit(1)
    finally:
        pg_session.close()
        sqlite_conn.close()

if __name__ == "__main__":
    print("="*50)
    print("🚀 Starting SQLite → PostgreSQL Migration")
    print("="*50)
    migrate_data()
