#!/usr/bin/env python
"""
Initialize default admin user for admin portal
Run after database migration: python init_admin.py
"""

import sys
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.models_admin import AdminUser
from app.admin_auth import hash_password
from app.database import Base

def init_admin_user():
    """Create default admin user"""
    
    # Get database URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)
    
    # Create engine and session
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Create tables (checkfirst=True prevents crash on already-existing indexes/tables)
    Base.metadata.create_all(bind=engine, checkfirst=True)
    
    db = SessionLocal()
    
    try:
        # Check if admin already exists
        admin = db.query(AdminUser).filter(AdminUser.username == "Admin").first()
        if admin:
            print("✓ Default admin user 'Admin' already exists")
            print(f"  Email: {admin.email}")
            print(f"  Role: {admin.role}")
            print(f"  Active: {admin.is_active}")
            print(f"  Created: {admin.created_at}")
            return
        
        # Create default admin
        default_admin = AdminUser(
            username="Admin",
            email="admin@beacontelematics.co.uk",
            hashed_password=hash_password("123456789_Plus"),
            full_name="System Administrator",
            role="admin",
            is_active=True,
            created_at=datetime.utcnow()
        )
        
        db.add(default_admin)
        db.commit()
        db.refresh(default_admin)
        
        print("✓ Default admin user created successfully!")
        print(f"  Username: Admin")
        print(f"  Password: 123456789_Plus")
        print(f"  Email: admin@beacontelematics.co.uk")
        print(f"  User ID: {default_admin.id}")
        print(f"  Role: {default_admin.role}")
        print()
        print("⚠️  IMPORTANT: Change the password immediately after first login!")
        
        # Create system user for app logs
        system_user = db.query(AdminUser).filter(AdminUser.username == "system").first()
        if not system_user:
            system_user = AdminUser(
                username="system",
                email="system@beacontelematics.co.uk",
                hashed_password=hash_password(os.urandom(32).hex()),  # Random password
                full_name="System Logger",
                role="admin",
                is_active=True,
                created_at=datetime.utcnow()
            )
            db.add(system_user)
            db.commit()
            print("✓ System user for app logs created")
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    init_admin_user()
