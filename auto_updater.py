"""
Auto-Updater for CyberServer V2 components.

Checks GitHub Releases for a newer version and self-updates.
Works for all 3 executables: CyberServer, CyberClient_Admin, CyberClient_User.
"""

import os
import sys
import json
import time
import logging
import subprocess
from urllib import request, error

VERSION = "2.5.0"
GITHUB_REPO = "PawZzGR/CyberServer"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
UPDATE_CHECK_TIMEOUT = 10  # seconds


def get_exe_path():
    """Get the path of the currently running executable."""
    if getattr(sys, 'frozen', False):
        return sys.executable
    return None


def get_exe_name():
    """Get the filename of the current executable (e.g. 'CyberServer.exe')."""
    exe_path = get_exe_path()
    if exe_path:
        return os.path.basename(exe_path)
    return None


def parse_version(version_str):
    """Parse version string like '2.4.0' or 'v2.4.0' into a tuple (2, 4, 0)."""
    try:
        clean = version_str.strip().lstrip('v')
        return tuple(int(x) for x in clean.split('.'))
    except Exception:
        return (0, 0, 0)


def _cleanup_old_files():
    """Remove leftover .old and .new files from previous updates."""
    exe_path = get_exe_path()
    if not exe_path:
        return
    
    for suffix in ['.old', '.new']:
        path = exe_path + suffix
        if os.path.exists(path):
            try:
                os.remove(path)
                logging.info(f"[AUTO-UPDATE] Cleaned up {os.path.basename(path)}")
            except Exception:
                pass


def check_for_updates():
    """Check GitHub for a newer release and auto-update if found.
    
    This function should be called once at program startup.
    If an update is found, it downloads the new EXE, replaces
    the current one, and restarts the program. The calling code
    will NOT continue after a successful update.
    
    If no update is available or the check fails, this function
    returns silently and the program continues normally.
    """
    exe_path = get_exe_path()
    if not exe_path:
        # Running as a Python script, not a compiled EXE — skip
        return
    
    exe_name = get_exe_name()
    
    # Always clean up leftover files from previous updates
    _cleanup_old_files()
    
    try:
        logging.info(f"[AUTO-UPDATE] Checking for updates... (current: v{VERSION})")
        
        # Query GitHub API for latest release
        req = request.Request(
            GITHUB_API_URL,
            headers={"User-Agent": "CyberServer-AutoUpdater"}
        )
        with request.urlopen(req, timeout=UPDATE_CHECK_TIMEOUT) as resp:
            release = json.loads(resp.read().decode())
        
        remote_version = release.get("tag_name", "0.0.0")
        remote_tuple = parse_version(remote_version)
        local_tuple = parse_version(VERSION)
        
        if remote_tuple <= local_tuple:
            logging.info(f"[AUTO-UPDATE] Up to date (v{VERSION})")
            return
        
        logging.info(f"[AUTO-UPDATE] New version found: {remote_version} (current: v{VERSION})")
        
        # Find the matching EXE asset in the release
        assets = release.get("assets", [])
        download_url = None
        asset_size = 0
        
        for asset in assets:
            if asset.get("name") == exe_name:
                download_url = asset.get("browser_download_url")
                asset_size = asset.get("size", 0)
                break
        
        if not download_url:
            logging.warning(f"[AUTO-UPDATE] No asset '{exe_name}' in release {remote_version}. Skipping.")
            return
        
        # Download the new EXE
        new_path = exe_path + ".new"
        logging.info(f"[AUTO-UPDATE] Downloading {exe_name} ({asset_size / (1024*1024):.1f} MB)...")
        
        req = request.Request(
            download_url,
            headers={"User-Agent": "CyberServer-AutoUpdater"}
        )
        with request.urlopen(req, timeout=300) as resp:
            with open(new_path, 'wb') as f:
                bytes_downloaded = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    bytes_downloaded += len(chunk)
        
        # Verify download size
        if asset_size > 0 and bytes_downloaded != asset_size:
            logging.error(f"[AUTO-UPDATE] Download size mismatch: got {bytes_downloaded}, expected {asset_size}")
            os.remove(new_path)
            return
        
        logging.info(f"[AUTO-UPDATE] Downloaded successfully ({bytes_downloaded / (1024*1024):.1f} MB)")
        
        # Replace: current → .old, .new → current
        old_path = exe_path + ".old"
        
        # Remove any existing .old file first
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass
        
        os.rename(exe_path, old_path)
        os.rename(new_path, exe_path)
        
        logging.info(f"[AUTO-UPDATE] Updated {exe_name}: v{VERSION} → {remote_version}. Restarting...")
        
        # Restart the program
        subprocess.Popen([exe_path] + sys.argv[1:])
        sys.exit(0)
        
    except error.URLError as e:
        logging.info(f"[AUTO-UPDATE] Cannot reach GitHub (offline?): {e}")
    except Exception as e:
        logging.warning(f"[AUTO-UPDATE] Check failed: {e}")
        # Clean up partial download
        try:
            new_path = exe_path + ".new"
            if os.path.exists(new_path):
                os.remove(new_path)
        except Exception:
            pass
