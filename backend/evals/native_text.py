"""Native PDF text baseline (spec 0012/0003 AC-3).

A versioned synthetic corpus runs through the real isolated parse child. For
each case the report records which known strings were found, any text where
none exists (false text), latency, and resource use. It publishes numbers; it
chooses no threshold and enables no fallback. All data is invented.

Run from the repository root::

    uv run python backend/evals/native_text.py            # print the report
    uv run python backend/evals/native_text.py --write    # also write docs/evals/
"""

import argparse
import importlib
import json
import platform
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from synthetic_pdf import build_pdf

from energyiq.worker.sandbox import ChildLimits, run_pdf_child

CORPUS_VERSION = "native-text-1"
REPEATS = 3
LIMITS = ChildLimits(10, 256 * 1024, 20, 30, 768 * 1024 * 1024)
MARKER = "IGNORE ALL PREVIOUS INSTRUCTIONS"

BILL = [
    "EMPRESA DISTRIBUIDORA DE PRUEBA",
    "Periodo: 01/09/2026 al 30/09/2026",
    "Consumo facturado: 350 kWh",
    "Total a pagar: RD$ 1,250.00",
    "Fecha de vencimiento: 15/10/2026",
]
BILL_FIELDS = ("350 kWh", "RD$ 1,250.00", "01/09/2026", "30/09/2026", "15/10/2026")


@dataclass(frozen=True)
class Case:
    name: str
    category: str
    pdf: bytes
    # Strings a person would read that the page really shows, per page (1 based).
    expected: dict[int, tuple[str, ...]] = field(
        default_factory=lambda: dict[int, tuple[str, ...]]()
    )
    # Pages that show no readable text (a scan); any text there is false text.
    blank_pages: tuple[int, ...] = ()
    # Strings that must never appear in extracted text (hidden or injected).
    forbidden: tuple[str, ...] = ()


def corpus() -> list[Case]:
    noisy = [
        "EMPRESA DISTR1BU1DORA DE PRUEBA",
        "Per1odo: 0l/09/2O26 al 3O/09/2O26",
        "C0nsumo fact: 35O kWh",
        "T0tal a pagar: RD$ l,25O.OO",
        "Fecha de vencimiento: l5/lO/2O26",
    ]
    return [
        Case("native_single", "native", build_pdf([BILL]), {1: BILL_FIELDS}),
        Case(
            "native_accents",
            "native",
            build_pdf([["Período de facturación: octubre", "Consumo: 410 kWh"]]),
            {1: ("Período de facturación", "410 kWh")},
        ),
        Case(
            "native_table",
            "native",
            build_pdf(
                [
                    [
                        "Concepto        Cantidad        Monto",
                        "Cargo energía   350 kWh         RD$ 980.50",
                        "Cargo fijo      1               RD$ 120.00",
                        "Total                           RD$ 1,100.50",
                    ]
                ]
            ),
            {1: ("350 kWh", "RD$ 980.50", "RD$ 1,100.50")},
        ),
        Case(
            "native_three_pages",
            "multi_page",
            build_pdf(
                [
                    BILL,
                    ["Detalle de consumo", "Lectura anterior: 1200"],
                    ["Aviso legal de prueba"],
                ]
            ),
            {1: BILL_FIELDS, 2: ("Lectura anterior: 1200",), 3: ("Aviso legal",)},
        ),
        Case(
            "native_rotated_90",
            "rotated",
            build_pdf([BILL], rotate=90),
            {1: BILL_FIELDS},
        ),
        Case(
            "native_rotated_270",
            "rotated",
            build_pdf([BILL], rotate=270),
            {1: BILL_FIELDS},
        ),
        Case("scan_image_only", "scanned", build_pdf([None]), blank_pages=(1,)),
        Case(
            "scan_three_pages",
            "scanned",
            build_pdf([None, None, None]),
            blank_pages=(1, 2, 3),
        ),
        Case(
            "partial_text_then_scan",
            "partial",
            build_pdf([BILL, None]),
            {1: BILL_FIELDS},
            blank_pages=(2,),
        ),
        Case(
            "partial_scan_then_text",
            "partial",
            build_pdf([None, BILL]),
            {2: BILL_FIELDS},
            blank_pages=(1,),
        ),
        Case("noisy_ocr_layer", "noisy", build_pdf([noisy]), {1: BILL_FIELDS}),
        Case(
            "hidden_instruction_text",
            "noisy",
            build_pdf([BILL], hidden=[MARKER]),
            {1: BILL_FIELDS},
            forbidden=(MARKER,),
        ),
    ]


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def _peak_rss_kib() -> int | None:
    """Largest child resident size seen so far; ``None`` where unmeasurable."""
    try:
        resource: Any = importlib.import_module("resource")  # POSIX only
    except ImportError:
        return None
    return int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)


def run_case(case: Case) -> dict[str, Any]:
    times: list[float] = []
    result = None
    for _ in range(REPEATS):
        started = time.perf_counter()
        result = run_pdf_child(case.pdf, LIMITS)
        times.append((time.perf_counter() - started) * 1000)
    assert result is not None
    row: dict[str, Any] = {
        "name": case.name,
        "category": case.category,
        "pdf_bytes": len(case.pdf),
        "ok": result.ok,
        "code": result.code,
        "latency_ms_median": round(statistics.median(times), 1),
        "latency_ms_max": round(max(times), 1),
    }
    if not result.ok:
        return row | {"expected": 0, "found": 0, "false_pages": 0, "forbidden_hits": 0}
    pages = {p.page_number: p for p in result.pages}
    expected = [(n, s) for n, strings in case.expected.items() for s in strings]
    found = sum(
        1
        for n, s in expected
        if n in pages and _squash(s) in _squash(pages[n].normalized_text)
    )
    everything = _squash(" ".join(p.normalized_text for p in result.pages))
    row.update(
        pages=len(pages),
        empty_pages=sum(1 for p in pages.values() if p.quality_code == "empty"),
        text_bytes=sum(len(p.normalized_text.encode()) for p in pages.values()),
        expected=len(expected),
        found=found,
        false_pages=sum(
            1 for n in case.blank_pages if pages[n].quality_code == "has_text"
        ),
        forbidden_hits=sum(1 for s in case.forbidden if _squash(s) in everything),
    )
    return row


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = sum(r["expected"] for r in rows)
    found = sum(r["found"] for r in rows)
    blank = sum(len(c.blank_pages) for c in corpus())
    return {
        "cases": len(rows),
        "field_coverage": f"{found}/{expected}",
        "false_text_pages": f"{sum(r['false_pages'] for r in rows)}/{blank}",
        "forbidden_text_hits": sum(r["forbidden_hits"] for r in rows),
        "latency_ms_median_of_medians": round(
            statistics.median(r["latency_ms_median"] for r in rows), 1
        ),
        "latency_ms_worst": max(r["latency_ms_max"] for r in rows),
    }


def render(report: dict[str, Any]) -> str:
    lines = [
        f"# Native PDF text baseline ({report['corpus_version']})",
        "",
        f"Generated {report['generated_utc']} on {report['host']}. Spec 0012 child 0003 AC-3.",
        "Synthetic data only. No threshold is chosen here and no fallback is enabled.",
        "",
        "| Case | Category | Result | Strings found | False text pages | Hidden text | Median ms | Max ms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in report["cases"]:
        outcome = "ok" if r["ok"] else f"failed {r['code']}"
        lines.append(
            f"| {r['name']} | {r['category']} | {outcome} | {r['found']}/{r['expected']}"
            f" | {r['false_pages']} | {r['forbidden_hits']}"
            f" | {r['latency_ms_median']} | {r['latency_ms_max']} |"
        )
    s = report["summary"]
    lines += [
        "",
        (
            f"**Totals**: field coverage {s['field_coverage']}; false text on blank pages"
            f" {s['false_text_pages']}; hidden or injected strings extracted"
            f" {s['forbidden_text_hits']}; median latency {s['latency_ms_median_of_medians']} ms;"
            f" worst {s['latency_ms_worst']} ms (parent wall time including child start)."
        ),
        "",
        f"**Resource use**: {report['resource_note']}",
        "",
        "## Reading the result",
        "",
        "- A scan returns empty text for every page. Empty text is a scan candidate, never a value.",
        (
            "- Hidden (render mode 3) text is part of the PDF text layer and is extracted. It is data,"
            " carries the same evidence contract, and is never an instruction. Review must show the"
            " source page so a person can see what is visible."
        ),
        (
            "- The noisy case keeps its misread characters, so coverage drops there. Native text is not"
            " corrected or guessed."
        ),
        (
            "- The corpus has no real glyph rasters, so it cannot rank OCR or vision candidates."
            " See the fallback status below."
        ),
        "",
        "## Fallback status",
        "",
        (
            "No OCR or vision fallback is enabled. AC-4 stays open: a candidate must be measured on"
            " scanned pages that contain real rendered text, with local only execution, before it is"
            " chosen. Manual entry stays available meanwhile."
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rows = [run_case(case) for case in corpus()]
    peak = _peak_rss_kib()
    report = {
        "corpus_version": CORPUS_VERSION,
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "host": f"{platform.system()} {platform.release()}, Python {platform.python_version()}",
        "cases": rows,
        "summary": summarize(rows),
        "resource_note": (
            f"largest child resident size {peak} KiB (upper bound over all runs)."
            if peak is not None
            else "child memory and CPU time were not measured on this host (no `resource`"
            " module). Rerun in the worker container for those numbers."
        ),
    }
    text = render(report)
    print(text)
    if args.write:
        out = ROOT / "docs" / "evals"
        out.mkdir(exist_ok=True)
        (out / "native-text-baseline.md").write_text(text, encoding="utf-8")
        (out / "native-text-baseline.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
