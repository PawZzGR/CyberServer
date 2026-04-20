import os
import sys

# --- ENVIRONMENT SANITIZATION ---
# This MUST happen before any third-party imports (like tkinter) to ensure
# the embedded Python interpreter doesn't try to load system-wide libraries.
for env_var in ['PYTHONPATH', 'PYTHONHOME', 'PYTHONNOUSERSITE', 'PYTHONUSERBASE']:
    if env_var in os.environ:
        del os.environ[env_var]

import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog, ttk
import json
import threading
import time
import os
import sys
from urllib import request, error
import ctypes
from ctypes import wintypes
import subprocess
import logging

# Add parent directory to sys.path to find auto_updater.py when running from source
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import auto_updater for version info and manual update checks
try:
    import auto_updater
except ImportError:
    auto_updater = None

# Configure basic debugging logger
logging.basicConfig(
    filename='client_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.info("Starting AdminClient...")
try:
    from utils import hash_password, verify_password
except Exception:
    # Fallback if utils missing or bcrypt not installed
    def hash_password(pwd): return pwd
    def verify_password(pwd, hashed): return pwd == hashed

# Import toast if available
try:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'PythonServerArduino'))
    from toast import show_toast
    TOAST_AVAILABLE = True
except:
    TOAST_AVAILABLE = False
    def show_toast(root, message, toast_type='info', duration=3000):
        if toast_type == 'error':
            messagebox.showerror("Error", message, parent=root)
        elif toast_type == 'success':
            messagebox.showinfo("Success", message, parent=root)
        else:
            messagebox.showinfo("Info", message, parent=root)

# -------- SERVER CONFIG --------
# Detect if running as compiled EXE or as script
if getattr(sys, 'frozen', False):
    # Running as compiled EXE (PyInstaller, cx_Freeze, etc.)
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    # Running as Python script
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = "admin_config.json"
MAPPINGS_FILE = "client_admin_mappings.json"
SYNC_FOLDERS_FILE = "sync_folders.json"

# Default values
SERVER_HOST = "192.168.1.6"
SERVER_PORT = 5000
STATION_NAME = "Unknown"
FILE_SERVER_PORT = 5001
SCAN_INTERVAL = 60  # Minutes
FILE_SERVER_PORT = 5001
SCAN_INTERVAL = 60  # Minutes
SETTINGS_PASSWORD_HASH = None # Default, will be loaded from config

def get_app_data_dir():
    """Get the persistent AppData directory for settings."""
    app_data = os.getenv('APPDATA')
    if not app_data:
        app_data = os.path.expanduser("~")
    
    path = os.path.join(app_data, "CyberClient", "Admin")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        print(f"Failed to create AppData dir: {e}")
        return _BASE_DIR # Fallback to local
    return path

def get_config_path():
    return os.path.join(get_app_data_dir(), CONFIG_FILE)

def get_sync_folders_path():
    return os.path.join(get_app_data_dir(), SYNC_FOLDERS_FILE)

def save_json_atomic(filepath, data):
    """Save JSON to file atomically to prevent corruption on crash/reboot."""
    tmp_path = filepath + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno()) # Ensure write to disk
        
        # Atomic replace
        if os.path.exists(filepath):
            os.remove(filepath)
        os.rename(tmp_path, filepath)
    except Exception as e:
        logging.error(f"Failed to save atomic {filepath}: {e}")

def get_local_ip():
    """Get the local IP address of this machine."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def load_config():
    global SERVER_HOST, SERVER_PORT, STATION_NAME, SYNC_INTERVAL, FILE_SERVER_PORT, SCAN_INTERVAL, SETTINGS_PASSWORD_HASH
    
    # Try AppData first
    cfg_path = get_config_path()
    
    # Migration: Check local first
    local_config = os.path.join(_BASE_DIR, "admin_config.json")
    if not os.path.exists(cfg_path) and os.path.exists(local_config):
        logging.info("Migrating Admin config to AppData...")
        try:
            with open(local_config, 'r', encoding='utf-8') as f:
                data = json.load(f)
            save_json_atomic(cfg_path, data)
        except: pass

    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            SERVER_HOST = config.get("server_address", "192.168.1.5")
            SERVER_PORT = config.get("server_port", 5000)
            STATION_NAME = config.get("client_machine", "Unknown")
            SYNC_INTERVAL = config.get("sync_interval", 3600)
            FILE_SERVER_PORT = config.get("file_server_port", 5001)
            SCAN_INTERVAL = config.get("scan_interval", 60)
            SETTINGS_PASSWORD_HASH = config.get("settings_password_hash", None)
            
            logging.info(f"Loaded config: SERVER={SERVER_HOST}:{SERVER_PORT}, STATION={STATION_NAME}")
    except Exception as e:
        logging.error(f"Failed to load config: {e}")
        SYNC_INTERVAL = 3600
        pass

load_config()

LOGIN_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/login"
UPDATE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/update_remaining"
PING_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/ping"
PATHS_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/game_paths"

# File Sync API URLs
REGISTER_SOURCE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/file_sync/register_source"
ADD_FOLDER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/file_sync/add_folder"
REMOVE_FOLDER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/file_sync/remove_folder"
UPDATE_INDEX_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/file_sync/update_index"
GET_FOLDERS_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/file_sync/folders"

# -------- WINDOWS KEYBLOCK --------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_TAB = 0x09
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_ESCAPE = 0x1B
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt key
keyboard_block_enabled = True
keyboard_hook_id = None

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", wintypes.ULONG)]

def low_level_keyboard_proc(nCode, wParam, lParam):
    if nCode == 0 and keyboard_block_enabled and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk = kb.vkCode
        ctrl_down = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        alt_down = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
        
        # Block Alt+Tab and Alt+Esc (task switcher)
        if alt_down and vk == VK_TAB: return 1
        if alt_down and vk == VK_ESCAPE: return 1
        
        # Block Windows keys
        if vk in (VK_LWIN, VK_RWIN): return 1
        
        # Block Ctrl+Esc (Start menu)
        if ctrl_down and vk == VK_ESCAPE: return 1
        
    return user32.CallNextHookEx(keyboard_hook_id, nCode, wParam, lParam)

LowLevelKeyboardProc = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.INT, wintypes.WPARAM, wintypes.LPARAM)

def install_keyboard_hook():
    global keyboard_hook_id, keyboard_block_enabled
    if keyboard_hook_id is not None: return
    prot = LowLevelKeyboardProc(low_level_keyboard_proc)
    keyboard_hook_id = user32.SetWindowsHookExW(WH_KEYBOARD_LL, prot, kernel32.GetModuleHandleW(None), 0)
    # Keep reference to callback to prevent GC
    install_keyboard_hook.prot = prot 
    keyboard_block_enabled = True

def uninstall_keyboard_hook():
    global keyboard_hook_id, keyboard_block_enabled
    if keyboard_hook_id:
        user32.UnhookWindowsHookEx(keyboard_hook_id)
        keyboard_hook_id = None
    keyboard_block_enabled = False

def pump_messages():
    msg = wintypes.MSG()
    while True:
        while user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)

# -------- HTTP FILE SERVER FOR GAME SYNC --------

from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse
import socket

class FileSyncHandler(SimpleHTTPRequestHandler):
    """HTTP handler that serves files from configured sync folders."""
    
    sync_folders = []  # Will be set by ClientApp
    
    def translate_path(self, path):
        """Translate URL path to filesystem path."""
        # Parse the path: /folder_index/relative/path/to/file
        # OR just /folder_index/ for root of that folder
        path = unquote(urlparse(path).path)
        parts = path.strip('/').split('/', 1)
        
        if len(parts) < 1 or not parts[0]:
            return None
        
        try:
            folder_idx = int(parts[0])
            # If only folder index provided, rel_path is empty (list root)
            rel_path = parts[1] if len(parts) > 1 else ""
        except (ValueError, IndexError):
            return None
        
        if folder_idx >= len(self.sync_folders):
            return None
            
        folder = self.sync_folders[folder_idx]
        if rel_path:
            full_path = os.path.join(folder, rel_path.replace('/', os.sep))
        else:
            full_path = folder  # Return the folder root itself
        return full_path
    
    def do_GET(self):
        try:
            if self.path == '/folders':
                # Return list of shared folders
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"folders": self.sync_folders}).encode())
                return
                
            path = self.translate_path(self.path)
            if not path or not os.path.exists(path):
                self.send_error(404, "File not found")
                return
                
            if os.path.isdir(path):
                # List directory
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                files = []
                for item in os.listdir(path):
                    full = os.path.join(path, item)
                    try:
                        stat = os.stat(full)
                        files.append({
                            "name": item,
                            "is_dir": os.path.isdir(full),
                            "size": stat.st_size if os.path.isfile(full) else 0,
                            "mtime": stat.st_mtime  # Modification time for date comparison
                        })
                    except:
                        files.append({
                            "name": item,
                            "is_dir": os.path.isdir(full),
                            "size": 0,
                            "mtime": 0
                        })
                self.wfile.write(json.dumps({"files": files}).encode())
            else:
                # Serve file with proper socket cleanup
                try:
                    with open(path, 'rb') as f:
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/octet-stream')
                        self.send_header('Content-Length', os.path.getsize(path))
                        self.end_headers()
                        while chunk := f.read(65536):
                            try:
                                self.wfile.write(chunk)
                            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError) as conn_err:
                                logging.warning(f"Client disconnected during download: {path} - {conn_err}")
                                return  # Exit cleanly without crashing
                except FileNotFoundError:
                    self.send_error(404, "File not found")
                except PermissionError:
                    self.send_error(403, "Permission denied")
                except Exception as e:
                    logging.error(f"Error serving file {path}: {e}")
                    try:
                        self.send_error(500, str(e))
                    except:
                        pass  # Client already disconnected
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError) as e:
            # Client disconnected during response - log and continue
            logging.debug(f"Client connection lost during request: {e}")
        except Exception as e:
            logging.error(f"Unexpected error in do_GET: {e}")
    
    def log_message(self, format, *args):
        pass  # Suppress logging

def start_file_server(port, folders):
    """Start the HTTP file server with auto-restart watchdog.
    
    Uses ThreadingHTTPServer for concurrent connections and
    automatically restarts if the server crashes.
    """
    FileSyncHandler.sync_folders = folders
    max_restarts = 50  # Allow many restarts before giving up
    restart_count = 0
    restart_delay = 2  # Start with 2 seconds
    
    while restart_count < max_restarts:
        try:
            # Use ThreadingHTTPServer for concurrent connections
            httpd = ThreadingHTTPServer(('0.0.0.0', port), FileSyncHandler)
            httpd.daemon_threads = True  # Threads die when main thread dies
            httpd.request_queue_size = 50  # Allow more pending connections
            
            print(f"[FILE SERVER] Listening on port {port} (ThreadingHTTPServer)")
            logging.info(f"File server started on port {port}")
            
            # Reset restart tracking on successful start
            restart_count = 0
            restart_delay = 2
            
            httpd.serve_forever()
        except OSError as e:
            if e.errno == 10048:  # Port already in use (Windows)
                logging.error(f"Port {port} already in use, waiting...")
                time.sleep(5)
            else:
                restart_count += 1
                logging.error(f"File server OSError, restarting ({restart_count}/{max_restarts}): {e}")
                time.sleep(restart_delay)
                restart_delay = min(restart_delay * 2, 30)  # Exponential backoff, max 30s
        except Exception as e:
            restart_count += 1
            print(f"[FILE SERVER ERROR] Restarting ({restart_count}/{max_restarts}): {e}")
            logging.error(f"File server crashed, restarting ({restart_count}/{max_restarts}): {e}")
            time.sleep(restart_delay)
            restart_delay = min(restart_delay * 2, 30)  # Exponential backoff, max 30s
    
    logging.critical(f"File server exceeded max restarts ({max_restarts}), giving up")
    print(f"[FILE SERVER] FATAL: Exceeded max restarts, server is down")

def scan_folder(folder_path):
    """Scan a folder and return list of files with metadata."""
    files = []
    if not os.path.exists(folder_path):
        return files
    
    for root, dirs, filenames in os.walk(folder_path):
        for filename in filenames:
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, folder_path)
            try:
                stat = os.stat(full_path)
                files.append({
                    "relative_path": rel_path.replace(os.sep, '/'),
                    "file_size": stat.st_size,
                    "modified_time": stat.st_mtime
                })
            except:
                pass
    return files

def load_sync_folders():
    """Load sync folders from persistent config."""
    path = get_sync_folders_path()
    
    # Migration
    local_path = os.path.join(_BASE_DIR, "sync_folders.json")
    if not os.path.exists(path) and os.path.exists(local_path):
        try:
            with open(local_path, 'r') as f: save_json_atomic(path, json.load(f))
        except: pass
        
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return []

def save_sync_folders(folders):
    """Save sync folders to persistent config."""
    try:
        save_json_atomic(get_sync_folders_path(), folders)
    except:
        pass

# -------- CLIENT APP (ADMIN / PUSH) --------

class ClientApp:
    BG_MAIN = "#FAF5EF" # Beige Theme
    BG_CARD = "#EFE0D0" # Darker Beige/Tan for card
    BG_BUTTON = "#8B7355" # Brownish button
    BORDER_COLOR = "#D7C4A8"
    TEXT_PRIMARY = "#3E2723" # Dark Brown text
    ACCENT = "#C19A6B"

    def __init__(self, root):
        self.root = root
        self.username = None
        self.password = None
        self.remaining_seconds = 0
        self.remaining_seconds = 0
        self.timer_running = False
        self.popup_active = False # Track if a dialog/settings is open
        self.maintenance_mode = False # Track if maintenance is active
        
        # Reboot countdown after session ends
        self.session_ended_naturally = False  # True only when time runs out
        self.reboot_countdown_active = False  # True when countdown is running
        self.reboot_countdown_seconds = 0     # Remaining seconds to reboot
        self.base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        
        # Game Sync settings
        self.sync_folders = load_sync_folders()
        self.file_server_running = False
        
        self.setup_window()
        self.build_login_ui()
        
        # Start file server for game sync immediately (system service behavior)
        self.start_game_sync_server()

        # Start Smart Watchdog for Focus
        self.check_lock_focus()

    def setup_window(self):
        self.root.configure(bg=self.BG_MAIN)
        self.root.overrideredirect(True)
        self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_reboot)

    def on_close_reboot(self):
        # Reboot the PC when the application is closed
        subprocess.Popen([r"C:\Windows\System32\shutdown.exe", "/r", "/t", "0"], shell=False)

    def clear_window(self):
        for w in self.root.winfo_children(): w.destroy()

    def check_lock_focus(self):
        """Aggressive focus enforcement when locked."""
        # IF session is running OR maintenance mode OR popup open -> Do NOT enforce focus
        if self.timer_running or getattr(self, 'maintenance_mode', False) or self.popup_active:
            # Relax topmost if we just switched state
            if self.root.attributes("-topmost"):
                self.root.attributes("-topmost", False)
            
            # Re-check less frequently just to be safe, or stop entirely
            self.root.after(1000, self.check_lock_focus)
            return

        # OTHERWISE (Locked): Force window to top
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
            # self.root.focus_force() # Optional: can be annoying if typing elsewhere
        except:
            pass
            
        # Check again in 100ms
        self.root.after(100, self.check_lock_focus)

    # --- UI ---

    def build_login_ui(self):
        self.clear_window()
        self.root.overrideredirect(True)
        self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        self.root.lift()
        
        # Background Image
        bg_path = os.path.join(self.base_dir, "background.png")
        if os.path.exists(bg_path):
            try:
                self.bg_img = tk.PhotoImage(file=bg_path)
                bg_lbl = tk.Label(self.root, image=self.bg_img)
                bg_lbl.place(x=0, y=0, relwidth=1, relheight=1)
            except Exception as e:
                print(f"Failed to load background: {e}")
        
        # Gear Icon
        gear_btn = tk.Button(self.root, text="⚙", font=("Segoe UI", 16), bg=self.BG_MAIN, fg=self.TEXT_PRIMARY, bd=0, command=self.open_settings_password, cursor="hand2")
        gear_btn.place(relx=0.95, rely=0.05, anchor="ne")

        # Main Card Frame (Centered) - Admin Theme (Dark Grey/Blue)
        card = tk.Frame(self.root, bg=self.BG_CARD, padx=50, pady=50, highlightthickness=1, highlightbackground=self.BORDER_COLOR)
        card.place(relx=0.5, rely=0.5, anchor="center")
        
        # Header
        tk.Label(card, text="CyberClient", font=("Segoe UI", 28, "bold"), bg=self.BG_CARD, fg=self.TEXT_PRIMARY).pack(pady=(0, 5))
        tk.Label(card, text="Administrator Access!!!", font=("Segoe UI", 12), bg=self.BG_CARD, fg=self.ACCENT).pack(pady=(0, 5))
        # Version label
        _ver = auto_updater.VERSION if auto_updater else "?.?.?"
        tk.Label(card, text=f"v{_ver}", font=("Segoe UI", 9), bg=self.BG_CARD, fg="#999999").pack(pady=(0, 20))
        
        # Custom Entry Style Helper
        def create_entry(parent, placeholder, is_password=False):
            # Input wrapper for border
            f = tk.Frame(parent, bg=self.BG_CARD, highlightthickness=1, highlightbackground=self.BORDER_COLOR, padx=10, pady=5)
            f.pack(fill="x", pady=10)
            
            ent = tk.Entry(f, font=("Segoe UI", 11), bd=0, bg=self.BG_CARD, fg=self.TEXT_PRIMARY, width=30, show="*" if is_password else "", insertbackground='white')
            ent.pack(fill="x")
            
            # Simple placeholder logic
            if not is_password:
                ent.insert(0, placeholder)
                ent.bind("<FocusIn>", lambda e: ent.delete(0, tk.END) if ent.get() == placeholder else None)
                ent.bind("<FocusOut>", lambda e: ent.insert(0, placeholder) if not ent.get() else None)
                
            return ent

        self.user_entry = create_entry(card, "Username")
        self.pass_entry = create_entry(card, "Password", is_password=True)
        
        # Connection Status (Inside Card)
        self.lbl_status = tk.Label(card, text="Connecting...", font=("Segoe UI", 9, "bold"), bg=self.BG_CARD, fg=self.ACCENT)
        self.lbl_status.pack(pady=(15, 5))
        
        # Login Button
        btn_frame = tk.Frame(card, bg=self.BG_BUTTON, padx=0, pady=0)
        btn_frame.pack(fill="x", pady=15)
        
        login_btn = tk.Button(btn_frame, text="LOG IN", command=self.login, bg=self.BG_BUTTON, fg="white", 
                            font=("Segoe UI", 12, "bold"), bd=0, padx=10, pady=10, activebackground=self.ACCENT, cursor="hand2")
        login_btn.pack(fill="x")
        
        # Reboot countdown label (shown only when countdown is active, no X button)
        self.reboot_label = tk.Label(card, text="", font=("Segoe UI", 11, "bold"), 
                                      bg=self.BG_CARD, fg="#e74c3c")
        self.reboot_label.pack(pady=(10, 0))
        self.check_conn_running = True
        threading.Thread(target=self.connection_checker, daemon=True).start()
        
        self.user_entry.bind("<Return>", lambda e: self.pass_entry.focus())
        self.pass_entry.bind("<Return>", lambda e: self.login())
        self.user_entry.focus()

    def login(self):
        u = self.user_entry.get().strip()
        p = self.pass_entry.get().strip()
        if not u or not p: return
        
        def run():
            try:
                data = json.dumps({"username": u, "password": p, "station": STATION_NAME}).encode()
                req = request.Request(LOGIN_URL, data=data, headers={"Content-Type": "application/json"})
                with request.urlopen(req, timeout=5) as res:
                    resp = json.loads(res.read().decode())
                self.root.after(0, lambda: self.handle_login(resp, u, p))
            except error.URLError:
                self.root.after(0, lambda: messagebox.showerror("Connection Error", "Not connection with the server"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=run, daemon=True).start()

    def handle_login(self, resp, u, p):
        if resp.get("status") == "ok":
            # Cancel any active reboot countdown
            self.reboot_countdown_active = False
            self.session_ended_naturally = False
            
            self.username = u
            self.password = p
            self.remaining_seconds = resp.get("remaining_seconds", 0)
            self.check_conn_running = False # Stop login checker
            self.start_session()
            # Sync server is already running from init
        else:
            reason = resp.get("reason", "")
            if reason == "not_found":
                msg = "Account does not exist"
            elif reason == "no_time":
                msg = "No remaining time"
            elif reason == "already_logged_in":
                msg = "This account is already being used."
            else:
                msg = reason or "Unknown error"
            messagebox.showerror("Login Failed", msg)

    def start_session(self):
        uninstall_keyboard_hook()
        self.timer_running = True
        self.clear_window()
        self.root.overrideredirect(False)
        self.root.attributes("-topmost", False)
        self.root.geometry("300x150")
        self.root.configure(bg=self.BG_MAIN)
        
        # Settings Button (Small, Top Right)
        gear_btn = tk.Button(self.root, text="⚙", font=("Segoe UI", 10), bg=self.BG_MAIN, fg=self.TEXT_PRIMARY, bd=0, command=self.open_settings_password, cursor="hand2")
        gear_btn.place(relx=0.98, rely=0.02, anchor="ne")
        
        # Maintenance Lock Button (if in maintenance mode)
        if hasattr(self, 'maintenance_mode') and self.maintenance_mode:
            tk.Label(self.root, text="MAINTENANCE MODE", font=("Segoe UI", 12, "bold"), fg="red", bg=self.BG_MAIN).pack(pady=10)
            tk.Button(self.root, text="LOCK PC", command=self.restore_lock_screen, bg="#e74c3c", fg="white", font=("Segoe UI", 12, "bold")).pack(pady=5)
            return # Don't show timer UI

        lbl = tk.Label(self.root, text="", font=("Segoe UI", 20, "bold"), bg=self.BG_MAIN, fg=self.TEXT_PRIMARY)
        lbl.pack(expand=True)
        
        def tick():
            while self.timer_running and self.remaining_seconds > 0:
                m, s = divmod(self.remaining_seconds, 60)
                h, m = divmod(m, 60)
                self.root.after(0, lambda: lbl.config(text=f"{h:02}:{m:02}:{s:02}"))
                time.sleep(1)
                self.remaining_seconds -= 1
                if self.remaining_seconds % 5 == 0: self.send_update()
            
            # Check why loop ended
            if self.remaining_seconds <= 0:
                 self.session_ended_naturally = True
            else:
                 self.session_ended_naturally = False
                 
            self.timer_running = False
            self.send_update()
            # Restore full lock screen
            self.root.after(0, self.restore_lock_screen)
            
        threading.Thread(target=tick, daemon=True).start()
    
    def restore_lock_screen(self):
        """Restore full screen lock when session ends"""
        self.maintenance_mode = False # Reset maintenance flag
        install_keyboard_hook()
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)
        self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        self.root.focus_force()
        self.root.lift()
        self.build_login_ui()
        
        # Start reboot countdown only if session ended due to time running out
        if self.session_ended_naturally:
            self.start_reboot_countdown()
    
    def start_reboot_countdown(self):
        """Start 120-second countdown to reboot. Only cancelled by successful login."""
        self.reboot_countdown_active = True
        self.reboot_countdown_seconds = 120
        logging.info("Starting reboot countdown (120 seconds)")
        
        def countdown():
            while self.reboot_countdown_seconds > 0:
                # Cancel if user logged in (timer_running becomes True)
                if self.timer_running or not self.reboot_countdown_active:
                    self.reboot_countdown_active = False
                    self.session_ended_naturally = False  # Reset for next session
                    logging.info("Reboot countdown cancelled - user logged in")
                    # Clear the label
                    self.root.after(0, lambda: self.update_reboot_label(0))
                    return
                
                # Update UI with countdown (no X button, just display)
                self.root.after(0, lambda s=self.reboot_countdown_seconds: 
                    self.update_reboot_label(s))
                
                time.sleep(1)
                self.reboot_countdown_seconds -= 1
            
            # 60 seconds passed, no login - REBOOT!
            if not self.timer_running and self.reboot_countdown_active:
                logging.info("Reboot countdown expired - rebooting PC")
                subprocess.Popen([r"C:\Windows\System32\shutdown.exe", "/r", "/t", "0"], shell=False)
        
        threading.Thread(target=countdown, daemon=True).start()
    
    def update_reboot_label(self, seconds):
        """Update the reboot countdown display on login screen."""
        try:
            if hasattr(self, 'reboot_label') and self.reboot_label.winfo_exists():
                if seconds > 0:
                    self.reboot_label.config(text=f"⚠️ Επανεκκίνηση σε {seconds} δευτ...")
                else:
                    self.reboot_label.config(text="")
        except tk.TclError:
            pass  # Widget destroyed

    def send_update(self):
        try:
            data = json.dumps({"username": self.username, "password": self.password, "remaining_seconds": self.remaining_seconds, "station": STATION_NAME}).encode()
            with request.urlopen(request.Request(UPDATE_URL, data=data, headers={"Content-Type": "application/json"}, method="POST"), timeout=2) as resp:
                result = json.loads(resp.read().decode())
                if result.get("status") != "ok":
                    print(f"[UPDATE FAILED] {result}")
                else:
                    print(f"[UPDATE OK] Remaining: {self.remaining_seconds}s")
        except Exception as e:
            print(f"[UPDATE ERROR] {e}")
            # If update fails (server down), force logout
            self.timer_running = False

    def connection_checker(self):
        def safe_update(text, fg, bg):
            try:
                if self.lbl_status.winfo_exists():
                    self.lbl_status.config(text=text, fg=fg, bg=bg)
            except: pass

        while self.check_conn_running:
            try:
                with request.urlopen(PING_URL, timeout=2) as r:
                    if r.status == 200:
                        self.root.after(0, lambda: safe_update("CONNECTED", "#00FF00", self.BG_CARD))
                    else:
                        raise Exception(f"HTTP {r.status}")
            except Exception as e:
                logging.warning(f"Connection failed to {PING_URL}: {e}")
                self.root.after(0, lambda: safe_update("DISCONNECTED", "#FF5252", self.BG_CARD))
            time.sleep(5)

    def start_maintenance_session(self):
        """Unlock the PC for maintenance without server connection."""
        logging.info("Starting Maintenance Session")
        self.maintenance_mode = True
        uninstall_keyboard_hook()
        self.timer_running = False # No timer
        self.session_ended_naturally = False
        self.reboot_countdown_active = False # Cancel any reboot
        
        # Close settings
        if hasattr(self, 'close_settings_callback'):
            self.close_settings_callback()
            
        # Show "Session" window but with Maintenance UI
        self.clear_window()
        self.root.overrideredirect(False)
        self.root.attributes("-topmost", False) # Allow using other apps
        self.root.geometry("300x150") # Small tool window
        self.root.configure(bg=self.BG_MAIN)
        
        # Re-use start_session UI logic which we modified to handle maintenance_mode
        self.start_session() 

    # --- SETTINGS / SYNC ---

    def check_settings_password(self, pwd):
        if not SETTINGS_PASSWORD_HASH: return True # Should not happen if flow is correct
        try:
            return verify_password(pwd, SETTINGS_PASSWORD_HASH)
        except:
             # Fallback if hash not valid or bcrypt missing
            return False

    def open_settings_password(self):
        """Ask for password before opening settings."""
        global SETTINGS_PASSWORD_HASH
        self.popup_active = True
        try:
            self.root.attributes("-topmost", False) # Allow dialog to float
            
            if not SETTINGS_PASSWORD_HASH:
                # First time setup
                pwd = simpledialog.askstring("Settings Setup", "Set a password for Admin Settings:", show="*", parent=self.root)
                if pwd:
                    try:
                        hashed = hash_password(pwd)
                        SETTINGS_PASSWORD_HASH = hashed
                        
                        # Save immediately
                        new_conf = {
                            "client_machine": STATION_NAME,
                            "server_address": SERVER_HOST,
                            "server_port": SERVER_PORT,
                            "sync_interval": SYNC_INTERVAL,
                            "settings_password_hash": SETTINGS_PASSWORD_HASH
                        }
                        save_json_atomic(get_config_path(), new_conf)
                        
                        messagebox.showinfo("Setup", "Password set! opening settings...", parent=self.root)
                        self.open_settings_ui()
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to set password: {e}")
                
                if not hasattr(self, 'settings_open'): 
                    self.popup_active = False
                return

            pwd = simpledialog.askstring("Settings", "Enter Password:", show="*", parent=self.root)
            if pwd and self.check_settings_password(pwd):
                self.open_settings_ui()
            elif pwd:
                messagebox.showerror("Error", "Wrong password")
                self.popup_active = False
            else:
                 self.popup_active = False
                 
        except:
             self.popup_active = False

    def open_settings_ui(self):
        # Relax main window (security restored on close)
        self.root.attributes("-topmost", False)
        self.popup_active = True
        self.settings_open = True
        
        win = tk.Toplevel(self.root)
        win.title("Admin Client Settings")
        win.geometry("600x650")
        win.attributes("-topmost", True)
        win.focus_force()
        win.grab_set() # Modal
        
        def on_close():
            self.popup_active = False
            if hasattr(self, 'settings_open'): del self.settings_open
            win.destroy()
            if not getattr(self, 'maintenance_mode', False) and not self.timer_running:
                self.root.attributes("-topmost", True)

        self.close_settings_callback = on_close
        win.protocol("WM_DELETE_WINDOW", self.close_settings_callback)
        
        # --- Config Section ---
        tk.Label(win, text="General Configuration", font=("Segoe UI", 12, "bold"), fg=self.ACCENT).pack(pady=(10, 5))
        
        cfg_frame = tk.Frame(win, padx=20)
        cfg_frame.pack(fill="x")
        
        def add_field(parent, label, val):
            f = tk.Frame(parent)
            f.pack(fill="x", pady=2)
            tk.Label(f, text=label, width=20, anchor="w").pack(side="left")
            e = tk.Entry(f)
            e.pack(side="left", fill="x", expand=True)
            e.insert(0, str(val))
            return e
            
        self.ent_station = add_field(cfg_frame, "Station Name:", STATION_NAME)
        self.ent_host = add_field(cfg_frame, "Server IP:", SERVER_HOST)
        self.ent_port = add_field(cfg_frame, "Server Port:", SERVER_PORT)
        self.ent_interval = add_field(cfg_frame, "Sync Interval (sec):", SYNC_INTERVAL)
        
        ttk.Separator(win, orient="horizontal").pack(fill="x", pady=15)
        
        # --- Game Sync Section (P2P) ---
        tk.Label(win, text="Game Sync (Share to User Clients)", font=("Segoe UI", 12, "bold"), fg=self.ACCENT).pack(pady=(10, 5))
        
        # Status
        status_text = f"Serving {len(self.sync_folders)} folders" if self.sync_folders else "No folders configured"
        self.sync_status_lbl = tk.Label(win, text=f"Status: {status_text}", font=("Segoe UI", 9))
        self.sync_status_lbl.pack(pady=2)
        
        # Sync folders list frame
        sync_list_frame = tk.Frame(win, height=100)
        sync_list_frame.pack(fill="x", padx=10, pady=5)
        sync_list_frame.pack_propagate(False)
        
        self.sync_listbox = tk.Listbox(sync_list_frame, font=("Segoe UI", 9), height=4)
        sync_scrollbar = tk.Scrollbar(sync_list_frame, orient="vertical", command=self.sync_listbox.yview)
        self.sync_listbox.configure(yscrollcommand=sync_scrollbar.set)
        
        sync_scrollbar.pack(side="right", fill="y")
        self.sync_listbox.pack(side="left", fill="both", expand=True)
        
        # Populate listbox
        for folder in self.sync_folders:
            self.sync_listbox.insert(tk.END, folder)
        
        # Buttons for add/remove
        sync_btn_frame = tk.Frame(win)
        sync_btn_frame.pack(pady=5)
        
        def add_sync_folder():
            folder = filedialog.askdirectory(parent=win)
            if folder:
                folder = folder.replace("/", "\\")
                if self.add_sync_folder_ui(folder):
                    self.sync_listbox.insert(tk.END, folder)
                    self.sync_status_lbl.config(text=f"Status: Serving {len(self.sync_folders)} folders")
                    messagebox.showinfo("Added", f"Folder added: {folder}", parent=win)
                else:
                    messagebox.showwarning("Exists", "Folder already in list", parent=win)
        
        def remove_sync_folder():
            sel = self.sync_listbox.curselection()
            if sel:
                folder = self.sync_listbox.get(sel[0])
                self.remove_sync_folder_ui(folder)
                self.sync_listbox.delete(sel[0])
                self.sync_status_lbl.config(text=f"Status: Serving {len(self.sync_folders)} folders")
        
        def scan_now():
            self.sync_status_lbl.config(text="Status: Scanning...")
            def do_scan():
                self.scan_and_update_index()
                def update_ui():
                    if self.sync_status_lbl.winfo_exists():
                        self.sync_status_lbl.config(text=f"Status: Scan complete! ({len(self.sync_folders)} folders)")
                self.root.after(0, update_ui)
            threading.Thread(target=do_scan, daemon=True).start()
        
        tk.Button(sync_btn_frame, text="+ Add Folder", command=add_sync_folder, bg=self.BG_BUTTON, fg="white").pack(side="left", padx=5)
        tk.Button(sync_btn_frame, text="Remove Selected", command=remove_sync_folder, bg="#C0392B", fg="white").pack(side="left", padx=5)
        tk.Button(sync_btn_frame, text="Scan Now", command=scan_now, bg="#27AE60", fg="white").pack(side="left", padx=5)
        
        # Scan interval
        scan_frame = tk.Frame(win)
        scan_frame.pack(pady=5)
        tk.Label(scan_frame, text="Auto-scan every:", font=("Segoe UI", 9)).pack(side="left")
        self.ent_scan_interval = tk.Entry(scan_frame, width=5)
        self.ent_scan_interval.pack(side="left", padx=5)
        self.ent_scan_interval.insert(0, str(SCAN_INTERVAL))
        tk.Label(scan_frame, text="minutes", font=("Segoe UI", 9)).pack(side="left")
            
        tk.Button(win, text="Save Settings", command=lambda: self.save_settings(win), bg=self.BG_BUTTON, fg="white", font=("Segoe UI", 10, "bold")).pack(pady=10)
        
        # --- System Actions (Bottom) ---
        ttk.Separator(win, orient="horizontal").pack(fill="x", pady=5)
        
        sys_frame = tk.Frame(win)
        sys_frame.pack(fill="x", pady=10)
        
        # Left side: Maintenance unlock
        tk.Button(sys_frame, text="🔓 UNLOCK / MAINTENANCE", command=self.start_maintenance_session, bg="#e67e22", fg="white", font=("Segoe UI", 10, "bold")).pack(side="left", padx=20)
        
        # Right side: Updates
        upd_frame = tk.Frame(sys_frame)
        upd_frame.pack(side="right", padx=20)
        _ver = auto_updater.VERSION if auto_updater else "?.?.?"
        tk.Label(upd_frame, text=f"Version: v{_ver}", font=("Segoe UI", 9), fg="#666666").pack(pady=(0,2))
        tk.Button(upd_frame, text="🔄 Check Updates", command=lambda: self.check_updates_ui(win), bg="#3498DB", fg="white", font=("Segoe UI", 9, "bold")).pack()

    def save_settings(self, win):
        global SERVER_HOST, SERVER_PORT, STATION_NAME, SYNC_INTERVAL, SCAN_INTERVAL
        global LOGIN_URL, UPDATE_URL, PING_URL, PATHS_URL
        
        # Save Config
        try:
            SERVER_HOST = self.ent_host.get().strip()
            SERVER_PORT = int(self.ent_port.get().strip())
            STATION_NAME = self.ent_station.get().strip()
            SYNC_INTERVAL = int(self.ent_interval.get().strip())
            SCAN_INTERVAL = int(self.ent_scan_interval.get().strip()) if self.ent_scan_interval.get().strip() else 60
            
            # Update URLs dynamically
            LOGIN_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/login"
            UPDATE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/update_remaining"
            PING_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/ping"

            new_conf = {
                "client_machine": STATION_NAME,
                "server_address": SERVER_HOST,
                "server_port": SERVER_PORT,
                "sync_interval": SYNC_INTERVAL,
                "scan_interval": SCAN_INTERVAL,
                "settings_password_hash": SETTINGS_PASSWORD_HASH
            }
            save_json_atomic(get_config_path(), new_conf)
            
            messagebox.showinfo("Saved", "Settings saved!", parent=win)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save config: {e}", parent=win)
            return

        self.close_settings_ui(win)

    def check_updates_ui(self, parent_win):
        """Check for updates and show result in a popup."""
        if not auto_updater:
            messagebox.showerror("Error", "Update module not available.", parent=parent_win)
            return
        
        # Show checking message
        checking_lbl = tk.Label(parent_win, text="Checking for updates...", font=("Segoe UI", 9, "italic"), fg="orange")
        checking_lbl.pack(pady=2)
        parent_win.update()
        
        def do_check():
            result = auto_updater.check_for_updates_manual()
            self.root.after(0, lambda: show_result(result))
        
        def show_result(result):
            # Remove "checking" label
            try:
                checking_lbl.destroy()
            except:
                pass
            
            if "error" in result:
                messagebox.showerror("Update Check Failed", result["error"], parent=parent_win)
                return
            
            if not result.get("update_available"):
                messagebox.showinfo("Up to Date", "✅ Cyber is up to date.", parent=parent_win)
                return
            
            # New version available — show Update/Cancel dialog
            remote_ver = result.get("remote_version", "?")
            download_url = result.get("download_url")
            asset_size = result.get("asset_size", 0)
            
            popup = tk.Toplevel(parent_win)
            popup.title("Update Available")
            popup.geometry("380x180")
            popup.resizable(False, False)
            popup.attributes("-topmost", True)
            popup.transient(parent_win)
            popup.grab_set()
            
            # Center on parent
            popup.update_idletasks()
            x = parent_win.winfo_x() + (parent_win.winfo_width() // 2) - 190
            y = parent_win.winfo_y() + (parent_win.winfo_height() // 2) - 90
            popup.geometry(f"+{x}+{y}")
            
            tk.Label(popup, text="🚀 Update Available", font=("Segoe UI", 14, "bold"), fg=self.ACCENT).pack(pady=(15, 5))
            tk.Label(popup, text=f"New version of Cyber is available! ({remote_ver})", font=("Segoe UI", 10)).pack(pady=5)
            current_ver = auto_updater.VERSION
            tk.Label(popup, text=f"Current: v{current_ver}  →  New: {remote_ver}", font=("Segoe UI", 9), fg="#666666").pack(pady=2)
            
            btn_frame = tk.Frame(popup)
            btn_frame.pack(pady=15)
            
            def do_update():
                popup.destroy()
                messagebox.showinfo("Updating", "Downloading update... The application will restart.", parent=parent_win)
                def run_update():
                    err = auto_updater.download_and_apply_update(download_url, asset_size)
                    if err:
                        self.root.after(0, lambda: messagebox.showerror("Update Failed", err, parent=parent_win))
                threading.Thread(target=run_update, daemon=True).start()
            
            tk.Button(btn_frame, text="Update", command=do_update, bg="#27AE60", fg="white", font=("Segoe UI", 10, "bold"), width=10, cursor="hand2").pack(side="left", padx=10)
            tk.Button(btn_frame, text="Cancel", command=popup.destroy, bg="#95A5A6", fg="white", font=("Segoe UI", 10), width=10, cursor="hand2").pack(side="left", padx=10)
        
        threading.Thread(target=do_check, daemon=True).start()

    def close_settings_ui(self, win):
        try: win.destroy()
        except: pass
        self.root.attributes("-topmost", True)
        self.root.focus_force()

    # -------- GAME SYNC METHODS --------
    
    def start_game_sync_server(self):
        """Start the HTTP file server and register with main server."""
        # Always start the sync system, even if no folders configured yet
        # This ensures we register with the server immediately
        if not self.sync_folders:
            print("[GAME SYNC] No folders configured yet, but starting sync system anyway")
            
        # Start HTTP file server in background (will serve empty list if no folders)
        def run_server():
            self.file_server_running = True
            start_file_server(FILE_SERVER_PORT, self.sync_folders)
        
        threading.Thread(target=run_server, daemon=True).start()
        
        # Register as source with main server
        threading.Thread(target=self.register_as_source, daemon=True).start()
        
        # Start periodic scanning
        threading.Thread(target=self.game_sync_loop, daemon=True).start()
    
    def register_as_source(self):
        """Register this AdminClient as the file sync source."""
        time.sleep(2)  # Wait for server to be ready
        local_ip = get_local_ip()
        try:
            payload = json.dumps({
                "admin_ip": local_ip,
                "admin_port": FILE_SERVER_PORT
            }).encode()
            
            
            headers = {"Content-Type": "application/json"}
                
            req = request.Request(REGISTER_SOURCE_URL, data=payload, 
                                  headers=headers, method="POST")
            with request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode())
                if result.get("status") == "ok":
                    print(f"[GAME SYNC] Registered as source: {local_ip}:{FILE_SERVER_PORT}")
                else:
                    print(f"[GAME SYNC] Failed to register: {result}")
        except Exception as e:
            print(f"[GAME SYNC] Registration error: {e}")
    
    def scan_and_update_index(self):
        """Scan all sync folders and update the server's file index."""
        for idx, folder_path in enumerate(self.sync_folders):
            print(f"[GAME SYNC] Scanning: {folder_path}")
            files = scan_folder(folder_path)
            print(f"[GAME SYNC] Found {len(files)} files")
            
            # First, make sure folder is registered on server
            try:
                headers = {"Content-Type": "application/json"}
                    
                payload = json.dumps({"folder_path": folder_path}).encode()
                req = request.Request(ADD_FOLDER_URL, data=payload,
                                      headers=headers, method="POST")
                with request.urlopen(req, timeout=5) as resp:
                    result = json.loads(resp.read().decode())
                    folder_id = result.get("folder_id")
                    
                    if folder_id:
                        # Update file index for this folder
                        idx_payload = json.dumps({
                            "folder_id": folder_id,
                            "files": files
                        }).encode()
                        req2 = request.Request(UPDATE_INDEX_URL, data=idx_payload,
                                              headers=headers, method="POST")
                        with request.urlopen(req2, timeout=30) as resp2:
                            result2 = json.loads(resp2.read().decode())
                            print(f"[GAME SYNC] Index updated: {result2.get('added', 0)} files")
            except Exception as e:
                print(f"[GAME SYNC] Index update error: {e}")
    
    def game_sync_loop(self):
        """Periodically scan folders and update index."""
        time.sleep(5)  # Initial delay
        while True:
            self.scan_and_update_index()
            time.sleep(SCAN_INTERVAL * 60)  # Convert minutes to seconds
    
    def add_sync_folder_ui(self, folder_path):
        """Add a folder to the sync list and save."""
        if folder_path not in self.sync_folders:
            self.sync_folders.append(folder_path)
            save_sync_folders(self.sync_folders)
            FileSyncHandler.sync_folders = self.sync_folders
            return True
        return False
    
    def remove_sync_folder_ui(self, folder_path):
        """Remove a folder from the sync list and save."""
        if folder_path in self.sync_folders:
            self.sync_folders.remove(folder_path)
            save_sync_folders(self.sync_folders)
            FileSyncHandler.sync_folders = self.sync_folders
            
            # Notify server to remove from DB
            threading.Thread(target=self._remove_folder_from_server, args=(folder_path,), daemon=True).start()
            
            return True
        return False

    def _remove_folder_from_server(self, folder_path):
        try:
            headers = {"Content-Type": "application/json"}
            if self.username and self.password:
                headers["X-Auth-User"] = self.username
                headers["X-Auth-Pass"] = self.password
                
            # 1. Get ID (by "adding" it)
            payload = json.dumps({"folder_path": folder_path}).encode()
            req = request.Request(ADD_FOLDER_URL, data=payload, headers=headers, method="POST")
            
            folder_id = None
            with request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode())
                folder_id = result.get("folder_id")
            
            if folder_id:
                # 2. Remove by ID
                del_payload = json.dumps({"folder_id": folder_id}).encode()
                req2 = request.Request(REMOVE_FOLDER_URL, data=del_payload, headers=headers, method="POST")
                with request.urlopen(req2, timeout=5) as resp2:
                    print(f"[GAME SYNC] Removed folder {folder_path} (ID: {folder_id}) from server")
        except Exception as e:
            print(f"[GAME SYNC] Error removing folder from server: {e}")


def early_lock_enforcer(root):
    """
    THREAD: Aggressively force window to foreground during startup (first 5 seconds).
    """
    try:
        hwnd = 0
        for _ in range(50):
            try:
                hwnd = ctypes.windll.user32.GetForegroundWindow() 
                if root.winfo_id():
                    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
                    if not hwnd: hwnd = root.winfo_id()
                    break
            except: pass
            time.sleep(0.1)
        # Aggressive loop for 20 seconds
        end_time = time.time() + 20
        while time.time() < end_time:
            root.after(0, lambda: root.attributes("-topmost", True))
            root.after(0, lambda: root.lift())
            root.after(0, lambda: root.focus_force())
            
            if hwnd:
                ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                
            time.sleep(0.1)
    except Exception as e:
        print(f"Early lock error: {e}")

if __name__ == "__main__":
    # 0. Check for updates (will restart if update found)
    try:
        import auto_updater
        auto_updater.check_for_updates()
    except Exception:
        pass  # Continue even if update check fails

    # 1. IMMEDIATE LOCK (Before loading anything else)
    install_keyboard_hook()
    threading.Thread(target=pump_messages, daemon=True).start()

    root = tk.Tk()
    
    # 2. START EARLY LOCK ENFORCER
    threading.Thread(target=early_lock_enforcer, args=(root,), daemon=True).start()
    
    app = ClientApp(root)
    root.mainloop()
