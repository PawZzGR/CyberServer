"""
Toast notification system for elegant notifications
"""
import tkinter as tk
from threading import Timer


class Toast:
    """Elegant toast notification widget"""
    
    COLORS = {
        'success': {'bg': '#10B981', 'fg': 'white'},
        'error': {'bg': '#EF4444', 'fg': 'white'},
        'info': {'bg': '#3B82F6', 'fg': 'white'},
        'warning': {'bg': '#F59E0B', 'fg': 'white'},
    }
    
    def __init__(self, root, message, toast_type='info', duration=3000):
        self.root = root
        self.message = message
        self.toast_type = toast_type
        self.duration = duration
        self.toast_window = None
        
    def show(self):
        """Show the toast notification"""
        # Create overlay window
        self.toast_window = tk.Toplevel(self.root)
        self.toast_window.overrideredirect(True)
        self.toast_window.attributes("-topmost", True)
        self.toast_window.attributes("-alpha", 0.0)
        
        # Get screen dimensions
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # Position at top-right
        width = 350
        height = 70
        x = screen_width - width - 20
        y = 20
        
        self.toast_window.geometry(f"{width}x{height}+{x}+{y}")
        
        # Get colors
        colors = self.COLORS.get(self.toast_type, self.COLORS['info'])
        
        # Create frame
        frame = tk.Frame(
            self.toast_window,
            bg=colors['bg'],
            relief='flat',
            bd=0
        )
        frame.pack(fill='both', expand=True, padx=2, pady=2)
        
        # Icon (simple emoji)
        icons = {
            'success': '✓',
            'error': '✗',
            'info': 'ℹ',
            'warning': '⚠'
        }
        
        icon_label = tk.Label(
            frame,
            text=icons.get(self.toast_type, 'ℹ'),
            bg=colors['bg'],
            fg=colors['fg'],
            font=('Segoe UI', 16, 'bold')
        )
        icon_label.pack(side='left', padx=(15, 10), pady=15)
        
        # Message
        message_label = tk.Label(
            frame,
            text=self.message,
            bg=colors['bg'],
            fg=colors['fg'],
            font=('Segoe UI', 11),
            wraplength=250,
            justify='left'
        )
        message_label.pack(side='left', fill='both', expand=True, padx=(0, 15), pady=15)
        
        # Fade in
        self.fade_in()
        
        # Auto-dismiss
        self.timer = Timer(self.duration / 1000.0, self.dismiss)
        self.timer.start()
        
    def fade_in(self):
        """Fade in animation"""
        if not self.toast_window or not self.toast_window.winfo_exists():
            return
        alpha = self.toast_window.attributes("-alpha")
        if alpha < 0.95:
            alpha += 0.1
            self.toast_window.attributes("-alpha", alpha)
            self.root.after(20, self.fade_in)
        else:
            self.toast_window.attributes("-alpha", 0.95)
    
    def fade_out(self):
        """Fade out animation"""
        if not self.toast_window or not self.toast_window.winfo_exists():
            return
        alpha = self.toast_window.attributes("-alpha")
        if alpha > 0.1:
            alpha -= 0.1
            self.toast_window.attributes("-alpha", alpha)
            self.root.after(20, self.fade_out)
        else:
            if self.toast_window:
                self.toast_window.destroy()
    
    def dismiss(self):
        """Dismiss the toast"""
        if self.timer:
            self.timer.cancel()
        if self.toast_window:
            self.fade_out()


def show_toast(root, message, toast_type='info', duration=3000):
    """Convenience function to show a toast"""
    toast = Toast(root, message, toast_type, duration)
    toast.show()
    return toast

