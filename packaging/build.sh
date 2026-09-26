#!/usr/bin/env bash
# Đóng gói igam3-screen. Chạy trên máy Ubuntu đã cài và chạy ổn (cần môi trường Python .venv của bản cài):
#   bash packaging/build.sh              -> dist/igam3-screen-installer-<VERSION>.run  (Linux, không cần Internet)
#                                          dist/igam3-screen-windows-<VERSION>.zip    (Windows, thử nghiệm)
#   bash packaging/build.sh repo THƯ_MỤC -> cây mã nguồn sạch để đưa lên GitHub (không có dữ liệu riêng của máy)
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VERSION=$(cat "$ROOT/VERSION")
for candidate in "$ROOT/.venv/bin/python" "$HOME/igam3-screen/.venv/bin/python"; do
    if [[ -x "$candidate" ]]; then PY="$candidate"; break; fi
done
[[ -n "${PY:-}" ]] || { echo "Cần môi trường Python của một bản cài (chạy install.sh trước)" >&2; exit 1; }

# The files an installed copy needs, without anything that belongs to this machine
stage() {
    local dest="$1"
    mkdir -p "$dest/tools"
    cp -a "$ROOT"/{README.md,VERSION,LICENSE,NOTICE,requirements.txt,requirements.lock} "$dest/"
    cp -a "$ROOT"/{igam3-screen,igam3-screen.cmd,setup-root.sh,install.sh,uninstall.sh} "$dest/"
    cp -a "$ROOT"/{install-windows.ps1,install-windows.cmd,uninstall-windows.ps1} "$dest/"
    cp -a "$ROOT"/{systemd,examples} "$dest/"
    cp -a "$ROOT"/tools/*.py "$ROOT/tools/web" "$dest/tools/"
    "$PY" "$ROOT/packaging/stage_app.py" "$ROOT/app" "$dest/app"
    # Default look of the iGam3 theme (this machine's title and blocks live in custom.yaml, which is not copied)
    "$PY" "$dest/app/res/themes/iGam3/make_theme.py" >/dev/null
    rm -rf "$dest/app/res/themes/iGam3/__pycache__"
}

if [[ "${1:-}" == "repo" ]]; then
    REPO=$(realpath -m "${2:?Cách dùng: build.sh repo THƯ_MỤC}")
    if [[ -e "$REPO" && ! -d "$REPO/.git" && -n "$(ls -A "$REPO" 2>/dev/null)" ]]; then
        echo "$REPO đã có dữ liệu và không phải repo git: chọn thư mục khác" >&2
        exit 1
    fi
    mkdir -p "$REPO"
    # Refresh everything except the git history
    find "$REPO" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
    stage "$REPO"
    mkdir -p "$REPO/packaging"
    cp -a "$ROOT"/packaging/{build.sh,stage_app.py,selfextract.sh,make_zip.py} "$REPO/packaging/"
    cp -a "$ROOT"/{docs,.gitignore,.gitattributes} "$REPO/"
    echo "Cây mã nguồn: $REPO ($(du -sh "$REPO" --exclude=.git | cut -f1))"
    exit 0
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/igam3-screen"

echo "==> Thư viện Python đang dùng -> requirements.txt / requirements.lock"
"$PY" - "$ROOT" <<'EOF'
import subprocess, sys
from importlib.metadata import version
root = sys.argv[1]
freeze = subprocess.run([sys.executable, "-m", "pip", "freeze", "--disable-pip-version-check"],
                        capture_output=True, text=True, check=True).stdout.splitlines()
with open(f"{root}/requirements.txt", "w", encoding="utf8") as f:
    f.write("# Thư viện Python của igam3-screen (Linux và Windows), cài qua Internet:\n"
            "#   python -m pip install -r requirements.txt\n"
            "# Tạo lại bằng packaging/build.sh từ môi trường đã chạy thử.\n")
    f.write("\n".join(freeze) + "\n" + 'pywin32>=306; sys_platform == "win32"\n')
with open(f"{root}/requirements.lock", "w", encoding="utf8") as f:
    f.write("# Cùng các thư viện, dạng tên==phiên bản: cài không cần Internet từ thư mục wheels/ của bộ cài Linux .run\n")
    for line in freeze:
        name = line.split(" @ ")[0].split("==")[0].strip()
        f.write(f"{name}=={version(name)}\n")
EOF

echo "==> Chương trình igam3-screen $VERSION"
stage "$STAGE"
mkdir -p "$ROOT/dist"

echo "==> Gói Windows (.zip, thư viện tải khi cài)"
"$PY" "$ROOT/packaging/make_zip.py" "$WORK" "$ROOT/dist/igam3-screen-windows-$VERSION.zip"

echo "==> Bộ cài Linux (.run, kèm thư viện Python để cài không cần Internet)"
grep -v '^pywin32' "$ROOT/requirements.txt" > "$WORK/requirements-linux.txt"
"$PY" -m pip wheel --quiet --disable-pip-version-check --wheel-dir "$STAGE/wheels" -r "$WORK/requirements-linux.txt"
"$PY" -m pip download --quiet --disable-pip-version-check --only-binary=:all: --dest "$STAGE/wheels" pip
OUT="$ROOT/dist/igam3-screen-installer-$VERSION.run"
tar -C "$WORK" -czf "$WORK/payload.tar.gz" igam3-screen
cat "$ROOT/packaging/selfextract.sh" "$WORK/payload.tar.gz" > "$OUT"
chmod +x "$OUT"

echo "Xong:"
ls -lh "$ROOT/dist/igam3-screen-installer-$VERSION.run" "$ROOT/dist/igam3-screen-windows-$VERSION.zip" | awk '{print "  " $5 "  " $9}'
