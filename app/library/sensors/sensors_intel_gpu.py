# SPDX-License-Identifier: GPL-3.0-or-later
#
# Intel integrated graphics (i915 driver) for sensors_python, on Linux and without root rights (added by igam3-screen)
#   load:        busy time of the GPU engines, from the DRM fdinfo of the processes that use the GPU
#                (/proc/<pid>/fdinfo/<fd>: drm-engine-<engine> in ns, per DRM client)
#   memory:      GPU buffers these processes keep resident (drm-resident-*): integrated graphics use system memory
#   frequency:   actual GPU frequency (sysfs gt_act_freq_mhz), or the requested one while the GPU sleeps between frames
#   temperature: integrated graphics share the die of the CPU and have no sensor of their own: CPU package temperature
# Only the processes of the same user can be read: GPU work of other users (another desktop session) is not counted.

import math
import os
import time
from pathlib import Path
from typing import Tuple

import psutil

import library.sensors.sensors as sensors

RESCAN_S = 10  # look for new GPU clients in /proc every 10 s: walking every file descriptor costs ~30 ms
UNITS = {"": 1, "KiB": 1, "MiB": 1024, "GiB": 1024 * 1024}


def _find_card():
    """sysfs folder of the first Intel GPU driven by i915, or None"""
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        if "-" in card.name:  # connectors such as card1-HDMI-A-1
            continue
        try:
            if (card / "device" / "vendor").read_text().strip() == "0x8086" \
                    and (card / "device" / "driver").resolve().name == "i915":
                return card
        except OSError:
            pass
    return None


class _Clients:
    """DRM clients (processes with the GPU open) and their engine busy time / resident memory"""

    def __init__(self, pdev):
        self.pdev = pdev  # PCI address of the GPU, as written in fdinfo (drm-pdev)
        self.paths = []
        self.scanned = -RESCAN_S
        self.previous = None  # (time in ns, {client id: {engine: busy ns}})

    def _scan(self):
        paths = []
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                fds = os.listdir(f"/proc/{pid}/fd")
            except OSError:
                continue
            for fd in fds:
                try:
                    if os.readlink(f"/proc/{pid}/fd/{fd}").startswith("/dev/dri/"):
                        paths.append(f"/proc/{pid}/fdinfo/{fd}")
                except OSError:
                    pass
        self.paths = paths
        self.scanned = time.monotonic()

    def read(self):
        """{client id: ({engine: busy ns}, resident KiB, {engine: engine count})}"""
        if time.monotonic() - self.scanned > RESCAN_S:
            self._scan()
        clients = {}
        for path in self.paths:
            try:
                with open(path) as f:
                    lines = f.read().splitlines()
            except OSError:
                continue
            fields = {}
            for line in lines:
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip()
            client = fields.get("drm-client-id")
            if fields.get("drm-pdev") != self.pdev or not client or client in clients:
                continue  # another GPU, or a client already read through another file descriptor
            engines, capacity, resident = {}, {}, 0
            for key, value in fields.items():
                number, _, unit = value.partition(" ")
                if not number.isdigit():
                    continue
                if key.startswith("drm-engine-capacity-"):
                    capacity[key[len("drm-engine-capacity-"):]] = int(number)
                elif key.startswith("drm-engine-") and unit == "ns":
                    engines[key[len("drm-engine-"):]] = int(number)
                elif key.startswith("drm-resident-"):
                    resident += int(number) * UNITS.get(unit, 1)
            clients[client] = (engines, resident, capacity)
        return clients

    def load_and_memory(self):
        """(busiest engine in %, resident memory in MiB) since the previous call"""
        now = time.monotonic_ns()
        clients = self.read()
        busy = {client: engines for client, (engines, _, _) in clients.items()}
        memory_mib = sum(resident for _, resident, _ in clients.values()) / 1024
        load = math.nan
        if self.previous:
            before, previous_busy = self.previous
            elapsed = now - before
            per_engine = {}
            capacity = {}
            for client, engines in busy.items():
                old = previous_busy.get(client)  # a new client: counted from the next reading on
                if old is None:
                    continue
                for engine, ns in engines.items():
                    per_engine[engine] = per_engine.get(engine, 0) + max(0, ns - old.get(engine, ns))
                capacity.update(clients[client][2])
            if elapsed > 0:
                load = max([100 * ns / elapsed / max(1, capacity.get(engine, 1)) for engine, ns in per_engine.items()] or [0])
                load = min(100.0, load)
        self.previous = (now, busy)
        return load, memory_mib


CARD = None
CLIENTS = None


def _read_int(name):
    try:
        return int((CARD / name).read_text())
    except (OSError, ValueError, TypeError):
        return None


def _package_temperature():
    try:
        entries = psutil.sensors_temperatures().get("coretemp") or []
    except Exception:
        return math.nan
    package = [e.current for e in entries if e.label.lower().startswith("package")]
    values = package or [e.current for e in entries]
    return max(values) if values else math.nan


class GpuIntel(sensors.Gpu):
    @staticmethod
    def stats() -> Tuple[float, float, float, float, float]:  # load (%) / used mem (%) / used mem (Mb) / total mem (Mb) / temp (°C)
        try:
            load, memory_mib = CLIENTS.load_and_memory()
        except Exception:
            load, memory_mib = math.nan, math.nan
        total_mib = psutil.virtual_memory().total / 1024 / 1024  # shared with the system
        memory_percent = 100 * memory_mib / total_mib if total_mib and not math.isnan(memory_mib) else math.nan
        return load, memory_percent, memory_mib, total_mib, _package_temperature()

    @staticmethod
    def fps() -> int:
        return -1

    @staticmethod
    def fan_percent() -> float:
        return math.nan

    @staticmethod
    def frequency() -> float:
        mhz = _read_int("gt_act_freq_mhz") or _read_int("gt_cur_freq_mhz")
        return float(mhz) if mhz is not None else math.nan

    @staticmethod
    def is_available() -> bool:
        global CARD, CLIENTS
        if CARD is None:
            CARD = _find_card()
            if CARD is not None:
                CLIENTS = _Clients(CARD.joinpath("device").resolve().name)
                CLIENTS.load_and_memory()  # first reading: the next one gives the load
        return CARD is not None
