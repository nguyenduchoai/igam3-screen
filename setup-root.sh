#!/usr/bin/env bash
# Cấu hình một lần (cần quyền root) cho màn hình 3.5" gắn trên iGam3 M1 (Turing Smart Screen, USB 1a86:5722).
# Chạy:  sudo ~/igam3-screen/setup-root.sh        (chạy lại nhiều lần cũng không sao)
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Cần chạy bằng sudo:  sudo $0" >&2
    exit 1
fi
TARGET_USER="${SUDO_USER:-}"
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
    echo "Hãy chạy bằng sudo từ tài khoản người dùng thường (không đăng nhập root)." >&2
    exit 1
fi

RULE=/etc/udev/rules.d/60-igam3-screen.rules

echo "[1/5] Quy tắc udev: cho phép người dùng mở màn hình, ModemManager bỏ qua thiết bị này"
cat > "$RULE" <<'EOF'
# iGam3 M1 built-in screen: Turing Smart Screen 3.5" (TURZX "UsbMonitor", USB 1a86:5722)
# - GROUP dialout + uaccess: the logged-in user and the igam3-screen service can open the serial port
# - ID_MM_DEVICE_IGNORE: ModemManager must not probe the screen as if it were a modem
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="5722", GROUP="dialout", MODE="0660", TAG+="uaccess", ENV{ID_MM_DEVICE_IGNORE}="1", SYMLINK+="igam3-screen"
EOF
udevadm control --reload-rules
for dev in /dev/ttyACM*; do
    [[ -e "$dev" ]] || continue
    if udevadm info -q property -n "$dev" | grep -qx 'ID_MODEL_ID=5722'; then
        udevadm trigger --action=change "$dev"
    fi
done
udevadm settle

echo "[2/5] Thêm $TARGET_USER vào nhóm dialout (có hiệu lực đầy đủ sau khi khởi động lại máy)"
usermod -aG dialout "$TARGET_USER"

echo "[3/5] Cho dịch vụ của $TARGET_USER tự chạy lúc khởi động, kể cả khi chưa đăng nhập"
loginctl enable-linger "$TARGET_USER"

echo "[4/5] Cài python3-tk cho giao diện cấu hình (igam3-screen config)"
if ! apt-get install -y python3-tk; then
    echo "  -> Không cài được python3-tk (không bắt buộc, màn hình vẫn chạy bình thường)."
fi

echo "[5/5] Chế độ Dòng lệnh: cho phép đọc màn hình dòng lệnh tty3 (nhóm tty)"
usermod -aG tty "$TARGET_USER"
# Group membership reaches the service after a reboot; this ACL gives the same read access right away
setfacl -m "u:$TARGET_USER:r" /dev/vcsa3 /dev/vcsu3 || true

echo
echo "Bật màn hình chính..."
if systemctl --user --machine="$TARGET_USER@" enable --now igam3-screen.service; then
    echo "Xong! Màn hình trên máy sẽ hiện màn hình chính sau khoảng 10 giây."
else
    echo "Chưa bật được dịch vụ. Chạy thử bằng tài khoản thường:  igam3-screen enable"
fi
ls -l /dev/igam3-screen 2>/dev/null || true
