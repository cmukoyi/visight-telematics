"""
DBLogHandler — captures Python logging output and writes to app_logs table.
Wired up in main.py startup so all backend logger.info/warning/error calls
are visible in the admin portal logs UI.
"""
import logging
from datetime import datetime


class DBLogHandler(logging.Handler):
    """Logging handler that persists records to the app_logs DB table."""

    # Names that would cause infinite recursion — skip them
    SKIP_LOGGERS = {
        'sqlalchemy', 'sqlalchemy.engine', 'sqlalchemy.pool',
        'sqlalchemy.orm', 'app.db_log_handler', 'multipart',
        'watchfiles', 'uvicorn.lifespan',
    }

    def __init__(self, level=logging.WARNING):
        super().__init__(level)
        self._system_admin_id = None
        self._initialised = False
        self.setFormatter(logging.Formatter('%(name)s - %(message)s'))

    def _resolve_admin_id(self):
        """Lazily resolve system admin ID (called once after DB is ready)."""
        if self._system_admin_id:
            return self._system_admin_id
        try:
            from app.database import SessionLocal
            from app.models_admin import AdminUser
            db = SessionLocal()
            try:
                admin = db.query(AdminUser).filter(AdminUser.username == "system").first()
                if not admin:
                    admin = db.query(AdminUser).first()
                if admin:
                    self._system_admin_id = str(admin.id)
            finally:
                db.close()
        except Exception:
            pass
        return self._system_admin_id

    def emit(self, record: logging.LogRecord):
        # Skip noisy / recursive loggers
        for prefix in self.SKIP_LOGGERS:
            if record.name == prefix or record.name.startswith(prefix + '.'):
                return

        admin_id = self._resolve_admin_id()
        if not admin_id:
            return

        try:
            from app.database import SessionLocal
            from app.models_admin import AppLog

            # Map levelname → category
            category_map = {
                'uvicorn.access': 'http',
                'uvicorn.error': 'server',
                'app.routes_admin': 'admin',
            }
            category = category_map.get(record.name, record.name.split('.')[0] if '.' in record.name else 'backend')

            message = self.format(record)[:4000]

            # Include exc_info if present
            if record.exc_info and record.exc_info[0] is not None:
                import traceback
                stack = ''.join(traceback.format_exception(*record.exc_info))
            else:
                stack = None

            db = SessionLocal()
            try:
                db.add(AppLog(
                    admin_user_id=admin_id,
                    level=record.levelname,
                    category=category,
                    message=message,
                    stack_trace=stack,
                    source=f'{record.module}:{record.lineno}',
                    created_at=datetime.utcnow(),
                ))
                db.commit()
            finally:
                db.close()
        except Exception:
            pass  # Never let the log handler crash the application


def setup_db_logging(level: int = logging.WARNING):
    """Call once from startup to attach DBLogHandler to the root logger."""
    handler = DBLogHandler(level=level)
    root = logging.getLogger()
    # Avoid duplicate handlers if startup is called multiple times
    for h in root.handlers:
        if isinstance(h, DBLogHandler):
            return
    root.addHandler(handler)

    # Also capture uvicorn access & error logs
    for name in ('uvicorn.access', 'uvicorn.error', 'fastapi'):
        lg = logging.getLogger(name)
        lg.addHandler(handler)
