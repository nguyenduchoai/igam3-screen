# Copies what the 3.5" screen needs from turing-smart-screen-python (app/) into the installer, without this machine's data.
# Usage: stage_app.py <app dir> <destination>
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

STORE_MARKER = ".igam3-store.json"  # tools/theme_store.py: themes of other authors installed on this machine
STORE_FONTS = ".igam3-store-fonts.json"  # tools/theme_store.py: fonts added for them

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
FILES = ["main.py", "configure.py", "theme-editor.py", "config.yaml", "requirements.txt", "LICENSE", "AUTHORS",
         "COPYRIGHT", "README.md"]
FONT_DIRS = ["roboto", "roboto-mono", "jetbrains-mono", "generale-mono"]  # every font used by the packaged themes
SKIP_THEMES = {"Terminal"}  # uses the GeForce font, which comes without a licence file
# Files that belong to this machine (settings, uploads, logs) or are only build leftovers
ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.orig", "log.log", "screencap.png", "custom.yaml",
                                "photo.*", "*_preview.png")

dst.mkdir(parents=True)
for name in FILES:
    shutil.copy2(src / name, dst / name)
shutil.copytree(src / "library", dst / "library", ignore=ignore)
shutil.copytree(src / "res" / "icons", dst / "res" / "icons", ignore=ignore)
# Fonts added for community themes are never shipped
try:
    store_fonts = set(json.loads((src / "res" / "fonts" / STORE_FONTS).read_text(encoding="utf8")))
except (OSError, ValueError):
    store_fonts = set()
for name in FONT_DIRS:
    font_dir = src / "res" / "fonts" / name
    skip = lambda folder, names: ignore(folder, names) | {
        n for n in names if str((Path(folder) / n).relative_to(src / "res" / "fonts")).replace("\\", "/") in store_fonts}
    shutil.copytree(font_dir, dst / "res" / "fonts" / name, ignore=skip)

themes = src / "res" / "themes"
(dst / "res" / "themes").mkdir(parents=True)
for name in ("default.yaml", "theme_example.yaml"):
    shutil.copy2(themes / name, dst / "res" / "themes" / name)
count = 0
for theme in sorted(themes.iterdir()):
    # Community themes installed on this machine belong to their authors: never shipped
    if theme.name in SKIP_THEMES or not (theme / "theme.yaml").is_file() or (theme / STORE_MARKER).exists():
        continue
    with open(theme / "theme.yaml", encoding="utf8") as f:
        size = str(((yaml.safe_load(f) or {}).get("display") or {}).get("DISPLAY_SIZE", '3.5"'))
    if size == '3.5"':
        shutil.copytree(theme, dst / "res" / "themes" / theme.name, ignore=ignore)
        count += 1

# A new machine starts from the iGam3 defaults, not from the choices made on this one.
# Network cards differ between machines: "igam3-screen init" detects them on the target.
DEFAULTS = {"COM_PORT": '"AUTO"', "THEME": "iGam3", "ETH": '""', "WLO": '""', "REVISION": "A", "BRIGHTNESS": "50",
            "DISPLAY_REVERSE": "true", "RESET_ON_STARTUP": "true"}  # the screen of the iGam3 M1 is mounted upside down
config = (dst / "config.yaml").read_text(encoding="utf8")
for key, value in DEFAULTS.items():
    config, found = re.subn(rf'^(  {key}: )("[^"]*"|[^\s#]*)', lambda m: m.group(1) + value, config, count=1,
                            flags=re.M)
    if not found:
        sys.exit(f"config.yaml: {key} not found")
(dst / "config.yaml").write_text(config, encoding="utf8")
print(f"app: {count} 3.5\" themes, {len(FONT_DIRS)} font families")
