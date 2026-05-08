# 🎮 CyberServer V2 — Linux Deployment Guide

> Πλήρης οδηγός εγκατάστασης Server, AdminClient, UserClient σε CachyOS KDE Plasma  
> + DeepFreeze-style auto-rollback μέσω Btrfs/Snapper

---

## 📋 Αρχιτεκτονική Δικτύου

```
┌──────────────────────────────────────────────────────────┐
│                    ΤΟΠΙΚΟ ΔΙΚΤΥΟ (LAN)                   │
│                                                          │
│  ┌─────────────┐                                         │
│  │  SERVER PC   │  IP: 192.168.1.6                       │
│  │  (CachyOS)   │  Τρέχει: CyberServer (Flask API)      │
│  │              │  Port: 5000                            │
│  │              │  Database: SQLite (cybercafe.db)       │
│  │              │  GUI: Διαχείριση χρηστών/χρόνου        │
│  └──────┬───────┘                                        │
│         │                                                │
│  ┌──────┴───────┐                                        │
│  │  ADMIN PC    │  IP: 192.168.1.10 (παράδειγμα)        │
│  │  (CachyOS)   │  Τρέχει: CyberClient_Admin            │
│  │              │  Port: 5001 (File Sync Server)         │
│  │              │  Ρόλος: Game updates, sync, management │
│  └──────┬───────┘                                        │
│         │                                                │
│  ┌──────┴───────┐  ┌───────────┐  ┌───────────┐         │
│  │ USER PC #1   │  │ USER PC #2│  │ USER PC #N│         │
│  │ (CachyOS)    │  │ (CachyOS) │  │ (CachyOS) │         │
│  │ cyberguest   │  │ cyberguest│  │ cyberguest│         │
│  │ LOCKED DOWN  │  │ LOCKED    │  │ LOCKED    │         │
│  │ + DeepFreeze │  │ + Freeze  │  │ + Freeze  │         │
│  └──────────────┘  └───────────┘  └───────────┘         │
└──────────────────────────────────────────────────────────┘
```

---

## Μέρος 1: Εγκατάσταση CachyOS (Κοινό για όλα τα PCs)

### 1.1 Download & Install CachyOS

1. Κατέβασε ISO: https://cachyos.org/download/
2. Burn σε USB (χρησιμοποίησε Ventoy ή Rufus)
3. Boot από USB
4. **ΣΗΜΑΝΤΙΚΟ στον installer:**
   - Filesystem: **Btrfs** (default, ΜΗΝ αλλάξεις!)
   - Desktop: **KDE Plasma** (default)
   - Τσέκαρε "Enable Snapper" αν υπάρχει η επιλογή
5. Φτιάξε admin user (π.χ. `cyberadmin`) με password
6. Ολοκλήρωσε εγκατάσταση, reboot

### 1.2 Post-Install (σε ΟΛΑ τα PCs)

```bash
# Ενημέρωσε το σύστημα
sudo pacman -Syu

# Εγκατάστησε βασικά πακέτα
sudo pacman -S --noconfirm git python python-pip tk python-bcrypt noto-fonts base-devel

# Κατέβασε το CyberServer
cd /opt
sudo git clone https://github.com/PawZzGR/CyberServer.git cyberserver
sudo chmod -R 755 /opt/cyberserver

# Python packages
pip install --break-system-packages evdev tkcalendar
```

---

## Μέρος 2: Setup SERVER PC

> Αυτό είναι το κεντρικό PC που κρατάει τη βάση δεδομένων, τους χρόνους, τα accounts.

### 2.1 Ρύθμιση Config

```bash
# Δημιούργησε config directory
mkdir -p ~/.config/CyberClient/Server

# Δημιούργησε/τροποποίησε config
nano /opt/cyberserver/Server/config.json
```

Παράδειγμα `config.json`:
```json
{
    "server": {
        "host": "0.0.0.0",
        "port": 5000
    },
    "database": {
        "file": "cybercafe.db"
    },
    "logging": {
        "level": "INFO",
        "file": "server.log"
    }
}
```

### 2.2 Εγκατάσταση Systemd Service

```bash
# Αντίγραψε το service file
sudo cp /opt/cyberserver/systemd/cyberserver.service /etc/systemd/system/

# Ενεργοποίησε & ξεκίνα
sudo systemctl daemon-reload
sudo systemctl enable cyberserver.service
sudo systemctl start cyberserver.service

# Έλεγξε ότι τρέχει
sudo systemctl status cyberserver.service
```

### 2.3 Firewall (αν υπάρχει)

```bash
# Άνοιξε port 5000 για τους clients
sudo firewall-cmd --permanent --add-port=5000/tcp
sudo firewall-cmd --reload

# Ή αν δεν έχεις firewalld:
sudo iptables -A INPUT -p tcp --dport 5000 -j ACCEPT
```

### 2.4 Δοκιμή

```bash
# Τρέξε χειροκίνητα για debug
cd /opt/cyberserver/Server
python3 main.py

# Πρέπει να δεις: "Server running on 0.0.0.0:5000"
# Από άλλο PC: http://192.168.1.6:5000 πρέπει να ανταποκρίνεται
```

### 2.5 Static IP (ΣΗΜΑΝΤΙΚΟ!)

Ο Server ΠΡΕΠΕΙ να έχει σταθερή IP:

```bash
# KDE Plasma: System Settings → Network → Connections
# Ή μέσω nmcli:
sudo nmcli connection modify "Wired connection 1" \
    ipv4.addresses "192.168.1.6/24" \
    ipv4.gateway "192.168.1.1" \
    ipv4.dns "8.8.8.8" \
    ipv4.method manual
sudo nmcli connection up "Wired connection 1"
```

---

## Μέρος 3: Setup ADMIN PC

> Αυτό το PC χρησιμοποιεί ο admin/ιδιοκτήτης. Βάζει game updates, sync folders κλπ.

### 3.1 Ρύθμιση Config

```bash
mkdir -p ~/.config/CyberClient/Admin
nano ~/.config/CyberClient/Admin/admin_config.json
```

```json
{
    "server_address": "192.168.1.6",
    "server_port": 5000,
    "client_machine": "ADMIN-PC",
    "file_server_port": 5001,
    "scan_interval": 60,
    "sync_interval": 3600
}
```

### 3.2 Εγκατάσταση Service

```bash
sudo cp /opt/cyberserver/systemd/cyberclient-admin.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cyberclient-admin.service
sudo systemctl start cyberclient-admin.service
```

### 3.3 Χρήση

```bash
# Τρέξε χειροκίνητα (πρώτη φορά)
cd /opt/cyberserver/AdminClient
python3 CyberClient_Admin.py

# Μέσα στην εφαρμογή:
# - Settings → Server IP: 192.168.1.6
# - Add Sync Folders → Επέλεξε φακέλους παιχνιδιών
# - Τα παιχνίδια θα γίνονται sync στους UserClients
```

---

## Μέρος 4: Setup USER PCs (Guests — Πελάτες)

> Αυτά είναι τα μηχανήματα πελατών. ΠΛΗΡΩΣ κλειδωμένα.

### 4.1 Αυτόματη Εγκατάσταση (One-Click)

```bash
cd /opt/cyberserver
sudo bash linux_setup.sh
```

**Αυτό κάνει αυτόματα:**
- ✅ Εγκαθιστά dependencies
- ✅ Δημιουργεί `cyberguest` user (χωρίς sudo)
- ✅ Ρυθμίζει evdev/uinput permissions
- ✅ Βάζει polkit rules (deny reboot/shutdown)
- ✅ Ρυθμίζει SDDM auto-login
- ✅ Βάζει CyberClient autostart
- ✅ Εγκαθιστά systemd service

### 4.2 Ρύθμιση Client Config

```bash
# Δημιούργησε config για τον guest user
sudo mkdir -p /home/cyberguest/.config/CyberClient/User
sudo nano /home/cyberguest/.config/CyberClient/User/user_config.json
```

```json
{
    "server_address": "192.168.1.6",
    "server_port": 5000,
    "client_machine": "PC-1",
    "sync_interval": 10800,
    "game_sync_interval": 30
}
```

> ⚠️ Άλλαξε `client_machine` σε κάθε PC (PC-1, PC-2, PC-3...)

```bash
# Σωστό ownership
sudo chown -R cyberguest:cyberguest /home/cyberguest/
```

### 4.3 Reboot & Test

```bash
sudo reboot
```

**Αποτέλεσμα:**
1. Boot → Auto-login ως `cyberguest`
2. CyberClient ξεκινάει fullscreen
3. Βλέπεις lock screen (login required)
4. Keyboard: Super, Alt+Tab, Ctrl+Alt+F2 = ΜΠΛΟΚΑΡΙΣΜΕΝΑ
5. Ο πελάτης κάνει login → Timer ξεκινάει
6. Timer τελειώνει → Lock screen + reboot countdown

---

## Μέρος 5: DeepFreeze — Αυτόματο Reset στο Reboot

> Σαν DeepFreeze/Shadow Defender: Ό,τι αλλάξει ο πελάτης, σβήνεται στο reboot.

### Μέθοδος: Btrfs Snapshot Rollback

Το CachyOS χρησιμοποιεί **Btrfs** filesystem by default. Αυτό σημαίνει ότι μπορούμε να:
1. Φτιάξουμε ένα "καθαρό" snapshot
2. Σε κάθε reboot, να επαναφέρουμε σε αυτό

### 5.1 Εγκατάσταση Snapper & Btrfs Assistant

```bash
sudo pacman -S --noconfirm snapper snap-pac btrfs-assistant
```

### 5.2 Setup Snapper Config

```bash
# Δημιούργησε snapper config για root
sudo snapper -c root create-config /

# Ρύθμισε limits (μην γεμίσει ο δίσκος)
sudo snapper -c root set-config "TIMELINE_CREATE=yes"
sudo snapper -c root set-config "TIMELINE_LIMIT_HOURLY=2"
sudo snapper -c root set-config "TIMELINE_LIMIT_DAILY=3"
sudo snapper -c root set-config "TIMELINE_LIMIT_WEEKLY=0"
sudo snapper -c root set-config "TIMELINE_LIMIT_MONTHLY=0"
sudo snapper -c root set-config "TIMELINE_LIMIT_YEARLY=0"

# Ενεργοποίησε τα timers
sudo systemctl enable --now snapper-timeline.timer
sudo systemctl enable --now snapper-cleanup.timer
```

### 5.3 Δημιούργησε το "Καθαρό" Snapshot

Αφού ρυθμίσεις τα πάντα (CyberClient, games, drivers, settings):

```bash
# Δημιούργησε το golden snapshot
sudo snapper -c root create --description "GOLDEN - Clean CyberCafe State" --type single

# Σημείωσε τον αριθμό (π.χ. 5)
sudo snapper -c root list
```

Θα δεις κάτι σαν:
```
 # | Type   | Pre | Date                            | User | Cleanup | Description
---+--------+-----+---------------------------------+------+---------+-----------------------------------
 0 | single |     |                                 | root |         | current
 1 | single |     | Thu May 08 15:00:00 2026        | root |         | GOLDEN - Clean CyberCafe State
```

### 5.4 Αυτόματο Rollback σε κάθε Boot

Δημιούργησε ένα script που τρέχει στο **shutdown/reboot** και επαναφέρει στο golden snapshot:

```bash
# Δημιούργησε το rollback script
sudo nano /usr/local/bin/cyber-rollback.sh
```

Περιεχόμενα:
```bash
#!/bin/bash
# =================================================================
# CyberServer V2 — DeepFreeze Rollback Script
# =================================================================
# Αυτό τρέχει ΠΡΙΝ το shutdown/reboot.
# Επαναφέρει το σύστημα στο "golden" snapshot.
# =================================================================

GOLDEN_SNAPSHOT_ID=1  # <-- ΑΛΛΑΞΕ ΑΥΤΟ στο ID του golden snapshot σου!

# Log
echo "[CYBER-ROLLBACK] Starting rollback to snapshot #${GOLDEN_SNAPSHOT_ID}..."
logger -t cyber-rollback "Rolling back to snapshot #${GOLDEN_SNAPSHOT_ID}"

# Εκτέλεση rollback
/usr/bin/snapper -c root undochange ${GOLDEN_SNAPSHOT_ID}..0

echo "[CYBER-ROLLBACK] Rollback complete."
logger -t cyber-rollback "Rollback complete."
```

```bash
# Κάνε executable
sudo chmod +x /usr/local/bin/cyber-rollback.sh
```

### 5.5 Systemd Service για Auto-Rollback

```bash
sudo nano /etc/systemd/system/cyber-rollback.service
```

```ini
[Unit]
Description=CyberServer DeepFreeze - Rollback on Shutdown
DefaultDependencies=no
Before=shutdown.target reboot.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/cyber-rollback.sh
TimeoutStartSec=120

[Install]
WantedBy=shutdown.target reboot.target
```

```bash
# Ενεργοποίησε
sudo systemctl daemon-reload
sudo systemctl enable cyber-rollback.service
```

### 5.6 Εξαίρεση Σημαντικών Φακέλων

> ⚠️ **ΣΗΜΑΝΤΙΚΟ:** Δεν θέλουμε να σβήνονται ΟΛΑ. Κάποια πράγματα πρέπει να παραμένουν.

Το Btrfs έχει ξεχωριστά subvolumes. Στο CachyOS, αυτά είναι ΗΔΗ ξεχωριστά:

| Τι | Subvolume | Rollback; |
|----|-----------|-----------|
| Σύστημα (`/`) | `@` | ✅ ΝΑΙ — επαναφέρεται |
| Home (`/home`) | `@home` | ❌ ΟΧΙ — παραμένει |
| Logs (`/var/log`) | `@log` | ❌ ΟΧΙ — παραμένει |
| Cache (`/var/cache`) | `@cache` | ❌ ΟΧΙ — παραμένει |

**Αυτό σημαίνει:**
- Το **σύστημα** (εγκατεστημένα apps, ρυθμίσεις, temp files) → **ΣΒΗΝΕΤΑΙ**
- Ο φάκελος `/home/cyberguest/` → **ΔΕΝ σβήνεται** (γιατί είναι σε `@home`)

Αν θέλεις να σβήνεται ΚΑΙ το home του guest:

```bash
# Πρόσθεσε στο cyber-rollback.sh ΠΡΙΝ το snapper undochange:

# Reset guest home directory to clean state
rm -rf /home/cyberguest/Desktop/* 2>/dev/null
rm -rf /home/cyberguest/Downloads/* 2>/dev/null
rm -rf /home/cyberguest/Documents/* 2>/dev/null
rm -rf /home/cyberguest/.cache/* 2>/dev/null
rm -rf /home/cyberguest/.local/share/Trash/* 2>/dev/null
# Μην σβήσεις τα .config/CyberClient — εκεί είναι τα settings!
```

### 5.7 Πώς να Κάνεις Μόνιμες Αλλαγές (Admin Mode)

Αφού ενεργοποιήσεις το rollback, κάθε αλλαγή σβήνεται στο reboot. Για μόνιμες αλλαγές:

```bash
# ΒΗΜΑ 1: Απενεργοποίησε το rollback ΠΡΟΣΩΡΙΝΑ
sudo systemctl disable cyber-rollback.service

# ΒΗΜΑ 2: Κάνε τις αλλαγές σου (install games, update, κλπ)
sudo pacman -Syu
# ... κάνε ό,τι χρειάζεται ...

# ΒΗΜΑ 3: Δημιούργησε ΝΕΟ golden snapshot
sudo snapper -c root create --description "GOLDEN v2 - Updated Games" --type single

# ΒΗΜΑ 4: Ενημέρωσε το script με το νέο snapshot ID
sudo nano /usr/local/bin/cyber-rollback.sh
# Άλλαξε GOLDEN_SNAPSHOT_ID στο νέο ID

# ΒΗΜΑ 5: Ξαναενεργοποίησε το rollback
sudo systemctl enable cyber-rollback.service

# ΒΗΜΑ 6: Reboot
sudo reboot
```

---

## Μέρος 6: Εναλλακτική Μέθοδος — OverlayFS (Πιο Ασφαλής)

> Αυτή η μέθοδος είναι πιο αξιόπιστη αλλά πιο σύνθετη.  
> Λειτουργεί σαν "RAM disk" — όλες οι αλλαγές γράφονται στη RAM, χάνονται στο reboot.

### Πώς δουλεύει:
```
Boot
  ↓
Root filesystem (Btrfs) → ΜΟΝΟ ΑΝΑΓΝΩΣΗ (read-only)
  ↓
OverlayFS → Αλλαγές πάνε στη RAM (tmpfs)
  ↓
Ο χρήστης βλέπει merged view
  ↓
Reboot → RAM σβήνεται → Σύστημα "καθαρό"
```

### Εγκατάσταση:

```bash
# 1. Εγκατάστησε το overlayfs hook για mkinitcpio
# Αυτό προσθέτει overlay στο boot process
sudo pacman -S --noconfirm mkinitcpio

# 2. Δημιούργησε overlay hook
sudo nano /etc/initcpio/hooks/overlay
```

```bash
#!/usr/bin/ash
run_hook() {
    # Mount tmpfs for overlay
    mkdir -p /overlay/upper /overlay/work
    mount -t tmpfs tmpfs /overlay
    mkdir -p /overlay/upper /overlay/work
    
    # Create overlay mount
    mount -t overlay overlay \
        -o lowerdir=/new_root,upperdir=/overlay/upper,workdir=/overlay/work \
        /new_root
}
```

> ⚠️ Αυτή η μέθοδος χρειάζεται πιο βαθύ configuration στο initramfs.
> Αν η Μέθοδος Snapper (Μέρος 5) δουλεύει καλά, **μείνε σε αυτή**.

---

## Μέρος 7: Checklist Ολοκλήρωσης

### Server PC ☐
- [ ] CachyOS εγκατεστημένο
- [ ] Static IP ρυθμισμένη (192.168.1.6)
- [ ] `/opt/cyberserver` clone
- [ ] `config.json` ρυθμισμένο
- [ ] `cyberserver.service` enabled & running
- [ ] Port 5000 ανοιχτό στο firewall
- [ ] Test: `curl http://localhost:5000/api/ping`

### Admin PC ☐
- [ ] CachyOS εγκατεστημένο
- [ ] `/opt/cyberserver` clone
- [ ] `admin_config.json` ρυθμισμένο
- [ ] `cyberclient-admin.service` enabled
- [ ] Sync folders ρυθμισμένα (games, updates)
- [ ] Test: Βλέπει τον Server, στέλνει updates

### User PCs (x N) ☐
- [ ] CachyOS εγκατεστημένο (Btrfs!)
- [ ] `linux_setup.sh` εκτελέστηκε
- [ ] `user_config.json` ρυθμισμένο (σωστό server IP)
- [ ] `client_machine` μοναδικό σε κάθε PC
- [ ] Reboot → Auto-login → CyberClient fullscreen
- [ ] Keyboard lock λειτουργεί (Super, Alt+Tab blocked)
- [ ] Login/Timer λειτουργεί
- [ ] DeepFreeze (snapper rollback) ενεργοποιημένο
- [ ] BIOS password ρυθμισμένο
- [ ] USB boot disabled στο BIOS

---

## Μέρος 8: Troubleshooting

### Πρόβλημα: CyberClient δεν ξεκινάει

```bash
# Δες τα logs
sudo journalctl -u cyberclient-user.service -f

# Τρέξε χειροκίνητα ως cyberguest
sudo -u cyberguest DISPLAY=:0 python3 /opt/cyberserver/UserClient/CyberClient_User.py
```

### Πρόβλημα: Keyboard lock δεν δουλεύει

```bash
# Έλεγξε ότι ο cyberguest είναι στο input group
groups cyberguest  # Πρέπει να δείξει: input

# Έλεγξε uinput module
lsmod | grep uinput  # Πρέπει να δείξει: uinput

# Έλεγξε permissions
ls -la /dev/uinput  # Πρέπει: crw-rw---- input
ls -la /dev/input/event*  # Πρέπει να είναι readable
```

### Πρόβλημα: Δεν βρίσκει τον Server

```bash
# Από User PC:
ping 192.168.1.6  # Πρέπει να απαντάει

# Test API
curl http://192.168.1.6:5000/api/ping
```

### Πρόβλημα: Snapper rollback δεν δουλεύει

```bash
# Δες τα snapshots
sudo snapper -c root list

# Δοκίμασε χειροκίνητα
sudo snapper -c root undochange 1..0 --dry-run  # Dry run πρώτα!
sudo snapper -c root undochange 1..0             # Πραγματικό rollback
```

### Πρόβλημα: Ο guest κάνει bypass

```bash
# Verify polkit
sudo -u cyberguest systemctl poweroff  # Πρέπει: denied

# Verify no sudo
sudo -u cyberguest sudo ls  # Πρέπει: not in sudoers

# Verify keyboard grab
sudo evtest  # Δες ποια devices υπάρχουν
```

---

## Μέρος 9: Συντήρηση & Updates

### Update CyberServer (σε όλα τα PCs):

```bash
cd /opt/cyberserver
sudo git pull origin main
sudo systemctl restart cyberserver.service     # Server PC
sudo systemctl restart cyberclient-admin.service  # Admin PC
sudo systemctl restart cyberclient-user.service   # User PCs
```

### Update Games (Admin PC):

1. Κατέβασε/εγκατάστησε games στο Admin PC
2. Πρόσθεσε τον φάκελο μέσω AdminClient → Settings → Add Sync Folder
3. Κάνε "Scan Now"
4. Οι UserClients θα κατεβάσουν τα games αυτόματα

### Νέο Golden Snapshot μετά από updates (User PCs):

```bash
sudo systemctl disable cyber-rollback.service
sudo reboot  # Κάνε ό,τι αλλαγές χρειάζεται
# ... updates/games install ...
sudo snapper -c root create --description "GOLDEN v3" --type single
# Ενημέρωσε GOLDEN_SNAPSHOT_ID στο script
sudo systemctl enable cyber-rollback.service
sudo reboot
```

---

## ⚡ Quick Reference — Χρήσιμες Εντολές

| Εντολή | Τι κάνει |
|--------|---------|
| `sudo systemctl status cyberserver` | Κατάσταση Server |
| `sudo systemctl restart cyberclient-user` | Restart User Client |
| `sudo journalctl -u cyberclient-user -f` | Live logs User Client |
| `sudo snapper -c root list` | Λίστα snapshots |
| `sudo snapper -c root create -d "Backup"` | Νέο snapshot |
| `sudo snapper -c root undochange X..0` | Rollback σε #X |
| `sudo systemctl disable cyber-rollback` | Απενεργοποίηση freeze |
| `sudo systemctl enable cyber-rollback` | Ενεργοποίηση freeze |
| `groups cyberguest` | Δες groups του guest |
| `sudo -u cyberguest whoami` | Test guest user |
