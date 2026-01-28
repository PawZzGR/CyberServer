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
import logging

# Configure basic debugging logger
logging.basicConfig(
    filename='client_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.info("Starting UserClient...")

# Import utils for password hashing
try:
    from utils import hash_password, verify_password
except ImportError:
    # Fallback if utils not found
    def hash_password(pwd): return pwd
    def verify_password(pwd, hashed): return pwd == hashed

# Import toast if available
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'PythonServerArduino'))
    from toast import show_toast
    TOAST_AVAILABLE = True
except ImportError as e:
    logging.debug(f"Toast module not available: {e}")
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

CONFIG_FILE = os.path.join(_BASE_DIR, "user_config.json")
GAME_MAPPINGS_FILE = os.path.join(_BASE_DIR, "game_mappings.json")

# Default values
SERVER_HOST = "192.168.1.6"
SERVER_PORT = 5000
ADMIN_HOST = ""  # Direct Admin IP (if empty, falls back to Server lookup)
ADMIN_PORT = 5001
STATION_NAME = "Unknown"
SYNC_INTERVAL = 10800  # Seconds (3 hours default)
GAME_SYNC_INTERVAL = 30  # Minutes
DOWNLOAD_FOLDER = os.path.join(_BASE_DIR, "Games")

# Named constants for timing (Issue #11 - avoid magic numbers)
MESSAGE_PUMP_INTERVAL = 0.01  # Seconds - keyboard hook message pump
DOWNLOAD_COMPLETE_DISPLAY_TIME = 1  # Seconds - show "complete" before closing
INITIAL_SYNC_DELAY = 10  # Seconds - delay before first auto-sync
SCAN_RATE_LIMIT_DELAY = 0.05  # Seconds - delay between folder scan requests

def normalize_path(path):
    """Convert relative paths to absolute, expand ~ and environment variables."""
    if not path:
        return path
    
    # Expand user home directory (~)
    path = os.path.expanduser(path)
    
    # Expand environment variables like %USERPROFILE%
    path = os.path.expandvars(path)
    
    # Handle common shortcuts
    if path.lower().startswith("desktop"):
        # Convert "Desktop/folder" to full path
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        path = path.replace("Desktop", desktop, 1).replace("desktop", desktop, 1)
    
    # Convert to absolute path
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    
    # Normalize separators
    path = path.replace("/", os.sep)
    
    return path

def load_config():
    global SERVER_HOST, SERVER_PORT, ADMIN_HOST, ADMIN_PORT, STATION_NAME, SYNC_INTERVAL, GAME_SYNC_INTERVAL, DOWNLOAD_FOLDER, SETTINGS_PASSWORD_HASH
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            SERVER_HOST = config.get("server_address", "192.168.1.5")
            SERVER_PORT = config.get("server_port", 5000)
            ADMIN_HOST = config.get("admin_address", "")
            ADMIN_PORT = config.get("admin_port", 5001)
            STATION_NAME = config.get("client_machine", "Unknown")
            SYNC_INTERVAL = config.get("sync_interval", 10800)
            GAME_SYNC_INTERVAL = config.get("game_sync_interval", 30)
            DOWNLOAD_FOLDER = config.get("download_folder", os.path.join(_BASE_DIR, "Games"))
            SETTINGS_PASSWORD_HASH = config.get("settings_password_hash", None)
            
            logging.info(f"Loaded config: SERVER={SERVER_HOST}:{SERVER_PORT}, ADMIN={ADMIN_HOST}:{ADMIN_PORT}, STATION={STATION_NAME}")
    except Exception as e:
        logging.error(f"Failed to load config: {e}")
        SYNC_INTERVAL = 10800
        pass

load_config()

LOGIN_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/login"
UPDATE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/update_remaining"
PING_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/ping"
PATHS_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/game_paths"

# File Sync API URLs
GET_SOURCE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/file_sync/source"
GET_INDEX_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/file_sync/index"
GET_FOLDERS_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/file_sync/folders"

# Settings password - stored as hash for security
SETTINGS_PASSWORD_HASH = None  # Will be set on first use or loaded from config

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
        
        # Block Ctrl+Alt+Delete cannot be blocked by software (Windows security)
        
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
        time.sleep(MESSAGE_PUMP_INTERVAL)

# -------- DOWNLOAD PROGRESS POPUP --------

class DownloadProgressWindow:
    """Progress popup for game downloads with project-consistent styling."""
    
    # Match ClientApp colors
    BG_MAIN = "#FAF5EF"
    BG_CARD = "#EFE0D0"
    BG_BUTTON = "#8B7355"
    BORDER_COLOR = "#D7C4A8"
    TEXT_PRIMARY = "#3E2723"
    ACCENT = "#C19A6B"
    
    def __init__(self, parent, total_files=0, total_size=0):
        self.parent = parent
        self.total_files = total_files
        self.total_size = total_size
        self.current_file = 0
        self.downloaded_size = 0
        self.cancelled = False
        
        self.window = tk.Toplevel(parent)
        self.window.title("Game Updates")
        self.window.geometry("500x250")  # Larger window
        self.window.minsize(450, 220)  # Minimum size
        self.window.configure(bg=self.BG_MAIN)
        self.window.resizable(True, True)  # Allow resizing
        self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        
        # Center on parent
        self.window.transient(parent)
        self.window.grab_set()
        
        # Title
        tk.Label(
            self.window, 
            text="🎮 Game Updates Loading...", 
            font=("Segoe UI", 14, "bold"),
            fg=self.ACCENT,
            bg=self.BG_MAIN
        ).pack(pady=(15, 10))
        
        # Current file label - fixed height with ellipsis for long names
        self.file_label = tk.Label(
            self.window,
            text="Preparing...",
            font=("Segoe UI", 9),
            fg=self.TEXT_PRIMARY,
            bg=self.BG_MAIN,
            height=2,  # Fixed height for 2 lines max
            anchor="center"
        )
        self.file_label.pack(pady=5, fill="x", padx=20)
        
        # Progress bar frame
        progress_frame = tk.Frame(self.window, bg=self.BG_MAIN)
        progress_frame.pack(fill="x", padx=30, pady=10)
        
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            length=390,
            mode='determinate',
            maximum=100
        )
        self.progress_bar.pack(fill="x")
        
        # Stats label (X of Y files, size)
        self.stats_label = tk.Label(
            self.window,
            text="0 of 0 files | 0 MB / 0 MB",
            font=("Segoe UI", 9),
            fg=self.TEXT_PRIMARY,
            bg=self.BG_MAIN
        )
        self.stats_label.pack(pady=5)
        
        # Cancel button
        tk.Button(
            self.window,
            text="Cancel",
            command=self.cancel,
            bg="#C0392B",
            fg="white",
            font=("Segoe UI", 10),
            width=12
        ).pack(pady=10)
        
        self.window.update()
    
    def _truncate_filename(self, filename, max_length=55):
        """Truncate long file names with ellipsis."""
        if len(filename) <= max_length:
            return filename
        # Show beginning and end of the path
        return filename[:25] + "..." + filename[-27:]
    
    def update_progress(self, current_file, file_name, downloaded_bytes=0):
        """Update the progress display."""
        if self.cancelled:
            return
        
        self.current_file = current_file
        self.downloaded_size += downloaded_bytes
        
        # Calculate percentages
        file_percent = (current_file / max(self.total_files, 1)) * 100
        
        # Update UI with truncated file name
        display_name = self._truncate_filename(file_name)
        self.file_label.config(text=f"Downloading: {display_name}")
        self.progress_bar['value'] = file_percent
        
        # Format sizes
        downloaded_mb = self.downloaded_size / (1024 * 1024)
        total_mb = self.total_size / (1024 * 1024)
        
        self.stats_label.config(
            text=f"{current_file} of {self.total_files} files | {downloaded_mb:.1f} MB / {total_mb:.1f} MB"
        )
        
        self.window.update()
    
    def set_complete(self):
        """Mark download as complete."""
        self.file_label.config(text="✅ Download Complete!")
        self.progress_bar['value'] = 100
        self.window.update()
        time.sleep(DOWNLOAD_COMPLETE_DISPLAY_TIME)
        self.close()
    
    def cancel(self):
        """Cancel the download."""
        self.cancelled = True
        self.close()
    
    def close(self):
        """Close the progress window."""
        try:
            self.window.destroy()
        except tk.TclError:
            # Window already destroyed
            pass
    
    def is_cancelled(self):
        """Check if download was cancelled."""
        return self.cancelled

# -------- CLIENT APP (USER / PULL) --------

class ClientApp:
    BG_MAIN = "#FAF5EF"
    BG_CARD = "#EFE0D0"
    BG_BUTTON = "#8B7355"
    BORDER_COLOR = "#D7C4A8"
    TEXT_PRIMARY = "#3E2723"
    ACCENT = "#C19A6B"

    def __init__(self, root):
        self.root = root
        self.username = None
        self.password = None
        self.remaining_seconds = 0
        self.timer_running = False
        
        # Reboot countdown after session ends
        self.session_ended_naturally = False  # True only when time runs out
        self.reboot_countdown_active = False  # True when countdown is running
        self.reboot_countdown_seconds = 0     # Remaining seconds to reboot
        
        self.base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.download_folder = DOWNLOAD_FOLDER
        self.game_mappings = self.load_game_mappings()  # {folder_name: local_path}
        
        self.setup_window()
        self.build_login_ui()
        
        # Start hooks and monitors
        install_keyboard_hook()
        threading.Thread(target=pump_messages, daemon=True).start()
        
        # Start game sync from AdminClient
        self.start_game_sync()

    def setup_window(self):
        self.root.configure(bg=self.BG_MAIN)
        self.root.overrideredirect(True)
        self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_reboot)

    def on_close_reboot(self):
        # Reboot the PC when the application is closed
        os.system("shutdown /r /t 0")

    def clear_window(self):
        for w in self.root.winfo_children(): w.destroy()
    
    def load_game_mappings(self):
        """Load per-game destination mappings from config file."""
        try:
            with open(GAME_MAPPINGS_FILE, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logging.debug(f"Game mappings file not found: {GAME_MAPPINGS_FILE}")
            return {}
        except json.JSONDecodeError as e:
            logging.warning(f"Invalid JSON in game mappings file: {e}")
            return {}
    
    def save_game_mappings(self):
        """Save per-game destination mappings to config file."""
        try:
            with open(GAME_MAPPINGS_FILE, 'w') as f:
                json.dump(self.game_mappings, f, indent=2)
        except OSError as e:
            logging.error(f"Failed to save game mappings: {e}")

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

        # Main Card Frame (Centered)
        # Using a slight varying color for shadow effect could be complex, sticking to clean flat design with border
        card = tk.Frame(self.root, bg="#FFFFFF", padx=50, pady=50, highlightthickness=1, highlightbackground=self.BORDER_COLOR)
        card.place(relx=0.5, rely=0.5, anchor="center")
        
        # Header
        tk.Label(card, text="CyberClient", font=("Segoe UI", 28, "bold"), bg="#FFFFFF", fg=self.TEXT_PRIMARY).pack(pady=(0, 5))
        tk.Label(card, text="User Access", font=("Segoe UI", 12), bg="#FFFFFF", fg=self.ACCENT).pack(pady=(0, 30))
        
        # Custom Entry Style Helper
        def create_entry(parent, placeholder, is_password=False):
            f = tk.Frame(parent, bg="#FFFFFF", highlightthickness=1, highlightbackground=self.BORDER_COLOR, padx=10, pady=5)
            f.pack(fill="x", pady=10)
            
            ent = tk.Entry(f, font=("Segoe UI", 11), bd=0, bg="#FFFFFF", width=30, show="*" if is_password else "")
            ent.pack(fill="x")
            
            # Simple placeholder logic
            if not is_password:
                ent.insert(0, placeholder)
                ent.bind("<FocusIn>", lambda e: ent.delete(0, tk.END) if ent.get() == placeholder else None)
                ent.bind("<FocusOut>", lambda e: ent.insert(0, placeholder) if not ent.get() else None)
                ent.config(fg="grey")
                ent.bind("<Key>", lambda e: ent.config(fg="black"))
                
            return ent

        self.user_entry = create_entry(card, "Username")
        self.pass_entry = create_entry(card, "Password", is_password=True)
        
        # Connection Status (Inside Card)
        self.lbl_status = tk.Label(card, text="Connecting...", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg=self.ACCENT)
        self.lbl_status.pack(pady=(15, 5))
        
        # Login Button
        btn_frame = tk.Frame(card, bg=self.BG_BUTTON, padx=0, pady=0)
        btn_frame.pack(fill="x", pady=15)
        
        login_btn = tk.Button(btn_frame, text="LOG IN", command=self.login, bg=self.BG_BUTTON, fg="white", 
                            font=("Segoe UI", 12, "bold"), bd=0, padx=10, pady=10, activebackground=self.ACCENT, cursor="hand2")
        login_btn.pack(fill="x")
        
        # Reboot countdown label (shown only when countdown is active, no X button)
        self.reboot_label = tk.Label(card, text="", font=("Segoe UI", 11, "bold"), 
                                      bg="#FFFFFF", fg="#e74c3c")
        self.reboot_label.pack(pady=(10, 0))
        
        # Start connection checker
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
        else:
            reason = resp.get("reason", "")
            if reason == "not_found":
                msg = "Account does not exist"
            elif reason == "no_time":
                msg = "No remaining time"
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
        
        lbl = tk.Label(self.root, text="", font=("Segoe UI", 20, "bold"), bg=self.BG_MAIN, fg=self.TEXT_PRIMARY)
        lbl.pack(expand=True)
        
        def tick():
            while self.timer_running and self.remaining_seconds > 0:
                m, s = divmod(self.remaining_seconds, 60)
                h, m = divmod(m, 60)
                self.root.after(0, lambda h=h, m=m, s=s: lbl.config(text=f"{h:02}:{m:02}:{s:02}"))
                time.sleep(1)
                self.remaining_seconds -= 1
                if self.remaining_seconds % 5 == 0: self.send_update()
            self.timer_running = False
            self.session_ended_naturally = True  # Mark that session ended due to time
            self.send_update()
            # Restore full lock screen
            self.root.after(0, self.restore_lock_screen)
            
        threading.Thread(target=tick, daemon=True).start()
    
    def restore_lock_screen(self):
        """Restore full screen lock when session ends"""
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
        """Start 60-second countdown to reboot. Only cancelled by successful login."""
        self.reboot_countdown_active = True
        self.reboot_countdown_seconds = 60
        logging.info("Starting reboot countdown (60 seconds)")
        
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
                os.system("shutdown /r /t 0")
        
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
        fail_count = 0
        while self.check_conn_running:
            try:
                with request.urlopen(PING_URL, timeout=5) as r:
                    if r.status == 200:
                        self.root.after(0, lambda: self.lbl_status.config(text="CONNECTED", fg="#2ecc71", bg="#FFFFFF"))
                        fail_count = 0
                    else:
                        raise Exception(f"HTTP {r.status}")
            except Exception as e:
                logging.warning(f"Connection failed to {PING_URL}: {e}")
                self.root.after(0, lambda: self.lbl_status.config(text="DISCONNECTED", fg="#e74c3c", bg="#FFFFFF"))
                fail_count += 1
            
            # Exponential backoff: 5, 10, 20, 30 (max)
            sleep_time = min(30, 5 * (2 ** max(0, fail_count - 1))) if fail_count > 0 else 5
            time.sleep(sleep_time)

    # --- SETTINGS / SYNC ---

    def open_settings_password(self):
        global SETTINGS_PASSWORD_HASH
        
        if not SETTINGS_PASSWORD_HASH:
            # First time setup - create password
            pwd = simpledialog.askstring("Settings Setup", "Create a password for settings:", show="*", parent=self.root)
            if pwd:
                try:
                    SETTINGS_PASSWORD_HASH = hash_password(pwd)
                    # Save immediately
                    self._save_password_hash()
                    messagebox.showinfo("Setup", "Password set! Opening settings...", parent=self.root)
                    self.open_settings_ui()
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to set password: {e}")
            return
        
        # Verify existing password
        pwd = simpledialog.askstring("Settings", "Enter Password:", show="*", parent=self.root)
        if pwd and verify_password(pwd, SETTINGS_PASSWORD_HASH):
            self.open_settings_ui()
        elif pwd:
            messagebox.showerror("Error", "Wrong password")
    
    def _save_password_hash(self):
        """Save the password hash to config file."""
        try:
            # Load existing config
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                config = {}
            
            config["settings_password_hash"] = SETTINGS_PASSWORD_HASH
            
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
        except OSError as e:
            logging.error(f"Failed to save password hash: {e}")

    def open_settings_ui(self):
        # Relax main window (security restored on close)
        self.root.attributes("-topmost", False)
        
        win = tk.Toplevel(self.root)
        win.title("Client Settings")
        win.geometry("600x650")
        win.attributes("-topmost", True)
        win.focus_force()
        win.grab_set() # Modal
        
        self.close_settings_callback = lambda: self.close_settings_ui(win)
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
        
        # --- Admin Connection Section (Direct P2P) ---
        tk.Label(win, text="Admin Connection (Direct P2P)", font=("Segoe UI", 12, "bold"), fg=self.ACCENT).pack(pady=(10, 5))
        
        admin_frame = tk.Frame(win, padx=20)
        admin_frame.pack(fill="x")
        
        self.ent_admin_host = add_field(admin_frame, "Admin IP:", ADMIN_HOST)
        self.ent_admin_port = add_field(admin_frame, "Admin Port:", ADMIN_PORT)
        
        # Admin connection status
        self.admin_status_lbl = tk.Label(win, text="Admin Status: Not tested", font=("Segoe UI", 9))
        self.admin_status_lbl.pack(pady=2)
        
        def test_admin_connection():
            self.admin_status_lbl.config(text="Admin Status: Testing...", fg="orange")
            def do_test():
                admin_ip = self.ent_admin_host.get().strip()
                admin_port = self.ent_admin_port.get().strip()
                if not admin_ip:
                    self.root.after(0, lambda: self.admin_status_lbl.config(text="Admin Status: No IP configured", fg="gray"))
                    return
                try:
                    url = f"http://{admin_ip}:{admin_port}/folders"
                    with request.urlopen(url, timeout=5) as resp:
                        data = json.loads(resp.read().decode())
                        folder_count = len(data.get("folders", []))
                        self.root.after(0, lambda: self.admin_status_lbl.config(text=f"Admin Status: Connected! ({folder_count} folders)", fg="green"))
                except Exception as e:
                    self.root.after(0, lambda: self.admin_status_lbl.config(text=f"Admin Status: Failed - {e}", fg="red"))
            threading.Thread(target=do_test, daemon=True).start()
        
        tk.Button(win, text="Test Connection", command=test_admin_connection, bg="#3498DB", fg="white").pack(pady=5)
        
        ttk.Separator(win, orient="horizontal").pack(fill="x", pady=15)
        
        # --- Game Sync Section (Download from Admin) ---
        tk.Label(win, text="Game Sync (Download from Admin)", font=("Segoe UI", 12, "bold"), fg=self.ACCENT).pack(pady=(10, 5))
        
        # Status and Refresh
        status_frame = tk.Frame(win)
        status_frame.pack(fill="x", padx=20, pady=5)
        self.game_sync_status = tk.Label(status_frame, text="Status: Click Refresh to see available games", font=("Segoe UI", 9))
        self.game_sync_status.pack(side="left")
        
        def refresh_games():
            self.game_sync_status.config(text="Status: Fetching...")
            def do_refresh():
                games, error_msg = self.fetch_available_games()
                self.root.after(0, lambda: self.populate_game_list(games, error_msg))
            threading.Thread(target=do_refresh, daemon=True).start()
        
        tk.Button(status_frame, text="⟳ Refresh", command=refresh_games, bg="#3498DB", fg="white").pack(side="right")
        
        # Default download folder
        dl_frame = tk.Frame(win)
        dl_frame.pack(fill="x", padx=20, pady=5)
        tk.Label(dl_frame, text="Default folder:", font=("Segoe UI", 9), width=12, anchor="w").pack(side="left")
        self.ent_download_folder = tk.Entry(dl_frame, font=("Segoe UI", 9))
        self.ent_download_folder.pack(side="left", fill="x", expand=True, padx=5)
        self.ent_download_folder.insert(0, self.download_folder)
        tk.Button(dl_frame, text="...", command=lambda: self.browse_download_folder(), width=3).pack(side="left")
        
        # Games list with per-game destinations
        tk.Label(win, text="Available Games (set custom destination per game):", font=("Segoe UI", 9)).pack(pady=(10, 2), anchor="w", padx=20)
        
        # Scrollable game list frame
        game_list_container = tk.Frame(win, height=150)
        game_list_container.pack(fill="x", padx=20, pady=5)
        game_list_container.pack_propagate(False)
        
        canvas = tk.Canvas(game_list_container, borderwidth=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(game_list_container, orient="vertical", command=canvas.yview)
        self.game_list_frame = tk.Frame(canvas)
        
        self.game_list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.game_list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        self.game_entries = {}  # {folder_name: entry_widget}
        
        # Sync interval
        sync_int_frame = tk.Frame(win)
        sync_int_frame.pack(pady=5)
        tk.Label(sync_int_frame, text="Check every:", font=("Segoe UI", 9)).pack(side="left")
        self.ent_game_sync_interval = tk.Entry(sync_int_frame, width=5)
        self.ent_game_sync_interval.pack(side="left", padx=5)
        self.ent_game_sync_interval.insert(0, str(GAME_SYNC_INTERVAL))
        tk.Label(sync_int_frame, text="minutes", font=("Segoe UI", 9)).pack(side="left")
        
        # Sync Now button
        def sync_now():
            # Auto-save mappings from UI before syncing
            for game_name, entry in self.game_entries.items():
                dest = entry.get().strip()
                if dest:
                    self.game_mappings[game_name] = dest
            # We don't save to file here to avoid annoying disk writes, but we update memory
            
            self.game_sync_status.config(text="Status: Syncing...")
            def on_complete():
                self.game_sync_status.config(text="Status: Sync complete!")
            self.manual_sync(callback=on_complete)
        
        tk.Button(win, text="Sync Now", command=sync_now, bg="#27AE60", fg="white", font=("Segoe UI", 10)).pack(pady=5)
            
        tk.Button(win, text="Save Settings", command=lambda: self.save_settings(win), bg=self.BG_BUTTON, fg="white", font=("Segoe UI", 10, "bold")).pack(pady=10)
        
        # Auto-refresh on open
        self.root.after(500, refresh_games)
        
        # Start Auto-Check for Admin Connection
        self.admin_check_running = True
        def auto_check_admin():
            fail_count = 0
            while self.admin_check_running:
                try:
                    # Only check if we have an IP
                    admin_ip = self.ent_admin_host.get().strip()
                    admin_port = self.ent_admin_port.get().strip()
                    if admin_ip and admin_port:
                        url = f"http://{admin_ip}:{admin_port}/folders"
                        with request.urlopen(url, timeout=3) as resp:
                            data = json.loads(resp.read().decode())
                            count = len(data.get("folders", []))
                            fail_count = 0 # Reset on success
                            if self.admin_status_lbl.winfo_exists():
                                self.admin_status_lbl.config(text=f"Admin Status: Connected! ({count} folders)", fg="green")
                    else:
                         if self.admin_status_lbl.winfo_exists():
                            self.admin_status_lbl.config(text="Admin Status: No IP configured", fg="gray")
                except:
                    fail_count += 1
                    # Only show disconnected if failed 3 times in a row (debounce)
                    if fail_count >= 3:
                        if self.admin_status_lbl.winfo_exists():
                            self.admin_status_lbl.config(text="Admin Status: Disconnected", fg="red")
                
                # Check every 5 seconds
                for _ in range(50): 
                    if not self.admin_check_running: break
                    time.sleep(0.1)

        threading.Thread(target=auto_check_admin, daemon=True).start()
        
        # Stop checker on close
        old_protocol = win.protocol("WM_DELETE_WINDOW")
        def on_close_settings():
            self.admin_check_running = False
            self.close_settings_callback()
        win.protocol("WM_DELETE_WINDOW", on_close_settings)

    def browse_download_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            folder = folder.replace("/", "\\")
            self.ent_download_folder.delete(0, tk.END)
            self.ent_download_folder.insert(0, folder)
            self.download_folder = folder
    
    def fetch_available_games(self):
        """Fetch list of available games from AdminClient (direct or via server)."""
        admin_ip = None
        admin_port = ADMIN_PORT
        
        try:
            # Use direct config if available, otherwise ask server
            if ADMIN_HOST:
                admin_ip = ADMIN_HOST
                admin_port = ADMIN_PORT
                logging.info(f"Using direct admin config: {admin_ip}:{admin_port}")
            else:
                # Fallback: ask server for admin location
                source = self.get_admin_source()
                if not source:
                    return [], "No Admin configured (set Admin IP in settings)"
                admin_ip = source.get("admin_ip")
                admin_port = source.get("admin_port", 5001)
                logging.info(f"Got admin from server: {admin_ip}:{admin_port}")
            
            if not admin_ip:
                return [], "Admin IP not configured"
            
            folders_url = f"http://{admin_ip}:{admin_port}/folders"
            with request.urlopen(folders_url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                folders = data.get("folders", [])
                # Return just the folder names (basenames)
                return [os.path.basename(f) for f in folders], None
        except error.URLError as e:
            logging.error(f"URLError fetching games: {e}")
            return [], f"Cannot reach Admin ({admin_ip}:{admin_port})"
        except Exception as e:
            logging.error(f"Error fetching games: {e}")
            return [], str(e)
    
    def populate_game_list(self, games, error_msg=None):
        """Populate the game list UI with available games and destination entries."""
        # Clear existing entries
        for widget in self.game_list_frame.winfo_children():
            widget.destroy()
        self.game_entries = {}
        
        if not games:
            if error_msg:
                self.game_sync_status.config(text=f"Status: {error_msg}")
            else:
                self.game_sync_status.config(text="Status: No games available (Admin not connected?)")
            return
        
        self.game_sync_status.config(text=f"Status: {len(games)} games available")
        
        for game_name in games:
            row = tk.Frame(self.game_list_frame)
            row.pack(fill="x", pady=2)
            
            # Game name label
            tk.Label(row, text=game_name, font=("Segoe UI", 9, "bold"), width=20, anchor="w").pack(side="left")
            
            # Destination entry
            ent = tk.Entry(row, font=("Segoe UI", 8), width=30)
            ent.pack(side="left", padx=5)
            
            # Pre-fill with saved mapping or default
            default_dest = self.game_mappings.get(game_name, os.path.join(self.download_folder, game_name))
            ent.insert(0, default_dest)
            
            # Browse button
            def browse_for_game(entry=ent):
                folder = filedialog.askdirectory()
                if folder:
                    folder = folder.replace("/", "\\")
                    entry.delete(0, tk.END)
                    entry.insert(0, folder)
            
            tk.Button(row, text="...", command=browse_for_game, width=3).pack(side="left")
            
            self.game_entries[game_name] = ent

    def save_settings(self, win):
        global SERVER_HOST, SERVER_PORT, ADMIN_HOST, ADMIN_PORT, STATION_NAME, SYNC_INTERVAL, GAME_SYNC_INTERVAL
        global LOGIN_URL, UPDATE_URL, PING_URL, PATHS_URL
        
        # Save game mappings from UI
        for game_name, entry in self.game_entries.items():
            dest = entry.get().strip()
            if dest:
                self.game_mappings[game_name] = dest
        self.save_game_mappings()
        
        # Save Config
        try:
            SERVER_HOST = self.ent_host.get().strip()
            SERVER_PORT = int(self.ent_port.get().strip())
            ADMIN_HOST = self.ent_admin_host.get().strip()
            ADMIN_PORT = int(self.ent_admin_port.get().strip()) if self.ent_admin_port.get().strip() else 5001
            STATION_NAME = self.ent_station.get().strip()
            SYNC_INTERVAL = int(self.ent_interval.get().strip())
            GAME_SYNC_INTERVAL = int(self.ent_game_sync_interval.get().strip()) if self.ent_game_sync_interval.get().strip() else 30
            
            # Update URLs dynamically
            LOGIN_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/login"
            UPDATE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/update_remaining"
            PING_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/ping"
            PATHS_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/api/game_paths"

            new_conf = {
                "client_machine": STATION_NAME,
                "server_address": SERVER_HOST,
                "server_port": SERVER_PORT,
                "admin_address": ADMIN_HOST,
                "admin_port": ADMIN_PORT,
                "sync_interval": SYNC_INTERVAL,
                "game_sync_interval": GAME_SYNC_INTERVAL,
                "settings_password_hash": SETTINGS_PASSWORD_HASH  # Preserve password hash
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(new_conf, f, indent=4)
            
            messagebox.showinfo("Saved", "Settings and game mappings saved!", parent=win)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save config: {e}", parent=win)
            return

        self.close_settings_ui(win)

    def close_settings_ui(self, win):
        try:
            win.destroy()
        except tk.TclError:
            # Window already destroyed
            pass
        self.root.attributes("-topmost", True)
        self.root.focus_force()

    # -------- GAME SYNC METHODS (Download from AdminClient) --------
    
    def start_game_sync(self):
        """Start the game sync background thread."""
        threading.Thread(target=self.game_sync_loop, daemon=True).start()
    
    def game_sync_loop(self):
        """Periodically check for updates and download from AdminClient."""
        time.sleep(INITIAL_SYNC_DELAY)
        while True:
            self.sync_from_admin()
            time.sleep(GAME_SYNC_INTERVAL * 60)
    
    def get_admin_source(self):
        """Get the AdminClient's IP and port from the server."""
        try:
            with request.urlopen(GET_SOURCE_URL, timeout=5) as resp:
                result = json.loads(resp.read().decode())
                if result.get("status") == "ok" and result.get("source"):
                    return result["source"]
        except Exception as e:
            print(f"[GAME SYNC] Error getting source: {e}")
        return None
    
    def get_file_index_from_admin(self, admin_ip, admin_port):
        """Get the file index directly from AdminClient (P2P).
        
        Scans all folders on Admin and builds a comprehensive file list.
        """
        files = []
        try:
            # First get list of folders from Admin
            folders_url = f"http://{admin_ip}:{admin_port}/folders"
            logging.info(f"[GAME SYNC] Getting folders from {folders_url}")
            with request.urlopen(folders_url, timeout=10) as resp:
                folders_data = json.loads(resp.read().decode())
                admin_folders = folders_data.get("folders", [])
            
            if not admin_folders:
                logging.warning("[GAME SYNC] Admin has no folders configured")
                return [], admin_folders
            
            logging.info(f"[GAME SYNC] Admin has {len(admin_folders)} folders: {admin_folders}")
            
            # For each folder, recursively list all files
            for folder_idx, folder_path in enumerate(admin_folders):
                folder_name = os.path.basename(folder_path)
                self._scan_admin_folder_recursive(admin_ip, admin_port, folder_idx, folder_path, "", files)
            
            logging.info(f"[GAME SYNC] Found {len(files)} total files across all folders")
            return files, admin_folders
            
        except error.URLError as e:
            print(f"[GAME SYNC] Error connecting to Admin at {admin_ip}:{admin_port}: {e}")
            logging.error(f"URLError getting index from Admin: {e}")
            return [], []
        except Exception as e:
            print(f"[GAME SYNC] Error getting index from Admin: {e}")
            logging.error(f"Error getting index from Admin: {e}")
            return [], []
    
    def _scan_admin_folder_recursive(self, admin_ip, admin_port, folder_idx, folder_path, rel_dir, files_list):
        """Recursively scan a folder on Admin to get all files.
        
        Includes rate limiting to prevent overwhelming the server.
        """
        # Rate limiting: delay between requests to prevent server flooding
        time.sleep(SCAN_RATE_LIMIT_DELAY)
        
        try:
            if rel_dir:
                url = f"http://{admin_ip}:{admin_port}/{folder_idx}/{rel_dir}"
            else:
                url = f"http://{admin_ip}:{admin_port}/{folder_idx}/"
            
            with request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                items = data.get("files", [])
                
                for item in items:
                    name = item.get("name", "")
                    is_dir = item.get("is_dir", False)
                    size = item.get("size", 0)
                    
                    if rel_dir:
                        item_rel_path = f"{rel_dir}/{name}"
                    else:
                        item_rel_path = name
                    
                    if is_dir:
                        # Recurse into subdirectory
                        self._scan_admin_folder_recursive(admin_ip, admin_port, folder_idx, folder_path, item_rel_path, files_list)
                    else:
                        # Add file to list
                        files_list.append({
                            "folder_path": folder_path,
                            "folder_idx": folder_idx,
                            "relative_path": item_rel_path,
                            "file_size": size,
                            "modified_time": item.get("mtime", 0)  # Get mtime from Admin
                        })
        except error.URLError as e:
            logging.warning(f"URLError scanning {rel_dir} on Admin: {e}")
        except Exception as e:
            logging.warning(f"Error scanning {rel_dir} on Admin: {e}")
    
    def sync_from_admin(self, show_progress=False):
        """Download updated files from AdminClient.
        
        Includes health check before starting sync to avoid connecting to dead server.
        """
        # Use direct config if available, otherwise ask server
        if ADMIN_HOST:
            admin_ip = ADMIN_HOST
            admin_port = ADMIN_PORT
            logging.info(f"Sync using direct admin config: {admin_ip}:{admin_port}")
        else:
            source = self.get_admin_source()
            if not source:
                logging.warning("[GAME SYNC] No source available")
                print("[GAME SYNC] No Admin source configured. Set Admin IP in settings.")
                return
            admin_ip = source.get("admin_ip")
            admin_port = source.get("admin_port", 5001)
        
        if not admin_ip:
            print("[GAME SYNC] No Admin IP configured")
            return
        
        # === FIX #5: Health check before starting long sync ===
        print(f"[GAME SYNC] Checking Admin at {admin_ip}:{admin_port}...")
        try:
            health_url = f"http://{admin_ip}:{admin_port}/folders"
            with request.urlopen(health_url, timeout=5) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
            print(f"[GAME SYNC] Admin is online, starting sync...")
        except Exception as e:
            logging.warning(f"[GAME SYNC] Admin health check failed: {e}")
            print(f"[GAME SYNC] Admin not responding ({e}), skipping sync")
            return
        
        # Get file index directly from Admin (P2P)
        files, admin_folders = self.get_file_index_from_admin(admin_ip, admin_port)
        if not files:
            print("[GAME SYNC] No files to sync (Admin may have no folders or connection failed)")
            return
        
        print(f"[GAME SYNC] Syncing {len(files)} files from {admin_ip}:{admin_port}")
        
        # Build download list (admin_folders already available from get_file_index_from_admin)
        download_list = []
        total_size = 0
        
        for f in files:
            folder_path = f.get("folder_path")
            folder_idx = f.get("folder_idx", 0)  # Already in the file data from scanning
            
            folder_name = os.path.basename(folder_path)
            
            # Get mapped destination or use default
            raw_local_folder = self.game_mappings.get(folder_name)
            if raw_local_folder:
                local_folder = normalize_path(raw_local_folder)
                print(f"[GAME SYNC] Using custom mapping for '{folder_name}': {raw_local_folder} -> {local_folder}")
            else:
                local_folder = os.path.join(self.download_folder, folder_name)
                print(f"[GAME SYNC] Using default folder for '{folder_name}': {local_folder}")
            
            rel_path = f.get("relative_path", "")
            remote_mtime = f.get("modified_time", 0)
            remote_size = f.get("file_size", 0)
            local_path = os.path.join(local_folder, rel_path.replace("/", os.sep))
            
            # Check if file needs updating
            need_download = True
            if os.path.exists(local_path):
                local_stat = os.stat(local_path)
                if local_stat.st_size == remote_size and local_stat.st_mtime >= remote_mtime:
                    need_download = False
            
            if need_download:
                download_list.append({
                    "folder_idx": folder_idx,
                    "rel_path": rel_path,
                    "local_path": local_path,
                    "size": remote_size
                })
                total_size += remote_size
        
        if not download_list:
            print("[GAME SYNC] All files up to date")
            return
        
        print(f"[GAME SYNC] {len(download_list)} files need updating ({total_size / (1024*1024):.1f} MB)")
        
        # Show progress window if requested (manual sync)
        progress_window = None
        if show_progress:
            try:
                progress_window = DownloadProgressWindow(
                    self.root, 
                    total_files=len(download_list), 
                    total_size=total_size
                )
            except Exception as e:
                logging.error(f"Failed to create progress window: {e}")
        
        # Download files
        success_count = 0
        fail_count = 0
        for i, item in enumerate(download_list, 1):
            if progress_window and progress_window.is_cancelled():
                print("[GAME SYNC] Download cancelled by user")
                break
            
            print(f"[GAME SYNC] Downloading [{i}/{len(download_list)}]: {item['rel_path']}")
            success = self.download_file(
                admin_ip, admin_port, 
                item["folder_idx"], 
                item["rel_path"], 
                item["local_path"],
                progress_window=progress_window,
                file_number=i,
                file_size=item["size"]
            )
            if success:
                success_count += 1
            else:
                fail_count += 1
                print(f"[GAME SYNC] FAILED: {item['rel_path']}")
        
        print(f"[GAME SYNC] Complete! Success: {success_count}, Failed: {fail_count}")
        
        # Complete
        if progress_window and not progress_window.is_cancelled():
            progress_window.set_complete()
    
    def download_file(self, admin_ip, admin_port, folder_idx, rel_path, local_path, progress_window=None, file_number=0, file_size=0):
        """Download a single file from AdminClient with retries and proper error handling."""
        max_retries = 3
        
        # Update progress window if available
        if progress_window:
            progress_window.update_progress(file_number, rel_path, 0)
        
        for attempt in range(max_retries):
            try:
                # Ensure directory exists (handle root-level files)
                parent_dir = os.path.dirname(local_path)
                if parent_dir:  # Only makedirs if there's a parent directory
                    os.makedirs(parent_dir, exist_ok=True)
                
                url = f"http://{admin_ip}:{admin_port}/{folder_idx}/{rel_path}"
                print(f"  -> URL: {url}")
                print(f"  -> Saving to: {local_path}")
                
                with request.urlopen(url, timeout=300) as resp:
                    with open(local_path, 'wb') as f:
                        bytes_written = 0
                        while chunk := resp.read(65536):
                            f.write(chunk)
                            bytes_written += len(chunk)
                        print(f"  -> Wrote {bytes_written} bytes")
                
                # Update progress with file size after successful download
                if progress_window:
                    progress_window.update_progress(file_number, rel_path, file_size)
                
                return True
            except error.URLError as e:
                print(f"  -> URLError (Attempt {attempt+1}): {e}")
                logging.warning(f"URLError downloading {rel_path} (Attempt {attempt+1}): {e}")
                time.sleep(2 * (attempt + 1))  # Backoff: 2, 4, 6 seconds
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
                print(f"  -> Connection error (Attempt {attempt+1}): {e}")
                logging.warning(f"Connection error downloading {rel_path} (Attempt {attempt+1}): {e}")
                time.sleep(3 * (attempt + 1))  # Longer backoff for connection issues
            except OSError as e:
                print(f"  -> Disk error: {e}")
                logging.error(f"Disk error saving {rel_path}: {e}")
                return False  # Don't retry disk errors
            except Exception as e:
                print(f"  -> Error (Attempt {attempt+1}): {e}")
                logging.warning(f"Download error for {rel_path} (Attempt {attempt+1}): {e}")
                time.sleep(2 * (attempt + 1))
        
        print(f"  -> FAILED after {max_retries} attempts")
        logging.error(f"Failed to download {rel_path} after {max_retries} attempts")
        return False
    
    def manual_sync(self, callback=None):
        """Manually trigger a sync and optionally call a callback when done."""
        def do_sync():
            self.sync_from_admin(show_progress=True)
            if callback:
                self.root.after(0, callback)
        threading.Thread(target=do_sync, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    ClientApp(root)
    root.mainloop()
