#!/bin/bash
# SportsCaster Pro v2 - Raspberry Pi Hotspot Setup
# Usage: sudo bash setup_hotspot.sh
set -e

SSID="SportsCaster"
PASS="broadcast1"
IP="192.168.4.1"
IFACE="wlan0"

echo "==================================="
echo "  Hotspot Setup"
echo "  SSID: ${SSID}  IP: ${IP}"
echo "==================================="

apt-get update -qq
apt-get install -y hostapd dnsmasq rfkill
rfkill unblock wifi || true
systemctl stop hostapd dnsmasq 2>/dev/null || true

# Static IP
grep -q "SportsCaster" /etc/dhcpcd.conf 2>/dev/null || cat >> /etc/dhcpcd.conf <<EOF

# SportsCaster
interface ${IFACE}
    static ip_address=${IP}/24
    nohook wpa_supplicant
EOF

# dnsmasq
mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak 2>/dev/null || true
cat > /etc/dnsmasq.conf <<EOF
interface=${IFACE}
dhcp-range=192.168.4.100,192.168.4.200,255.255.255.0,24h
domain=local
address=/sportscaster.local/${IP}
bogus-priv
EOF

# hostapd
cat > /etc/hostapd/hostapd.conf <<EOF
interface=${IFACE}
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
wpa=2
wpa_passphrase=${PASS}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF

sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd
systemctl unmask hostapd 2>/dev/null || true
systemctl enable hostapd dnsmasq
systemctl start hostapd dnsmasq

echo ""
echo "==================================="
echo "  Done! WiFi: ${SSID} / ${PASS}"
echo "  App: http://${IP}:3000"
echo "==================================="
