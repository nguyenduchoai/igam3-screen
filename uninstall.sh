#!/usr/bin/env bash
# Gỡ igam3-screen: dừng màn hình, xoá dịch vụ, lệnh, biểu tượng, phím tắt và quy tắc udev.
# Chạy: bash ~/igam3-screen/uninstall.sh
set -uo pipefail

DEST=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CLI="$DEST/igam3-screen"

"$CLI" shortcut off >/dev/null 2>&1
"$CLI" web --lan off >/dev/null 2>&1
systemctl --user disable --now igam3-screen.service 2>/dev/null
pkill -f "$DEST/tools/web_panel.py"
rm -f ~/.config/systemd/user/igam3-screen.service ~/.config/systemd/user/igam3-screen-web.service \
      ~/.local/bin/igam3-screen ~/.local/share/applications/igam3-screen.desktop
systemctl --user daemon-reload
echo "Đã gỡ dịch vụ, lệnh, biểu tượng và phím tắt."

echo "Gỡ quy tắc udev của màn hình (cần mật khẩu sudo)..."
sudo rm -f /etc/udev/rules.d/60-igam3-screen.rules && sudo udevadm control --reload-rules

read -r -p "Xoá luôn thư mục $DEST (cả cấu hình, ảnh, mật khẩu)? [c/K] " answer
if [[ "$answer" == [cC] ]]; then
    rm -rf "$DEST"
    echo "Đã xoá $DEST."
else
    echo "Giữ lại $DEST. Cài lại bất cứ lúc nào bằng bộ cài .run."
fi
