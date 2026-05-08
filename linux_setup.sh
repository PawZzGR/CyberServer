#!/bin/bash
# ==============================================================================
# CyberServer V2 — CachyOS/KDE Plasma Full Setup Script
# ==============================================================================
# 
# This script sets up a complete CyberServer V2 Linux installation including:
#   1. System dependencies (Python, tkinter, fonts)
#   2. Python packages (evdev, tkcalendar, bcrypt)
#   3. Locked-down guest user account (cyberguest)
#   4. Keyboard input permissions (evdev/uinput)
#   5. Polkit rules (deny shutdown/reboot for guest)
#   6. Auto-login configuration
#   7. CyberClient autostart
#   8. Systemd services
#
# Run as root or with sudo:
#   sudo bash linux_setup.sh
#
# ==============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   CyberServer V2 — Linux Setup (CachyOS)    ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
echo ""

# Check for root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[ERROR] This script must be run as root (sudo bash linux_setup.sh)${NC}"
    exit 1
fi

# Detect install directory (where this script lives)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/cyberserver"

echo -e "${YELLOW}[1/10] Installing system dependencies...${NC}"
pacman -S --noconfirm --needed \
    python python-pip \
    tk \
    python-bcrypt \
    noto-fonts \
    python-setuptools \
    python-wheel \
    2>/dev/null || echo "Some packages may already be installed"

echo -e "${YELLOW}[2/10] Installing Python packages...${NC}"
pip install --break-system-packages evdev tkcalendar 2>/dev/null || \
pip install evdev tkcalendar 2>/dev/null || \
echo -e "${YELLOW}  Warning: pip install failed, trying pacman...${NC}"
pacman -S --noconfirm --needed python-evdev 2>/dev/null || true

echo -e "${YELLOW}[3/10] Copying files to ${INSTALL_DIR}...${NC}"
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/" 2>/dev/null || true
chmod -R 755 "$INSTALL_DIR"

echo -e "${YELLOW}[4/10] Creating locked-down guest user (cyberguest)...${NC}"
if id "cyberguest" &>/dev/null; then
    echo -e "  User 'cyberguest' already exists, skipping creation"
else
    useradd -m -s /bin/bash cyberguest
    echo -e "  ${GREEN}User 'cyberguest' created${NC}"
fi

# Ensure cyberguest is NOT in wheel/sudo group (CRITICAL)
gpasswd -d cyberguest wheel 2>/dev/null || true
gpasswd -d cyberguest sudo 2>/dev/null || true
echo -e "  ${GREEN}Guest user has NO admin privileges${NC}"

echo -e "${YELLOW}[5/10] Setting up input permissions (evdev/uinput)...${NC}"
# Add cyberguest to input group (for keyboard grabbing)
usermod -aG input cyberguest

# Load uinput module now and on boot
modprobe uinput 2>/dev/null || true
echo "uinput" > /etc/modules-load.d/uinput.conf 2>/dev/null || true

# Udev rule for uinput access
cat > /etc/udev/rules.d/99-uinput.rules << 'EOF'
KERNEL=="uinput", MODE="0660", GROUP="input"
EOF
udevadm control --reload-rules 2>/dev/null || true
echo -e "  ${GREEN}Input permissions configured${NC}"

echo -e "${YELLOW}[6/10] Setting up Polkit rules (deny shutdown/reboot for guest)...${NC}"
mkdir -p /etc/polkit-1/rules.d
cat > /etc/polkit-1/rules.d/99-cyberguest-deny.rules << 'POLKIT_EOF'
// CyberServer V2: Deny all dangerous actions for cyberguest
polkit.addRule(function(action, subject) {
    if (subject.user == "cyberguest") {
        // Deny reboot/shutdown
        if (action.id.indexOf("org.freedesktop.login1.reboot") >= 0 ||
            action.id.indexOf("org.freedesktop.login1.power-off") >= 0 ||
            action.id.indexOf("org.freedesktop.login1.halt") >= 0 ||
            action.id.indexOf("org.freedesktop.login1.hibernate") >= 0 ||
            action.id.indexOf("org.freedesktop.login1.suspend") >= 0) {
            return polkit.Result.NO;
        }
        // Deny USB mounting
        if (action.id.indexOf("org.freedesktop.udisks2") >= 0) {
            return polkit.Result.NO;
        }
        // Deny package management
        if (action.id.indexOf("org.freedesktop.packagekit") >= 0) {
            return polkit.Result.NO;
        }
        // Deny network management
        if (action.id.indexOf("org.freedesktop.NetworkManager") >= 0) {
            return polkit.Result.NO;
        }
    }
});
POLKIT_EOF
echo -e "  ${GREEN}Polkit rules installed${NC}"

echo -e "${YELLOW}[7/10] Configuring auto-login for cyberguest...${NC}"
# Check which display manager is active
if systemctl is-active --quiet sddm; then
    # SDDM (default for KDE Plasma)
    mkdir -p /etc/sddm.conf.d
    cat > /etc/sddm.conf.d/autologin.conf << 'EOF'
[Autologin]
User=cyberguest
Session=plasma
EOF
    echo -e "  ${GREEN}SDDM auto-login configured${NC}"
elif [ -f /etc/sddm.conf ]; then
    # SDDM with main config
    if ! grep -q "Autologin" /etc/sddm.conf; then
        cat >> /etc/sddm.conf << 'EOF'

[Autologin]
User=cyberguest
Session=plasma
EOF
    fi
    echo -e "  ${GREEN}SDDM auto-login configured${NC}"
else
    echo -e "  ${YELLOW}Warning: Could not detect display manager. Configure auto-login manually.${NC}"
fi

echo -e "${YELLOW}[8/10] Setting up CyberClient autostart...${NC}"
# Create autostart entry for cyberguest's KDE session
AUTOSTART_DIR="/home/cyberguest/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/cyberclient.desktop" << EOF
[Desktop Entry]
Type=Application
Name=CyberClient User
Comment=CyberServer V2 User Client
Exec=/usr/bin/python3 ${INSTALL_DIR}/UserClient/CyberClient_User.py
X-KDE-autostart-phase=2
X-KDE-autostart-after=panel
Hidden=false
NoDisplay=false
EOF

# Ensure correct ownership
chown -R cyberguest:cyberguest /home/cyberguest/
echo -e "  ${GREEN}Autostart configured${NC}"

echo -e "${YELLOW}[9/10] Installing systemd services...${NC}"
SYSTEMD_DIR="$INSTALL_DIR/systemd"
if [ -d "$SYSTEMD_DIR" ]; then
    cp "$SYSTEMD_DIR"/*.service /etc/systemd/system/ 2>/dev/null || true
    systemctl daemon-reload
    
    # Enable the user client service (for guest PCs)
    systemctl enable cyberclient-user.service 2>/dev/null || true
    echo -e "  ${GREEN}Systemd services installed and enabled${NC}"
else
    echo -e "  ${YELLOW}No systemd directory found, creating services...${NC}"
    
    # Create cyberclient-user.service
    cat > /etc/systemd/system/cyberclient-user.service << EOF
[Unit]
Description=CyberClient User Session
After=network-online.target graphical.target
Wants=network-online.target

[Service]
Type=simple
User=cyberguest
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/cyberguest/.Xauthority
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/UserClient/CyberClient_User.py
Restart=always
RestartSec=2
KillMode=process

[Install]
WantedBy=graphical.target
EOF
    
    systemctl daemon-reload
    systemctl enable cyberclient-user.service
    echo -e "  ${GREEN}Systemd user service created and enabled${NC}"
fi

echo -e "${YELLOW}[10/10] Creating config directories...${NC}"
# Create XDG config dirs for cyberguest
sudo -u cyberguest mkdir -p /home/cyberguest/.config/CyberClient/User 2>/dev/null || true
sudo -u cyberguest mkdir -p /home/cyberguest/.config/CyberClient/Admin 2>/dev/null || true
echo -e "  ${GREEN}Config directories created${NC}"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          SETUP COMPLETE! 🎮                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Next steps:"
echo -e "  1. ${BLUE}Edit the client config:${NC}"
echo -e "     /home/cyberguest/.config/CyberClient/User/user_config.json"
echo -e "     Set 'server_address' to your server's IP"
echo -e ""
echo -e "  2. ${BLUE}Reboot to test:${NC}"
echo -e "     sudo reboot"
echo -e ""
echo -e "  3. ${BLUE}The system will:${NC}"
echo -e "     Auto-login as 'cyberguest' → CyberClient starts fullscreen"
echo -e "     Keyboard locked (Super, Alt+Tab, Ctrl+Alt+F2 blocked)"
echo -e "     Guest cannot: sudo, install apps, open terminal, reboot"
echo ""
echo -e "${YELLOW}⚠️  IMPORTANT: Set a BIOS password to prevent booting from USB!${NC}"
echo ""
