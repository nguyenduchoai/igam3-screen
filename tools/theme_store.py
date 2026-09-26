# Community themes: 3.5" themes that people shared in the Themes discussions of turing-smart-screen-python
# (https://github.com/mathoudebine/turing-smart-screen-python/discussions/categories/themes).
# They are not part of igam3-screen: theme_catalog.json only lists where each author published a theme, and a theme
# is downloaded from there when the user installs it. packaging/theme_catalog.py builds and tests the catalog.

import hashlib
import io
import json
import posixpath
import re
import shutil
import urllib.request
import zipfile
from pathlib import Path

CATALOG = Path(__file__).resolve().parent / "theme_catalog.json"
MARKER = ".igam3-store.json"  # in the folder of every theme installed from the catalog
FONTS_MANIFEST = ".igam3-store-fonts.json"  # in the fonts folder: fonts added for community themes
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_MEMBER = 64 * 1024 * 1024
THEME_FILES = {".yaml", ".yml", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}  # never code, whatever the archive holds
FONT_FILES = {".ttf", ".otf"}


class StoreError(Exception):
    pass


def load_catalog():
    try:
        with open(CATALOG, encoding="utf8") as f:
            return json.load(f)["themes"]
    except (OSError, ValueError, KeyError):
        return []


def find(theme_id):
    return next((entry for entry in load_catalog() if entry["id"] == theme_id), None)


def installed_themes(themes_dir):
    """{catalog id: theme folder name} of the themes installed from the catalog"""
    result = {}
    for marker in Path(themes_dir).glob(f"*/{MARKER}"):
        try:
            result[json.loads(marker.read_text(encoding="utf8"))["id"]] = marker.parent.name
        except (OSError, ValueError, KeyError):
            pass
    return result


def download(url, sha256):
    request = urllib.request.Request(url, headers={"User-Agent": "igam3-screen"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(MAX_ARCHIVE + 1)
    if len(data) > MAX_ARCHIVE:
        raise StoreError("archive too large")
    if hashlib.sha256(data).hexdigest() != sha256:
        raise StoreError("the archive changed since the catalog was made (checksum mismatch)")
    return data


def _inside(base, relative):
    path = posixpath.normpath(relative.replace("\\", "/"))
    if path.startswith(("/", "../")) or path in (".", "..") or ":" in path:
        raise StoreError(f"unsafe path in the archive: {relative}")
    return base / path


def fix_font_case(text, fonts_dir):
    """Themes made on Windows may write font paths with the wrong case: Linux needs the exact file name"""
    exact = {str(p.relative_to(fonts_dir)).replace("\\", "/") for p in Path(fonts_dir).rglob("*")
             if p.suffix.lower() in FONT_FILES}
    lower = {path.lower(): path for path in exact}

    def fix(match):
        font = match.group(2)
        if font in exact or font.lower() not in lower:
            return match.group(0)
        return match.group(1) + lower[font.lower()]

    return re.sub(r"^(\s*FONT:\s*[\"']?)([^\s#'\"][^#'\"]*?)(?=[\"']?\s*(#.*)?$)", fix, text, flags=re.M)


def _record_font(fonts_dir, relative):
    """Remember the fonts added for community themes: the installers never ship them (packaging/stage_app.py)"""
    manifest = fonts_dir / FONTS_MANIFEST
    try:
        fonts = set(json.loads(manifest.read_text(encoding="utf8")))
    except (OSError, ValueError):
        fonts = set()
    fonts.add(posixpath.normpath(relative.replace("\\", "/")))
    manifest.write_text(json.dumps(sorted(fonts), indent=1), encoding="utf8")


def install(entry, themes_dir, fonts_dir, data=None, fetch=download):
    """Install one catalog entry (downloaded unless data is given); returns the name of the theme folder"""
    themes_dir, fonts_dir = Path(themes_dir), Path(fonts_dir)
    if data is None:
        data = download(entry["url"], entry["sha256"])
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise StoreError("not a zip archive")
    folder = entry.get("folder", "").strip("/")
    prefix = f"{folder}/" if folder else ""
    name = entry["name"]
    target = themes_dir / name
    if target.exists() and not (target / MARKER).is_file():
        raise StoreError(f"another theme is already named {name}")
    staging = themes_dir / f".{name}.part"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.startswith(prefix) or "__MACOSX" in info.filename:
                continue
            relative = info.filename[len(prefix):]
            if posixpath.splitext(relative)[1].lower() not in THEME_FILES or info.file_size > MAX_MEMBER:
                continue
            dest = _inside(staging, relative)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(archive.read(info))
        # Fonts of turing-smart-screen-python that igam3-screen does not ship: from the upstream repository
        for font in entry.get("upstream_fonts", []):
            dest = _inside(fonts_dir, font["path"])
            if not dest.exists():
                content = fetch(font["url"], font["sha256"])
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
                _record_font(fonts_dir, font["path"])
        # Fonts that come with the theme go next to the other fonts (an existing font is never replaced)
        for font, member in entry.get("fonts", {}).items():
            dest = _inside(fonts_dir, font)
            if not dest.exists():
                if archive.getinfo(member).file_size > MAX_MEMBER:
                    raise StoreError(f"font too large: {member}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.read(member))
                _record_font(fonts_dir, font)
        # The chosen file becomes theme.yaml (a folder can hold several variants, e.g. landscape and portrait)
        source = _inside(staging, entry.get("yaml", "theme.yaml"))
        if not source.is_file():
            raise StoreError("the archive has no theme.yaml for this theme")
        text = source.read_text(encoding="utf-8-sig", errors="replace")
        (staging / "theme.yaml").write_text(fix_font_case(text, fonts_dir), encoding="utf8")
        (staging / MARKER).write_text(json.dumps({"id": entry["id"], "url": entry["url"],
                                                  "discussion": entry.get("discussion", "")}), encoding="utf8")
        shutil.rmtree(target, ignore_errors=True)
        staging.rename(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return name


def remove(theme_id, themes_dir):
    """Delete a theme installed from the catalog; returns its folder name, or None if it is not installed"""
    name = installed_themes(themes_dir).get(theme_id)
    if name:
        shutil.rmtree(Path(themes_dir) / name)
    return name
