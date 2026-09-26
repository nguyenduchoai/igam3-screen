#!/usr/bin/env bash
# Uninstall igam3-screen: stops the screen, removes the services, command, icon, shortcut and udev rule.
# Run: bash ~/igam3-screen/uninstall.sh
set -uo pipefail

case "${LANGUAGE:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}" in vi*) VI=1 ;; *) VI=0 ;; esac
t() { if (( VI )); then printf '%s' "$1"; else printf '%s' "$2"; fi; }  # t "Tiếng Việt" "English"

DEST=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CLI="$DEST/igam3-screen"

"$CLI" shortcut off >/dev/null 2>&1
"$CLI" web --lan off >/dev/null 2>&1
systemctl --user disable --now igam3-screen.service 2>/dev/null
pkill -f "$DEST/tools/web_panel.py"
rm -f ~/.config/systemd/user/igam3-screen.service ~/.config/systemd/user/igam3-screen-web.service \
      ~/.local/bin/igam3-screen ~/.local/share/applications/igam3-screen.desktop
systemctl --user daemon-reload
echo "$(t "Đã gỡ dịch vụ, lệnh, biểu tượng và phím tắt." "Removed the services, command, icon and shortcut.")"

echo "$(t "Gỡ quy tắc udev của màn hình (cần mật khẩu sudo)..." "Removing the udev rule of the screen (needs the sudo password)...")"
sudo rm -f /etc/udev/rules.d/60-igam3-screen.rules && sudo udevadm control --reload-rules

read -r -p "$(t "Xoá luôn thư mục $DEST (cả cấu hình, ảnh, mật khẩu)? [c/K] " \
                 "Also delete the folder $DEST (settings, pictures, password)? [y/N] ")" answer
if [[ "$answer" == [cCyY] ]]; then
    rm -rf "$DEST"
    echo "$(t "Đã xoá" "Deleted") $DEST."
else
    echo "$(t "Giữ lại $DEST. Cài lại bất cứ lúc nào bằng bộ cài .run." "Kept $DEST. Reinstall any time with the .run installer.")"
fi
