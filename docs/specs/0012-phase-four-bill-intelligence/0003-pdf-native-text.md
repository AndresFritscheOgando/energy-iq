# 0003. PDF native text and fallback evaluation

## Summary

Extract text from each PDF page and retain evidence that a person can inspect. A scan without useful native text stays available for manual review. OCR and vision are evaluated before either becomes a product dependency.

## Requirements

- **AC-1**: A bounded parser returns normalized page text, page number, exact source span, and a text quality code. It preserves the original PDF and never treats extracted text as an instruction.
- **AC-2**: Empty, scanned, corrupt, encrypted, or timed out PDFs have explicit safe outcomes. They never produce a guessed bill field or a confirmed invoice.
- **AC-3**: A versioned evaluation set includes native, scanned, rotated, noisy, partial, and multi page synthetic or permitted anonymized layouts. It reports native extraction coverage, false text, latency, and resource use before a fallback is chosen.
- **AC-4**: Any later OCR or vision fallback is local, bounded, and measured on the same corpus. Its output has the same page evidence contract and still needs human confirmation.

## Decision

Start with `pypdf` (pin at 6.6.2 or later, which fixes CVE-2026-24688, and verify Python 3.13 support and the exact version at build time) for page text and native text spans. It is pure Python with a permissive license. The runner up is `pypdfium2`, which handles odd files more robustly but is native code and so a larger attack surface; reconsider it only if the baseline corpus shows `pypdf` missing text that it finds. `PyMuPDF` is excluded for its AGPL license. Parse only inside the child process defined in child 0002, using its page, text, CPU, wall clock, and memory limits. The adapter reads pages one at a time and stops as soon as the page or text limit is passed. It rejects an encrypted file without trying a password. Record page and quote offsets as mandatory evidence; a bounding box is optional because text geometry is not consistently reliable across PDFs. Put parsing behind a small adapter and process boundary. Evaluate a local OCR or vision candidate only after the native baseline, and keep manual entry available meanwhile.

## Feature design

**Output contract**: `ParsedPage(page_number, normalized_text, source_kind, quality_code, text_digest)` plus bounded spans. `source_kind` is `native`, `ocr`, or `vision`. A field evidence row references the immutable run and exact page span. If text normalization prevents an exact quote match, preserve the raw source span and its normalization mapping or mark it unverified.

**Quality gate**: Empty text alone identifies a scan candidate, not a license to infer values. The benchmark chooses a fallback by required field coverage and false field rate with resource and latency costs reported. No threshold is invented before the baseline is observed. A fallback failing the chosen gate remains disabled.

**Tests**: Synthetic native text, an image only scan, malformed streams, encrypted files, oversized decoded content, and instruction text embedded in the PDF. Verify page mapping and evidence span round trips.

## Build plan

1. Add the parser adapter, page text limits, and source span contract, satisfies **AC-1**, **AC-2**. Built 2026-11-05.
2. Run and publish the baseline corpus report, satisfies **AC-3**. Built 2026-11-05: `backend/evals/native_text.py`, report in `docs/evals/native-text-baseline.md`.
3. Evaluate a local fallback and enable only one whose result supports it, satisfies **AC-4**. Not run: needs scans with real rendered text and a local candidate. Fallback stays disabled.

## Consequences

Native text is cheap and clear, but many scans need manual entry until a measured fallback is available.

## Rationale

The owner chose manual review while fallback is evaluated. The official `pypdf` guide states that it does not extract text from images, so a scan cannot be treated as a parser success.
