import sqlite3
from datetime import datetime
from utils import hash_password, verify_password, is_hashed
from common import DB_FILE, logger

# --- SETUP ---

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Users Table
    c.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0, remaining_seconds INTEGER NOT NULL DEFAULT 0,
            total_purchased_seconds INTEGER NOT NULL DEFAULT 0)""")
    
    # --- MIGRATION: SESSION COLUMNS ---
    # session_paid_seconds: Πόσα δευτερόλεπτα πλήρωσε σε ΑΥΤΟ το login
    try:
        c.execute("ALTER TABLE users ADD COLUMN session_paid_seconds INTEGER DEFAULT 0")
        logger.info("Migrated DB: Added session_paid_seconds column")
    except sqlite3.OperationalError: pass

    # session_awarded_rules: Κείμενο που κρατάει ποια Bonus Rules πήρε (π.χ. "1,3,5")
    try:
        c.execute("ALTER TABLE users ADD COLUMN session_awarded_rules TEXT DEFAULT ''")
        logger.info("Migrated DB: Added session_awarded_rules column")
    except sqlite3.OperationalError: pass
    
    # Settings & Logs
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY, seconds_per_pulse INTEGER NOT NULL, bonus_hours_required INTEGER NOT NULL DEFAULT 10)""")
    c.execute("""CREATE TABLE IF NOT EXISTS coin_pulses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, pulses INTEGER NOT NULL,
            seconds_added INTEGER NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS session_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, username TEXT NOT NULL,
            station TEXT NOT NULL, action TEXT NOT NULL, login_time DATETIME, logout_time DATETIME,
            duration_seconds INTEGER, remaining_seconds INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS bonus_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, threshold_seconds INTEGER NOT NULL, bonus_seconds INTEGER NOT NULL)""")
    
    # Game Paths Table (New)
    c.execute("""CREATE TABLE IF NOT EXISTS game_paths (
            id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    
    # File Sync System Tables
    c.execute("""CREATE TABLE IF NOT EXISTS file_sync_source (
            id INTEGER PRIMARY KEY,
            admin_ip TEXT NOT NULL,
            admin_port INTEGER NOT NULL DEFAULT 5001,
            last_update DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS file_sync_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_path TEXT UNIQUE NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS file_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            relative_path TEXT NOT NULL,
            folder_id INTEGER NOT NULL,
            file_size INTEGER NOT NULL,
            modified_time REAL NOT NULL,
            checksum TEXT,
            last_scan DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(folder_id) REFERENCES file_sync_folders(id),
            UNIQUE(relative_path, folder_id))""")
    
    # Indexes & Defaults
    c.execute("CREATE INDEX IF NOT EXISTS idx_session_logs_user ON session_logs(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_session_logs_created ON session_logs(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_coin_pulses_user ON coin_pulses(user_id)")
    
    c.execute("SELECT id FROM settings WHERE id = 1")
    if c.fetchone() is None:
        c.execute("INSERT INTO settings (id, seconds_per_pulse, bonus_hours_required) VALUES (1, 300, 10)")
    
    # Default Admin
    c.execute("SELECT id FROM users WHERE is_admin = 1")
    if c.fetchone() is None:
        admin_password = hash_password("admin")
        c.execute("INSERT INTO users (username, password, is_admin, remaining_seconds, total_purchased_seconds) VALUES (?, ?, 1, 0, 0)", ("admin", admin_password))

    # Password Hash Migration
    c.execute("SELECT id, password FROM users")
    for row in c.fetchall():
        user_id, password = row
        if not is_hashed(password):
            hashed = hash_password(password)
            c.execute("UPDATE users SET password=? WHERE id=?", (hashed, user_id))

    conn.commit()
    conn.close()
    logger.info("Database initialized")

# --- SETTINGS & RULES ---

def get_seconds_per_pulse():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT seconds_per_pulse FROM settings WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else 300

def set_seconds_per_pulse(value: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE settings SET seconds_per_pulse=? WHERE id=1", (int(value),))
    conn.commit()
    conn.close()

def get_game_paths():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, path FROM game_paths ORDER BY path")
    rows = c.fetchall()
    conn.close()
    return rows

def add_game_path(path_str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO game_paths (path) VALUES (?)", (path_str,))
        conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "Path already exists"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def remove_game_path(path_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM game_paths WHERE id=?", (path_id,))
    conn.commit()
    conn.close()

def get_bonus_rules():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, threshold_seconds, bonus_seconds FROM bonus_rules ORDER BY threshold_seconds ASC")
    rows = c.fetchall()
    conn.close()
    return rows

def add_bonus_rule(threshold_seconds: int, bonus_seconds: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO bonus_rules (threshold_seconds, bonus_seconds) VALUES (?, ?)", (int(threshold_seconds), int(bonus_seconds)))
    conn.commit()
    conn.close()

def update_bonus_rule(rule_id, threshold, bonus):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE bonus_rules SET threshold_seconds=?, bonus_seconds=? WHERE id=?", (int(threshold), int(bonus), int(rule_id)))
    conn.commit()
    conn.close()

def delete_bonus_rule(rule_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM bonus_rules WHERE id=?", (int(rule_id),))
    conn.commit()
    conn.close()

# --- USERS ---

def get_user(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("SELECT id, username, password, is_admin, remaining_seconds, COALESCE(total_purchased_seconds,0) FROM users WHERE username=?", (username,))
    except sqlite3.OperationalError:
        c.execute("SELECT id, username, password, is_admin, remaining_seconds, COALESCE(total_purchased_seconds,0) FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if not row: return None
    return {
        "id": row[0], "username": row[1], "password": row[2], "is_admin": bool(row[3]), 
        "remaining_seconds": row[4], "total_purchased_seconds": row[5]
    }

def verify_user_password(username, password):
    user = get_user(username)
    if not user: return False
    return verify_password(password, user["password"])

def list_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, username, is_admin, remaining_seconds, COALESCE(total_purchased_seconds,0) FROM users ORDER BY username")
    rows = c.fetchall()
    conn.close()
    return rows

def add_user(username, password, is_admin=False):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        hashed = hash_password(password)
        c.execute("INSERT INTO users (username,password,is_admin,remaining_seconds,total_purchased_seconds,session_paid_seconds,session_awarded_rules) VALUES (?,?,?,?,?,0,'')",
                  (username, hashed, 1 if is_admin else 0, 0, 0))
        conn.commit()
        return True, None
    except sqlite3.IntegrityError as e:
        return False, str(e)
    finally:
        conn.close()

def update_remaining_seconds(user_id, seconds: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET remaining_seconds=? WHERE id=?", (int(seconds), user_id))
    conn.commit()
    conn.close()

def update_user_password(user_id, new_pwd):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    hashed = hash_password(new_pwd)
    c.execute("UPDATE users SET password=? WHERE id=?", (hashed, user_id))
    conn.commit()
    conn.close()

# --- SESSION RESET LOGIC ---

def reset_session_stats(user_id):
    """Καλείται στο LOGIN για να μηδενίσει τα στατιστικά της τρέχουσας συνεδρίας."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET session_paid_seconds=0, session_awarded_rules='' WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    print(f"[DEBUG] Session stats reset for User ID {user_id}")

# --- NEW CORE LOGIC: SESSION BASED ACCUMULATION ---

def add_pulses_to_user(user_id, pulses: int):
    sp = get_seconds_per_pulse()
    seconds_to_add = pulses * sp
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 1. Φέρνουμε τα δεδομένα της ΤΡΕΧΟΥΣΑΣ συνεδρίας
    try:
        c.execute("SELECT remaining_seconds, COALESCE(total_purchased_seconds,0), COALESCE(session_paid_seconds,0), COALESCE(session_awarded_rules,'') FROM users WHERE id=?", (user_id,))
    except sqlite3.OperationalError:
        c.execute("SELECT remaining_seconds, COALESCE(total_purchased_seconds,0), 0, '' FROM users WHERE id=?", (user_id,))

    row = c.fetchone()
    if not row:
        conn.close()
        return 0, 0
    
    remaining = row[0] or 0
    total_purchased = row[1] or 0
    current_session_paid = row[2] or 0
    awarded_rules_str = row[3] or ""
    
    # Μετατροπή των awarded rules σε λίστα (π.χ. από "1,3" σε ['1', '3'])
    awarded_rules = set(awarded_rules_str.split(',')) if awarded_rules_str else set()
    
    print("------------------------------------------------")
    print(f"[DEBUG] Adding: {seconds_to_add} sec")
    print(f"[DEBUG] Session Paid Before: {current_session_paid}")
    
    # 2. Ενημερώνουμε το ποσό που πλήρωσε σε ΑΥΤΟ το login
    new_session_paid = current_session_paid + seconds_to_add
    print(f"[DEBUG] Session Paid After: {new_session_paid}")
    
    # 3. Έλεγχος Bonus Rules
    rules = get_bonus_rules()
    total_bonus_now = 0
    
    for rule_id, threshold, gift in rules:
        rule_id_str = str(rule_id)
        threshold = int(threshold)
        gift = int(gift)
        
        # Αν φτάσαμε το όριο ΚΑΙ δεν έχουμε πάρει ακόμα αυτό το δώρο σε αυτό το session
        if new_session_paid >= threshold:
            if rule_id_str not in awarded_rules:
                print(f"[DEBUG] >>> BONUS TRIGGERED! Rule ID {rule_id}: Paid {new_session_paid} >= {threshold}. Gift: {gift}")
                total_bonus_now += gift
                awarded_rules.add(rule_id_str)
            else:
                print(f"[DEBUG] Rule ID {rule_id} already awarded in this session. Skipping.")
    
    # 4. Ενημέρωση Βάσης
    new_remaining = remaining + seconds_to_add + total_bonus_now
    new_total_purchased = total_purchased + seconds_to_add
    
    # Αποθήκευση των rules πίσω σε string
    new_awarded_str = ",".join(awarded_rules)
    
    print(f"[DEBUG] Total Bonus Awarded Now: {total_bonus_now}")
    print(f"[DEBUG] New Remaining: {new_remaining}")
    print("------------------------------------------------")

    c.execute("""UPDATE users SET 
                 remaining_seconds=?, 
                 total_purchased_seconds=?, 
                 session_paid_seconds=?, 
                 session_awarded_rules=? 
                 WHERE id=?""", 
              (new_remaining, new_total_purchased, new_session_paid, new_awarded_str, user_id))
    
    c.execute("INSERT INTO coin_pulses (user_id,pulses,seconds_added) VALUES (?,?,?)", (user_id, pulses, seconds_to_add))
    
    conn.commit()
    conn.close()
    return seconds_to_add, total_bonus_now

# --- LOGGING & HISTORY ---

def log_session(user_id, username, station, action, login_time=None, logout_time=None, duration_seconds=None, remaining_seconds=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("""INSERT INTO session_logs 
            (user_id, username, station, action, login_time, logout_time, duration_seconds, remaining_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username, station, action, login_time, logout_time, duration_seconds, remaining_seconds))
        conn.commit()
    except Exception as e:
        logger.error(f"Error logging session: {e}")
    finally:
        conn.close()

def get_session_history(user_id=None, limit=100):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if user_id:
        c.execute("SELECT * FROM session_logs WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit))
    else:
        c.execute("SELECT * FROM session_logs ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_user_history(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT pulses, seconds_added, created_at FROM coin_pulses WHERE user_id=? ORDER BY created_at DESC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def set_user_admin_flag(user_id, is_admin: bool):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET is_admin=? WHERE id=?", (1 if is_admin else 0, user_id))
    conn.commit()
    conn.close()

def delete_user_by_id(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

def create_guest_user(code, seconds_total: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username,password,is_admin,remaining_seconds,total_purchased_seconds,session_paid_seconds,session_awarded_rules) VALUES (?,?,?,?,?,0,'')",
                  (code, code, 0, seconds_total, seconds_total))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

# --- GUEST BONUS CALCULATION ---

def calculate_total_time_with_bonus(pulses: int):
    """
    Υπολογίζει τον συνολικό χρόνο (Πληρωμένο + Bonus) για Guest Tickets
    με βάση τους κανόνες που ισχύουν για το session.
    """
    sp = get_seconds_per_pulse()
    paid_seconds = pulses * sp
    
    # Αν δεν υπάρχουν pulses, επιστρέφουμε 0
    if paid_seconds <= 0:
        return 0
        
    rules = get_bonus_rules()
    total_bonus = 0
    
    # Ελέγχουμε ΚΑΘΕ κανόνα. Αν το πληρωμένο ποσό τον καλύπτει, προσθέτουμε το δώρο.
    # Ακριβώς όπως κάνουμε και στο session του χρήστη.
    for rule_id, threshold, gift in rules:
        threshold = int(threshold)
        gift = int(gift)
        
        if paid_seconds >= threshold:
            total_bonus += gift
            
    return paid_seconds + total_bonus

# --- DASHBOARD STATS ---

def get_daily_revenue():
    """Returns the total revenue (in pulses * cost) for the current day."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")
    today_end = datetime.now().strftime("%Y-%m-%d 23:59:59")
    
    # Sum pulses for today
    c.execute("SELECT COALESCE(SUM(pulses), 0) FROM coin_pulses WHERE created_at BETWEEN ? AND ?", (today_start, today_end))
    total_pulses = c.fetchone()[0]
    
    # Get current price
    sp = get_seconds_per_pulse()
    # Assuming 1 pulse = 0.50 EUR based on previous code comments. 
    # Ideally this should be in settings, but for now we follow the existing logic.
    # Logic from gui.py: 0.50€ = 1 pulse.
    revenue = total_pulses * 0.50
    
    conn.close()
    return revenue

def get_active_user_count():
    """Returns count of users who have > 0 remaining seconds."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE remaining_seconds > 0 AND is_admin = 0")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_total_user_count():
    """Returns total number of registered non-admin users."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE is_admin = 0")
    count = c.fetchone()[0]
    conn.close()
    return count

# --- FILE SYNC SYSTEM ---

def register_file_sync_source(admin_ip: str, admin_port: int = 5001):
    """Register or update the AdminClient as the file sync source."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM file_sync_source")  # Only one source allowed
    c.execute("INSERT INTO file_sync_source (id, admin_ip, admin_port, last_update) VALUES (1, ?, ?, CURRENT_TIMESTAMP)",
              (admin_ip, admin_port))
    conn.commit()
    conn.close()

def get_file_sync_source():
    """Get the current file sync source (AdminClient IP and port)."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT admin_ip, admin_port, last_update FROM file_sync_source WHERE id=1")
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {"admin_ip": row[0], "admin_port": row[1], "last_update": row[2]}

def add_sync_folder(folder_path: str):
    """Add a folder to sync. Returns (True, folder_id) if added, or (False, existing_folder_id) if exists."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO file_sync_folders (folder_path) VALUES (?)", (folder_path,))
        conn.commit()
        folder_id = c.lastrowid
        return True, folder_id
    except sqlite3.IntegrityError:
        # Folder already exists, get its ID
        c.execute("SELECT id FROM file_sync_folders WHERE folder_path=?", (folder_path,))
        row = c.fetchone()
        folder_id = row[0] if row else None
        return False, folder_id
    finally:
        conn.close()

def remove_sync_folder(folder_id: int):
    """Remove a sync folder and its file index entries."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM file_index WHERE folder_id=?", (folder_id,))
    c.execute("DELETE FROM file_sync_folders WHERE id=?", (folder_id,))
    conn.commit()
    conn.close()

def get_sync_folders():
    """Get all sync folders."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, folder_path FROM file_sync_folders ORDER BY folder_path")
    rows = c.fetchall()
    conn.close()
    return rows

def update_file_index(folder_id: int, files: list):
    """
    Update the file index for a folder.
    files: list of dicts with {relative_path, file_size, modified_time}
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Get existing files for this folder
    c.execute("SELECT relative_path FROM file_index WHERE folder_id=?", (folder_id,))
    existing = set(row[0] for row in c.fetchall())
    
    new_paths = set()
    for f in files:
        new_paths.add(f["relative_path"])
        c.execute("""INSERT OR REPLACE INTO file_index 
                     (relative_path, folder_id, file_size, modified_time, last_scan)
                     VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                  (f["relative_path"], folder_id, f["file_size"], f["modified_time"]))
    
    # Remove files that no longer exist
    removed = existing - new_paths
    for path in removed:
        c.execute("DELETE FROM file_index WHERE folder_id=? AND relative_path=?", (folder_id, path))
    
    conn.commit()
    conn.close()
    return len(files), len(removed)

def get_file_index(folder_id: int = None):
    """Get the file index, optionally filtered by folder."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if folder_id:
        c.execute("""SELECT fi.id, fi.relative_path, fi.file_size, fi.modified_time, fsf.folder_path
                     FROM file_index fi
                     JOIN file_sync_folders fsf ON fi.folder_id = fsf.id
                     WHERE fi.folder_id=?
                     ORDER BY fi.relative_path""", (folder_id,))
    else:
        c.execute("""SELECT fi.id, fi.relative_path, fi.file_size, fi.modified_time, fsf.folder_path
                     FROM file_index fi
                     JOIN file_sync_folders fsf ON fi.folder_id = fsf.id
                     ORDER BY fsf.folder_path, fi.relative_path""")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "relative_path": r[1], "file_size": r[2], "modified_time": r[3], "folder_path": r[4]} for r in rows]

def get_file_index_summary():
    """Get summary of file index: folder count and total file count."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM file_sync_folders")
    folder_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM file_index")
    file_count = c.fetchone()[0]
    conn.close()
    return {"folder_count": folder_count, "file_count": file_count}
