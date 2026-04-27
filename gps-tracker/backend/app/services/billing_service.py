"""
Billing service for tracking user and device metrics
"""
from datetime import datetime, timedelta
from typing import Dict, List
from sqlalchemy.orm import Session
from app.models import User, BLETag
from app.models_admin import BillingData, BillingTransaction
import logging

logger = logging.getLogger(__name__)


def calculate_daily_billing(db: Session) -> BillingData:
    """
    Calculate daily billing metrics
    - Total users
    - Active users (with IMEIs)
    - Total IMEIs
    - Device assignment by user
    """
    try:
        # Get today's date (start of day)
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Check if billing already calculated for today
        existing = db.query(BillingData).filter(
            BillingData.date >= today,
            BillingData.date < today + timedelta(days=1)
        ).first()
        
        if existing:
            return existing
        
        # Count total users
        total_users = db.query(User).filter(User.is_active == True).count()
        
        # Get all users with IMEIs
        active_users_with_imeis = db.query(User).filter(
            User.is_active == True
        ).outerjoin(BLETag).filter(
            BLETag.id != None,
            BLETag.is_active == True
        ).distinct().all()
        
        active_users = len(active_users_with_imeis)
        
        # Get all active IMEIs
        total_imeis = db.query(BLETag).filter(
            BLETag.is_active == True
        ).count()
        
        # Build device assignment map
        active_devices_by_user = {}
        imei_to_user = {}
        user_device_count = {}
        
        for user in active_users_with_imeis:
            devices = db.query(BLETag).filter(
                BLETag.user_id == user.id,
                BLETag.is_active == True
            ).all()
            
            if devices:
                imei_list = [device.imei for device in devices]
                active_devices_by_user[str(user.id)] = imei_list
                user_device_count[str(user.id)] = len(imei_list)
                
                for device in devices:
                    imei_to_user[device.imei] = str(user.id)
        
        # Create billing record
        billing = BillingData(
            date=today,
            total_users=total_users,
            active_users=active_users,
            total_imeis=total_imeis,
            active_devices_by_user=active_devices_by_user,
            imei_to_user=imei_to_user,
            user_device_count=user_device_count,
            created_at=datetime.utcnow()
        )
        
        db.add(billing)
        db.commit()
        db.refresh(billing)
        
        logger.info(f"✓ Billing calculated for {today.date()}: "
                   f"Users={total_users}, Active={active_users}, IMEIs={total_imeis}")
        
        return billing
        
    except Exception as e:
        logger.error(f"Error calculating billing: {str(e)}")
        db.rollback()
        raise


def record_billing_transaction(
    db: Session,
    user_id: str = None,
    transaction_type: str = None,
    imei: str = None,
    amount: float = 0,
    description: str = None,
    metadata: Dict = None
):
    """Record a billing transaction"""
    try:
        transaction = BillingTransaction(
            user_id=user_id,
            transaction_type=transaction_type,
            imei=imei,
            amount=amount,
            currency="USD",
            description=description,
            metadata=metadata or {},
            created_at=datetime.utcnow()
        )
        
        db.add(transaction)
        db.commit()
        db.refresh(transaction)
        
        logger.info(f"✓ Transaction recorded: {transaction_type} - {description}")
        
        return transaction
        
    except Exception as e:
        logger.error(f"Error recording transaction: {str(e)}")
        db.rollback()
        raise


def get_user_device_count(db: Session, user_id: str) -> int:
    """Get number of active devices for a user"""
    return db.query(BLETag).filter(
        BLETag.user_id == user_id,
        BLETag.is_active == True
    ).count()


def get_billing_summary(db: Session, date: datetime = None) -> Dict:
    """Get billing summary for a specific date"""
    if date is None:
        date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    billing = db.query(BillingData).filter(
        BillingData.date >= date,
        BillingData.date < date + timedelta(days=1)
    ).first()
    
    if not billing:
        return {
            "date": date,
            "total_users": 0,
            "active_users": 0,
            "total_imeis": 0,
            "active_devices_by_user": {},
            "imei_to_user": {},
            "user_device_count": {}
        }
    
    return {
        "date": billing.date,
        "total_users": billing.total_users,
        "active_users": billing.active_users,
        "total_imeis": billing.total_imeis,
        "active_devices_by_user": billing.active_devices_by_user,
        "imei_to_user": billing.imei_to_user,
        "user_device_count": billing.user_device_count
    }

