# CyberServer V2

Internet Café / Gaming Center management system with centralized time tracking, account management, and game synchronization.

## Components

| Component | Folder | Description |
|-----------|--------|-------------|
| **Server** | `Server/` | Central server — manages accounts, tracks time, handles logins |
| **AdminClient** | `AdminClient/` | Runs on the admin PC — manage accounts, add time, serve game files |
| **UserClient** | `UserClient/` | Runs on customer PCs — login screen, time countdown, game sync |

## Project Structure

```
CyberServer V2/
├── Server/                    ← Server source code
│   ├── main.py                   Entry point
│   ├── api.py                    HTTP API (login, update, sync)
│   ├── database.py               SQLite database layer
│   ├── gui.py                    Server admin GUI
│   ├── common.py                 Shared state & keyboard hooks
│   ├── utils.py                  Password hashing & config utils
│   └── toast.py                  Windows notifications
│
├── AdminClient/               ← Admin client source code
│   ├── CyberClient_Admin.py      Main admin application
│   ├── common.py                 Keyboard hooks & config
│   ├── utils.py                  Password hashing & config utils
│   └── toast.py                  Windows notifications
│
├── UserClient/                ← User client source code
│   ├── CyberClient_User.py       Main user application
│   └── toast.py                  Windows notifications
│
├── scripts/                   ← Utility scripts
│   ├── Firewall_AdminPC.ps1      Firewall rules for admin PC
│   ├── Firewall_ServerPC.ps1     Firewall rules for server PC
│   └── Firewall_UserPC.ps1      Firewall rules for user PCs
│
├── CyberServer.spec           ← PyInstaller spec (Server)
├── CyberClient_Admin.spec     ← PyInstaller spec (Admin)
├── CyberClient_User.spec      ← PyInstaller spec (User)
├── background.png             ← Login screen background
├── VERSION                    ← Current version number
└── .gitignore                 ← Ignores build artifacts & runtime data
```

## Setup

### Server PC
1. Copy `server_config.json.example` → `server_config.json` and edit
2. Run `CyberServer.exe`

### Admin PC
1. Configure Admin IP and Server IP in the settings panel
2. Run `CyberClient_Admin.exe`

### User PCs
1. Copy `user_config.json.example` → `user_config.json` and edit
2. Set station name, server IP, and admin IP
3. Set game mappings for each game in Settings → Game Sync
4. Run `CyberClient_User.exe`

## Building

```powershell
python -m PyInstaller CyberServer.spec
python -m PyInstaller CyberClient_Admin.spec
python -m PyInstaller CyberClient_User.spec
```

Compiled EXEs appear in `dist/`.

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.4.0 | 2026-04-15 | Auto cleanup of default Games folder, mapping validation before sync, sync logging |
| 2.3.0 | 2026-03-18 | Single-login enforcement (same account can't be used on 2 PCs simultaneously) |
| 2.2.0 | — | Maintenance mode, force-lock on startup |
| 2.1.0 | — | Atomic config save, AppData storage, Alt+Tab lock |
| 2.0.0 | — | Initial V2 release |
