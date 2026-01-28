import threading
import tkinter as tk
import database as db
from api import run_http_server
from gui import ServerApp

def main():
    # 1. Initialize Database
    db.init_db()

    # 2. Start HTTP API in a separate thread
    api_thread = threading.Thread(target=run_http_server, daemon=True)
    api_thread.start()

    # 3. Start GUI
    root = tk.Tk()
    app = ServerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()