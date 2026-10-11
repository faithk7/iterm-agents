"""Process-table snapshots from macOS libproc, with a ps fallback.

These blocking readers run in the server's worker thread. Every snapshot
retains all parent links; session_pids only limits full argument reads in
the native backend, allowing the detector to walk ancestors reliably.
"""

from __future__ import annotations

import contextlib
import ctypes
import functools
import subprocess
import sys

from iterm_agents.models import ProcessInfo


def build_process_table(session_pids: set[int] | None = None) -> dict[int, ProcessInfo]:
    """Read the process table in-process, falling back to `ps`."""
    with contextlib.suppress(OSError, AttributeError):
        return _libproc_process_table(session_pids)
    return _ps_process_table()


class _ProcBSDInfo(ctypes.Structure):
    """`struct proc_bsdinfo` from <sys/proc_info.h>."""

    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("status", ctypes.c_uint32),
        ("xstatus", ctypes.c_uint32),
        ("pid", ctypes.c_uint32),
        ("ppid", ctypes.c_uint32),
        ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32),
        ("ruid", ctypes.c_uint32),
        ("rgid", ctypes.c_uint32),
        ("svuid", ctypes.c_uint32),
        ("svgid", ctypes.c_uint32),
        ("rfu", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16),
        ("name", ctypes.c_char * 32),
        ("nfiles", ctypes.c_uint32),
        ("pgid", ctypes.c_uint32),
        ("pjobc", ctypes.c_uint32),
        ("tdev", ctypes.c_uint32),
        ("tpgid", ctypes.c_uint32),
        ("nice", ctypes.c_int32),
        ("start_sec", ctypes.c_uint64),
        ("start_usec", ctypes.c_uint64),
    ]


_PROC_PIDTBSDINFO = 3
_CTL_KERN = 1
_KERN_PROCARGS2 = 49


@functools.cache
def _libsystem() -> ctypes.CDLL:
    """Load and configure native call signatures once per process."""
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    libc.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
    libc.proc_pidinfo.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    libc.sysctl.argtypes = [
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    libc.sysctlbyname.argtypes = [
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    return libc


def _parse_procargs(raw: bytes) -> str | None:
    """Join KERN_PROCARGS2 argv like `ps -o command`, leaving out the environment.

    Layout: argc, the executable path, NUL padding, argc NUL-terminated args,
    then environment strings.
    """
    if len(raw) < 4:
        return None
    argc = int.from_bytes(raw[:4], sys.byteorder)
    start = raw.find(b"\0", 4)
    if start < 0:
        return None
    while start < len(raw) and raw[start] == 0:
        start += 1
    args = raw[start:].split(b"\0", argc)[:argc]
    return " ".join(arg.decode(errors="replace") for arg in args) or None


def _libproc_process_table(session_pids: set[int] | None) -> dict[int, ProcessInfo]:
    """Read the process table without spawning `ps` on each scan.

    Only processes under a session shell need full arguments; other rows
    carry the process name, which is enough for ancestor walks to rule out.
    """
    libc = _libsystem()
    count = libc.proc_listallpids(None, 0)
    if count <= 0:
        raise OSError("proc_listallpids failed")
    pids = (ctypes.c_int * (count + 64))()
    count = libc.proc_listallpids(pids, ctypes.sizeof(pids))
    if count <= 0:
        raise OSError("proc_listallpids failed")

    info = _ProcBSDInfo()
    rows: dict[int, tuple[int, str]] = {}
    for pid in pids[:count]:
        read = libc.proc_pidinfo(pid, _PROC_PIDTBSDINFO, 0, ctypes.byref(info), ctypes.sizeof(info))
        if read == ctypes.sizeof(info):
            rows[pid] = (info.ppid, (info.name or info.comm).decode(errors="replace"))
    if not rows:
        raise OSError("no readable processes")

    if session_pids is None:
        wanted = set(rows)
    else:
        children: dict[int, list[int]] = {}
        for pid, (ppid, _) in rows.items():
            children.setdefault(ppid, []).append(pid)
        wanted, stack = set(), list(session_pids)
        while stack:
            pid = stack.pop()
            if pid not in wanted:
                wanted.add(pid)
                stack.extend(children.get(pid, []))

    argmax = ctypes.c_int()
    size = ctypes.c_size_t(ctypes.sizeof(argmax))
    if libc.sysctlbyname(b"kern.argmax", ctypes.byref(argmax), ctypes.byref(size), None, 0):
        raise OSError("kern.argmax unavailable")
    buffer = ctypes.create_string_buffer(argmax.value)
    table: dict[int, ProcessInfo] = {}
    for pid, (ppid, name) in rows.items():
        command = None
        if pid in wanted:
            mib = (ctypes.c_int * 3)(_CTL_KERN, _KERN_PROCARGS2, pid)
            size = ctypes.c_size_t(argmax.value)
            if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) == 0:
                command = _parse_procargs(ctypes.string_at(buffer, size.value))
        table[pid] = ProcessInfo(pid=pid, ppid=ppid, command=command or name)
    return table


def _ps_process_table() -> dict[int, ProcessInfo]:
    """Build a process table from ps output.

    `command` includes arguments. Cursor Agent's on-disk launcher is a shell
    wrapper that execs a private `node` binary, so the executable basename
    alone is not enough to tell it from any other Node process.
    """
    result = subprocess.run(
        ["ps", "-axww", "-o", "pid,ppid,command"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise RuntimeError("iterm-agents: process scan failed")

    table: dict[int, ProcessInfo] = {}
    for line in result.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        table[pid] = ProcessInfo(pid=pid, ppid=ppid, command=parts[2].strip())
    if not table:
        raise RuntimeError("iterm-agents: process scan returned no valid rows")
    return table
