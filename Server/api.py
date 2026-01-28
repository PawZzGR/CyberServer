import json
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from utils import verify_password
import database as db
from common import logger, ACTIVE_SESSIONS, ACTIVE_LOCK, SERVER_HOST, SERVER_PORT

class RequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_GET(self):
        if self.path.startswith("/api/ping"):
            self._send_json(200, {"status": "ok"})
        elif self.path.startswith("/api/game_paths"):
            self.handle_game_paths()
        elif self.path.startswith("/api/file_sync/source"):
            self.handle_get_sync_source()
        elif self.path.startswith("/api/file_sync/folders"):
            self.handle_get_sync_folders()
        elif self.path.startswith("/api/file_sync/index"):
            self.handle_get_file_index()
        else:
            self.send_error(404, "Not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            body = {}

        if self.path in ("/api/login", "/login"):
            self.handle_login(body)
        elif self.path in ("/api/update_remaining", "/update_remaining"):
            self.handle_update_remaining(body)
        elif self.path == "/api/file_sync/register_source":
            self.handle_register_sync_source(body)
        elif self.path == "/api/file_sync/add_folder":
            self.handle_add_sync_folder(body)
        elif self.path == "/api/file_sync/remove_folder":
            self.handle_remove_sync_folder(body)
        elif self.path == "/api/file_sync/update_index":
            self.handle_update_file_index(body)
        else:
            self._send_json(404, {"status": "error", "reason": "not_found"})

    def handle_game_paths(self):
        paths = [p[1] for p in db.get_game_paths()]
        self._send_json(200, {"status": "ok", "paths": paths})

    def handle_login(self, data):
        username = data.get("username", "")
        password = data.get("password", "")
        station = data.get("station", "Unknown")

        user = db.get_user(username)
        if not user or not verify_password(password, user["password"]):
            logger.warning(f"Failed login attempt for {username} from {station}")
            self._send_json(200, {"status": "error", "reason": "not_found"})
            return
        if user["remaining_seconds"] <= 0:
            logger.info(f"Login denied for {username}: no time remaining")
            self._send_json(200, {"status": "error", "reason": "no_time"})
            return

        login_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with ACTIVE_LOCK:
            ACTIVE_SESSIONS[station] = {
                "username": user["username"],
                "remaining_seconds": user["remaining_seconds"],
                "last_update": time.time(),
                "login_time": login_time,
            }

        db.log_session(user["id"], user["username"], station, "login", login_time=login_time, remaining_seconds=user["remaining_seconds"])
        logger.info(f"User {username} logged in on {station}")
        
        self._send_json(200, {"status": "ok", "remaining_seconds": user["remaining_seconds"]})

    def handle_update_remaining(self, data):
        username = data.get("username", "")
        password = data.get("password", "")
        station = data.get("station", "Unknown")
        remaining_seconds = data.get("remaining_seconds", None)

        if remaining_seconds is None:
            self._send_json(400, {"status": "error", "reason": "missing_remaining"})
            return

        user = db.get_user(username)
        if not user or not verify_password(password, user["password"]):
            self._send_json(200, {"status": "error", "reason": "not_found"})
            return

        value = int(remaining_seconds)
        if value < 0: value = 0
        
        with ACTIVE_LOCK:
            entry = ACTIVE_SESSIONS.get(station)
            was_active = entry is not None and entry.get("remaining_seconds", 0) > 0
            
        if was_active and value == 0:
            logout_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            login_time = entry.get("login_time") if entry else None
            duration = None
            if login_time:
                try:
                    duration = int((datetime.strptime(logout_time, "%Y-%m-%d %H:%M:%S") - datetime.strptime(login_time, "%Y-%m-%d %H:%M:%S")).total_seconds())
                except: pass
            
            db.log_session(user["id"], user["username"], station, "logout", login_time=login_time, logout_time=logout_time, duration_seconds=duration, remaining_seconds=value)
            logger.info(f"User {username} logged out from {station}")

        db.update_remaining_seconds(user["id"], value)

        with ACTIVE_LOCK:
            entry = ACTIVE_SESSIONS.get(station)
            if entry is None:
                ACTIVE_SESSIONS[station] = {"username": user["username"], "remaining_seconds": value, "last_update": time.time()}
            else:
                entry["username"] = user["username"]
                entry["remaining_seconds"] = value
                entry["last_update"] = time.time()

        self._send_json(200, {"status": "ok"})

    def log_message(self, format, *args):
        return

    def _check_auth(self):
        """Check for valid admin credentials in headers."""
        username = self.headers.get("X-Auth-User")
        password = self.headers.get("X-Auth-Pass")
        
        if not username or not password:
            return False
            
        if not user:
            return False
            
        return verify_password(password, user["password"])

    # --- FILE SYNC HANDLERS ---
    
    def handle_get_sync_source(self):
        source = db.get_file_sync_source()
        if source:
            self._send_json(200, {"status": "ok", "source": source})
        else:
            self._send_json(200, {"status": "ok", "source": None})
    
    def handle_get_sync_folders(self):
        folders = db.get_sync_folders()
        self._send_json(200, {"status": "ok", "folders": [{"id": f[0], "path": f[1]} for f in folders]})
    
    def handle_get_file_index(self):
        index = db.get_file_index()
        summary = db.get_file_index_summary()
        self._send_json(200, {"status": "ok", "files": index, "summary": summary})
    
    def handle_register_sync_source(self, data):
        # Allow registration without login (machine-to-machine)
        admin_ip = data.get("admin_ip", "")
        admin_port = data.get("admin_port", 5001)
        if not admin_ip:
            self._send_json(400, {"status": "error", "reason": "missing_admin_ip"})
            return
        db.register_file_sync_source(admin_ip, admin_port)
        logger.info(f"File sync source registered: {admin_ip}:{admin_port}")
        self._send_json(200, {"status": "ok"})
    
    def handle_add_sync_folder(self, data):
        # Allow folder adding without login
        folder_path = data.get("folder_path", "")
        if not folder_path:
            self._send_json(400, {"status": "error", "reason": "missing_folder_path"})
            return
        success, folder_id = db.add_sync_folder(folder_path)
        # Return folder_id whether it's new or existing
        self._send_json(200, {"status": "ok", "folder_id": folder_id, "created": success})
    
    def handle_remove_sync_folder(self, data):
        # Allow removal without login
        folder_id = data.get("folder_id")
        if folder_id is None:
            self._send_json(400, {"status": "error", "reason": "missing_folder_id"})
            return
        db.remove_sync_folder(int(folder_id))
        self._send_json(200, {"status": "ok"})
    
    def handle_update_file_index(self, data):
        # Allow updates without login
        folder_id = data.get("folder_id")
        files = data.get("files", [])
        if folder_id is None:
            self._send_json(400, {"status": "error", "reason": "missing_folder_id"})
            return
        added, removed = db.update_file_index(int(folder_id), files)
        self._send_json(200, {"status": "ok", "added": added, "removed": removed})

def run_http_server():
    httpd = HTTPServer((SERVER_HOST, SERVER_PORT), RequestHandler)
    print(f"HTTP API listening on {SERVER_HOST}:{SERVER_PORT}")
    httpd.serve_forever()