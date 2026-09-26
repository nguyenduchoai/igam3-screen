#!/usr/bin/env python3
# Builds tools/theme_catalog.json: the 3.5" community themes of the Themes discussions of turing-smart-screen-python
# that install and run with igam3-screen. Only links, checksums and install instructions go into the catalog: the
# themes themselves stay with their authors and are downloaded by "igam3-screen store install" on the user's computer.
#
#   python packaging/theme_catalog.py [--cache DIR] [--workers 4] [--no-test]
#
# Needs the GitHub CLI (gh, logged in) to read the discussions, and an installed igam3-screen (.venv) to test the
# themes in the screen simulator of turing-smart-screen-python.

import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import posixpath
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import theme_store  # noqa: E402

REPO = "mathoudebine/turing-smart-screen-python"
UPSTREAM_TAG = "3.10.0"  # the version igam3-screen ships in app/
THEMES_CATEGORY = "DIC_kwDOFinNbM4CA3mR"
DISCUSSIONS = f"https://github.com/{REPO}/discussions"
PACKAGED_FONTS = {"roboto", "roboto-mono", "jetbrains-mono", "generale-mono"}  # packaging/stage_app.py FONT_DIRS
ARCHIVE = re.compile(r"https://github\.com/(?:[\w.-]+/[\w.-]+/files/\d+|user-attachments/files/\d+)/[^\s)\]\"'<>]+?\.zip", re.I)
IMAGE = re.compile(r"https://(?:user-images\.githubusercontent\.com/\d+/[^\s)\"'<>]+?\.(?:png|jpe?g|gif|webp)"
                   r"|github\.com/user-attachments/assets/[0-9a-f-]{36}"
                   r"|github\.com/[\w.-]+/[\w.-]+/assets/\d+/[0-9a-f-]{36})", re.I)
# Themes whose theme.yaml sits at the root of the archive get the name of their discussion: better names
RENAME = {(897, "example.zip"): "c0ldJS Dashboard", (628, "PurpleGraphs.zip"): "Purple Graphs",
          (58, "ironman.zip"): "Iron Man", (759, "Persona3_Reload(no_font)"): "Persona 3 Reload"}
# Modified versions posted in someone else's discussion that differ enough to be listed next to the original
VARIANTS = {(538, "DigitalLandscape", "DJRoby19"), (291, "Fallout", "jbovatsek"),
            (284, "Material_Dark_Full_Portrait", "Adzzzzzzzzz")}


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def graphql(query, **variables):
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is not None:
            args += ["-f", f"{key}={value}"]
    return json.loads(subprocess.run(args, capture_output=True, text=True, check=True).stdout)["data"]


def fetch_discussions():
    query = '''query($cursor: String) { repository(owner: "%s", name: "%s") {
      discussions(first: 25, after: $cursor, categoryId: "%s", orderBy: {field: CREATED_AT, direction: DESC}) {
        pageInfo { hasNextPage endCursor }
        nodes { number title createdAt author { login } body
          comments(first: 100) { nodes { author { login } createdAt body
            replies(first: 50) { nodes { author { login } createdAt body } } } } } } } }''' % (*REPO.split("/"), THEMES_CATEGORY)
    nodes, cursor = [], None
    while True:
        page = graphql(query, cursor=cursor)["repository"]["discussions"]
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return nodes
        cursor = page["pageInfo"]["endCursor"]


def posts(discussion):
    """(author, date, text) of the discussion body, its comments and their replies"""
    login = lambda node: (node.get("author") or {}).get("login") or "ghost"
    yield login(discussion), discussion["createdAt"], discussion["body"] or ""
    for comment in discussion["comments"]["nodes"]:
        yield login(comment), comment["createdAt"], comment["body"] or ""
        for reply in comment["replies"]["nodes"]:
            yield login(reply), reply["createdAt"], reply["body"] or ""


def download(url, cache):
    path = cache / "archives" / hashlib.sha256(url.encode()).hexdigest()[:20]
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "igam3-screen theme catalog"})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read(theme_store.MAX_ARCHIVE + 1)
        except OSError as e:
            log(f"  cannot download {url}: {e}")
            return None
        if len(data) > theme_store.MAX_ARCHIVE:
            return None
        path.write_bytes(data)
    return path


class UpstreamFonts:
    """Fonts of turing-smart-screen-python UPSTREAM_TAG (igam3-screen only ships PACKAGED_FONTS)"""

    def __init__(self, cache):
        tree = json.loads(subprocess.run(["gh", "api", f"repos/{REPO}/git/trees/{UPSTREAM_TAG}?recursive=1"],
                                         capture_output=True, text=True, check=True).stdout)["tree"]
        self.paths = {item["path"][len("res/fonts/"):] for item in tree
                      if item["path"].startswith("res/fonts/") and item["path"].lower().endswith((".ttf", ".otf"))}
        self.lower = {path.lower(): path for path in self.paths}
        self.cache = cache / "fonts"

    def url(self, path):
        return f"https://raw.githubusercontent.com/{REPO}/{UPSTREAM_TAG}/res/fonts/{urllib.parse.quote(path)}"

    def content(self, path):
        local = self.cache / path
        if not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(self.url(path), timeout=120) as response:
                local.write_bytes(response.read())
        return local.read_bytes()


def walk(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key), value
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def shows(node, prefix):
    return any(key == "SHOW" and value is True for key, value in walk(node.get(prefix) or {}))


def analyse(archive_path, link, fonts):
    """Candidate catalog entries (3.5" themes whose images and fonts are all available) and the rejected ones"""
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile:
        return [], []
    names = [n for n in archive.namelist() if not n.endswith("/") and "__MACOSX" not in n]
    by_base = {}
    for n in names:
        by_base.setdefault(posixpath.basename(n).lower(), n)
    entries, rejected = [], []
    with_theme_yaml = {posixpath.dirname(n) for n in names if posixpath.basename(n).lower() == "theme.yaml"}
    for member in names:
        base = posixpath.basename(member)
        if posixpath.splitext(base)[1].lower() not in (".yaml", ".yml") or base.lower() == "config.yaml":
            continue
        # Other theme files only count in a folder without theme.yaml (variants such as astra_3half_h.yaml)
        if base.lower() != "theme.yaml" and posixpath.dirname(member) in with_theme_yaml:
            continue
        try:
            data = yaml.safe_load(archive.read(member).decode("utf-8-sig", errors="replace"))
        except Exception:
            continue
        if not isinstance(data, dict) or "STATS" not in data:
            continue
        display = data.get("display") or {}
        if str(display.get("DISPLAY_SIZE", '3.5"')) != '3.5"':
            continue
        folder = posixpath.dirname(member)
        inside = {posixpath.normpath(posixpath.relpath(n, folder) if folder else n) for n in names
                  if not folder or n.startswith(folder + "/")}
        stats = data.get("STATS") or {}
        images, used_fonts = set(), set()
        for key, value in walk(data):
            if isinstance(value, str):
                if key.upper() == "FONT":
                    used_fonts.add(value.replace("\\", "/").strip())
                elif (key.upper() == "PATH" or "IMAGE" in key.upper()) and re.search(r"\.(png|jpe?g|gif|bmp|webp)$", value, re.I):
                    images.add(posixpath.normpath(value.replace("\\", "/")))
        title = posixpath.basename(folder) if folder else link["zip_name"]
        if base.lower() != "theme.yaml":
            title = f"{title} {str(display.get('DISPLAY_ORIENTATION', 'portrait')).capitalize()}"
        reason = None
        if any(key.startswith("CUSTOM") for key in stats) and shows(stats, "CUSTOM"):
            reason = "custom data sources (needs the author's Python code)"
        elif images - inside:
            reason = f"missing pictures {sorted(images - inside)[:3]}"
        from_zip, upstream, missing = {}, [], []
        for font in sorted(used_fonts):
            exact = fonts.lower.get(font.lower())
            if exact and exact.split("/")[0] in PACKAGED_FONTS:
                continue
            member_font = by_base.get(posixpath.basename(font).lower())
            if member_font and posixpath.splitext(member_font)[1].lower() in theme_store.FONT_FILES:
                from_zip[font] = member_font
            elif exact:
                upstream.append(exact)
            else:
                missing.append(font)
        if not reason and missing:
            reason = f"missing fonts {missing}"
        entry = {**link, "folder": folder, "yaml": base, "title_guess": title, "fonts": from_zip,
                 "upstream_font_paths": upstream, "orientation": str(display.get("DISPLAY_ORIENTATION", "portrait")),
                 "gpu": shows(stats, "GPU"), "content": content_hash(archive, folder, member)}
        (rejected if reason else entries).append({**entry, "reason": reason} if reason else entry)
    return entries, rejected


def content_hash(archive, folder, yaml_member):
    digest = hashlib.sha256(archive.read(yaml_member))
    for n in sorted(archive.namelist()):
        if (not folder or n.startswith(folder + "/")) and posixpath.splitext(n)[1].lower() in theme_store.THEME_FILES \
                and not n.lower().endswith((".yaml", ".yml")):
            digest.update(hashlib.sha256(archive.read(n)).digest())
    return digest.hexdigest()


def select(entries):
    """One entry per theme: identical uploads once, and the newest upload of a theme within a discussion"""
    unique = {}
    for e in sorted(entries, key=lambda e: (e["poster"] != e["op"], e["date"], e["discussion"])):
        unique.setdefault(e["content"], e)
    newest = {}
    for e in sorted(unique.values(), key=lambda e: e["date"], reverse=True):
        key = (e["discussion"], e["title_guess"].lower())
        if (e["discussion"], e["title_guess"], e["poster"]) in VARIANTS:
            key += (e["poster"],)
        newest.setdefault(key, e)
    return sorted(newest.values(), key=lambda e: (-e["discussion"], e["title_guess"].lower()))


def name_entries(entries, bundled):
    used = {name.lower() for name in bundled}
    for e in sorted(entries, key=lambda e: (e["discussion"], e["date"])):
        base = RENAME.get((e["discussion"], e["zip_name"]), RENAME.get((e["discussion"], e["title_guess"])))
        if not base:
            base = e["title_guess"] if (e["folder"] or e["yaml"].lower() != "theme.yaml") else e["discussion_title"]
        base = re.sub(r"[\\/:*?\"<>|]+", " ", base).strip()[:40] or "Theme"
        name, n = base, 2
        if name.lower() in used:
            name = f"{base} ({e['poster']})"
        while name.lower() in used:
            name, n = f"{base} ({e['poster']} {n})", n + 1
        used.add(name.lower())
        e["name"] = name
        e["id"] = re.sub(r"[^a-z0-9]+", "-", f"{e['discussion']}-{name}".lower()).strip("-")[:60]


def test_themes(entries, fonts, workers):
    """Install every entry with theme_store into a simulator sandbox and run it; returns {id: error or None}"""
    python = str(ROOT / ".venv" / "bin" / "python")
    if not Path(python).exists():
        python = str(Path.home() / "igam3-screen" / ".venv" / "bin" / "python")
    work = Path(os.environ.get("TMPDIR", "/tmp")) / f"igam3-theme-test-{os.getpid()}"
    sandboxes = []
    for i in range(workers):
        sandbox = work / f"sandbox{i}"
        subprocess.run([python, str(ROOT / "packaging" / "stage_app.py"), str(ROOT / "app"), str(sandbox / "app")],
                       check=True, capture_output=True)
        shutil.copytree(ROOT / "tools", sandbox / "tools", ignore=shutil.ignore_patterns("__pycache__"))
        config = (sandbox / "app" / "config.yaml").read_text(encoding="utf8").replace("  REVISION: A", "  REVISION: SIMU", 1)
        (sandbox / "app" / "config.yaml").write_text(config, encoding="utf8")
        (sandbox / "settings.yaml").write_text("mode: stats\nlanguage: en\n", encoding="utf8")
        (sandbox / "run").mkdir()
        sandboxes.append(sandbox)
    pending, results = list(entries), {}

    def run(sandbox):
        app = sandbox / "app"
        while pending:
            e = pending.pop()
            try:
                name = theme_store.install(e, app / "res/themes", app / "res/fonts", data=Path(e["archive"]).read_bytes(),
                                           fetch=lambda url, sha256: fonts.content(
                                               urllib.parse.unquote(url.split(f"/{UPSTREAM_TAG}/res/fonts/", 1)[1])))
            except Exception as error:
                results[e["id"]] = f"install: {error}"
                continue
            config = re.sub(r"^  THEME: .*$", lambda m: f'  THEME: "{name}"', (app / "config.yaml").read_text(encoding="utf8"),
                            count=1, flags=re.M)
            (app / "config.yaml").write_text(config, encoding="utf8")
            shot = app / "screencap.png"
            shot.unlink(missing_ok=True)
            env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
            env.update(XDG_RUNTIME_DIR=str(sandbox / "run"), IGAM3_LANG="en")
            process = subprocess.Popen([python, str(sandbox / "tools" / "igam3_screen.py"), "run"], cwd=sandbox, env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            time.sleep(12)
            process.send_signal(signal.SIGINT)
            try:
                output = process.communicate(timeout=20)[0]
            except subprocess.TimeoutExpired:
                process.kill()
                output = process.communicate()[0]
            # Simulators of parallel workers share port 5678 for their web page: not a theme problem
            errors = [line for line in output.splitlines() if ("[ERROR]" in line or "Traceback" in line or "Error:" in line)
                      and "Error starting webserver" not in line]
            results[e["id"]] = "; ".join(errors[:2]) if errors else (None if shot.is_file() else "nothing drawn")
            if shot.is_file():
                (fonts.cache.parent / "shots").mkdir(parents=True, exist_ok=True)
                shutil.copy2(shot, fonts.cache.parent / "shots" / f"{e['id']}.png")

    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        list(pool.map(run, sandboxes))
    shutil.rmtree(work, ignore_errors=True)
    return results


def picture_hash(data):
    """Difference hash of a picture (16x16 = 256 bits): small distance = same picture, whatever its size"""
    import io
    from PIL import Image
    with Image.open(io.BytesIO(data)) as img:
        pixels = list(img.convert("L").resize((17, 16), Image.LANCZOS).tobytes())
    bits = 0
    for y in range(16):
        for x in range(16):
            bits = (bits << 1) | (pixels[y * 17 + x] > pixels[y * 17 + x + 1])
    return bits


def fetch_picture(url, cache):
    path = cache / "pictures" / hashlib.sha256(url.encode()).hexdigest()[:20]
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "igam3-screen"}), timeout=60) as r:
                path.write_bytes(r.read(20 * 1024 * 1024))
        except OSError:
            return None
    return path.read_bytes()


def assign_previews(entries, cache):
    """Preview = a picture of the author's post. When a post holds several themes, each theme gets the picture that
    looks like its own preview file (or its simulator screenshot); no picture rather than the picture of another theme"""
    shared = Counter(tuple(e["images"]) for e in entries)
    for e in entries:
        candidates = e["images"] or e["body_images"]
        if not candidates:
            e["preview"] = ""
            continue
        if len(candidates) == 1 and shared[tuple(e["images"])] == 1:
            e["preview"] = candidates[0]
            continue
        references = []
        archive = zipfile.ZipFile(e["archive"])
        prefix = f"{e['folder']}/" if e["folder"] else ""
        for name in ("preview.png", "theme_example.png", "preview.jpg", "screenshot.png"):
            member = next((n for n in archive.namelist() if n.lower() == (prefix + name).lower()), None)
            if member:
                references.append(archive.read(member))
        shot = cache / "shots" / f"{e['id']}.png"
        if shot.exists():
            references.append(shot.read_bytes())
        scores = []
        for url in candidates:
            data = fetch_picture(url, cache)
            try:
                picture = picture_hash(data) if data else None
            except Exception:
                picture = None
            if picture is None:
                continue
            distance = min(bin(picture ^ picture_hash(ref)).count("1") for ref in references) if references else 256
            scores.append((distance, url))
        scores.sort()
        good = scores and scores[0][0] <= 64 and (len(scores) == 1 or scores[1][0] - scores[0][0] >= 8)
        e["preview"] = scores[0][1] if good else ""


def main():
    parser = argparse.ArgumentParser(description="Build tools/theme_catalog.json from the Themes discussions")
    parser.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "igam3-screen" / "theme-catalog")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-test", action="store_true", help="skip the simulator test of every theme")
    args = parser.parse_args()

    log("==> Reading the Themes discussions")
    links = []
    for discussion in fetch_discussions():
        op = (discussion.get("author") or {}).get("login") or "ghost"
        body_images = list(dict.fromkeys(IMAGE.findall(discussion["body"] or "")))
        for poster, date, text in posts(discussion):
            images = list(dict.fromkeys(IMAGE.findall(text)))
            for url in dict.fromkeys(ARCHIVE.findall(text)):
                links.append({"discussion": discussion["number"], "discussion_title": discussion["title"].strip(),
                              "op": op, "poster": poster, "date": date[:10], "url": url,
                              "zip_name": urllib.parse.unquote(url.rsplit("/", 1)[-1]), "images": images,
                              "body_images": body_images})
    log(f"    {len(links)} archives")

    log("==> Downloading and checking the archives")
    fonts = UpstreamFonts(args.cache)
    entries, rejected = [], []
    for link in links:
        path = download(link["url"], args.cache)
        if not path:
            continue
        data = path.read_bytes()
        link.update(archive=str(path), sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        found, refused = analyse(path, link, fonts)
        entries += found
        rejected += refused
    entries = select(entries)
    # Names already taken by the themes igam3-screen ships (not by community themes installed on this machine)
    name_entries(entries, [p.name for p in (ROOT / "app" / "res" / "themes").iterdir()
                           if p.is_dir() and not (p / theme_store.MARKER).exists()])
    for e in entries:
        e["upstream_fonts"] = [{"path": path, "url": fonts.url(path), "sha256": hashlib.sha256(fonts.content(path)).hexdigest()}
                               for path in e.pop("upstream_font_paths")]
    log(f"    {len(entries)} themes to test, {len(rejected)} rejected")
    for r in rejected:
        log(f"      #{r['discussion']} {r['title_guess']}: {r['reason']}")

    if not args.no_test:
        log(f"==> Running every theme in the simulator ({args.workers} at a time)")
        results = test_themes(entries, fonts, args.workers)
        for e in entries:
            if results.get(e["id"]):
                log(f"    FAILED #{e['discussion']} {e['name']}: {results[e['id']][:200]}")
        entries = [e for e in entries if not results.get(e["id"])]

    log("==> Matching the pictures of the posts with the themes")
    assign_previews(entries, args.cache)
    log(f"    {sum(1 for e in entries if e['preview'])} of {len(entries)} themes have a preview picture")

    catalog = {
        "source": f"{DISCUSSIONS}/categories/themes",
        "generated": datetime.date.today().isoformat(),
        "note": "Themes by their authors, downloaded from where they published them. Not part of igam3-screen.",
        "themes": [{
            "id": e["id"], "name": e["name"], "author": e["poster"],
            **({"original_author": e["op"]} if e["poster"] != e["op"] else {}),
            "discussion": f"{DISCUSSIONS}/{e['discussion']}", "discussion_title": e["discussion_title"],
            "date": e["date"], "orientation": e["orientation"], "gpu": e["gpu"], "preview": e["preview"],
            "url": e["url"], "sha256": e["sha256"], "bytes": e["bytes"], "folder": e["folder"], "yaml": e["yaml"],
            "fonts": e["fonts"], "upstream_fonts": e["upstream_fonts"],
        } for e in sorted(entries, key=lambda e: e["name"].lower())],
    }
    out = ROOT / "tools" / "theme_catalog.json"
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
    log(f"==> {out}: {len(catalog['themes'])} themes")


if __name__ == "__main__":
    main()
