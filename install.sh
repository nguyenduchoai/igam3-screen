#!/usr/bin/env bash
# igam3-screen installer: manager of the 3.5" screen (Turing Smart Screen / TURZX, USB 1a86:5722) of the iGam3 M1, on Ubuntu.
# Run it as a normal user (not with sudo): it asks for the sudo password itself when it needs it.
#   From the one-file installer:  bash igam3-screen-installer-<version>.run    (no Internet needed)
#   From the source code:         git clone ... && bash igam3-screen/install.sh  (downloads the Python libraries)
# Reinstall / upgrade: run the installer again, the settings, pictures and password are kept.
# Messages are in Vietnamese on Vietnamese systems, in English otherwise (or: --lang vi|en).
set -euo pipefail

SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEST="$HOME/igam3-screen"
INIT_ARGS=()
ROOT_SETUP=1
SERVICE=1
case "${LANGUAGE:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}" in vi*) VI=1 ;; *) VI=0 ;; esac
for ((i = 1; i < $#; i++)); do  # --lang first: it decides the language of the messages below
    if [[ "${!i}" == "--lang" ]]; then j=$((i + 1)); [[ "${!j}" == "vi" ]] && VI=1 || VI=0; fi
done

t() { if (( VI )); then printf '%s' "$1"; else printf '%s' "$2"; fi; }  # t "Tiếng Việt" "English"
say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
    if (( VI )); then
        cat <<'EOF'
Cách dùng: bash igam3-screen-installer-*.run [tuỳ chọn]    (hoặc từ mã nguồn: bash install.sh [tuỳ chọn])
  --title "Chữ lớn"   chữ tiêu đề trên bảng thông số (mặc định: Hoài Nguyễn)
  --tag "NHÃN"        nhãn bên cạnh tiêu đề (mặc định: Bizino.AI)
  --lang vi|en        ngôn ngữ (mặc định: theo ngôn ngữ của máy)
  --dir THƯ_MỤC       nơi cài (mặc định: ~/igam3-screen)
  --skip-root         không chạy bước cần sudo (quyền màn hình, tự chạy khi khởi động)
  --skip-service      chỉ chép chương trình và chuẩn bị Python, không cài dịch vụ
EOF
    else
        cat <<'EOF'
Usage: bash igam3-screen-installer-*.run [options]    (or from the source code: bash install.sh [options])
  --title "Big text"  title of the dashboard (default: Hoài Nguyễn)
  --tag "TAG"         tag next to the title (default: Bizino.AI)
  --lang vi|en        language (default: the language of the system)
  --dir FOLDER        where to install (default: ~/igam3-screen)
  --skip-root         skip the step that needs sudo (screen permission, start at boot)
  --skip-service      only copy the program and prepare Python, no service
EOF
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --title) INIT_ARGS+=(--title "$2"); shift 2 ;;
        --tag) INIT_ARGS+=(--tag "$2"); shift 2 ;;
        --lang) [[ "$2" == vi || "$2" == en ]] || { usage; die "--lang vi|en"; }; INIT_ARGS+=(--language "$2"); shift 2 ;;
        --dir) DEST="$2"; shift 2 ;;
        --skip-root) ROOT_SETUP=0; shift ;;
        --skip-service) SERVICE=0; ROOT_SETUP=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "$(t "Tuỳ chọn không hợp lệ" "Invalid option"): $1" ;;
    esac
done

[[ $EUID -ne 0 ]] || die "$(t "Hãy chạy bằng tài khoản thường, không dùng sudo. Bộ cài sẽ tự hỏi mật khẩu khi cần." \
                           "Run this as a normal user, without sudo. The installer asks for the password when needed.")"
[[ "$(uname -m)" == "x86_64" ]] || warn "$(t "Bộ cài làm cho máy x86_64 (iGam3 M1), máy này là" \
                                           "This installer is made for x86_64 (iGam3 M1), this computer is") $(uname -m)."
command -v python3 >/dev/null || die "$(t "Máy chưa có python3." "python3 is missing.")"
command -v systemctl >/dev/null || die "$(t "Cần Ubuntu có systemd." "A Linux with systemd is required.")"
PYVER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if command -v lsusb >/dev/null && ! lsusb -d 1a86:5722 >/dev/null 2>&1; then
    warn "$(t "Chưa thấy màn hình USB 1a86:5722 (Turing/TURZX 3.5\"). Vẫn cài; màn sẽ chạy khi máy nhận được màn." \
              "No USB screen 1a86:5722 (Turing/TURZX 3.5\") found. Installing anyway; it starts once the screen is detected.")"
fi

DEST=$(realpath -m "$DEST")
say "igam3-screen $(cat "$SRC/VERSION") → $DEST"

# Upgrade: keep what the user set on this machine
KEEP=(app/config.yaml app/res/themes/iGam3/custom.yaml settings.yaml web.yaml telegram.yaml images uploads)
BACKUP=$(mktemp -d)
trap 'rm -rf "$BACKUP"' EXIT
if [[ -f "$DEST/tools/igam3_screen.py" ]]; then
    say "$(t "Đã có bản cài: nâng cấp, giữ nguyên cấu hình, ảnh và mật khẩu" \
             "Already installed: upgrading, keeping the settings, pictures and password")"
    if (( SERVICE )); then
        systemctl --user stop igam3-screen.service 2>/dev/null || true
    fi
    (
        cd "$DEST"
        for item in "${KEEP[@]}" app/res/themes/iGam3/photo.*; do
            if [[ -e "$item" ]]; then cp -a --parents "$item" "$BACKUP/"; fi
        done
    )
fi

say "$(t "Chép chương trình" "Copying the program")"
mkdir -p "$DEST"
if [[ "$SRC" != "$DEST" ]]; then
    # From a git clone: not the repository metadata, build outputs or a developer venv
    tar -C "$SRC" --exclude=./.git --exclude=./dist --exclude=./.venv -cf - . | tar -C "$DEST" -xf -
fi
cp -a "$BACKUP/." "$DEST/"

# Libraries: from wheels/ when installing from the .run bundle (no Internet needed), else from PyPI
WHEELS="$DEST/wheels"
if [[ -d "$WHEELS" ]]; then
    say "$(t "Chuẩn bị Python $PYVER (dùng thư viện đóng gói sẵn, không cần Internet)" \
             "Preparing Python $PYVER (bundled libraries, no Internet needed)")"
else
    say "$(t "Chuẩn bị Python $PYVER (tải thư viện từ Internet)" "Preparing Python $PYVER (downloading the libraries)")"
fi
VENV="$DEST/.venv"
if [[ -x "$VENV/bin/python" ]] && [[ "$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" != "$PYVER" ]]; then
    rm -rf "$VENV"  # Python of the system changed since the last install
fi
# --without-pip: works even when Ubuntu's python3-venv package (ensurepip) is not installed
[[ -x "$VENV/bin/python" ]] || python3 -m venv --without-pip "$VENV"
if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    if PIP_WHEEL=$(ls "$WHEELS"/pip-*.whl 2>/dev/null | head -1) && [[ -n "$PIP_WHEEL" ]]; then
        "$VENV/bin/python" "$PIP_WHEEL/pip" install --quiet --disable-pip-version-check --no-index \
            --find-links "$WHEELS" pip
    else
        GET_PIP="$BACKUP/get-pip.py"
        python3 -c 'import sys, urllib.request; urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", sys.argv[1])' \
            "$GET_PIP" || die "$(t "Không tải được pip. Kiểm tra mạng rồi chạy lại bộ cài." \
                                   "Cannot download pip. Check the network and run the installer again.")"
        "$VENV/bin/python" "$GET_PIP" --quiet --disable-pip-version-check
    fi
fi
PIP=("$VENV/bin/python" -m pip install --quiet --disable-pip-version-check)
if ! { [[ -d "$WHEELS" ]] && "${PIP[@]}" --no-index --find-links "$WHEELS" -r "$DEST/requirements.lock"; }; then
    if [[ -d "$WHEELS" ]]; then
        warn "$(t "Thư viện đóng gói sẵn không hợp với Python $PYVER của máy này: tải từ Internet..." \
                  "The bundled libraries do not fit Python $PYVER of this computer: downloading them...")"
    fi
    "${PIP[@]}" -r "$DEST/requirements.txt" || die "$(t "Không cài được thư viện Python. Kiểm tra mạng rồi chạy lại bộ cài." \
                                                        "Cannot install the Python libraries. Check the network and run the installer again.")"
fi

say "$(t "Cấu hình cho máy này" "Settings for this computer")"
"$DEST/igam3-screen" init "${INIT_ARGS[@]}"

if (( SERVICE )); then
    say "$(t "Cài dịch vụ màn hình, lệnh igam3-screen và biểu tượng \"iGam3 Screen\"" \
             "Installing the screen service, the igam3-screen command and the \"iGam3 Screen\" icon")"
    "$DEST/igam3-screen" install
    if gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings >/dev/null 2>&1; then
        "$DEST/igam3-screen" shortcut on || true
    fi
fi

if (( ROOT_SETUP )); then
    say "$(t "Cấp quyền dùng màn hình và bật màn hình (cần mật khẩu sudo)" \
             "Screen permission and start (needs the sudo password)")"
    sudo "$DEST/setup-root.sh" --lang "$(t vi en)"
elif (( SERVICE )); then
    systemctl --user enable --now igam3-screen.service ||
        warn "$(t "Chưa bật được màn hình. Chạy:" "The screen did not start. Run:") sudo $DEST/setup-root.sh"
fi

echo
if (( VI )); then
    say "Xong! igam3-screen $(cat "$DEST/VERSION") đã cài ở $DEST"
    cat <<EOF
  - Màn hình nhỏ hiện bảng thông số sau khoảng 10 giây.
  - Giao diện quản lý: biểu tượng "iGam3 Screen" trong menu ứng dụng, hoặc lệnh: igam3-screen panel
  - Dùng từ điện thoại: igam3-screen web --password  rồi  igam3-screen web --lan on
  - Phím tắt Ctrl+Alt+Q: hiện mã QR trên màn nhỏ
  - Đổi ngôn ngữ: igam3-screen language en   (hoặc vi, auto)
  - Hướng dẫn đầy đủ: $DEST/README.vi.md
  Lệnh igam3-screen có sẵn từ lần đăng nhập sau; trước đó gọi: $DEST/igam3-screen
EOF
else
    say "Done! igam3-screen $(cat "$DEST/VERSION") is installed in $DEST"
    cat <<EOF
  - The small screen shows the dashboard in about 10 seconds.
  - Web panel: the "iGam3 Screen" icon in the application menu, or the command: igam3-screen panel
  - From a phone: igam3-screen web --password  then  igam3-screen web --lan on
  - Shortcut Ctrl+Alt+Q: QR code on the small screen
  - Language: igam3-screen language vi   (or en, auto)
  - Full guide: $DEST/README.md
  The igam3-screen command is available from the next login; until then use: $DEST/igam3-screen
EOF
fi
