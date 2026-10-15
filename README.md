# ColoringBookFactory

**Current factory version: 113.0**

ColoringBookFactory is a Windows-oriented Python application for producing coloring books, organizing world/series lore, preparing marketplace listing drafts, and checking production packages before release.

## Publishing handoff (options 31 and 32)\n\nUse **31. Publishing Completion Center** for the platform-specific PDF and listing checklist, then **32. Publishing Handoff Inventory** to fingerprint the files in each platform folder and identify missing folders, zero-byte files, filename collisions, and read errors. Reports are saved without overwriting earlier reports. See [Publishing Handoff Inventory](docs/PUBLISHING_HANDOFF_INVENTORY.md). These are local checks only; they do not upload or publish products.\n\n## Requirements

- Python 3.14 (the source-validation workflow uses Python 3.14).
- Install the dependencies required by the features you use. Some image/PDF and OCR capabilities are optional; the factory's capability report identifies optional modules available in the current environment.
- OCR for scanned pages requires the optional OCR/rendering tools documented by the OCR utility. Embedded PDF text extraction is preferred when available.

## Run the factory

From the repository root in PowerShell:

```powershell
python -X utf8 .\factory.py
```

The main menu includes book creation/import, production, publishing, marketing, worlds and series, lore intake, release diagnostics, canon tools, listing generation, automatic post-import listing preparation, upload-readiness reporting, a one-click five-stage publishing run, source-PDF provenance auditing, a preserved manual upload checklist, prioritized release action plans, delivery-folder inventory, a five-stage creation/artwork quality center, a prompt-generation ZIP handoff, generated-art intake preview, lore continuity audit, assembly readiness gate, listing-metadata drift audit, package-freshness verification, persistent upload-state validation, gated release-handoff ZIP export, verified INPUT backups before assembly, confirmed generated-art import, a guided production flow, release evidence snapshots, file-level release comparisons, integrity rechecks, readiness trend history, and a read-only Publishing Completion Center that checks platform-specific listing folders, basic package-PDF integrity, ambiguous master sources, and exact missing deliverables; READY_TO_UPLOAD is a local check only and never means marketplace approval or completed upload. State and queue loaders now validate their JSON structure before use; malformed data produces an explicit warning and an in-memory safe fallback without rewriting the persisted file.

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


### 4. Run the one-click publishing workflow

Choose **24. One-Click Publishing Run**. It generates listing drafts without overwriting existing drafts, refreshes the upload-readiness board, checks the imported source PDF digest when one was recorded, preserves manual upload-checklist statuses, builds a prioritized task plan, and inventories exact package/listing paths. The summary is saved to `REPORTS\\PUBLISHING_RUN_SUMMARY.json`. This is local preparation: it does not rebuild the MASTER PDF, upload files, or publish a product.


### 5. Check creation and artwork quality

Choose **25. Creation & Artwork Quality Center** to audit the blueprint/prompt/queue counts, inspect artwork file readability and duplicate bytes, compare exported prompt text against the current prompt manifest, and create a prioritized creation action plan. The reports are written under `REPORTS`. This is a technical/structural audit: it does not alter prompts or artwork, change canon, or claim to judge artistic quality automatically.


### 6. Prepare artwork generation and assembly

Choose **26. Artwork Generation Handoff & Assembly Gate**. The factory checks prompt-to-world/location/series IDs, packages existing prompt text into a collision-safe ZIP for use in an external image-generation tool, previews how generated files map to stable image IDs, and verifies every artwork job before assembly. The external-art preview does not copy files; use the separate artwork import/QA workflow to bring assets into the project. Assembly readiness is not the same as a completed build.


### 7. Validate the final release handoff

Choose **27. Final Release Integrity & Handoff Center** to compare existing listing drafts against current project metadata, verify package manifests and recognizable interior-PDF freshness, review manual upload states, and export an offline handoff ZIP only when the gates pass. The ZIP contains local package/listing files and a SHA-256 inventory; it does not upload or publish anything.


### 8. Safely import generated artwork and stage a build

Choose **28. Safe Artwork Import & Guided Production**. The factory previews a generated-art folder, requires explicit confirmation before copying files into `ARTWORK_QUEUE/SOURCE`, rechecks hashes, refuses collisions, runs artwork QA after a successful import, and shows assembly readiness. Before assembly replaces images in `INPUT`, it creates and verifies a backup. A failed backup or staging operation blocks the build; this workflow does not automatically assemble or publish.


### 9. Track release evidence over time

Choose **29. Release Evidence History & Change Tracker** to save a no-clobber snapshot of the current MASTER, platform packages, listing drafts, and key project metadata. The factory hashes the tracked files, compares the new snapshot to the previous one, checks whether tracked files have changed since capture, and summarizes recent readiness states. Snapshots are local evidence—not proof that a product was uploaded or published.
