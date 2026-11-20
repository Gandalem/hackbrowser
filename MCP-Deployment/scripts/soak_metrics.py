"""Bounded, read-only Linux procfs metrics for OCI staging OAuth smoke.

The sum of per-process RSS can double count shared pages. Treat it as a
conservative process-tree accounting estimate, not machine physical usage.
Never reads browser profiles, cookies, environment or credentials.
"""
from __future__ import annotations

import os
from pathlib import Path

PAGE_BYTES = os.sysconf("SC_PAGE_SIZE")
CLOCK_TICKS = os.sysconf("SC_CLK_TCK")


def parse_proc_stat(line: str) -> tuple[int, int, int, int]:
    """Return (pid, ppid, CPU ticks, RSS bytes).

    Use the final closing parenthesis: Linux process names may include spaces
    and parentheses, so naive split() breaks stat field offsets.
    """
    closing = line.rfind(") ")
    opening = line.find("(")
    if opening < 0 or closing <= opening:
        raise ValueError("Invalid proc stat header")
    fields = line[closing + 2:].split()
    if len(fields) < 22:
        raise ValueError("Incomplete proc stat record")
    pid = int(line[:opening].strip())
    ppid = int(fields[1])                 # stat field 4
    cpu_ticks = int(fields[11]) + int(fields[12])   # fields 14 + 15
    rss_bytes = max(0, int(fields[21])) * PAGE_BYTES  # field 24
    if pid <= 0 or ppid < 0 or cpu_ticks < 0:
        raise ValueError("Invalid proc stat values")
    return pid, ppid, cpu_ticks, rss_bytes


def sample_tree(root_pid: int, proc_root: str | Path = "/proc") -> dict:
    """Estimate aggregate RSS and CPU of a staging gateway and descendants."""
    if not isinstance(root_pid, int) or root_pid <= 0:
        raise ValueError("A positive staging process ID is required")
    records = {}
    root = Path(proc_root)
    for entry in root.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            record = parse_proc_stat((entry / "stat").read_text())
        except (OSError, UnicodeError, ValueError):
            # Short-lived processes may exit during the scan.
            continue
        if record[0] == int(entry.name):
            records[record[0]] = record
    children = {}
    for pid, ppid, _, _ in records.values():
        children.setdefault(ppid, []).append(pid)
    seen = set()
    queue = [root_pid]
    while queue:
        current = queue.pop()
        if current in seen or current not in records:
            continue
        seen.add(current)
        queue.extend(children.get(current, ()))
    return {
        "processes": len(seen),
        "rss_mib": round(sum(records[pid][3] for pid in seen) / 1048576, 1),
        "cpu_ticks": sum(records[pid][2] for pid in seen),
    }


def available_memory_mib(meminfo: str | Path = "/proc/meminfo") -> float:
    """Report machine-wide MemAvailable; fail closed on malformed procfs."""
    for line in Path(meminfo).read_text().splitlines():
        if line.startswith("MemAvailable:"):
            words = line.split()
            if len(words) != 3 or words[2] != "kB":
                raise ValueError("Invalid MemAvailable format")
            return round(int(words[1]) / 1024, 1)
    raise ValueError("MemAvailable not found")


def process_cpu_percent(old_ticks: int, new_ticks: int, seconds: float) -> float:
    """CPU for one core = 100%; 3-vCPU hosts can measure up to 300%."""
    if seconds <= 0:
        raise ValueError("Elapsed seconds must be positive")
    return round(max(0, new_ticks - old_ticks) / CLOCK_TICKS / seconds * 100, 1)
