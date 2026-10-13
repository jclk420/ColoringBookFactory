# ColoringBookFactory

**Current factory version: 51.0**

ColoringBookFactory is a Windows-oriented Python application for producing coloring books, organizing world/series lore, preparing marketplace listing drafts, and checking production packages before release.

## Requirements

- Python 3.14 (the source-validation workflow uses Python 3.14).
- Install the dependencies required by the features you use. Some image/PDF and OCR capabilities are optional; the factory's capability report identifies optional modules available in the current environment.
- OCR for scanned pages requires the optional OCR/rendering tools documented by the OCR utility. Embedded PDF text extraction is preferred when available.

## Run the factory

From the repository root in PowerShell:

```powershell
python -X utf8 .\factory.py
```

The main menu includes book creation/import, production, publishing, marketing, worlds and series, lore intake, release diagnostics, canon tools, listing generation, and reliability/migration tools. State and queue loaders now validate their JSON structure before use; malformed data produces an explicit warning and an in-memory safe fallback without rewriting the persisted file.

## Core workflows

### 1. Intake and organize lore

1. Open **Lore Intake / Auto-Sort PDFs & Images**.
2. Select or drop supported PDFs/images to stage copies.
3. Review the proposed world, location, book, or creature classifications.
4. Use the read-only dashboard to inspect candidates, duplicates, provenance, and unresolved relationships.
5. Explicitly review and approve candidates before using the separate canon tools.

Unknown or ambiguous matches must remain review items. OCR-derived text is evidence, not canon. OCR review saves selected page-range text to a separate `OCR_TEXT_...txt` evidence file and records its path, page range, character count, and SHA-256 digest in the intake report; use non-overlapping page ranges for large scanned PDFs. The read-only quality audit provides complete finding-group counts, advisory hold/review recommendations, and plain-language next steps. It also reports malformed top-level input shapes instead of silently treating them as empty data, tolerates malformed source-file lists during similarity checks, scores placeholder evidence consistently, and avoids quadratic repeated-page counting. The intake dashboard also reports malformed nested fields, unknown statuses, missing source paths, malformed evidence, invalid candidate entries, and repeated report paths. Intake staging now reserves a unique batch directory, uses collision-safe staged filenames, and verifies staged bytes against the source SHA-256 before committing a staged file. The read-only dashboard also checks staged-file existence/hash integrity and verifies every retained OCR batch text path, page range, and recorded hash. It flags OCR evidence paths reused across batches and paths that resolve outside the intake report directory and configured intake roots, rather than silently treating those references as verified. PDF OCR suggests the next page after the highest saved range and requires explicit confirmation to repeat overlapping ranges. Before and after OCR, the factory verifies both the selected file and the staged copy against the original intake SHA-256; changed files cannot be attached as if they were the original evidence. Each new OCR batch also records that original source digest, and the read-only audit compares retained batch provenance against the pending intake record. The audit also cross-checks the batch count and latest-batch summary fields, detects exact duplicate page ranges, and flags malformed confidence, method, and warning-list metadata. The dashboard surfaces duplicate evidence paths, out-of-root paths, and invalid or mismatched source digests. OCR evidence filenames are unique per run and finalized without overwriting an existing evidence file. Legacy single-batch OCR metadata is retained in the batch history, and a failed report update removes the new text file when possible. It also flags missing or invalid page provenance, alias conflicts, incomplete relationships, conflicting targets, source files attributed to multiple distinct entities, high-confidence records without evidence, suspicious context placeholders, duplicate extracted candidates, unknown confidence labels, repeated page references, duplicate aliases, missing relationship provenance, and duplicate relationship candidates, malformed entity/relationship/record fields, duplicate canonical entities, aliases colliding with canonical names, and plain-language review actions, cross-kind name collisions, ambiguous relationship endpoints, duplicate source-path references, candidate-level traceability gaps, and placeholder/high-confidence evidence conflicts. Intake staging and diagnostic dashboards should not modify original source files or silently promote candidates into a Series Bible.

### 2. Prepare marketplace listings

Open **Platform Listing Builder** to generate per-platform JSON and paste-ready text drafts under each project's `MARKETING\LISTINGS` folder, plus `LISTING_READINESS.json`.

The builder supports KDP, Gumroad, Payhip, and Digital PDF drafts, and can identify other configured profiles. Prices and KDP categories are not guessed. Generated listings are drafts; the factory does not upload or publish products.

### 3. Verify a release

Use **Release Safety & Lore Diagnostics** and the reliability toolkit to inspect package manifests, detect changed/missing/empty files, and check release blockers. Treat a preflight pass as a local validation result, not proof that a marketplace accepted a product.

## Validation

Run the source checks from the repository root:

```powershell
python -m py_compile .\factory.py
python -m unittest discover -s tests -v
```

The GitHub Actions workflow runs compilation and the dependency-free regression suite on Windows with Python 3.14.

## Safety and scope

- Listing drafts are never represented as uploaded, approved, or published.
- Missing prices and marketplace-specific selections remain explicit user actions.
- Intake candidates retain provenance and confidence and do not automatically become canon.
- Diagnostic preflight/manifest verification is read-only with respect to production packages.
- Use backups and review previews before any explicit operation that writes to a Series Bible or changes production outputs.

See [CHANGELOG.md](CHANGELOG.md) for the documented release history and [ROADMAP.md](ROADMAP.md) for completed upgrades and future work.
