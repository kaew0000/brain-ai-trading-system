#!/bin/bash
# ══════════════════════════════════════════════════════
#  Brain Bot V13 — VPS Deployment Script (Ubuntu 22.04)
#  Usage: sudo bash deployment/deploy_vps.sh
# ══════════════════════════════════════════════════════
set -e

BOT_DIR="/opt/brain_bot_btcusdt"
BOT_USER="botuser"
LOG_DIR="/var/log/brain_bot"
SERVICE="brain_bot"

echo "=== Brain Bot V13 VPS Deployment ==="

# 1. System dependencies
apt-get update -q
apt-get install -y python3.11 python3.11-venv python3-pip curl git

# 2. Create user if not exists
id -u $BOT_USER &>/dev/null || useradd -m -s /bin/bash $BOT_USER

# 3. Copy files
mkdir -p $BOT_DIR $LOG_DIR
cp -r . $BOT_DIR/
chown -R $BOT_USER:$BOT_USER $BOT_DIR $LOG_DIR

# 4. Python venv + install
sudo -u $BOT_USER python3.11 -m venv $BOT_DIR/venv
sudo -u $BOT_USER $BOT_DIR/venv/bin/pip install --upgrade pip -q
sudo -u $BOT_USER $BOT_DIR/venv/bin/pip install -r $BOT_DIR/requirements.txt -q

# 5. Systemd service
cp $BOT_DIR/deployment/systemd/brain_bot.service /etc/systemd/system/$SERVICE.service
systemctl daemon-reload
systemctl enable $SERVICE

echo ""
echo "✅ Deployment complete."
echo ""
echo "Next steps:"
echo "  1. Edit $BOT_DIR/.env with your API keys"
echo "  2. Set EXECUTION_MODE in /etc/systemd/system/$SERVICE.service"
echo "  3. sudo systemctl start $SERVICE"
echo "  4. sudo systemctl status $SERVICE"
echo "  5. Dashboard: http://YOUR_VPS_IP:8000/dashboard"
