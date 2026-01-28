import threading
import ctypes
from ctypes import wintypes
import os
from utils import load_config, setup_logging
import logging

# ----------------- CONFIG & LOGGING -----------------
try:
    CONFIG = load_config()
except Exception as e:
    print(f"Warning: Error loading config, using defaults: {e}")
    CONFIG = {}

import sys
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = CONFIG.get("database", {}).get("file", "cybercafe.db")
if not os.path.isabs(DB_FILE):
    DB_FILE = os.path.join(BASE_DIR, DB_FILE)
SERVER_HOST = CONFIG.get("server", {}).get("host", "0.0.0.0")
SERVER_PORT = CONFIG.get("server", {}).get("port", 5000)

try:
    logger = setup_logging(CONFIG)
    if logger is None:
        raise Exception("Logger is None")
except Exception as e:
    logger = logging.getLogger("cybercafe")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler())

# ----------------- SHARED STATE -----------------
# Χρησιμοποιείται από το GUI και το API για να βλέπουν ποιοι είναι online
ACTIVE_SESSIONS = {}
ACTIVE_LOCK = threading.Lock()

# ----------------- KEYBOARD HOOKS -----------------
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_F4 = 0x73
VK_MENU = 0x12

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.ULONG),
    ]

LowLevelKeyboardProc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
keyboard_hook_handle = None
keyboard_proc = None

if os.name == "nt":
    user32 = ctypes.windll.user32
else:
    user32 = None

def low_level_keyboard_proc(nCode, wParam, lParam):
    if not user32: return 0
    if nCode < 0:
        return user32.CallNextHookEx(keyboard_hook_handle, nCode, wParam, lParam)
    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk = kb.vkCode
        alt_pressed = (user32.GetAsyncKeyState(VK_MENU) & 0x8000) != 0
        if alt_pressed and vk == VK_TAB: return 1
        if alt_pressed and vk == VK_ESCAPE: return 1
        if alt_pressed and vk == VK_F4: return 1
        if vk in (VK_LWIN, VK_RWIN): return 1
    return user32.CallNextHookEx(keyboard_hook_handle, nCode, wParam, lParam)

def install_keyboard_hook():
    global keyboard_hook_handle, keyboard_proc
    if os.name != "nt" or user32 is None: return
    if keyboard_hook_handle is not None: return
    kernel32 = ctypes.windll.kernel32
    keyboard_proc = LowLevelKeyboardProc(low_level_keyboard_proc)
    keyboard_hook_handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, keyboard_proc, kernel32.GetModuleHandleW(None), 0)

def uninstall_keyboard_hook():
    global keyboard_hook_handle, keyboard_proc
    if os.name != "nt" or user32 is None: return
    if keyboard_hook_handle:
        user32.UnhookWindowsHookEx(keyboard_hook_handle)
        keyboard_hook_handle = None
        keyboard_proc = None