"""
Utility functions for CyberCafe Server
"""
import json
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import hashlib
import bcrypt

# ----------------- CONFIGURATION -----------------

import sys
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "server_config.json")
DEFAULT_CONFIG = {
    "server": {
        "host": "0.0.0.0",
        "port": 5000
    },
    "database": {
        "file": "cybercafe.db"
    },
    "backup": {
        "enabled": True,
        "interval_hours": 24,
        "keep_backups": 7,
        "directory": "backups"
    },
    "logging": {
        "enabled": True,
        "level": "INFO",
        "file": "cybercafe.log",
        "max_bytes": 10485760,  # 10MB
        "backup_count": 5
    }
}


def load_config():
    """Load configuration from file or create default"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # Merge with defaults to ensure all keys exist
                merged = DEFAULT_CONFIG.copy()
                merged.update(config)
                return merged
        except Exception as e:
            print(f"Error loading config: {e}, using defaults")
            return DEFAULT_CONFIG
    else:
        # Create default config file
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG


def save_config(config):
    """Save configuration to file"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False


# ----------------- LOGGING -----------------

def setup_logging(config=None):
    """Setup logging with rotation"""
    if config is None:
        config = load_config()
    
    log_config = config.get("logging", {})
    if not log_config.get("enabled", True):
        return
    
    log_file = log_config.get("file", "cybercafe.log")
    if not os.path.isabs(log_file):
        log_file = os.path.join(BASE_DIR, log_file)
    log_level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
    max_bytes = log_config.get("max_bytes", 10485760)
    backup_count = log_config.get("backup_count", 5)
    
    # Create logger
    logger = logging.getLogger("cybercafe")
    logger.setLevel(log_level)
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


# ----------------- PASSWORD HASHING -----------------

def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    if isinstance(password, bytes):
        password = password.decode('utf-8')
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a hash"""
    try:
        if isinstance(password, bytes):
            password = password.decode('utf-8')
        if isinstance(hashed, bytes):
            hashed = hashed.decode('utf-8')
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        # Fallback for old plain text passwords (migration)
        return password == hashed


def is_hashed(password: str) -> bool:
    """Check if a password is already hashed (bcrypt format)"""
    return password.startswith('$2b$') or password.startswith('$2a$')


# ----------------- CSV EXPORT -----------------

def export_to_csv(data, filename, headers=None):
    """Export data to CSV file"""
    import csv
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if headers:
                writer.writerow(headers)
            writer.writerows(data)
        return True, None
    except Exception as e:
        return False, str(e)


def export_to_excel(data, filename, sheet_name="Data", headers=None):
    """Export data to Excel file (requires openpyxl)"""
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = sheet_name
        
        if headers:
            ws.append(headers)
        
        for row in data:
            ws.append(row)
        
        wb.save(filename)
        return True, None
    except ImportError:
        return False, "openpyxl not installed. Install with: pip install openpyxl"
    except Exception as e:
        return False, str(e)

