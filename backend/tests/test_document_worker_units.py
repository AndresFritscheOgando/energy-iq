"""Limits, the parse child, and the sandbox (spec 0012/0002 AC-1, AC-3). No database."""

import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pdfsupport import MALFORMED_PDF, NOT_A_PDF, make_pdf
from pydantic import ValidationError

from energyiq.documents.storage import LocalDocumentStore
from energyiq.platform.settings import MIB, Settings
from energyiq.worker.runner import check_isolation
from energyiq.worker.sandbox import ChildLimits, run_pdf_child

LIMITS = ChildLimits(
    max_pages=3,
    max_text_bytes=1024,
    cpu_seconds=10,
    wall_seconds=10,
    memory_bytes=768 * MIB,
)
LINUX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="needs Linux rlimits (RLIMIT_AS); run in the worker container",
)


def _settings(**values: Any) -> Settings:
    """Settings with loosely typed overrides, so tests can pass bad values."""
    return Settings(env="test", **values)  # pyright: ignore[reportArgumentType]


# Settings: every cap has a default, a ceiling, and no way to reach zero ------


@pytest.mark.parametrize(
    ("field", "default", "ceiling"),
    [
        ("upload_max_bytes", 5 * MIB, 20 * MIB),
        ("pdf_max_pages", 10, 50),
        ("pdf_max_text_bytes", 256 * 1024, MIB),
        ("pdf_cpu_seconds", 20, 60),
        ("pdf_wall_seconds", 30, 120),
        ("pdf_memory_bytes", 768 * MIB, 2048 * MIB),
        ("run_max_attempts", 2, 5),
        ("doc_max_runs", 3, 10),
        ("worker_concurrency", 1, 4),
        ("owner_max_active_docs", 3, 10),
        ("run_lease_seconds", 90, 600),
    ],
)
def test_each_limit_has_its_default_and_hard_ceiling(
    field: str, default: int, ceiling: int
) -> None:
    assert getattr(Settings(env="test"), field) == default
    # The lease rule needs a long lease when the wall clock limit is raised.
    extra: dict[str, Any] = (
        {"run_lease_seconds": 600} if field == "pdf_wall_seconds" else {}
    )
    assert getattr(_settings(**{field: ceiling, **extra}), field) == ceiling
    for bad in (0, -1, ceiling + 1):
        with pytest.raises(ValidationError) as caught:
            _settings(**{field: bad})
        assert field in str(caught.value)


def test_a_lease_must_outlast_the_wall_clock_limit_plus_thirty() -> None:
    Settings(env="test", pdf_wall_seconds=30, run_lease_seconds=61)
    with pytest.raises(ValidationError, match="lease"):
        Settings(env="test", pdf_wall_seconds=30, run_lease_seconds=60)


def test_prod_must_name_the_document_root(
    prod_secrets: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ENERGYIQ_DOCUMENT_ROOT")
    with pytest.raises(ValidationError) as caught:
        Settings(env="prod")
    assert "document_root" in str(caught.value)


def test_unisolated_workers_run_only_in_development_and_test(
    prod_secrets: dict[str, str],
) -> None:
    check_isolation(Settings(env="dev"))
    check_isolation(Settings(env="test", worker_isolation="none"))
    check_isolation(Settings(env="prod", worker_isolation="container"))
    assert Settings(env="prod").worker_isolation == "container"
    with pytest.raises(RuntimeError, match="dev or test"):
        check_isolation(Settings(env="prod", worker_isolation="none"))


# The parse child -------------------------------------------------------------


def test_a_valid_pdf_reports_its_page_count() -> None:
    result = run_pdf_child(make_pdf(2), LIMITS)

    assert (result.ok, result.page_count, result.code) == (True, 2, None)
    assert [p.quality_code for p in result.pages] == ["empty", "empty"]


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (make_pdf(1, password="secret"), "pdf_encrypted"),
        (make_pdf(1, password=""), "pdf_encrypted"),
        (make_pdf(LIMITS.max_pages + 1), "pdf_too_many_pages"),
        (MALFORMED_PDF, "pdf_malformed"),
        (NOT_A_PDF, "pdf_malformed"),
        (b"", "pdf_malformed"),
    ],
    ids=["password", "empty password", "too many pages", "broken", "text", "empty"],
)
def test_the_child_rejects_unusable_files_with_a_stable_code(
    data: bytes, code: str
) -> None:
    result = run_pdf_child(data, LIMITS)

    assert (result.ok, result.code) == (False, code)


def _python(source: str) -> list[str]:
    return [sys.executable, "-I", "-c", source]


def test_an_infinite_loop_is_killed_at_the_wall_clock_limit() -> None:
    limits = ChildLimits(3, 1024, 10, 1.0, 768 * MIB)

    result = run_pdf_child(b"x", limits, command=_python("while True: pass"))

    assert (result.ok, result.code) == (False, "pdf_parse_timeout")


def test_output_over_the_cap_is_rejected_and_the_child_killed() -> None:
    source = "import sys; sys.stdout.write('x' * 3_000_000)"

    result = run_pdf_child(b"x", LIMITS, command=_python(source))

    assert (result.ok, result.code) == (False, "pdf_parse_resource")


def test_a_crash_without_a_result_is_a_stable_failure() -> None:
    result = run_pdf_child(b"x", LIMITS, command=_python("raise SystemExit(3)"))

    assert (result.ok, result.code) == (False, "pdf_parse_failed")


@pytest.mark.parametrize("output", ["not json", "[]", '{"ok": true}', '{"ok": 1}'])
def test_only_a_complete_valid_result_is_accepted(output: str) -> None:
    source = f"import sys; sys.stdout.write({output!r})"

    result = run_pdf_child(b"x", LIMITS, command=_python(source))

    assert (result.ok, result.code) == (False, "pdf_parse_failed")


def test_the_child_inherits_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENERGYIQ_SECRET_KEY", "must-not-leak")
    monkeypatch.setenv("ENERGYIQ_DATABASE_URL", "postgresql://must-not-leak")
    source = (
        "import os, sys; names = [n for n in os.environ if n.startswith('ENERGYIQ')]"
        '; sys.stdout.write(\'{"ok": \' + (\'false, "code": "leaked"\' if names'
        " else 'true, \"page_count\": 0, \"pages\": []') + '}')"
    )

    result = run_pdf_child(b"x", LIMITS, command=_python(source))

    assert result.ok is True


@LINUX_ONLY
def test_a_memory_bomb_is_stopped_by_the_address_space_limit() -> None:
    limits = ChildLimits(3, 1024, 10, 10, 256 * MIB)
    # Mirror pdf_child: set the rlimit, then allocate past it.
    source = (
        "import resource; resource.setrlimit(resource.RLIMIT_AS, (256*1024*1024,)*2)"
        "; x = bytearray(1024*1024*1024)"
    )

    result = run_pdf_child(b"x", limits, command=_python(source))

    assert result.ok is False


@LINUX_ONLY
def test_the_child_cannot_write_a_file(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    source = (
        "import resource; resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))"
        f"; open({str(target)!r}, 'w').write('x')"
    )

    run_pdf_child(b"x", LIMITS, command=_python(source))

    assert not target.exists() or target.stat().st_size == 0


# The local store -------------------------------------------------------------


def test_commit_moves_a_temp_file_to_an_opaque_key(tmp_path: Path) -> None:
    store = LocalDocumentStore(tmp_path)
    temp = store.new_temp()
    temp.write_bytes(b"%PDF-")
    key = uuid4()

    store.commit(temp, key)

    assert not temp.exists()
    assert store.exists(key) and store.read(key) == b"%PDF-"
    assert list(store.keys()) == [key]
    assert store.delete(key) is True
    assert store.delete(key) is False
    assert not store.exists(key)


def test_a_discarded_temp_file_is_gone_and_foreign_names_are_ignored(
    tmp_path: Path,
) -> None:
    store = LocalDocumentStore(tmp_path)
    temp = store.new_temp()
    temp.write_bytes(b"x")
    store.discard(temp)
    store.discard(temp)  # already gone
    (tmp_path / "objects").mkdir(exist_ok=True)
    (tmp_path / "objects" / "not-a-uuid").write_bytes(b"x")

    assert not temp.exists()
    assert list(store.keys()) == []
    assert os.listdir(tmp_path / "tmp") == []


PARENT_SCRIPT = """
import subprocess, sys

if sys.argv[1] == "harden":
    from energyiq.worker.sandbox import make_parent_non_dumpable

    assert make_parent_non_dumpable()
child = subprocess.run(
    [sys.executable, "-I", sys.argv[2]], capture_output=True, text=True, timeout=30
)
print(child.stdout.strip())
"""

CHILD_SCRIPT = """
import os

try:
    data = open(f"/proc/{os.getppid()}/environ", "rb").read()
except PermissionError:
    print("DENIED")
else:
    print("READ" if b"SECRET_PROBE=hunter2" in data else "EMPTY")
"""


def _probe(mode: str, tmp_path: Path) -> str:
    import subprocess

    parent = tmp_path / "parent.py"
    child = tmp_path / "child.py"
    parent.write_text(PARENT_SCRIPT, encoding="utf-8")
    child.write_text(CHILD_SCRIPT, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(parent), mode, str(child)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
            "SECRET_PROBE": "hunter2",
        },
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_the_probe_scripts_are_valid_python() -> None:
    """Runs everywhere, so a broken probe cannot hide behind the Linux skip."""
    compile(PARENT_SCRIPT, "parent", "exec")
    compile(CHILD_SCRIPT, "child", "exec")


LINUX_NON_ROOT = pytest.mark.skipif(
    not sys.platform.startswith("linux") or getattr(os, "geteuid", lambda: 0)() == 0,
    reason="needs a non root Linux user (root may hold CAP_SYS_PTRACE)",
)


@LINUX_NON_ROOT
def test_a_same_uid_child_reads_the_parent_environ_without_the_flag(
    tmp_path: Path,
) -> None:
    """Control run: proves the probe can see the secret when nothing protects it."""
    assert _probe("plain", tmp_path) == "READ"


@LINUX_NON_ROOT
def test_a_non_dumpable_parent_hides_its_environ_from_a_same_uid_child(
    tmp_path: Path,
) -> None:
    assert _probe("harden", tmp_path) == "DENIED"
