"""Run the PDF parse child with a wall clock and an output cap (spec 0012/0002).

The worker parent starts one child per run with ``python -I`` on a standalone
file, sends the PDF on stdin, and reads one JSON result from stdout, capped at
1 MiB. The child gets an empty environment and no path; its standard error is
discarded and never logged. The parent kills the whole process group on
expiry and accepts only a complete, valid JSON result, so a killed child
never leaves a partial one.

Memory, file, and network isolation come from the Linux container and the
child's own rlimits. On Windows or any direct run this is development mode:
the child process, the timeout, and the output cap still apply, nothing else.
"""

import json
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, cast

CHILD_SCRIPT = Path(__file__).with_name("pdf_child.py")
MAX_OUTPUT_BYTES = 1024 * 1024
_WINDOWS = os.name == "nt"


@dataclass(frozen=True)
class ChildLimits:
    max_pages: int
    max_text_bytes: int
    cpu_seconds: int
    wall_seconds: float
    memory_bytes: int


@dataclass(frozen=True)
class ChildResult:
    ok: bool
    code: str | None = None
    page_count: int | None = None


def _environment() -> dict[str, str]:
    """Empty on POSIX. Windows cannot start Python without ``SYSTEMROOT``."""
    if _WINDOWS:
        return {"SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows")}
    return {}


def _kill(process: subprocess.Popen[bytes]) -> None:
    if _WINDOWS and process.poll() is not None:
        return
    try:
        if _WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
            process.kill()
        else:
            posix: Any = os
            posix.killpg(process.pid, 9)  # SIGKILL
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _feed(stream: IO[bytes], data: bytes) -> None:
    try:
        stream.write(data)
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            stream.close()
        except (BrokenPipeError, OSError):
            pass


def _parse(raw: bytes) -> ChildResult:
    try:
        loaded: object = json.loads(raw)
    except ValueError:
        return ChildResult(False, "pdf_parse_failed")
    if not isinstance(loaded, dict):
        return ChildResult(False, "pdf_parse_failed")
    value = cast("dict[str, Any]", loaded)
    if value.get("ok") is True and isinstance(value.get("page_count"), int):
        return ChildResult(True, None, value["page_count"])
    code = value.get("code")
    if value.get("ok") is False and isinstance(code, str):
        return ChildResult(False, code)
    return ChildResult(False, "pdf_parse_failed")


def run_pdf_child(
    data: bytes,
    limits: ChildLimits,
    *,
    command: Sequence[str] | None = None,
) -> ChildResult:
    """Parse ``data`` in a child; every failure is a stable code, never a raise.

    ``command`` replaces the child argv for tests (an infinite loop or a
    memory bomb); production always runs ``pdf_child.py``.
    """
    argv = (
        list(command)
        if command is not None
        else [
            sys.executable,
            "-I",
            str(CHILD_SCRIPT),
            str(limits.max_pages),
            str(limits.max_text_bytes),
            str(limits.cpu_seconds),
            str(limits.memory_bytes),
        ]
    )
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_environment(),
        cwd=os.path.dirname(sys.executable) if _WINDOWS else "/",
        start_new_session=not _WINDOWS,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if _WINDOWS else 0,  # pyright: ignore[reportAttributeAccessIssue]
    )
    assert process.stdin is not None and process.stdout is not None
    timed_out = threading.Event()

    def expire() -> None:
        timed_out.set()
        _kill(process)

    timer = threading.Timer(limits.wall_seconds, expire)
    timer.start()
    feeder = threading.Thread(target=_feed, args=(process.stdin, data), daemon=True)
    feeder.start()
    try:
        output = process.stdout.read(MAX_OUTPUT_BYTES + 1)
        too_big = len(output) > MAX_OUTPUT_BYTES
        if too_big:
            _kill(process)
        process.wait()
    finally:
        timer.cancel()
        _kill(process)
        process.stdout.close()
        feeder.join(timeout=1)
    if timed_out.is_set():
        return ChildResult(False, "pdf_parse_timeout")
    if too_big:
        return ChildResult(False, "pdf_parse_resource")
    if process.returncode != 0 and not output:
        return ChildResult(False, _crash_code(process.returncode))
    return _parse(output)


def _crash_code(returncode: int) -> str:
    """A signal (an rlimit or the kernel) is a limit breach; an exit is a failure.

    SIGXCPU is the CPU limit. Any other signal, such as SIGKILL from the
    memory limit or SIGSEGV, reads as a resource failure.
    """
    if returncode < 0:
        if -returncode == getattr(signal, "SIGXCPU", 24):
            return "pdf_parse_timeout"
        return "pdf_parse_resource"
    return "pdf_parse_failed"
