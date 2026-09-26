# SPDX-License-Identifier: GPL-3.0-or-later
#
# turing-smart-screen-python - a Python system monitor and library for USB-C displays like Turing Smart Screen or XuanFang
# https://github.com/mathoudebine/turing-smart-screen-python/
#
# Copyright (C) 2021 Matthieu Houdebine (mathoudebine)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# This file allows to add custom data source as sensors and display them in System Monitor themes
# There is no limitation on how much custom data source classes can be added to this file
# See CustomDataExample theme for the theme implementation part

import math
import platform
from abc import ABC, abstractmethod
from typing import List


# Custom data classes must be implemented in this file, inherit the CustomDataSource and implement its 2 methods
class CustomDataSource(ABC):
    @abstractmethod
    def as_numeric(self) -> float:
        # Numeric value will be used for graph and radial progress bars
        # If there is no numeric value, keep this function empty
        pass

    @abstractmethod
    def as_string(self) -> str:
        # Text value will be used for text display and radial progress bar inner text
        # Numeric value can be formatted here to be displayed as expected
        # It is also possible to return a text unrelated to the numeric value
        # If this function is empty, the numeric value will be used as string without formatting
        pass

    @abstractmethod
    def last_values(self) -> List[float]:
        # List of last numeric values will be used for plot graph
        # If you do not want to draw a line graph or if your custom data has no numeric values, keep this function empty
        pass


# Example for a custom data class that has numeric and text values
class ExampleCustomNumericData(CustomDataSource):
    # This list is used to store the last 10 values to display a line graph
    last_val = [math.nan] * 10  # By default, it is filed with math.nan values to indicate there is no data stored

    def as_numeric(self) -> float:
        # Numeric value will be used for graph and radial progress bars
        # Here a Python function from another module can be called to get data
        # Example: self.value = my_module.get_rgb_led_brightness() / audio.system_volume() ...
        self.value = 75.845

        # Store the value to the history list that will be used for line graph
        self.last_val.append(self.value)
        # Also remove the oldest value from history list
        self.last_val.pop(0)

        return self.value

    def as_string(self) -> str:
        # Text value will be used for text display and radial progress bar inner text.
        # Numeric value can be formatted here to be displayed as expected
        # It is also possible to return a text unrelated to the numeric value
        # If this function is empty, the numeric value will be used as string without formatting
        # Example here: format numeric value: add unit as a suffix, and keep 1 digit decimal precision
        return f'{self.value:>5.1f}%'
        # Important note! If your numeric value can vary in size, be sure to display it with a default size.
        # E.g. if your value can range from 0 to 9999, you need to display it with at least 4 characters every time.
        # --> return f'{self.as_numeric():>4}%'
        # Otherwise, part of the previous value can stay displayed ("ghosting") after a refresh

    def last_values(self) -> List[float]:
        # List of last numeric values will be used for plot graph
        return self.last_val


# Example for a custom data class that only has text values
class ExampleCustomTextOnlyData(CustomDataSource):
    def as_numeric(self) -> float:
        # If there is no numeric value, keep this function empty
        pass

    def as_string(self) -> str:
        # If a custom data class only has text values, it won't be possible to display graph or radial bars
        return "Python: " + platform.python_version()

    def last_values(self) -> List[float]:
        # If a custom data class only has text values, it won't be possible to display line graph
        pass


# ---------------------------------------------------------------------------------------------------------------------
# iGam3 M1 custom data sources, used by the "iGam3" theme (res/themes/iGam3)
# Every method catches its own errors: an exception here would stop all remaining custom sensors for this refresh
# ---------------------------------------------------------------------------------------------------------------------
import os
import socket
import time
from pathlib import Path

import psutil

psutil.cpu_percent(interval=None)  # the first call always returns 0.0: take it now, not on screen
SYSTEM_DISK = Path.home().anchor if os.name == "nt" else "/"  # C:\ on Windows
# Vietnamese or English: set by igam3-screen (IGAM3_LANG), else the language of the system
VI = os.environ.get("IGAM3_LANG", "vi" if os.environ.get("LANG", "").lower().startswith("vi") else "en") == "vi"


def _gib(n_bytes: float) -> str:
    gib = n_bytes / 1024 ** 3
    return f"{gib:.1f}" if gib < 100 else f"{gib:.0f}"


def primary_ipv4():
    # Source address the kernel would use to reach the internet (UDP connect sends no packet)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        pass
    # No default route: fall back to the first non-loopback IPv4 address
    try:
        for addrs in psutil.net_if_addrs().values():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    return addr.address
    except Exception:
        pass
    return None


class Igam3CpuPercent(CustomDataSource):
    value = 0.0

    def as_numeric(self) -> float:
        try:
            self.value = psutil.cpu_percent(interval=None)
        except Exception:
            self.value = 0.0
        return self.value

    def as_string(self) -> str:
        return f"{self.value:.0f}%"

    def last_values(self) -> List[float]:
        pass


class Igam3RamPercent(CustomDataSource):
    value = 0.0

    def as_numeric(self) -> float:
        try:
            vm = psutil.virtual_memory()
            self.value = (vm.total - vm.available) * 100 / vm.total
        except Exception:
            self.value = 0.0
        return self.value

    def as_string(self) -> str:
        return f"{self.value:.0f}%"

    def last_values(self) -> List[float]:
        pass


class Igam3RamText(CustomDataSource):
    def as_numeric(self) -> float:
        pass

    def as_string(self) -> str:
        try:
            vm = psutil.virtual_memory()
            return f"{_gib(vm.total - vm.available)} / {_gib(vm.total)} GB"
        except Exception:
            return "-"

    def last_values(self) -> List[float]:
        pass


class Igam3DiskPercent(CustomDataSource):
    value = 0.0

    def as_numeric(self) -> float:
        try:
            self.value = psutil.disk_usage(SYSTEM_DISK).percent
        except Exception:
            self.value = 0.0
        return self.value

    def as_string(self) -> str:
        return f"{self.value:.0f}%"

    def last_values(self) -> List[float]:
        pass


class Igam3DiskText(CustomDataSource):
    def as_numeric(self) -> float:
        pass

    def as_string(self) -> str:
        try:
            du = psutil.disk_usage(SYSTEM_DISK)
            return f"{_gib(du.used)} / {_gib(du.total)} GB"
        except Exception:
            return "-"

    def last_values(self) -> List[float]:
        pass


class Igam3Uptime(CustomDataSource):
    def as_numeric(self) -> float:
        pass

    def as_string(self) -> str:
        try:
            seconds = int(time.time() - psutil.boot_time())
        except Exception:
            return "-"
        days, rest = divmod(seconds, 86400)
        hours, rest = divmod(rest, 3600)
        minutes, seconds = divmod(rest, 60)
        if days:
            return f"{days} ngày {hours:02d}:{minutes:02d}" if VI else f"{days}d {hours:02d}:{minutes:02d}"
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def last_values(self) -> List[float]:
        pass


class Igam3Ip(CustomDataSource):
    def as_numeric(self) -> float:
        pass

    def as_string(self) -> str:
        return primary_ipv4() or ("Không có mạng" if VI else "No network")

    def last_values(self) -> List[float]:
        pass


class Igam3Hostname(CustomDataSource):
    def as_numeric(self) -> float:
        pass

    def as_string(self) -> str:
        try:
            return socket.gethostname()
        except Exception:
            return "-"

    def last_values(self) -> List[float]:
        pass


class Igam3CpuTemp(CustomDataSource):
    def as_numeric(self) -> float:
        pass

    def as_string(self) -> str:
        try:
            temps = psutil.sensors_temperatures()
            entries = temps.get("coretemp") or next(iter(temps.values()))
            return f"{entries[0].current:.0f}°C"
        except Exception:
            return "--°C"

    def last_values(self) -> List[float]:
        pass


class Igam3CpuFreq(CustomDataSource):
    def as_numeric(self) -> float:
        pass

    def as_string(self) -> str:
        try:
            return f"{psutil.cpu_freq().current / 1000:.2f} GHz"
        except Exception:
            return "-- GHz"

    def last_values(self) -> List[float]:
        pass


def _tcp_delay_ms(host):
    # Time to open a TCP connection: ICMP ping needs administrator rights on Windows
    for port in (53, 443):
        start = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=1):
                return (time.perf_counter() - start) * 1000
        except OSError:
            pass
    return None


class Igam3Ping(CustomDataSource):
    # Built-in PING sensor stops refreshing after the first timeout (int(None)): this one survives network loss
    def as_numeric(self) -> float:
        pass

    def as_string(self) -> str:
        host = "8.8.8.8"
        try:
            from ping3 import ping
            from library import config
            host = config.CONFIG_DATA["config"].get("PING", host)
            delay = ping(host, timeout=1, unit="ms")
        except Exception:
            delay = None
        if (delay is None or delay is False) and os.name == "nt":
            delay = _tcp_delay_ms(host)
        if delay is None or delay is False:
            return "Mất kết nối" if VI else "No connection"
        return f"{delay:.0f} ms"

    def last_values(self) -> List[float]:
        pass
