"""
Linux Keyboard Blocker for CyberServer V2.

Uses evdev (kernel-level input) to exclusively grab keyboard devices
and selectively block system shortcuts while allowing normal typing.

This works on BOTH X11 and Wayland — it operates at the kernel input
layer, below the display server.

Requirements:
    - python-evdev: pip install evdev
    - User must be in 'input' group: sudo usermod -aG input $USER
    - uinput module loaded: sudo modprobe uinput
    - udev rule for uinput access (see linux_setup.sh)

Usage:
    from linux_keyboard_blocker import LinuxKeyboardBlocker
    
    blocker = LinuxKeyboardBlocker()
    blocker.install()   # Start blocking
    blocker.uninstall() # Stop blocking
"""

import os
import sys
import time
import logging
import threading

# Only import evdev on Linux
if sys.platform == "linux":
    try:
        import evdev
        from evdev import InputDevice, UInput, ecodes
        EVDEV_AVAILABLE = True
    except ImportError:
        EVDEV_AVAILABLE = False
        logging.warning("[KEYBOARD] python-evdev not installed. Keyboard blocking disabled.")
else:
    EVDEV_AVAILABLE = False


class LinuxKeyboardBlocker:
    """Kernel-level keyboard blocker using evdev.
    
    How it works:
    1. Finds ALL keyboard devices (/dev/input/eventX)
    2. Grabs them EXCLUSIVELY — no other app sees the keypresses
    3. Creates a virtual keyboard (uinput) to forward allowed keys
    4. Blocks: Super, Alt+Tab, Alt+F4, Ctrl+Alt+Fx (TTY), Ctrl+Alt+Del
    5. Passes: Normal typing keys (letters, numbers, Enter, etc.)
    """
    
    # Keys that are ALWAYS blocked (even pressed alone)
    BLOCKED_KEYS = {
        ecodes.KEY_LEFTMETA,   # Super/Windows key (left)
        ecodes.KEY_RIGHTMETA,  # Super/Windows key (right)
    } if EVDEV_AVAILABLE else set()
    
    # Key combos that are blocked (modifier + key)
    # Format: (modifier_key_code, blocked_key_code)
    BLOCKED_COMBOS = set()
    
    # Function keys F1-F12 for TTY blocking
    F_KEYS = set()
    
    if EVDEV_AVAILABLE:
        F_KEYS = {
            ecodes.KEY_F1, ecodes.KEY_F2, ecodes.KEY_F3, ecodes.KEY_F4,
            ecodes.KEY_F5, ecodes.KEY_F6, ecodes.KEY_F7, ecodes.KEY_F8,
            ecodes.KEY_F9, ecodes.KEY_F10, ecodes.KEY_F11, ecodes.KEY_F12,
        }
    
    def __init__(self):
        self._running = False
        self._threads = []
        self._grabbed_devices = []
        self._uinput = None
        self._modifier_state = {}  # Track which modifiers are held
        self._lock = threading.Lock()
    
    def install(self):
        """Start keyboard blocking on all keyboard devices."""
        if not EVDEV_AVAILABLE:
            logging.warning("[KEYBOARD] evdev not available, keyboard blocking disabled")
            return
        
        if self._running:
            return
        
        self._running = True
        
        # Find all keyboard devices
        keyboards = self._find_keyboards()
        if not keyboards:
            logging.error("[KEYBOARD] No keyboard devices found!")
            return
        
        logging.info(f"[KEYBOARD] Found {len(keyboards)} keyboard device(s)")
        
        # Create virtual keyboard for forwarding allowed keys
        try:
            # Create uinput device that can emit all key events
            self._uinput = UInput(name="cyberclient-keyboard")
            logging.info("[KEYBOARD] Virtual keyboard (uinput) created")
        except Exception as e:
            logging.error(f"[KEYBOARD] Failed to create uinput: {e}")
            logging.error("[KEYBOARD] Make sure: sudo modprobe uinput && user is in 'input' group")
            self._running = False
            return
        
        # Grab each keyboard and start processing thread
        for dev_path in keyboards:
            try:
                dev = InputDevice(dev_path)
                dev.grab()
                self._grabbed_devices.append(dev)
                
                t = threading.Thread(
                    target=self._process_device,
                    args=(dev,),
                    daemon=True,
                    name=f"kbd-blocker-{os.path.basename(dev_path)}"
                )
                t.start()
                self._threads.append(t)
                
                logging.info(f"[KEYBOARD] Grabbed: {dev.name} ({dev_path})")
            except PermissionError:
                logging.error(f"[KEYBOARD] Permission denied for {dev_path}. Run as root or add user to 'input' group")
            except Exception as e:
                logging.error(f"[KEYBOARD] Failed to grab {dev_path}: {e}")
        
        # Start device watcher for hot-plugged keyboards
        t = threading.Thread(target=self._watch_new_devices, daemon=True, name="kbd-watcher")
        t.start()
        self._threads.append(t)
        
        logging.info(f"[KEYBOARD] Blocking active on {len(self._grabbed_devices)} device(s)")
    
    def uninstall(self):
        """Stop keyboard blocking and release all devices."""
        self._running = False
        
        # Ungrab all devices
        for dev in self._grabbed_devices:
            try:
                dev.ungrab()
                dev.close()
                logging.info(f"[KEYBOARD] Released: {dev.name}")
            except Exception:
                pass
        self._grabbed_devices.clear()
        
        # Close virtual keyboard
        if self._uinput:
            try:
                self._uinput.close()
            except Exception:
                pass
            self._uinput = None
        
        self._threads.clear()
        self._modifier_state.clear()
        
        logging.info("[KEYBOARD] Blocking disabled")
    
    def _find_keyboards(self):
        """Find all keyboard input devices."""
        keyboards = []
        try:
            devices = [InputDevice(path) for path in evdev.list_devices()]
            for dev in devices:
                caps = dev.capabilities(verbose=False)
                # Check if device has EV_KEY capability with typical keyboard keys
                if ecodes.EV_KEY in caps:
                    key_caps = caps[ecodes.EV_KEY]
                    # A keyboard should have letter keys (KEY_A = 30)
                    if ecodes.KEY_A in key_caps and ecodes.KEY_Z in key_caps:
                        keyboards.append(dev.path)
                dev.close()
        except Exception as e:
            logging.error(f"[KEYBOARD] Error scanning devices: {e}")
        return keyboards
    
    def _process_device(self, dev):
        """Process events from a single keyboard device.
        
        Reads all events, blocks forbidden combos, forwards allowed keys.
        """
        try:
            for event in dev.read_loop():
                if not self._running:
                    break
                
                if event.type == ecodes.EV_KEY:
                    key_code = event.code
                    key_value = event.value  # 0=release, 1=press, 2=repeat
                    
                    # Track modifier state
                    self._update_modifier_state(key_code, key_value)
                    
                    # Check if this key/combo should be blocked
                    if self._should_block(key_code, key_value):
                        continue  # Swallow the event
                    
                    # Forward allowed key to virtual keyboard
                    self._forward_key(event)
                else:
                    # Forward non-key events (SYN, LED, etc.)
                    self._forward_key(event)
                    
        except OSError:
            # Device was unplugged or closed
            logging.info(f"[KEYBOARD] Device disconnected: {dev.name}")
        except Exception as e:
            if self._running:
                logging.error(f"[KEYBOARD] Error processing {dev.name}: {e}")
    
    def _update_modifier_state(self, key_code, key_value):
        """Track which modifier keys are currently held down."""
        modifiers = {
            ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL,
            ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT,
            ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA,
            ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT,
        }
        if key_code in modifiers:
            with self._lock:
                if key_value in (1, 2):  # Press or repeat
                    self._modifier_state[key_code] = True
                elif key_value == 0:  # Release
                    self._modifier_state[key_code] = False
    
    def _is_modifier_held(self, *key_codes):
        """Check if ANY of the given modifier keys are held."""
        with self._lock:
            return any(self._modifier_state.get(k, False) for k in key_codes)
    
    def _ctrl_held(self):
        return self._is_modifier_held(ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL)
    
    def _alt_held(self):
        return self._is_modifier_held(ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT)
    
    def _meta_held(self):
        return self._is_modifier_held(ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA)
    
    def _should_block(self, key_code, key_value):
        """Determine if a key event should be blocked.
        
        Returns True if the key should be swallowed (not forwarded).
        """
        # Always block Super/Meta keys
        if key_code in self.BLOCKED_KEYS:
            return True
        
        # Block Alt+Tab (window switching)
        if self._alt_held() and key_code == ecodes.KEY_TAB:
            return True
        
        # Block Alt+F4 (close window)
        if self._alt_held() and key_code == ecodes.KEY_F4:
            return True
        
        # Block Alt+Escape
        if self._alt_held() and key_code == ecodes.KEY_ESC:
            return True
        
        # Block Ctrl+Alt+Fx (TTY switching) — CRITICAL for kiosk security
        if self._ctrl_held() and self._alt_held() and key_code in self.F_KEYS:
            return True
        
        # Block Ctrl+Alt+Delete
        if self._ctrl_held() and self._alt_held() and key_code == ecodes.KEY_DELETE:
            return True
        
        # Block Ctrl+Alt+Backspace (X11 kill)
        if self._ctrl_held() and self._alt_held() and key_code == ecodes.KEY_BACKSPACE:
            return True
        
        # Block Ctrl+Escape (some DEs open app menu)
        if self._ctrl_held() and key_code == ecodes.KEY_ESC:
            return True
        
        # Block Meta+number (KDE virtual desktop switching)
        if self._meta_held() and key_code in range(ecodes.KEY_1, ecodes.KEY_0 + 1):
            return True
        
        # Allow everything else
        return False
    
    def _forward_key(self, event):
        """Forward an allowed event to the virtual keyboard."""
        if self._uinput:
            try:
                self._uinput.write_event(event)
                # Sync after key events
                if event.type == ecodes.EV_KEY:
                    self._uinput.syn()
            except Exception as e:
                logging.debug(f"[KEYBOARD] Forward error: {e}")
    
    def _watch_new_devices(self):
        """Watch for newly connected keyboards (USB hot-plug).
        
        Checks every 5 seconds for new keyboard devices and grabs them.
        """
        known_paths = {dev.path for dev in self._grabbed_devices}
        
        while self._running:
            time.sleep(5)
            
            if not self._running:
                break
            
            try:
                current_keyboards = set(self._find_keyboards())
                new_keyboards = current_keyboards - known_paths
                
                for dev_path in new_keyboards:
                    try:
                        dev = InputDevice(dev_path)
                        dev.grab()
                        self._grabbed_devices.append(dev)
                        known_paths.add(dev_path)
                        
                        t = threading.Thread(
                            target=self._process_device,
                            args=(dev,),
                            daemon=True,
                            name=f"kbd-blocker-{os.path.basename(dev_path)}"
                        )
                        t.start()
                        self._threads.append(t)
                        
                        logging.info(f"[KEYBOARD] Hot-plugged keyboard grabbed: {dev.name} ({dev_path})")
                    except Exception as e:
                        logging.warning(f"[KEYBOARD] Failed to grab hot-plugged device {dev_path}: {e}")
            except Exception:
                pass  # Device listing failed, try again later


# -------- Module-Level Convenience Functions --------
# These mirror the Windows API (install_keyboard_hook / uninstall_keyboard_hook)

_blocker_instance = None

def install_keyboard_hook():
    """Install the Linux keyboard blocker (mirrors Windows API)."""
    global _blocker_instance
    if _blocker_instance is not None:
        return  # Already installed
    _blocker_instance = LinuxKeyboardBlocker()
    _blocker_instance.install()

def uninstall_keyboard_hook():
    """Uninstall the Linux keyboard blocker (mirrors Windows API)."""
    global _blocker_instance
    if _blocker_instance:
        _blocker_instance.uninstall()
        _blocker_instance = None

def pump_messages():
    """No-op on Linux — Windows needs a message pump for hooks, Linux doesn't."""
    # evdev uses read_loop() in threads, no message pump needed
    while True:
        time.sleep(1)
