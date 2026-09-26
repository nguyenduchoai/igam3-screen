#!/usr/bin/env bash
# One-time setup (needs root) for the 3.5" screen built into the iGam3 M1 (Turing Smart Screen, USB 1a86:5722).
# Run:  sudo ~/igam3-screen/setup-root.sh [--lang vi|en]     (running it again is harmless)
set -euo pipefail

case "${LANGUAGE:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}" in vi*) VI=1 ;; *) VI=0 ;; esac
if [[ "${1:-}" == "--lang" ]]; then [[ "${2:-}" == "vi" ]] && VI=1 || VI=0; fi
t() { if (( VI )); then printf '%s' "$1"; else printf '%s' "$2"; fi; }  # t "Tiếng Việt" "English"

if [[ $EUID -ne 0 ]]; then
    echo "$(t "Cần chạy bằng sudo:" "Run it with sudo:")  sudo $0" >&2
    exit 1
fi
TARGET_USER="${SUDO_USER:-}"
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
    echo "$(t "Hãy chạy bằng sudo từ tài khoản người dùng thường (không đăng nhập root)." \
              "Run it with sudo from a normal user account (not logged in as root).")" >&2
    exit 1
fi

RULE=/etc/udev/rules.d/60-igam3-screen.rules

echo "[1/5] $(t "Quy tắc udev: cho phép người dùng mở màn hình, ModemManager bỏ qua thiết bị này" \
                "udev rule: the user may open the screen, ModemManager leaves it alone")"
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

echo "[2/5] $(t "Thêm $TARGET_USER vào nhóm dialout (có hiệu lực đầy đủ sau khi khởi động lại máy)" \
                "Adding $TARGET_USER to the dialout group (fully effective after a restart)")"
usermod -aG dialout "$TARGET_USER"

echo "[3/5] $(t "Cho dịch vụ của $TARGET_USER tự chạy lúc khởi động, kể cả khi chưa đăng nhập" \
                "Letting the services of $TARGET_USER start at boot, even before anyone logs in")"
loginctl enable-linger "$TARGET_USER"

echo "[4/5] $(t "Cài python3-tk cho giao diện cấu hình (igam3-screen config)" \
                "Installing python3-tk for the configuration window (igam3-screen config)")"
if ! apt-get install -y python3-tk; then
    echo "  -> $(t "Không cài được python3-tk (không bắt buộc, màn hình vẫn chạy bình thường)." \
                   "python3-tk could not be installed (optional, the screen works without it).")"
fi

echo "[5/5] $(t "Chế độ Dòng lệnh: cho phép đọc màn hình dòng lệnh tty3 (nhóm tty)" \
                "Console mode: read access to the text console tty3 (tty group)")"
usermod -aG tty "$TARGET_USER"
# Group membership reaches the service after a reboot; this ACL gives the same read access right away
setfacl -m "u:$TARGET_USER:r" /dev/vcsa3 /dev/vcsu3 || true

echo
echo "$(t "Bật màn hình chính..." "Starting the main screen...")"
if systemctl --user --machine="$TARGET_USER@" enable --now igam3-screen.service; then
    echo "$(t "Xong! Màn hình trên máy sẽ hiện màn hình chính sau khoảng 10 giây." \
              "Done! The small screen shows the main screen in about 10 seconds.")"
else
    echo "$(t "Chưa bật được dịch vụ. Chạy thử bằng tài khoản thường:" \
              "The service did not start. Try as the normal user:")  igam3-screen enable"
fi
ls -l /dev/igam3-screen 2>/dev/null || true
