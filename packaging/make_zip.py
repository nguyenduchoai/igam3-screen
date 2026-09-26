# Windows .zip package from the staged folder: <parent>/igam3-screen -> <out>.zip
# Usage: make_zip.py <parent dir> <out.zip>
import sys
import zipfile
from pathlib import Path

parent, out = Path(sys.argv[1]), Path(sys.argv[2])
root = parent / "igam3-screen"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        data = path.read_bytes()
        if path.suffix in (".cmd", ".ps1"):
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")  # Windows line endings
        zf.writestr(str(path.relative_to(parent)), data)
print(f"{out.name}: {sum(1 for _ in zipfile.ZipFile(out).namelist())} files")
