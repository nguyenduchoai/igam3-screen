# Vietnamese / English.
# Language = IGAM3_LANG environment variable if set, else "language" in settings.yaml (vi, en or auto),
# where auto (the default) follows the language of the system: Vietnamese systems get Vietnamese, others English.

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "settings.yaml"
LANGUAGES = ("vi", "en")


def system_language():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return "vi" if value.lower().startswith("vi") else "en"
    if sys.platform == "win32":
        try:
            import ctypes
            primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return "vi" if primary == 0x2A else "en"  # LANG_VIETNAMESE
        except (AttributeError, OSError):
            pass
    return "en"


def language_setting():
    """'auto', 'vi' or 'en' as stored in settings.yaml"""
    try:
        import yaml
        with open(SETTINGS, encoding="utf8") as f:
            value = str((yaml.safe_load(f) or {}).get("language", "auto"))
    except Exception:  # missing or broken settings file
        value = "auto"
    return value if value in LANGUAGES else "auto"


def resolve():
    forced = os.environ.get("IGAM3_LANG")
    if forced in LANGUAGES:
        return forced
    setting = language_setting()
    return setting if setting in LANGUAGES else system_language()


LANG = resolve()


def refresh():
    """Pick up a language changed in settings.yaml (long-running web panel)"""
    global LANG
    LANG = resolve()
    return LANG


def tr(vi, en):
    return vi if LANG == "vi" else en
