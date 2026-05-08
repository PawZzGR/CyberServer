"""
Cross-Platform Utilities for CyberServer V2.

Provides platform-aware abstractions so the same codebase runs
on both Windows and Linux without modification.

Usage:
    from platform_utils import IS_WINDOWS, IS_LINUX, FONT, get_config_dir, reboot_system
"""

import os
import sys
import platform
import logging
import subprocess

# -------- Platform Detection --------
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

# -------- Font Selection --------
# Windows: Segoe UI (Microsoft proprietary, looks great on Windows)
# Linux:   Noto Sans (ships with KDE Plasma / CachyOS by default)
if IS_WINDOWS:
    FONT = "Segoe UI"
else:
    FONT = "Noto Sans"


# -------- Config Directory --------
def get_config_dir(app_name):
    """Get the persistent config directory for the given app component.
    
    Args:
        app_name: "User", "Admin", or "Server"
    
    Returns:
        Path string, e.g.:
            Windows: C:\\Users\\X\\AppData\\Roaming\\CyberClient\\User
            Linux:   /home/x/.config/CyberClient/User
    """
    if IS_WINDOWS:
        app_data = os.getenv('APPDATA')
        if not app_data:
            app_data = os.path.expanduser("~")
    else:
        # XDG Base Directory Specification
        app_data = os.getenv('XDG_CONFIG_HOME',
                             os.path.join(os.path.expanduser("~"), ".config"))
    
    path = os.path.join(app_data, "CyberClient", app_name)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        print(f"Failed to create config dir: {e}")
        # Fallback to current directory
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))
    return path


# -------- System Reboot --------
def reboot_system():
    """Reboot the system using OS-appropriate method.
    
    On Windows: Uses the existing bulletproof 3-method approach
                (Windows API → shutdown.exe → os.system)
    On Linux:   Uses systemctl → shutdown → os.system fallback
    """
    if IS_WINDOWS:
        _windows_reboot()
    else:
        _linux_reboot()


def _linux_reboot():
    """Reboot on Linux using systemctl with fallbacks."""
    # Method 1: systemctl (most modern, works on CachyOS/systemd)
    try:
        subprocess.run(["systemctl", "reboot"], check=True)
        return
    except Exception as e:
        logging.error(f"[REBOOT] systemctl reboot failed: {e}")
    
    # Method 2: shutdown command
    try:
        subprocess.run(["shutdown", "-r", "now"], check=True)
        return
    except Exception as e:
        logging.error(f"[REBOOT] shutdown -r now failed: {e}")
    
    # Method 3: Last resort
    try:
        os.system("reboot")
    except Exception as e:
        logging.error(f"[REBOOT] All Linux reboot methods failed: {e}")


def _windows_reboot():
    """Reboot on Windows using direct Windows API (ctypes).
    
    Strategy:
    1. Direct Windows API via ctypes — cannot be blocked by removing CLI permissions
    2. Fallback to shutdown.exe (direct path, no CMD)
    3. Last resort: os.system
    """
    # Method 1: Direct Windows API via ctypes (MOST RELIABLE)
    try:
        import ctypes
        from ctypes import wintypes
        
        TOKEN_ADJUST_PRIVILEGES = 0x0020
        TOKEN_QUERY = 0x0008
        SE_PRIVILEGE_ENABLED = 0x00000002
        EWX_REBOOT = 0x02
        EWX_FORCE = 0x04
        
        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]
        
        class LUID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]
        
        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [("PrivilegeCount", wintypes.DWORD),
                        ("Privileges", LUID_AND_ATTRIBUTES * 1)]
        
        hToken = ctypes.c_void_p()
        ctypes.windll.advapi32.OpenProcessToken(
            ctypes.windll.kernel32.GetCurrentProcess(),
            TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
            ctypes.byref(hToken)
        )
        
        luid = LUID()
        ctypes.windll.advapi32.LookupPrivilegeValueW(
            None, "SeShutdownPrivilege", ctypes.byref(luid)
        )
        
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        
        ctypes.windll.advapi32.AdjustTokenPrivileges(
            hToken, False, ctypes.byref(tp), 0, None, None
        )
        
        result = ctypes.windll.user32.ExitWindowsEx(EWX_REBOOT | EWX_FORCE, 0)
        if result:
            return
        
        logging.warning("[REBOOT] ExitWindowsEx returned False, trying fallback...")
    except Exception as e:
        logging.error(f"[REBOOT] Windows API method failed: {e}")
    
    # Method 2: Fallback to shutdown.exe
    try:
        subprocess.Popen([r"C:\Windows\System32\shutdown.exe", "/r", "/t", "0"], shell=False)
        return
    except Exception as e:
        logging.error(f"[REBOOT] shutdown.exe failed: {e}")
    
    # Method 3: Last resort
    try:
        os.system("shutdown /r /t 0")
    except Exception as e:
        logging.error(f"[REBOOT] All reboot methods failed: {e}")


# -------- Path Normalization (Cross-Platform) --------
def normalize_path(path):
    """Convert a path to the current OS's format.
    
    Handles:
    - Forward/backward slashes
    - ~ expansion
    - Environment variables (%USERPROFILE%, $HOME)
    - Relative to absolute
    """
    if not path:
        return path
    
    # Expand user home directory (~)
    path = os.path.expanduser(path)
    
    # Expand environment variables
    path = os.path.expandvars(path)
    
    # Handle "Desktop" shortcut
    if path.lower().startswith("desktop"):
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        path = path.replace("Desktop", desktop, 1).replace("desktop", desktop, 1)
    
    # Convert to absolute path
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    
    # Normalize separators for current OS
    path = os.path.normpath(path)
    
    return path


# -------- File Open (Cross-Platform) --------
def open_file_with_default(filepath):
    """Open a file with the system's default application.
    
    Windows: os.startfile()
    Linux:   xdg-open
    """
    if IS_WINDOWS:
        os.startfile(filepath)
    else:
        try:
            subprocess.Popen(["xdg-open", filepath],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception as e:
            logging.error(f"Failed to open file: {e}")


def print_file(filepath):
    """Print a file using the system's default print mechanism.
    
    Windows: os.startfile(path, 'print')
    Linux:   lpr command
    """
    if IS_WINDOWS:
        try:
            os.startfile(filepath, "print")
        except Exception as e:
            print(f"Ticket print error: {e}")
    else:
        try:
            subprocess.Popen(["lpr", filepath],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception as e:
            logging.error(f"Failed to print file: {e}")
