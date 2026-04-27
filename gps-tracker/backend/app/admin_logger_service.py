"""
Enhanced logging service for Flutter mobile app
Sends logs to backend with proper sanitization
"""
import logging
import requests
import json
from datetime import datetime
from typing import Optional, Dict, Any
import os

class AdminPortalLogger:
    """Logger that sends logs to admin portal backend"""
    
    def __init__(self, backend_url: str, admin_key: Optional[str] = None):
        """
        Initialize logger
        
        Args:
            backend_url: URL to admin portal API (e.g., https://api.example.com)
            admin_key: Optional API key for authentication
        """
        self.backend_url = backend_url.rstrip('/')
        self.admin_key = admin_key or os.getenv('ADMIN_PORTAL_KEY')
        self.session = requests.Session()
        
        # Setup local logger
        self.local_logger = logging.getLogger('beacon_telematics')
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        self.local_logger.addHandler(handler)
        self.local_logger.setLevel(logging.DEBUG)
    
    def _sanitize_log_data(self, message: str, context: Optional[Dict] = None) -> tuple:
        """
        Remove sensitive data from logs before sending
        """
        # Sensitive keys to redact
        sensitive_keys = {
            'password', 'token', 'secret', 'api_key', 'api_secret',
            'auth', 'authorization', 'bearer', 'credit_card', 'cvv',
            'ssn', 'pin', 'private_key', 'refresh_token', 'access_token'
        }
        
        sanitized_message = message
        sanitized_context = (context or {}).copy()
        
        # Redact in message
        for key in sensitive_keys:
            if key.lower() in sanitized_message.lower():
                sanitized_message = sanitized_message.replace(key, '[REDACTED]')
        
        # Redact in context
        def redact_dict(d):
            if not isinstance(d, dict):
                return d
            
            result = {}
            for k, v in d.items():
                if any(sensitive in k.lower() for sensitive in sensitive_keys):
                    result[k] = '[REDACTED]'
                elif isinstance(v, dict):
                    result[k] = redact_dict(v)
                elif isinstance(v, list):
                    result[k] = [redact_dict(item) if isinstance(item, dict) else item for item in v]
                else:
                    result[k] = v
            return result
        
        sanitized_context = redact_dict(sanitized_context)
        
        return sanitized_message, sanitized_context
    
    def send_log(
        self,
        level: str,
        category: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        stack_trace: Optional[str] = None,
        source: Optional[str] = None
    ):
        """Send log to admin portal"""
        try:
            # Sanitize
            safe_message, safe_context = self._sanitize_log_data(message, context)
            
            # Log locally first
            level_upper = level.upper()
            if level_upper == 'DEBUG':
                self.local_logger.debug(f"[{category}] {safe_message}")
            elif level_upper == 'INFO':
                self.local_logger.info(f"[{category}] {safe_message}")
            elif level_upper == 'WARNING':
                self.local_logger.warning(f"[{category}] {safe_message}")
            elif level_upper == 'ERROR':
                self.local_logger.error(f"[{category}] {safe_message}")
            elif level_upper == 'CRITICAL':
                self.local_logger.critical(f"[{category}] {safe_message}")
            
            # Send to backend
            payload = {
                'level': level_upper,
                'category': category,
                'message': safe_message,
                'context': safe_context,
                'stack_trace': stack_trace,
                'source': source or 'flutter_app'
            }
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            if self.admin_key:
                headers['X-Admin-Key'] = self.admin_key
            
            response = self.session.post(
                f"{self.backend_url}/api/admin/logs",
                json=payload,
                headers=headers,
                timeout=5
            )
            
            # Don't fail if log sending fails - just log locally
            if response.status_code not in [200, 201]:
                self.local_logger.warning(
                    f"Failed to send log to admin portal: {response.status_code}"
                )
        except Exception as e:
            # Fail silently - logging errors shouldn't crash the app
            self.local_logger.error(f"Error sending log: {str(e)}", exc_info=True)
    
    def debug(self, category: str, message: str, context: Optional[Dict] = None):
        """Log debug message"""
        self.send_log('DEBUG', category, message, context)
    
    def info(self, category: str, message: str, context: Optional[Dict] = None):
        """Log info message"""
        self.send_log('INFO', category, message, context)
    
    def warning(self, category: str, message: str, context: Optional[Dict] = None):
        """Log warning message"""
        self.send_log('WARNING', category, message, context)
    
    def error(self, category: str, message: str, context: Optional[Dict] = None, stack_trace: Optional[str] = None):
        """Log error message"""
        self.send_log('ERROR', category, message, context, stack_trace)
    
    def critical(self, category: str, message: str, context: Optional[Dict] = None, stack_trace: Optional[str] = None):
        """Log critical message"""
        self.send_log('CRITICAL', category, message, context, stack_trace)


# Global logger instance
_logger_instance = None

def initialize_logger(backend_url: str, admin_key: Optional[str] = None) -> AdminPortalLogger:
    """Initialize global logger instance"""
    global _logger_instance
    _logger_instance = AdminPortalLogger(backend_url, admin_key)
    return _logger_instance

def get_logger() -> AdminPortalLogger:
    """Get global logger instance"""
    global _logger_instance
    if _logger_instance is None:
        # Default to same domain
        _logger_instance = AdminPortalLogger(os.getenv('BACKEND_URL', 'https://beacontelematics.co.uk'))
    return _logger_instance

# Usage examples:
# logger = get_logger()
# logger.info('location', 'User location updated', {'lat': 51.5, 'lon': -0.1, 'user_id': '123'})
# logger.error('auth', 'Login failed', {'email': 'user@example.com'}, stack_trace=traceback.format_exc())
