"""跨平台资源采样器（Linux 主力，Windows 也可用）。

与 `_sampler.ps1` 输出**同一格式**的 CSV，所以基准工具不用改解析逻辑：

    time,cpu_total,free_mem_mb,gpu_util,gpu_mem_mb,power_w,temp_c,gpu_clock_mhz,per_core(|)

数据来源：
* CPU 总占用与每核：Linux 读 ``/proc/stat``；Windows 退回 ``psutil``（若未安装则跳过）
* 内存：Linux 读 ``/proc/meminfo``；Windows 用 ctypes ``GlobalMemoryStatusEx``
* GPU：``nvidia-smi``（驱动自带的查询接口，两个平台通用）

用法（作为独立进程运行，避免和被测量进程抢 GIL）：

    python -m tools.resource_sampler --out samples.csv --seconds 3600 --interval-ms 200
"""

import argparse
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

CPU_STAT = Path("/proc/stat")
MEMINFO = Path("/proc/meminfo")


def read_cpu_linux():
    """返回 (总占用百分比, [每核占用百分比])。需要两次采样求差分。"""
    lines = CPU_STAT.read_text().splitlines()
    totals = {}

    for line in lines:
        if line.startswith("cpu"):
            parts = line.split()
            name = parts[0]
            values = [int(value) for value in parts[1:]]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            totals[name] = (sum(values), idle)

    return totals


def cpu_delta(previous, current):
    total_delta = current[0] - previous[0]
    idle_delta = current[1] - previous[1]

    if total_delta <= 0:
        return None

    return (1 - idle_delta / total_delta) * 100


def read_mem_linux():
    info = {}

    for line in MEMINFO.read_text().splitlines():
        key, _, rest = line.partition(":")
        info[key] = int(rest.strip().split()[0]) / 1024.0  # KB -> MB

    total = info.get("MemTotal", 0.0)
    available = info.get("MemAvailable", info.get("MemFree", 0.0))

    return available


def read_mem_windows():
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)

    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None

    return status.ullAvailPhys / 1024 / 1024


def read_cpu_windows():
    """Windows 总 CPU：优先 psutil，没有就用 GetSystemTimes（ctypes，无依赖）。

    注意：GetSystemTimes 只给总量，不给每核，所以 per-core 在无 psutil 时为空。
    Linux 服务器上走 /proc/stat，两者都能拿到。
    """
    try:
        import psutil

        return (
            psutil.cpu_percent(interval=None, percpu=False),
            psutil.cpu_percent(interval=None, percpu=True),
        )
    except ImportError:
        pass

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]

    idle = FILETIME()
    kernel = FILETIME()
    user = FILETIME()

    if not ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    ):
        return None, []

    def to_int(value):
        return (value.dwHighDateTime << 32) | value.dwLowDateTime

    idle_time = to_int(idle)
    kernel_time = to_int(kernel)
    user_time = to_int(user)
    total = kernel_time + user_time

    global _PREVIOUS_WINDOWS_CPU

    current = (total, idle_time)
    previous = _PREVIOUS_WINDOWS_CPU
    _PREVIOUS_WINDOWS_CPU = current

    if previous is None:
        return None, []

    total_delta = total - previous[0]
    idle_delta = idle_time - previous[1]

    if total_delta <= 0:
        return None, []

    return (1 - idle_delta / total_delta) * 100, []


_PREVIOUS_WINDOWS_CPU = None


def query_gpu():
    try:
        output = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu,clocks.current.graphics",
             "--format=csv,noheader,nounits"],
            text=True, timeout=5, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001 - 没显卡或没驱动就留空
        return ["", "", "", "", ""]

    if not output:
        return ["", "", "", "", ""]

    return [part.strip() for part in output.splitlines()[0].split(",")]


def main(argv=None):
    parser = argparse.ArgumentParser(description="跨平台资源采样器")
    parser.add_argument("--out", required=True)
    parser.add_argument("--seconds", type=int, default=3600)
    parser.add_argument("--interval-ms", type=int, default=200)

    args = parser.parse_args(argv)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("", encoding="utf-8")

    linux = sys.platform.startswith("linux")
    previous_cpu = read_cpu_linux() if linux else None
    end = time.time() + args.seconds
    interval = args.interval_ms / 1000.0

    while time.time() < end:
        started = time.time()

        if linux:
            current_cpu = read_cpu_linux()
            total_cpu = cpu_delta(previous_cpu["cpu"], current_cpu["cpu"])
            cores = []

            for name, values in current_cpu.items():
                if name == "cpu":
                    continue

                value = cpu_delta(previous_cpu.get(name, values), values)

                if value is not None:
                    cores.append(value)

            previous_cpu = current_cpu
            free_mem = read_mem_linux()
        else:
            total_cpu, cores = read_cpu_windows()
            free_mem = read_mem_windows()

        gpu_util, gpu_mem, power, temp, clock = query_gpu()

        line = ",".join([
            time.strftime("%H:%M:%S") + f".{int(time.time() % 1 * 1000):03d}",
            f"{total_cpu:.1f}" if total_cpu is not None else "",
            f"{free_mem:.0f}" if free_mem is not None else "",
            gpu_util, gpu_mem, power, temp, clock,
            "|".join(f"{value:.1f}" for value in cores),
        ])

        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

        sleep = interval - (time.time() - started)

        if sleep > 0:
            time.sleep(sleep)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
