#!/usr/bin/env bash
# Bộ cài igam3-screen: quản lý màn hình 3.5" (Turing Smart Screen / TURZX, USB 1a86:5722) của máy iGam3 M1 trên Ubuntu.
# Chạy bằng tài khoản thường (không dùng sudo): bộ cài tự hỏi mật khẩu sudo ở bước cấp quyền.
#   Từ bộ cài một file:  bash igam3-screen-installer-<phiên bản>.run    (không cần Internet)
#   Từ mã nguồn:         git clone ... && bash igam3-screen/install.sh  (tải thư viện Python từ Internet)
# Cài lại / nâng cấp lên bản mới: chạy lại bộ cài, cấu hình, ảnh và mật khẩu đã đặt được giữ nguyên.
set -euo pipefail

SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEST="$HOME/igam3-screen"
INIT_ARGS=()
ROOT_SETUP=1
SERVICE=1

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Cách dùng: bash igam3-screen-installer-*.run [tuỳ chọn]    (hoặc từ mã nguồn: bash install.sh [tuỳ chọn])
  --title "Chữ lớn"   chữ tiêu đề trên bảng thông số (mặc định: iGam3 M1)
  --tag "NHÃN"        nhãn bên cạnh tiêu đề (mặc định: DePIN NODE)
  --dir THƯ_MỤC       nơi cài (mặc định: ~/igam3-screen)
  --skip-root         không chạy bước cần sudo (quyền màn hình, tự chạy khi khởi động)
  --skip-service      chỉ chép chương trình và chuẩn bị Python, không cài dịch vụ
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --title) INIT_ARGS+=(--title "$2"); shift 2 ;;
        --tag) INIT_ARGS+=(--tag "$2"); shift 2 ;;
        --dir) DEST="$2"; shift 2 ;;
        --skip-root) ROOT_SETUP=0; shift ;;
        --skip-service) SERVICE=0; ROOT_SETUP=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "Tuỳ chọn không hợp lệ: $1" ;;
    esac
done

[[ $EUID -ne 0 ]] || die "Hãy chạy bằng tài khoản thường, không dùng sudo. Bộ cài sẽ tự hỏi mật khẩu khi cần."
[[ "$(uname -m)" == "x86_64" ]] || warn "Bộ cài làm cho máy x86_64 (iGam3 M1), máy này là $(uname -m)."
command -v python3 >/dev/null || die "Máy chưa có python3."
command -v systemctl >/dev/null || die "Cần Ubuntu có systemd."
PYVER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if command -v lsusb >/dev/null && ! lsusb -d 1a86:5722 >/dev/null 2>&1; then
    warn "Chưa thấy màn hình USB 1a86:5722 (Turing/TURZX 3.5\"). Vẫn cài; màn sẽ chạy khi máy nhận được màn."
fi

DEST=$(realpath -m "$DEST")
say "igam3-screen $(cat "$SRC/VERSION") → $DEST"

# Upgrade: keep what the user set on this machine
KEEP=(app/config.yaml app/res/themes/iGam3/custom.yaml settings.yaml web.yaml images uploads)
BACKUP=$(mktemp -d)
trap 'rm -rf "$BACKUP"' EXIT
if [[ -f "$DEST/tools/igam3_screen.py" ]]; then
    say "Đã có bản cài: nâng cấp, giữ nguyên cấu hình, ảnh và mật khẩu"
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

say "Chép chương trình"
mkdir -p "$DEST"
if [[ "$SRC" != "$DEST" ]]; then
    # From a git clone: not the repository metadata, build outputs or a developer venv
    tar -C "$SRC" --exclude=./.git --exclude=./dist --exclude=./.venv -cf - . | tar -C "$DEST" -xf -
fi
cp -a "$BACKUP/." "$DEST/"

# Libraries: from wheels/ when installing from the .run bundle (no Internet needed), else from PyPI
WHEELS="$DEST/wheels"
if [[ -d "$WHEELS" ]]; then
    say "Chuẩn bị Python $PYVER (dùng thư viện đóng gói sẵn, không cần Internet)"
else
    say "Chuẩn bị Python $PYVER (tải thư viện từ Internet)"
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
            "$GET_PIP" || die "Không tải được pip. Kiểm tra mạng rồi chạy lại bộ cài."
        "$VENV/bin/python" "$GET_PIP" --quiet --disable-pip-version-check
    fi
fi
PIP=("$VENV/bin/python" -m pip install --quiet --disable-pip-version-check)
if ! { [[ -d "$WHEELS" ]] && "${PIP[@]}" --no-index --find-links "$WHEELS" -r "$DEST/requirements.lock"; }; then
    if [[ -d "$WHEELS" ]]; then
        warn "Thư viện đóng gói sẵn không hợp với Python $PYVER của máy này: tải từ Internet..."
    fi
    "${PIP[@]}" -r "$DEST/requirements.txt" || die "Không cài được thư viện Python. Kiểm tra mạng rồi chạy lại bộ cài."
fi

say "Cấu hình cho máy này"
"$DEST/igam3-screen" init "${INIT_ARGS[@]}"

if (( SERVICE )); then
    say "Cài dịch vụ màn hình, lệnh igam3-screen và biểu tượng \"iGam3 Screen\""
    "$DEST/igam3-screen" install
    if gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings >/dev/null 2>&1; then
        "$DEST/igam3-screen" shortcut on || true
    fi
fi

if (( ROOT_SETUP )); then
    say "Cấp quyền dùng màn hình và bật màn hình (cần mật khẩu sudo)"
    sudo "$DEST/setup-root.sh"
elif (( SERVICE )); then
    systemctl --user enable --now igam3-screen.service ||
        warn "Chưa bật được màn hình. Chạy: sudo $DEST/setup-root.sh"
fi

echo
say "Xong! igam3-screen $(cat "$DEST/VERSION") đã cài ở $DEST"
cat <<EOF
  - Màn hình nhỏ hiện bảng thông số sau khoảng 10 giây.
  - Giao diện quản lý: biểu tượng "iGam3 Screen" trong menu ứng dụng, hoặc lệnh: igam3-screen panel
  - Dùng từ điện thoại: igam3-screen web --password  rồi  igam3-screen web --lan on
  - Phím tắt Ctrl+Alt+Q: hiện mã QR trên màn nhỏ
  - Hướng dẫn đầy đủ: $DEST/README.md
  Lệnh igam3-screen có sẵn từ lần đăng nhập sau; trước đó gọi: $DEST/igam3-screen
EOF
