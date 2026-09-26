#!/usr/bin/env bash
# Builds igam3-screen. Run it on an Ubuntu computer where it is installed and works (it needs the .venv of that install):
#   bash packaging/build.sh             -> dist/igam3-screen-installer-<VERSION>.run  (Linux, no Internet needed)
#                                         dist/igam3-screen-windows-<VERSION>.zip    (Windows, experimental)
#   bash packaging/build.sh repo FOLDER -> clean source tree for GitHub (nothing that belongs to this computer)
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VERSION=$(cat "$ROOT/VERSION")
for candidate in "$ROOT/.venv/bin/python" "$HOME/igam3-screen/.venv/bin/python"; do
    if [[ -x "$candidate" ]]; then PY="$candidate"; break; fi
done
[[ -n "${PY:-}" ]] || { echo "Needs the Python environment of an install (run install.sh first)" >&2; exit 1; }

# The files an installed copy needs, without anything that belongs to this machine
stage() {
    local dest="$1"
    mkdir -p "$dest/tools"
    cp -a "$ROOT"/{README.md,README.vi.md,VERSION,LICENSE,NOTICE,requirements.txt,requirements.lock} "$dest/"
    cp -a "$ROOT"/{igam3-screen,igam3-screen.cmd,setup-root.sh,install.sh,uninstall.sh} "$dest/"
    cp -a "$ROOT"/{install-windows.ps1,install-windows.cmd,uninstall-windows.ps1} "$dest/"
    cp -a "$ROOT"/{systemd,examples} "$dest/"
    cp -a "$ROOT"/tools/*.py "$ROOT/tools/web" "$dest/tools/"
    "$PY" "$ROOT/packaging/stage_app.py" "$ROOT/app" "$dest/app"
    # Default look of the iGam3 theme (this machine's title and blocks live in custom.yaml, which is not copied).
    # English here; "igam3-screen init" redraws it in the language of the target computer
    IGAM3_LANG=en "$PY" "$dest/app/res/themes/iGam3/make_theme.py" >/dev/null
    rm -rf "$dest/app/res/themes/iGam3/__pycache__"
}

if [[ "${1:-}" == "repo" ]]; then
    REPO=$(realpath -m "${2:?usage: build.sh repo FOLDER}")
    if [[ -e "$REPO" && ! -d "$REPO/.git" && -n "$(ls -A "$REPO" 2>/dev/null)" ]]; then
        echo "$REPO is not empty and not a git repository: choose another folder" >&2
        exit 1
    fi
    mkdir -p "$REPO"
    # Refresh everything except the git history
    find "$REPO" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
    stage "$REPO"
    mkdir -p "$REPO/packaging"
    cp -a "$ROOT"/packaging/{build.sh,stage_app.py,selfextract.sh,make_zip.py} "$REPO/packaging/"
    cp -a "$ROOT"/{docs,.gitignore,.gitattributes} "$REPO/"
    echo "Source tree: $REPO ($(du -sh "$REPO" --exclude=.git | cut -f1))"
    exit 0
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/igam3-screen"

echo "==> Python libraries in use -> requirements.txt / requirements.lock"
"$PY" - "$ROOT" <<'EOF'
import subprocess, sys
from importlib.metadata import version
root = sys.argv[1]
freeze = subprocess.run([sys.executable, "-m", "pip", "freeze", "--disable-pip-version-check"],
                        capture_output=True, text=True, check=True).stdout.splitlines()
with open(f"{root}/requirements.txt", "w", encoding="utf8") as f:
    f.write("# Python libraries of igam3-screen (Linux and Windows), installed from the Internet:\n"
            "#   python -m pip install -r requirements.txt\n"
            "# Made by packaging/build.sh from a tested environment.\n")
    f.write("\n".join(freeze) + "\n" + 'pywin32>=306; sys_platform == "win32"\n')
with open(f"{root}/requirements.lock", "w", encoding="utf8") as f:
    f.write("# The same libraries as name==version: offline install from the wheels/ folder of the Linux .run installer\n")
    for line in freeze:
        name = line.split(" @ ")[0].split("==")[0].strip()
        f.write(f"{name}=={version(name)}\n")
EOF

echo "==> igam3-screen $VERSION"
stage "$STAGE"
mkdir -p "$ROOT/dist"

echo "==> Windows package (.zip, libraries downloaded at install)"
"$PY" "$ROOT/packaging/make_zip.py" "$WORK" "$ROOT/dist/igam3-screen-windows-$VERSION.zip"

echo "==> Linux installer (.run, with the Python libraries for an offline install)"
grep -v '^pywin32' "$ROOT/requirements.txt" > "$WORK/requirements-linux.txt"
"$PY" -m pip wheel --quiet --disable-pip-version-check --wheel-dir "$STAGE/wheels" -r "$WORK/requirements-linux.txt"
"$PY" -m pip download --quiet --disable-pip-version-check --only-binary=:all: --dest "$STAGE/wheels" pip
OUT="$ROOT/dist/igam3-screen-installer-$VERSION.run"
tar -C "$WORK" -czf "$WORK/payload.tar.gz" igam3-screen
cat "$ROOT/packaging/selfextract.sh" "$WORK/payload.tar.gz" > "$OUT"
chmod +x "$OUT"

echo "Done:"
ls -lh "$ROOT/dist/igam3-screen-installer-$VERSION.run" "$ROOT/dist/igam3-screen-windows-$VERSION.zip" | awk '{print "  " $5 "  " $9}'
