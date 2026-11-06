"""The native text corpus stays versioned, synthetic, and safe (spec 0012/0003 AC-3)."""

from native_text import CORPUS_VERSION, corpus, run_case


def test_the_corpus_covers_every_required_layout_kind() -> None:
    kinds = {case.category for case in corpus()}

    assert {"native", "scanned", "rotated", "noisy", "partial", "multi_page"} <= kinds
    assert CORPUS_VERSION.startswith("native-text-")


def test_a_scan_never_produces_text_and_no_case_fails_to_parse() -> None:
    for case in corpus():
        row = run_case(case)
        assert row["ok"], (case.name, row["code"])
        assert row["false_pages"] == 0, case.name
