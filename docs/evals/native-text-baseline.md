# Native PDF text baseline (native-text-1)

Generated 2026-11-05 15:56 on Windows 11, Python 3.13.15. Spec 0012 child 0003 AC-3.
Synthetic data only. No threshold is chosen here and no fallback is enabled.

| Case | Category | Result | Strings found | False text pages | Hidden text | Median ms | Max ms |
|---|---|---|---|---|---|---|---|
| native_single | native | ok | 5/5 | 0 | 0 | 213.1 | 221.4 |
| native_accents | native | ok | 2/2 | 0 | 0 | 205.8 | 218.3 |
| native_table | native | ok | 3/3 | 0 | 0 | 204.0 | 291.0 |
| native_three_pages | multi_page | ok | 7/7 | 0 | 0 | 234.2 | 296.7 |
| native_rotated_90 | rotated | ok | 5/5 | 0 | 0 | 292.1 | 303.2 |
| native_rotated_270 | rotated | ok | 5/5 | 0 | 0 | 206.4 | 365.1 |
| scan_image_only | scanned | ok | 0/0 | 0 | 0 | 201.9 | 215.3 |
| scan_three_pages | scanned | ok | 0/0 | 0 | 0 | 211.4 | 216.1 |
| partial_text_then_scan | partial | ok | 5/5 | 0 | 0 | 206.3 | 206.4 |
| partial_scan_then_text | partial | ok | 5/5 | 0 | 0 | 204.2 | 204.3 |
| noisy_ocr_layer | noisy | ok | 0/5 | 0 | 0 | 202.9 | 228.1 |
| hidden_instruction_text | noisy | ok | 5/5 | 0 | 1 | 231.6 | 247.7 |

**Totals**: field coverage 42/47; false text on blank pages 0/6; hidden or injected strings extracted 1; median latency 206.4 ms; worst 365.1 ms (parent wall time including child start).

**Resource use**: child memory and CPU time were not measured on this host (no `resource` module). Rerun in the worker container for those numbers.

## Reading the result

- A scan returns empty text for every page. Empty text is a scan candidate, never a value.
- Hidden (render mode 3) text is part of the PDF text layer and is extracted. It is data, carries the same evidence contract, and is never an instruction. Review must show the source page so a person can see what is visible.
- The noisy case keeps its misread characters, so coverage drops there. Native text is not corrected or guessed.
- The corpus has no real glyph rasters, so it cannot rank OCR or vision candidates. See the fallback status below.

## Fallback status

No OCR or vision fallback is enabled. AC-4 stays open: a candidate must be measured on scanned pages that contain real rendered text, with local only execution, before it is chosen. Manual entry stays available meanwhile.
