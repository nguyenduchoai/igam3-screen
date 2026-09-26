# Phần khác nhau giữa Linux và Windows: chạy nền, tự chạy khi khởi động, lối tắt, đường dẫn.
#   Linux:   dịch vụ systemd user (bật/tắt/tự chạy bằng systemctl --user)
#   Windows: tiến trình pythonw.exe chạy nền + lối tắt trong thư mục Startup (thử nghiệm)

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

WINDOWS = sys.platform == "win32"


def venv_python(root, windowless=False):
    if WINDOWS:
        return root / ".venv" / "Scripts" / ("pythonw.exe" if windowless else "python.exe")
    return root / ".venv" / "bin" / "python"


def runtime_dir():
    if WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "igam3-screen"
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "igam3-screen"


def background_kwargs():
    """subprocess.Popen arguments for a process that outlives its parent and has no console window"""
    if WINDOWS:
        return {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def no_window_kwargs():
    """subprocess.run arguments so that a program running in the background does not flash console windows"""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}


def matching_processes(script, *args):
    """Running processes of `script` with all of `args` on their command line, however they were started"""
    import psutil
    script = os.path.normcase(str(script))
    found = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        cmdline = proc.info["cmdline"] or []
        if proc.info["pid"] != os.getpid() and any(os.path.normcase(part) == script for part in cmdline) \
                and all(arg in cmdline for arg in args):
            found.append(proc)
    return found


def stop_processes(procs, timeout=5):
    import psutil
    for proc in procs:
        try:
            proc.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(procs, timeout=timeout)
    for proc in alive:
        proc.kill()
    return bool(procs)


# Windows has no SIGTERM for background processes: "stop" creates this file, the process watches for it
def stop_file(name):
    return runtime_dir() / f"{name}.stop"


def watch_stop_file(name, on_stop):
    path = stop_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)

    def wait_for_request():
        while not path.exists():
            time.sleep(0.5)
        path.unlink(missing_ok=True)
        on_stop()

    threading.Thread(target=wait_for_request, daemon=True).start()


def start_menu_dir():
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "iGam3 Screen"


def startup_dir():
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def create_shortcut(path, target, arguments="", workdir="", icon="", hotkey=""):
    """Windows .lnk shortcut, written by PowerShell (always present on Windows 10/11)"""
    quote = lambda text: "'" + str(text).replace("'", "''") + "'"
    path.parent.mkdir(parents=True, exist_ok=True)
    script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({quote(path)}); "
              f"$s.TargetPath = {quote(target)}; $s.Arguments = {quote(arguments)}; "
              f"$s.WorkingDirectory = {quote(workdir)}; "
              + (f"$s.IconLocation = {quote(icon)}; " if icon else "")
              + (f"$s.Hotkey = {quote(hotkey)}; " if hotkey else "")
              + "$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                   check=True, **no_window_kwargs())


class SystemdUserService:
    """Linux: systemd user unit"""

    def __init__(self, unit):
        self.unit = unit

    def _run(self, *args):
        return subprocess.run(["systemctl", "--user", *args]).returncode

    def _query(self, verb):
        result = subprocess.run(["systemctl", "--user", verb, self.unit], capture_output=True, text=True)
        return result.stdout.strip()

    def state(self):
        return self._query("is-active") or "unknown"

    def autostart(self):
        return self._query("is-enabled") == "enabled"

    def start(self):
        return self._run("start", self.unit)

    def stop(self):
        return self._run("stop", self.unit)

    def restart(self):
        return self._run("restart", self.unit)

    def set_autostart(self, on, now=False):
        return self._run("enable" if on else "disable", *(["--now"] if now else []), self.unit)


class WindowsBackgroundTask:
    """Windows: pythonw.exe running a script in the background; a shortcut in the Startup folder starts it at logon"""

    def __init__(self, name, title, pythonw, script, args, workdir):
        self.name, self.title = name, title
        self.pythonw, self.script, self.args, self.workdir = pythonw, script, list(args), workdir

    @property
    def startup_shortcut(self):
        return startup_dir() / f"{self.title}.lnk"

    def _processes(self):
        return matching_processes(self.script, *self.args)

    def state(self):
        return "active" if self._processes() else "inactive"

    def autostart(self):
        return self.startup_shortcut.exists()

    def start(self):
        if self._processes():
            return 0
        stop_file(self.name).unlink(missing_ok=True)
        subprocess.Popen([str(self.pythonw), str(self.script), *self.args], cwd=self.workdir,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, **background_kwargs())
        return 0

    def stop(self, timeout=15):
        import psutil
        procs = self._processes()
        if procs:
            stop_file(self.name).parent.mkdir(parents=True, exist_ok=True)
            stop_file(self.name).touch()  # the process turns the screen off and exits by itself
            _, alive = psutil.wait_procs(procs, timeout=timeout)
            for proc in alive:
                proc.kill()
        stop_file(self.name).unlink(missing_ok=True)
        return 0

    def restart(self):
        self.stop()
        return self.start()

    def set_autostart(self, on, now=False):
        if on:
            create_shortcut(self.startup_shortcut, self.pythonw,
                            " ".join([f'"{self.script}"', *self.args]), self.workdir)
        else:
            self.startup_shortcut.unlink(missing_ok=True)
        if now:
            return self.start() if on else self.stop()
        return 0
