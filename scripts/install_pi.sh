#!/bin/bash
# SportsCaster Pro v2 - Full Pi Installation
# Usage: sudo bash install_pi.sh
set -e
INSTALL_DIR="/home/pi/sportscaster2"

echo "============================================"
echo "  SportsCaster Pro v2 - Pi Installation"
echo "============================================"

apt-get update -qq
apt-get install -y python3 python3-pip python3-venv ffmpeg \
  libopencv-dev python3-opencv git curl hostapd dnsmasq \
  v4l-utils libatlas-base-dev

python3 -m venv "${INSTALL_DIR}/venv"
source "${INSTALL_DIR}/venv/bin/activate"
pip install --upgrade pip wheel --quiet
pip install fastapi==0.111.0 "uvicorn[standard]==0.30.1" websockets==12.0 \
  pydantic==2.7.1 "pydantic-settings==2.3.1" \
  opencv-python-headless==4.9.0.80 numpy==1.26.4 python-multipart==0.0.9

mkdir -p "${INSTALL_DIR}"/{recordings,reviews,models,training_data,config}
chown -R pi:pi "${INSTALL_DIR}"

# Services
cat > /etc/systemd/system/sportscaster-backend.service <<EOF
[Unit]
Description=SportsCaster Backend
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=${INSTALL_DIR}/backend
Environment="PATH=${INSTALL_DIR}/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/sportscaster-frontend.service <<EOF
[Unit]
Description=SportsCaster Frontend
After=sportscaster-backend.service

[Service]
Type=simple
User=pi
WorkingDirectory=${INSTALL_DIR}/frontend
ExecStart=/usr/bin/python3 -m http.server 3000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable sportscaster-backend sportscaster-frontend
systemctl start  sportscaster-backend sportscaster-frontend

bash "${INSTALL_DIR}/scripts/setup_hotspot.sh"

echo ""
echo "============================================"
echo "  Installation Complete!"
echo "  WiFi:     SportsCaster / broadcast1"
echo "  App:      http://192.168.4.1:3000"
echo "  Login:    admin / admin"
echo "============================================"
sleep 5 && reboot
