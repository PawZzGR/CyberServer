import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import sqlite3
import threading
import os
import shutil
import time
import random
import string
from datetime import datetime
from tkcalendar import Calendar
from utils import export_to_csv, save_config, verify_password
from toast import show_toast
import database as db
from common import CONFIG, DB_FILE, logger, ACTIVE_SESSIONS, ACTIVE_LOCK, install_keyboard_hook

class ServerApp:
    BG_MAIN = "#FAF5EF"
    BG_SECONDARY = "#F5E6D3"
    BG_CARD = "#EFE0D0"
    BG_BUTTON = "#8B7355"
    BG_BUTTON_HOVER = "#6B5D4F"
    BG_BUTTON_ACCENT = "#A0826D"
    TEXT_PRIMARY = "#3E2723"
    TEXT_SECONDARY = "#5D4037"
    TEXT_LIGHT = "#7A6B5E"
    BORDER_COLOR = "#D7C4A8"
    ACCENT = "#C19A6B"
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Cybercafe Server")
        self.root.configure(bg=self.BG_MAIN)
        try:
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.update_idletasks()
            w = self.root.winfo_screenwidth()
            h = self.root.winfo_screenheight()
            self.root.geometry(f"{w}x{h}+0+0")
        except Exception as e:
            print("Fullscreen error:", e)

        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        install_keyboard_hook()

        self.current_user = None
        self.pending_guest_pulses = 0
        self.guest_pulses_label = None
        self.guest_time_label = None
        self.coin_info_label_user = None
        self.coin_info_label_admin = None
        self.users_tree = None
        self.users_index = {}
        self.search_var = None
        self.stations_tree = None
        self.backup_label = None
        self.loading_label = None
        self.loading_frame = None
        self.connection_status = None
        self.backup_thread = None
        self.start_auto_backup()

        self.root.bind_all("<Key>", self.on_global_key)
        self.root.bind_all("<Return>", self.on_enter_key)
        self.root.bind_all("<Escape>", self.on_escape_key)

        self.build_login_ui()

    def on_global_key(self, event):
        if event.keysym == "F2":
            if self.current_user and not self.current_user.get("is_admin", False):
                db.add_pulses_to_user(self.current_user["id"], 1)
                self.update_remaining_label()
                show_toast(self.root, "Pulse added!", "success", 2000)
                return
            if self.current_user is None and self.guest_pulses_label is not None:
                self.pending_guest_pulses += 1
                self.update_guest_display()
                return

        if event.char == "6" or event.keysym == "6":
            if self.current_user is None:
                self.issue_guest_code()
            return
    
    def on_enter_key(self, event):
        widget = event.widget
        if isinstance(widget, tk.Entry):
            parent = widget.master
            while parent:
                if hasattr(self, 'username_entry') and widget == self.username_entry:
                    if hasattr(self, 'password_entry'): self.password_entry.focus()
                    return
                elif hasattr(self, 'password_entry') and widget == self.password_entry:
                    if self.current_user is None: self.login()
                    return
                elif hasattr(self, 'guest_code_entry') and widget == self.guest_code_entry:
                    self.login()
                    return
                parent = parent.master
    
    def on_escape_key(self, event):
        widget = event.widget
        if isinstance(widget, (tk.Toplevel, tk.Tk)):
            if isinstance(widget, tk.Toplevel): widget.destroy()

    def clear_window(self):
        for w in self.root.winfo_children(): w.destroy()
    
    def show_loading(self, message="Loading..."):
        if self.loading_frame and self.loading_frame.winfo_exists(): return
        # Transparent overlay feel using a big frame? 
        # Standard tkinter doesn't do true alpha transparency well without attributes logic which complicates embedding.
        # We will use a clean centered card with shadow effect (simulated by border).
        self.loading_frame = tk.Frame(self.root, bg=self.BG_MAIN)
        self.loading_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        
        # Inner card
        card = tk.Frame(self.loading_frame, bg="white", padx=40, pady=30, relief="flat", highlightthickness=1, highlightbackground=self.BORDER_COLOR)
        card.place(relx=0.5, rely=0.5, anchor="center")
        
        # Spinner/Text
        tk.Label(card, text="⏳", font=("Segoe UI", 32), bg="white").pack(pady=(0, 15))
        tk.Label(card, text=message, font=("Segoe UI", 14, "bold"), fg=self.TEXT_PRIMARY, bg="white").pack()
        self.loading_dots = tk.Label(card, text="...", font=("Segoe UI", 14), fg=self.ACCENT, bg="white")
        self.loading_dots.pack(pady=(5, 0))
        self.animate_loading()

    def on_search_change(self, *args):
        if hasattr(self, "_search_job") and self._search_job:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(300, lambda: self.refresh_users_tree(self.search_var.get()))
    
    def animate_loading(self):
        if not self.loading_frame or not self.loading_frame.winfo_exists(): return
        text = self.loading_dots.cget("text")
        self.loading_dots.config(text="." if text == "..." else text + ".")
        self.root.after(500, self.animate_loading)
    
    def hide_loading(self):
        if self.loading_frame and self.loading_frame.winfo_exists(): self.loading_frame.destroy()
        self.loading_frame = None

    def seconds_to_hms(self, seconds: int):
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return h, m, s

    def update_coin_info_display(self):
        sp = db.get_seconds_per_pulse()
        to_minutes = lambda sec: sec // 60
        m050, m1, m2 = to_minutes(sp * 1), to_minutes(sp * 2), to_minutes(sp * 4)
        
        user_text = f"0,50€ = {m050} λεπτά  |  1€ = {m1} λεπτά  |  2€ = {m2} λεπτά"
        if self.coin_info_label_user and self.coin_info_label_user.winfo_exists():
            self.coin_info_label_user.config(text=user_text, fg=self.TEXT_SECONDARY)

        admin_text = f"0,50€ (1 pulse) = {m050} λεπτά  |  1€ (2 pulses) = {m1} λεπτά  |  2€ (4 pulses) = {m2} λεπτά"
        if self.coin_info_label_admin and self.coin_info_label_admin.winfo_exists():
            self.coin_info_label_admin.config(text=admin_text, fg=self.TEXT_SECONDARY)

    def update_guest_display(self):
        # Χρησιμοποιούμε τη νέα συνάρτηση του DB που υπολογίζει ΚΑΙ τα bonus
        total_seconds = db.calculate_total_time_with_bonus(self.pending_guest_pulses)
        
        minutes = total_seconds // 60
        h, m = divmod(minutes, 60)

        if self.guest_pulses_label and self.guest_pulses_label.winfo_exists():
            self.guest_pulses_label.config(text=f"Pulses: {self.pending_guest_pulses}")
        
        if self.guest_time_label and self.guest_time_label.winfo_exists():
            # Δείχνουμε τον χρόνο ΜΑΖΙ με το bonus
            self.guest_time_label.config(text=f"Συνολικός χρόνος (με bonus): {h}h {m}m")

    def generate_guest_code(self):
        return "".join(random.choice(string.ascii_letters + "123456789") for _ in range(8))

    def print_guest_ticket(self, code, total_seconds):
        minutes = total_seconds // 60
        text = (f"==== CYBER TICKET ====\nCode: {code}\nΧρόνος: {minutes} λεπτά\n"
                f"Ημερομηνία: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n=======================\n")
        path = os.path.join(os.getcwd(), "last_ticket.txt")
        try:
            with open(path, "w", encoding="utf-8") as f: f.write(text)
        except Exception as e: print("Ticket write error:", e); return
        if os.name == "nt":
            try: os.startfile(path, "print")
            except Exception as e: print("Ticket print error:", e)

    def issue_guest_code(self):
        if self.pending_guest_pulses <= 0: return
        
        # ΠΑΛΙΑ ΕΝΤΟΛΗ (Διέγραψέ την ή κάντην σχόλιο):
        # sp = db.get_seconds_per_pulse()
        # seconds_total = self.pending_guest_pulses * sp
        
        # ΝΕΑ ΕΝΤΟΛΗ (Υπολογίζει χρόνο + Bonus):
        seconds_total = db.calculate_total_time_with_bonus(self.pending_guest_pulses)
        
        code = None
        for _ in range(10):
            c = self.generate_guest_code()
            if db.create_guest_user(c, seconds_total):
                code = c
                break
        if not code: return
        
        self.print_guest_ticket(code, seconds_total)
        self.pending_guest_pulses = 0
        self.update_guest_display()
        show_toast(self.root, f"Guest code {code} issued!", "success", 2000)

    def build_login_ui(self):
        self.clear_window()
        self.root.title("Cybercafe Server - Login / Guest")
        card = tk.Frame(self.root, padx=40, pady=40, bg=self.BG_CARD, relief="flat", bd=0, highlightthickness=2, highlightbackground=self.BORDER_COLOR)
        card.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(card, text="Cybercafe Server", font=("Segoe UI", 32, "bold"), fg=self.TEXT_PRIMARY, bg=self.BG_CARD).grid(row=0, column=0, columnspan=2, pady=(0, 30))
        lbl_style = {"fg": self.TEXT_SECONDARY, "bg": self.BG_CARD, "font": ("Segoe UI", 12)}
        tk.Label(card, text="Username:", **lbl_style).grid(row=1, column=0, sticky="e", pady=10, padx=(0, 15))
        self.username_entry = tk.Entry(card, width=24, font=("Segoe UI", 12), bg="white", fg=self.TEXT_PRIMARY, relief="flat", bd=0, highlightthickness=1, highlightbackground=self.BORDER_COLOR, highlightcolor=self.ACCENT, insertbackground=self.TEXT_PRIMARY)
        self.username_entry.grid(row=1, column=1, pady=10, ipady=6, sticky="w")
        self.root.after(100, lambda: self.username_entry.focus_set())
        tk.Label(card, text="Password:", **lbl_style).grid(row=2, column=0, sticky="e", pady=10, padx=(0, 15))
        self.password_entry = tk.Entry(card, show="*", width=24, font=("Segoe UI", 12), bg="white", fg=self.TEXT_PRIMARY, relief="flat", bd=0, highlightthickness=1, highlightbackground=self.BORDER_COLOR, highlightcolor=self.ACCENT, insertbackground=self.TEXT_PRIMARY)
        self.password_entry.grid(row=2, column=1, pady=10, ipady=6, sticky="w")
        btn_frame = tk.Frame(card, bg=self.BG_CARD)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=20)
        
        def make_btn(text, cmd):
            return tk.Button(btn_frame, text=text, command=cmd, font=("Segoe UI", 12, "bold"), bg=self.BG_BUTTON, fg="white", activebackground=self.BG_BUTTON_HOVER, activeforeground="white", relief="flat", padx=24, pady=10, cursor="hand2")
        
        make_btn("Login", self.login).grid(row=0, column=0, padx=8)
        make_btn("Register", self.register).grid(row=0, column=1, padx=8)
        
        guest_frame = tk.LabelFrame(card, text="Guest ticket (χωρίς λογαριασμό)", padx=18, pady=18, fg=self.TEXT_SECONDARY, bg=self.BG_CARD, font=("Segoe UI", 11, "bold"), bd=1, highlightthickness=0, relief="flat")
        guest_frame.grid(row=4, column=0, columnspan=2, pady=(15, 0), sticky="we")
        self.guest_pulses_label = tk.Label(guest_frame, text="Pulses: 0", fg=self.TEXT_PRIMARY, bg=self.BG_CARD, font=("Segoe UI", 11))
        self.guest_pulses_label.grid(row=0, column=0, sticky="w", padx=(0, 15))
        self.guest_time_label = tk.Label(guest_frame, text="Συνολικός χρόνος: 0h 0m", fg=self.TEXT_PRIMARY, bg=self.BG_CARD, font=("Segoe UI", 11))
        self.guest_time_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
        tk.Button(guest_frame, text="Έκδοση guest κωδικού (ticket)", command=self.issue_guest_code, font=("Segoe UI", 11, "bold"), bg=self.ACCENT, fg="white", activebackground=self.BG_BUTTON_HOVER, activeforeground="white", relief="flat", padx=16, pady=8, cursor="hand2").grid(row=0, column=1, rowspan=2, padx=(10, 0))
        self.update_guest_display()

    def login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        if not username or not password:
            show_toast(self.root, "Please enter username and password", "warning")
            return
        self.show_loading("Logging in...")
        def do_login():
            try:
                user = db.get_user(username)
                if not user or not verify_password(password, user["password"]):
                    self.root.after(0, lambda: show_toast(self.root, "Invalid username or password", "error"))
                    self.root.after(0, lambda: self.hide_loading())
                    return
                
                # --- ΠΡΟΣΘΕΣΕ ΑΥΤΟ ΕΔΩ ---
                db.reset_session_stats(user["id"])
                # -------------------------

                self.root.after(0, lambda: self.hide_loading())
                self.root.after(0, lambda: show_toast(self.root, f"Welcome, {username}!", "success", 2000))
                
                self.current_user = user
                if user["is_admin"]: self.root.after(0, self._safe_build_admin_ui)
                else: self.root.after(0, self.build_user_ui)
            except Exception as e:
                print(f"Login error: {e}")
                self.root.after(0, lambda: self.hide_loading())
                self.root.after(0, lambda: show_toast(self.root, f"Login error: {str(e)}", "error"))
        threading.Thread(target=do_login, daemon=True).start()
    
    def _safe_build_admin_ui(self):
        try: self.build_admin_ui()
        except Exception as e: messagebox.showerror("Error", f"Error loading admin panel:\n{str(e)}")

    def register(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        if not username or not password:
            show_toast(self.root, "Please enter username and password", "warning"); return
        if len(password) < 4:
            show_toast(self.root, "Password must be at least 4 characters", "warning"); return
        self.show_loading("Creating account...")
        def do_register():
            try:
                ok, err = db.add_user(username, password)
                self.root.after(0, lambda: self.hide_loading())
                if not ok: show_toast(self.root, "Username already exists", "error")
                else:
                    show_toast(self.root, "Account created successfully!", "success")
                    self.root.after(0, lambda: self.username_entry.delete(0, tk.END))
                    self.root.after(0, lambda: self.password_entry.delete(0, tk.END))
            except Exception:
                self.root.after(0, lambda: show_toast(self.root, "Registration error", "error"))
                self.root.after(0, lambda: self.hide_loading())
        threading.Thread(target=do_register, daemon=True).start()

    def build_user_ui(self):
        self.clear_window()
        card = tk.Frame(self.root, padx=40, pady=40, bg=self.BG_CARD, relief="flat", bd=0, highlightthickness=2, highlightbackground=self.BORDER_COLOR)
        card.place(relx=0.5, rely=0.5, anchor="center")
        self.remaining_label = tk.Label(card, text="", font=("Segoe UI", 20, "bold"), fg=self.TEXT_PRIMARY, bg=self.BG_CARD)
        self.remaining_label.pack(pady=(0, 20))
        self.update_remaining_label()
        self.coin_info_label_user = tk.Label(card, text="", font=("Segoe UI", 12), justify="left", fg=self.TEXT_SECONDARY, bg=self.BG_CARD)
        self.coin_info_label_user.pack(pady=(0, 25))
        tk.Button(card, text="Logout", command=self.logout, font=("Segoe UI", 11, "bold"), bg=self.BG_BUTTON, fg="white", activebackground=self.BG_BUTTON_HOVER, activeforeground="white", relief="flat", padx=30, pady=10, cursor="hand2").pack()

    def update_remaining_label(self):
        if not self.current_user: return
        user = db.get_user(self.current_user["username"])
        if user: self.current_user = user
        h, m, s = self.seconds_to_hms(self.current_user["remaining_seconds"])
        self.remaining_label.config(text=f"Υπόλοιπο: {h} ώρες {m} λεπτά {s} δευτερόλεπτα")

    def logout(self):
        self.current_user = None
        self.build_login_ui()

    def build_admin_ui(self):
        self.clear_window()
        main = tk.Frame(self.root, padx=15, pady=15, bg=self.BG_MAIN)
        main.pack(fill="both", expand=True)
        header = tk.Frame(main, bg=self.BG_MAIN)
        header.pack(fill="x", pady=(0, 10))
        tk.Label(header, text="Admin Panel", font=("Segoe UI", 24, "bold"), fg=self.TEXT_PRIMARY, bg=self.BG_MAIN).pack(side="left")
        status_frame = tk.Frame(header, bg=self.BG_MAIN)
        status_frame.pack(side="right", padx=(0, 15))
        self.connection_status = tk.Label(status_frame, text="●", font=("Segoe UI", 16), fg="#10B981", bg=self.BG_MAIN)
        self.connection_status.pack(side="left", padx=(0, 5))
        tk.Label(status_frame, text="Server Online", font=("Segoe UI", 9), fg=self.TEXT_SECONDARY, bg=self.BG_MAIN).pack(side="left")
        tk.Button(header, text="Logout", command=self.logout, font=("Segoe UI", 11, "bold"), bg=self.BG_BUTTON, fg="white", activebackground=self.BG_BUTTON_HOVER, activeforeground="white", relief="flat", padx=20, pady=8, cursor="hand2").pack(side="right")
        
        style = ttk.Style()
        try: style.theme_use("clam")
        except: pass
        style.configure("TNotebook", background=self.BG_MAIN, borderwidth=0, padding=[0, 5])
        style.configure("TNotebook.Tab", padding=[15, 10], background=self.BG_SECONDARY, foreground=self.TEXT_PRIMARY, font=("Segoe UI", 11), borderwidth=1, relief="flat")
        style.map("TNotebook.Tab", background=[("selected", self.BG_CARD)], expand=[("selected", [1, 1, 1, 0])])
        style.configure("Treeview", background="white", foreground=self.TEXT_PRIMARY, fieldbackground="white", font=("Segoe UI", 11), rowheight=30)
        style.configure("Treeview.Heading", background=self.BG_SECONDARY, foreground=self.TEXT_PRIMARY, font=("Segoe UI", 11, "bold"), relief="flat", padding=(10, 8))
        style.map("Treeview", background=[("selected", self.ACCENT)], foreground=[("selected", "white")])
        
        notebook = ttk.Notebook(main)
        notebook.pack(fill="both", expand=True)
        tabs = [
            ("Dashboard", self.build_dashboard_tab),
            ("Game Paths", self.build_game_paths_tab),
            ("Ρυθμίσεις", self.build_settings_tab), 
            ("Χρήστες", self.build_users_tab), 
            ("Σταθμοί", self.build_stations_tab), 
            ("Στατιστικά", self.build_stats_tab), 
            ("Session History", self.build_sessions_tab)
        ]
        for name, builder in tabs:
            f = ttk.Frame(notebook)
            notebook.add(f, text=name)
            builder(f)

    def build_dashboard_tab(self, parent):
        container = tk.Frame(parent, padx=30, pady=30, bg=self.BG_CARD)
        container.pack(fill="both", expand=True)
        
        tk.Label(container, text="Κέντρο Ελέγχου (Dashboard)", font=("Segoe UI", 20, "bold"), fg=self.TEXT_PRIMARY, bg=self.BG_CARD).pack(anchor="w", pady=(0, 30))
        
        stats_frame = tk.Frame(container, bg=self.BG_CARD)
        stats_frame.pack(fill="x", expand=True)
        
        def make_card(title, value_func, icon="📊"):
            f = tk.Frame(stats_frame, bg="white", padx=20, pady=20, relief="flat", highlightbackground=self.BORDER_COLOR, highlightthickness=1)
            f.pack(side="left", fill="both", expand=True, padx=10)
            tk.Label(f, text=icon, font=("Segoe UI", 24), bg="white").pack(anchor="ne")
            val_lbl = tk.Label(f, text="...", font=("Segoe UI", 28, "bold"), fg=self.ACCENT, bg="white")
            val_lbl.pack(anchor="w")
            tk.Label(f, text=title, font=("Segoe UI", 11), fg=self.TEXT_SECONDARY, bg="white").pack(anchor="w")
            
            def update():
                try: val_lbl.config(text=str(value_func()))
                except: val_lbl.config(text="-")
            
            return update

        # Get stats
        upd_rev = make_card("Daily Revenue (€)", lambda: f"{db.get_daily_revenue():.2f}€", "💰")
        upd_active = make_card("Active Users", db.get_active_user_count, "👥")
        upd_total = make_card("Total Registered", db.get_total_user_count, "📂")
        
        # Refresh button
        tk.Button(container, text="Refresh Dashboard", command=lambda: [upd_rev(), upd_active(), upd_total()], font=("Segoe UI", 11), bg=self.BG_BUTTON, fg="white", padx=20, pady=10).pack(anchor="e", pady=30)
        
        # Initial load
        self.root.after(100, lambda: [upd_rev(), upd_active(), upd_total()])

    def build_game_paths_tab(self, parent):
        frame = tk.Frame(parent, padx=20, pady=20, bg=self.BG_CARD)
        frame.pack(fill="both", expand=True)
        
        tk.Label(frame, text="Διαχείριση Φακέλων Παιχνιδιών (Mirror Copy)", font=("Segoe UI", 16, "bold"), fg=self.TEXT_PRIMARY, bg=self.BG_CARD).pack(anchor="w", pady=(0, 10))
        tk.Label(frame, text="Οι παρακάτω φάκελοι θα συγχρονίζονται αυτόματα από τους clients.", font=("Segoe UI", 10), fg=self.TEXT_SECONDARY, bg=self.BG_CARD).pack(anchor="w", pady=(0, 20))
        
        list_frame = tk.Frame(frame, bg="white", highlightthickness=1, highlightbackground=self.BORDER_COLOR)
        list_frame.pack(fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.paths_listbox = tk.Listbox(list_frame, font=("Segoe UI", 11), bd=0, highlightthickness=0, yscrollcommand=scrollbar.set, selectmode="single")
        self.paths_listbox.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar.pack(side="right", fill="y")
        scrollbar.config(command=self.paths_listbox.yview)
        
        self.refresh_game_paths()
        
        btn_frame = tk.Frame(frame, bg=self.BG_CARD)
        btn_frame.pack(fill="x", pady=20)
        
        tk.Button(btn_frame, text="➕ Προσθήκη Φακέλου", command=self.add_game_path_ui, font=("Segoe UI", 11, "bold"), bg=self.BG_BUTTON, fg="white", padx=15, pady=8).pack(side="left", padx=(0, 10))
        tk.Button(btn_frame, text="❌ Διαγραφή Επιλεγμένου", command=self.remove_game_path_ui, font=("Segoe UI", 11), bg=self.BG_BUTTON_ACCENT, fg="white", padx=15, pady=8).pack(side="left")

    def refresh_game_paths(self):
        if not hasattr(self, "paths_listbox"): return
        self.paths_listbox.delete(0, tk.END)
        self.paths_map = {} # index -> id
        for i, (pid, path) in enumerate(db.get_game_paths()):
            self.paths_listbox.insert(tk.END, path)
            self.paths_map[i] = pid

    def add_game_path_ui(self):
        path = filedialog.askdirectory(parent=self.root, title="Επιλογή φακέλου παιχνιδιού")
        if path:
            path = path.replace("/", "\\") # Windows path fix
            ok, err = db.add_game_path(path)
            if ok: 
                show_toast(self.root, "Path added", "success")
                self.refresh_game_paths()
            else:
                show_toast(self.root, f"Error: {err}", "error")

    def remove_game_path_ui(self):
        sel = self.paths_listbox.curselection()
        if not sel: return
        idx = sel[0]
        pid = self.paths_map.get(idx)
        path = self.paths_listbox.get(idx)
        
        if messagebox.askyesno("Confirm", f"Stop syncing '{path}'?"):
            db.remove_game_path(pid)
            self.refresh_game_paths()
            show_toast(self.root, "Path removed", "success")

    def build_settings_tab(self, parent):
        frame = tk.Frame(parent, padx=20, pady=20, bg=self.BG_CARD)
        frame.pack(fill="both", expand=True)
        lbl_style = {"fg": self.TEXT_PRIMARY, "bg": self.BG_CARD, "font": ("Segoe UI", 11, "bold")}
        entry_style = {"font": ("Segoe UI", 11), "bg": "white", "fg": self.TEXT_PRIMARY, "relief": "flat", "bd": 0, "highlightthickness": 1, "highlightbackground": self.BORDER_COLOR, "highlightcolor": self.ACCENT}
        tk.Label(frame, text="Seconds per pulse:", **lbl_style).grid(row=0, column=0, sticky="e", pady=12, padx=(0, 15))
        self.sp_entry = tk.Entry(frame, width=12, **entry_style)
        self.sp_entry.grid(row=0, column=1, sticky="w", pady=12, ipady=5)
        self.sp_entry.insert(0, str(db.get_seconds_per_pulse()))
        self.coin_info_label_admin = tk.Label(frame, text="", fg=self.TEXT_SECONDARY, bg=self.BG_CARD, justify="left", font=("Segoe UI", 10))
        self.coin_info_label_admin.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 15), padx=(0, 15))
        self.update_coin_info_display()
        tk.Label(frame, text="Bonus rules:", fg=self.TEXT_PRIMARY, bg=self.BG_CARD, font=("Segoe UI", 12, "bold")).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 5))
        bonus_frame = tk.Frame(frame, bg=self.BG_CARD)
        bonus_frame.grid(row=3, column=0, columnspan=2, sticky="nsew")
        frame.grid_rowconfigure(3, weight=1); frame.grid_columnconfigure(0, weight=1)
        self.bonus_tree = ttk.Treeview(bonus_frame, columns=("paid", "gift"), show="headings", height=6)
        self.bonus_tree.heading("paid", text="Αγορασμένες ώρες"); self.bonus_tree.heading("gift", text="Ώρες δώρο")
        self.bonus_tree.grid(row=0, column=0, sticky="nsew")
        ttk.Scrollbar(bonus_frame, orient="vertical", command=self.bonus_tree.yview).grid(row=0, column=1, sticky="ns")
        bonus_frame.grid_rowconfigure(0, weight=1); bonus_frame.grid_columnconfigure(0, weight=1)
        self.refresh_bonus_tree()
        btn_frame = tk.Frame(frame, bg=self.BG_CARD)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=(10, 0), sticky="w")
        make_btn = lambda t, c: tk.Button(btn_frame, text=t, command=c, font=("Segoe UI", 10, "bold"), bg=self.BG_BUTTON, fg="white", activebackground=self.BG_BUTTON_HOVER, activeforeground="white", relief="flat", padx=12, pady=6, cursor="hand2")
        make_btn("Προσθήκη bonus", self.admin_add_bonus_rule).pack(side="left", padx=(0, 8))
        make_btn("Επεξεργασία", self.admin_edit_bonus_rule).pack(side="left", padx=(0, 8))
        make_btn("Διαγραφή", self.admin_delete_bonus_rule).pack(side="left", padx=(0, 8))
        bottom_btn_frame = tk.Frame(frame, bg=self.BG_CARD)
        bottom_btn_frame.grid(row=5, column=0, columnspan=2, pady=20)
        tk.Button(bottom_btn_frame, text="Save", command=self.save_settings, font=("Segoe UI", 11, "bold"), bg=self.BG_BUTTON, fg="white", padx=25, pady=10).pack(side="left", padx=5)
        tk.Button(bottom_btn_frame, text="Backup DB", command=self.backup_database, font=("Segoe UI", 11, "bold"), bg=self.BG_BUTTON_ACCENT, fg="white", padx=25, pady=10).pack(side="left", padx=5)
        self.backup_label = tk.Label(frame, text="", fg=self.TEXT_LIGHT, bg=self.BG_CARD, font=("Segoe UI", 9))
        self.backup_label.grid(row=6, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def refresh_bonus_tree(self):
        if not self.bonus_tree: return
        for item in self.bonus_tree.get_children(): self.bonus_tree.delete(item)
        self.bonus_index = {}
        for rule_id, th, bon in db.get_bonus_rules():
            iid = self.bonus_tree.insert("", "end", values=(f"{th/3600.0:.2f}", f"{bon/3600.0:.2f}"))
            self.bonus_index[iid] = rule_id

    def admin_add_bonus_rule(self):
        p = simpledialog.askfloat("Νέο bonus", "Αγορασμένες ώρες:", minvalue=0.0, parent=self.root)
        if not p: return
        g = simpledialog.askfloat("Νέο bonus", "Ώρες δώρο:", minvalue=0.0, parent=self.root)
        if not g: return
        db.add_bonus_rule(int(p*3600), int(g*3600))
        show_toast(self.root, "Bonus rule προστέθηκε.", "success")
        self.refresh_bonus_tree()

    def admin_edit_bonus_rule(self):
        sel = self.bonus_tree.selection()
        if not sel: return
        rid = self.bonus_index.get(sel[0])
        p = simpledialog.askfloat("Edit", "Αγορασμένες ώρες:", minvalue=0.0, parent=self.root)
        if not p: return
        g = simpledialog.askfloat("Edit", "Ώρες δώρο:", minvalue=0.0, parent=self.root)
        if not g: return
        db.update_bonus_rule(rid, int(p*3600), int(g*3600))
        self.refresh_bonus_tree()

    def admin_delete_bonus_rule(self):
        sel = self.bonus_tree.selection()
        if not sel: return
        if messagebox.askyesno("Confirm", "Delete rule?"):
            db.delete_bonus_rule(self.bonus_index.get(sel[0]))
            self.refresh_bonus_tree()

    def build_users_tab(self, parent):
        container = tk.Frame(parent, padx=15, pady=15, bg=self.BG_CARD)
        container.pack(fill="both", expand=True)
        container.grid_rowconfigure(1, weight=1); container.grid_columnconfigure(0, weight=1)
        search_frame = tk.Frame(container, bg=self.BG_CARD)
        search_frame.grid(row=0, column=0, columnspan=3, sticky="we", pady=(0, 10))
        tk.Label(search_frame, text="Αναζήτηση:", fg=self.TEXT_PRIMARY, bg=self.BG_CARD).pack(side="left")
        self.search_var = tk.StringVar()
        tk.Entry(search_frame, textvariable=self.search_var).pack(side="left", padx=5)
        self.search_var.trace_add("write", self.on_search_change)
        self.users_tree = ttk.Treeview(container, columns=("username", "role", "remaining", "purchased"), show="headings", height=10)
        for c in ("username", "role", "remaining", "purchased"): self.users_tree.heading(c, text=c.capitalize())
        self.users_tree.grid(row=1, column=0, rowspan=7, sticky="nsew", padx=(0, 8))
        ttk.Scrollbar(container, orient="vertical", command=self.users_tree.yview).grid(row=1, column=1, rowspan=7, sticky="ns")
        btns = [("Προσθήκη χρήστη", self.admin_add_user), ("Προσθήκη pulses", self.admin_add_pulses), ("Ορισμός χρόνου", self.admin_set_time), 
                ("Toggle Admin", self.admin_toggle_admin), ("Reset password", self.admin_reset_password), ("Ιστορικό", self.admin_show_history), ("Διαγραφή", self.admin_delete_user)]
        for i, (txt, cmd) in enumerate(btns):
            tk.Button(container, text=txt, command=cmd, width=18, bg=self.BG_BUTTON, fg="white").grid(row=1+i, column=2, pady=2, sticky="ew")
        self.refresh_users_tree("")
        
        # Context Menu
        self.user_menu = tk.Menu(self.root, tearoff=0, bg="white", fg=self.TEXT_PRIMARY, font=("Segoe UI", 10))
        self.user_menu.add_command(label="➕ Προσθήκη Pulses", command=self.admin_add_pulses)
        self.user_menu.add_command(label="⏲ Ορισμός Χρόνου", command=self.admin_set_time)
        self.user_menu.add_separator()
        self.user_menu.add_command(label="🔑 Reset Password", command=self.admin_reset_password)
        self.user_menu.add_command(label="🛡 Toggle Admin", command=self.admin_toggle_admin)
        self.user_menu.add_separator()
        self.user_menu.add_command(label="📜 Ιστορικό", command=self.admin_show_history)
        self.user_menu.add_command(label="❌ Διαγραφή", command=self.admin_delete_user)
        
        def show_user_menu(event):
            item = self.users_tree.identify_row(event.y)
            if item:
                self.users_tree.selection_set(item)
                self.user_menu.post(event.x_root, event.y_root)
        
        self.users_tree.bind("<Button-3>", show_user_menu)
        self.schedule_user_refresh()

    def schedule_user_refresh(self):
        if self.users_tree and self.users_tree.winfo_exists():
            # Only refresh if NOT searching (to avoid overwriting user input results)
            # Or refresh but keep filter. Let's keep filter.
            current_filter = self.search_var.get()
            self.refresh_users_tree(current_filter)
        self.root.after(5000, self.schedule_user_refresh)

    def refresh_users_tree(self, filter_text):
        if not self.users_tree: return
        
        # Save current selection
        selected_uid = None
        sel = self.users_tree.selection()
        if sel:
            selected_uid = self.users_index.get(sel[0])
            
        for item in self.users_tree.get_children(): self.users_tree.delete(item)
        self.users_index = {}
        filter_text = (filter_text or "").lower()
        
        for uid, uname, is_admin, rem, pur in db.list_users():
            if filter_text and filter_text not in uname.lower(): continue
            h, m, s = self.seconds_to_hms(rem)
            iid = self.users_tree.insert("", "end", values=(uname, "Admin" if is_admin else "User", f"{h:02}:{m:02}:{s:02}", f"{pur/3600.0:.1f} h"))
            self.users_index[iid] = uid
            
            # Restore selection
            if selected_uid and selected_uid == uid:
                self.users_tree.selection_set(iid)
                self.users_tree.focus(iid)

    def get_selected_user(self):
        sel = self.users_tree.selection()
        if not sel: return None
        return self.users_index.get(sel[0]), sel[0]

    def admin_add_user(self):
        u = simpledialog.askstring("New User", "Username:", parent=self.root)
        if not u: return
        p = simpledialog.askstring("New User", "Password:", show="*", parent=self.root)
        if not p: return
        if len(p)<4: show_toast(self.root, "Password too short", "warning"); return
        
        self.show_loading("Adding User...")
        def task():
            ok, err = db.add_user(u.strip(), p.strip())
            self.root.after(0, lambda: self.hide_loading())
            if ok:
                self.root.after(0, lambda: [show_toast(self.root, "User created", "success"), self.refresh_users_tree(self.search_var.get())])
            else:
                self.root.after(0, lambda: show_toast(self.root, f"Error: {err}", "error"))
        threading.Thread(target=task, daemon=True).start()

    def admin_add_pulses(self):
        res = self.get_selected_user()
        if not res: return
        p = simpledialog.askinteger("Add pulses", "Pulses:", minvalue=1, parent=self.root)
        if not p: return
        
        self.show_loading("Adding Pulses...")
        def task():
            db.add_pulses_to_user(res[0], p)
            self.root.after(0, lambda: [self.hide_loading(), show_toast(self.root, "Pulses added", "success"), self.refresh_users_tree(self.search_var.get())])
        threading.Thread(target=task, daemon=True).start()

    def admin_set_time(self):
        res = self.get_selected_user()
        if not res: return
        m = simpledialog.askinteger("Set Time", "Minutes:", minvalue=0, parent=self.root)
        if m is None: return
        
        self.show_loading("Setting Time...")
        def task():
            db.update_remaining_seconds(res[0], m*60)
            self.root.after(0, lambda: [self.hide_loading(), show_toast(self.root, "Time updated", "success"), self.refresh_users_tree(self.search_var.get())])
        threading.Thread(target=task, daemon=True).start()

    def admin_toggle_admin(self):
        res = self.get_selected_user()
        if not res: return
        role = self.users_tree.item(res[1], "values")[1]
        
        self.show_loading("Updating Role...")
        def task():
            db.set_user_admin_flag(res[0], role != "Admin")
            self.root.after(0, lambda: [self.hide_loading(), show_toast(self.root, "Role updated", "success"), self.refresh_users_tree(self.search_var.get())])
        threading.Thread(target=task, daemon=True).start()

    def admin_reset_password(self):
        res = self.get_selected_user()
        if not res: return
        p = simpledialog.askstring("Reset", "New Password:", show="*", parent=self.root)
        if not p: return
        
        self.show_loading("Resetting Password...")
        def task():
            db.update_user_password(res[0], p.strip())
            self.root.after(0, lambda: [self.hide_loading(), show_toast(self.root, "Password updated", "success")])
        threading.Thread(target=task, daemon=True).start()

    def admin_show_history(self):
        res = self.get_selected_user()
        if not res: return
        
        # History is read-only and fast, but we can thread it if strictly needed.
        # For now, it opens a window. Let's keep it on main thread or just fetch data in thread.
        # Fetching data in thread is better.
        self.show_loading("Fetching History...")
        def task():
            data = db.get_user_history(res[0])
            self.root.after(0, lambda: [self.hide_loading(), self._open_history_window(data)])
        threading.Thread(target=task, daemon=True).start()
    
    def _open_history_window(self, data):
        win = tk.Toplevel(self.root); win.geometry("520x380"); win.title("History")
        tree = ttk.Treeview(win, columns=("date", "pulses", "seconds"), show="headings")
        for c in ("date", "pulses", "seconds"): tree.heading(c, text=c.capitalize())
        tree.pack(fill="both", expand=True)
        for p, s, c in data: tree.insert("", "end", values=(c, p, s))

    def admin_delete_user(self):
        res = self.get_selected_user()
        if not res: return
        if self.users_tree.item(res[1], "values")[0] == "admin": 
            show_toast(self.root, "Cannot delete main admin", "error")
            return
        if not messagebox.askyesno("Confirm", "Delete user?"): return
        
        self.show_loading("Deleting User...")
        def task():
            db.delete_user_by_id(res[0])
            self.root.after(0, lambda: [self.hide_loading(), show_toast(self.root, "User deleted", "success"), self.refresh_users_tree(self.search_var.get())])
        threading.Thread(target=task, daemon=True).start()

    def build_stations_tab(self, parent):
        container = tk.Frame(parent, padx=15, pady=15, bg=self.BG_CARD)
        container.pack(fill="both", expand=True)
        self.stations_tree = ttk.Treeview(container, columns=("station", "username", "remaining", "status", "last"), show="headings", height=12)
        for c in ("station", "username", "remaining", "status", "last"): self.stations_tree.heading(c, text=c.capitalize())
        self.stations_tree.pack(fill="both", expand=True)
        
        # Station Context Menu
        self.station_menu = tk.Menu(self.root, tearoff=0, bg="white", fg=self.TEXT_PRIMARY, font=("Segoe UI", 10))
        self.station_menu.add_command(label="⛔ Force Logout", command=self.admin_force_logout)
        
        def show_station_menu(event):
            item = self.stations_tree.identify_row(event.y)
            if item:
                self.stations_tree.selection_set(item)
                self.station_menu.post(event.x_root, event.y_root)
        
        self.stations_tree.bind("<Button-3>", show_station_menu)
        
        self.schedule_station_refresh()

    def admin_force_logout(self):
        sel = self.stations_tree.selection()
        if not sel: return
        # station name is in column 0
        station = self.stations_tree.item(sel[0], "values")[0]
        if messagebox.askyesno("Confirm", f"Force logout station {station}?"):
            # Update DB remaining seconds to 0 -> API will catch it?
            # Or remove from ACTIVE_SESSIONS?
            # Best way: set remaining to 0 in DB and API will logout on next heartbeat,
            # BUT we also want immediate effect if possible.
            # Let's find the user and set time to 0.
            
            # Find user based on station... simplified method:
            # We don't have easy immediate logout without API cooperation, 
            # but updating specific user logic is needed.
            # For now, let's just clear the session from memory so it shows offline.
            with ACTIVE_LOCK:
                if station in ACTIVE_SESSIONS:
                    del ACTIVE_SESSIONS[station]
            show_toast(self.root, "Station session cleared (User must log in again)", "success")
            self.schedule_station_refresh()

    def schedule_station_refresh(self):
        if not self.stations_tree or not self.stations_tree.winfo_exists(): return
        
        # SMART UPDATE: Update existing rows instead of clearing everything
        now = time.time()
        with ACTIVE_LOCK: items = list(ACTIVE_SESSIONS.items())
        
        # Get current items in tree
        tree_items = self.stations_tree.get_children()
        existing_stations = {}
        for item in tree_items:
            vals = self.stations_tree.item(item, "values")
            existing_stations[vals[0]] = item # Map station name -> item id

        active_station_names = set()
        
        for st, data in items:
            active_station_names.add(st)
            rem = data.get("remaining_seconds", 0)
            last = data.get("last_update", 0)
            h, m, s = self.seconds_to_hms(rem)
            status = "Time over" if rem <= 0 else "Online"
            if now - last > 40: status += " (old)"
            last_seen = datetime.fromtimestamp(last).strftime("%H:%M:%S")
            
            new_values = (st, data.get("username"), f"{h:02}:{m:02}:{s:02}", status, last_seen)
            
            if st in existing_stations:
                # Update if changed
                current_values = self.stations_tree.item(existing_stations[st], "values")
                if current_values != new_values:
                    self.stations_tree.item(existing_stations[st], values=new_values)
            else:
                # Insert new
                self.stations_tree.insert("", "end", values=new_values)

        # Remove stations that are no longer active
        for st_name, item_id in existing_stations.items():
            if st_name not in active_station_names:
                self.stations_tree.delete(item_id)
                
        self.root.after(1000, self.schedule_station_refresh) # Update more frequently (1s) since it's efficient now

    def build_stats_tab(self, parent):
        frame = tk.Frame(parent, padx=20, pady=20, bg=self.BG_CARD)
        frame.pack(fill="both", expand=True)

        # Τίτλος
        tk.Label(
            frame, 
            text="Οικονομική Αναφορά & Στατιστικά", 
            fg=self.TEXT_PRIMARY, 
            bg=self.BG_CARD, 
            font=("Segoe UI", 14, "bold")
        ).pack(anchor="w", pady=(0, 20))

        # Φίλτρα Ημερομηνίας
        filt_frame = tk.LabelFrame(frame, text="Επιλογή Περιόδου", padx=15, pady=15, bg=self.BG_CARD, fg=self.TEXT_SECONDARY, font=("Segoe UI", 10, "bold"))
        filt_frame.pack(anchor="w", fill="x", pady=(0, 20))

        # --- Από ---
        tk.Label(filt_frame, text="Από:", fg=self.TEXT_PRIMARY, bg=self.BG_CARD, font=("Segoe UI", 11)).pack(side="left")
        self.report_from_entry = tk.Entry(filt_frame, width=12, font=("Segoe UI", 11))
        self.report_from_entry.pack(side="left", padx=(5, 0))
        
        tk.Button(
            filt_frame, 
            text="📅", 
            command=lambda: self.open_datepicker(self.report_from_entry),
            bg=self.BG_BUTTON_ACCENT, fg="white", relief="flat", padx=8, pady=2
        ).pack(side="left", padx=(2, 20))

        # --- Έως ---
        tk.Label(filt_frame, text="Έως:", fg=self.TEXT_PRIMARY, bg=self.BG_CARD, font=("Segoe UI", 11)).pack(side="left")
        self.report_to_entry = tk.Entry(filt_frame, width=12, font=("Segoe UI", 11))
        self.report_to_entry.pack(side="left", padx=(5, 0))
        
        tk.Button(
            filt_frame, 
            text="📅", 
            command=lambda: self.open_datepicker(self.report_to_entry),
            bg=self.BG_BUTTON_ACCENT, fg="white", relief="flat", padx=8, pady=2
        ).pack(side="left", padx=(2, 30))

        # --- ΜΕΓΑΛΟ ΚΟΥΜΠΙ ΥΠΟΛΟΓΙΣΜΟΥ ---
        tk.Button(
            filt_frame,
            text="Υπολογισμός Εσόδων",
            command=self.calculate_coin_report,
            font=("Segoe UI", 11, "bold"),
            bg=self.BG_BUTTON,
            fg="white",
            activebackground=self.BG_BUTTON_HOVER,
            activeforeground="white",
            relief="flat",
            padx=25,     # Πλάτος
            pady=8,      # Ύψος
            cursor="hand2"
        ).pack(side="left")

        # Αποτελέσματα
        self.report_result_label = tk.Label(
            frame,
            text="Επιλέξτε ημερομηνίες και πατήστε Υπολογισμός.",
            fg=self.TEXT_PRIMARY,
            bg=self.BG_CARD,
            font=("Segoe UI", 12),
            justify="left",
            padx=10, pady=10,
            relief="groove",
            bd=1
        )
        self.report_result_label.pack(fill="x", pady=10)

    def open_datepicker(self, target_entry):
        """
        Ανοίγει calendar popup που μένει ΜΠΡΟΣΤΑ από το κεντρικό παράθυρο.
        """
        win = tk.Toplevel(self.root)
        win.title("Επιλογή ημερομηνίας")
        win.geometry("350x300")
        win.configure(bg=self.BG_MAIN)
        
        # --- ΤΟ FIX ΓΙΑ ΝΑ ΜΕΝΕΙ ΜΠΡΟΣΤΑ ---
        win.transient(self.root)        # Το συνδέει με το κεντρικό
        win.attributes("-topmost", True) # Το αναγκάζει να είναι πάντα πάνω
        win.lift()                      # Το φέρνει στην κορυφή
        win.focus_force()               # Του δίνει το πληκτρολόγιο
        win.grab_set()                  # Απαγορεύει κλικ στο από πίσω παράθυρο μέχρι να κλείσει αυτό
        # -----------------------------------

        # Στυλιζάρισμα του Calendar για να ταιριάζει με το θέμα
        cal = Calendar(
            win,
            selectmode="day",
            date_pattern="yyyy-mm-dd",
            background=self.ACCENT,
            foreground='white',
            headersbackground=self.BG_SECONDARY,
            headersforeground=self.TEXT_PRIMARY,
            bordercolor=self.BORDER_COLOR,
            normalbackground='white',
            normalforeground=self.TEXT_PRIMARY,
            weekendbackground='white',
            weekendforeground=self.TEXT_PRIMARY,
            selectbackground=self.BG_BUTTON,
            selectforeground='white'
        )
        cal.pack(padx=20, pady=20, expand=True, fill="both")

        def set_date():
            date_str = cal.get_date()
            target_entry.delete(0, tk.END)
            target_entry.insert(0, date_str)
            win.destroy()

        # Μεγάλο κουμπί ΟΚ
        tk.Button(
            win,
            text="Επιλογή",
            command=set_date,
            font=("Segoe UI", 11, "bold"),
            bg=self.BG_BUTTON,
            fg="white",
            activebackground=self.BG_BUTTON_HOVER,
            activeforeground="white",
            relief="flat",
            padx=20,
            pady=10,
            cursor="hand2",
        ).pack(pady=(0, 20))

    def calculate_coin_report(self):
        """
        Υπολογίζει τα έσοδα βάσει των ημερομηνιών που έβαλε ο χρήστης.
        """
        # 1. Παίρνουμε τις ημερομηνίες από τα πεδία
        from_str = self.report_from_entry.get().strip()
        to_str = self.report_to_entry.get().strip()

        # Έλεγχος αν είναι κενά
        if not from_str or not to_str:
            messagebox.showwarning("Προσοχή", "Παρακαλώ επιλέξτε και τις δύο ημερομηνίες.", parent=self.root)
            return

        # 2. Φτιάχνουμε το εύρος ώρας (από αρχή της πρώτης μέρας μέχρι τέλος της τελευταίας)
        start_date = from_str + " 00:00:00"
        end_date = to_str + " 23:59:59"

        try:
            # 3. Σύνδεση με βάση και υπολογισμός
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            
            # Αθροίζουμε τα pulses για αυτό το διάστημα
            c.execute(
                """
                SELECT COALESCE(SUM(pulses), 0)
                FROM coin_pulses
                WHERE created_at BETWEEN ? AND ?
                """,
                (start_date, end_date),
            )
            row = c.fetchone()
            conn.close()

            total_pulses = row[0] if row else 0
            
            # 4. Υπολογισμός σε Ευρώ (1 pulse = 0.50€)
            # Αν έχεις άλλη τιμή, άλλαξε το 0.50
            total_euros = total_pulses * 0.50

            # 5. Εμφάνιση αποτελέσματος στο Label
            result_text = (
                f"📊 ΑΠΟΤΕΛΕΣΜΑΤΑ ({from_str} έως {to_str})\n"
                f"----------------------------------------\n"
                f"Σύνολο Παλμών:  {total_pulses}\n"
                f"Συνολικά Έσοδα: {total_euros:.2f} €"
            )
            
            # Ενημερώνουμε το Label που φτιάξαμε πριν
            self.report_result_label.config(text=result_text, fg="#2E7D32") # Πράσινο χρώμα για τα λεφτά

        except Exception as e:
            print(f"Error calculating report: {e}")
            self.report_result_label.config(text=f"Σφάλμα κατά τον υπολογισμό: {e}", fg="red")
    
    def build_sessions_tab(self, parent):
        container = tk.Frame(parent, padx=15, pady=15, bg=self.BG_CARD); container.pack(fill="both", expand=True)
        tk.Button(container, text="Export CSV", command=self.export_session_history).pack()
        self.sessions_tree = ttk.Treeview(container, columns=("u", "s", "a", "in", "out", "dur", "rem"), show="headings")
        self.sessions_tree.pack(fill="both", expand=True)
        for s in db.get_session_history(limit=500):
            self.sessions_tree.insert("", "end", values=(s[2], s[3], s[4], s[5], s[6], s[7], s[8]))

    def export_session_history(self):
        fn = filedialog.asksaveasfilename(defaultextension=".csv")
        if fn:
            data = [["ID", "UID", "User", "Station", "Action", "In", "Out", "Dur", "Rem", "Created"]] + list(db.get_session_history(10000))
            export_to_csv(data, fn)

    def save_settings(self):
        try: db.set_seconds_per_pulse(int(self.sp_entry.get())); show_toast(self.root, "Saved", "success")
        except: pass

    def backup_database(self):
        self.show_loading("Backing up...")
        threading.Thread(target=self._do_backup, daemon=True).start()
    
    def _do_backup(self):
        try:
            bd = CONFIG.get("backup", {}).get("directory", "backups")
            os.makedirs(bd, exist_ok=True)
            dst = os.path.join(bd, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
            shutil.copy2(DB_FILE, dst)
            self.root.after(0, lambda: [self.hide_loading(), show_toast(self.root, "Backup OK", "success")])
        except: self.root.after(0, self.hide_loading)

    def start_auto_backup(self):
        if CONFIG.get("backup", {}).get("enabled", True):
            threading.Thread(target=self._auto_backup_loop, daemon=True).start()

    def _auto_backup_loop(self):
        while True:
            time.sleep(CONFIG.get("backup", {}).get("interval_hours", 24) * 3600)
            self.backup_database()