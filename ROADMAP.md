# Coloring Book Factory — Upgrade Roadmap

This roadmap separates shipped work from future candidates. Planned items are not implemented until their code, tests, and release notes are committed.

## Shipped on the current upgrade branch

### v19.0 — Lore Intake Review & Metadata Workflow (draft PR)
- Adds best-effort PDF title/page/text extraction through `pypdf` or `PyPDF2` when installed, and image dimensions/format metadata.
- Detects SHA-256 duplicates against previous intake batches as well as duplicates in the current batch.
- Adds an interactive review queue for correcting kind/name/world/location and approving or rejecting each staged file.
- Moves a staged copy to the corrected review-tree path when the user edits its classification.
- Writes approved records to `INTAKE/APPROVED_LORE.json`, de-duplicates approved records, and explicitly keeps that registry separate from Series Bible/world canon pending a later schema-aware import step.
- Adds tests for image/PDF metadata behavior, cross-batch duplicate lookup, approved-registry de-duplication, and menu wiring.


### v18.2 — Lore Intake & Auto-Sorter
- Adds a dedicated main-menu entry for batch intake of PDFs and images, including optional drag-and-drop when `tkinterdnd2` is installed and a multi-file picker fallback.
- Matches filenames against registered world, location, creature, and book names; ambiguous and unmatched files are sent to `_Needs_Review` instead of being guessed into canon.
- Copies files into a review-only World / Location / Creature tree and records SHA-256 hashes, match reasoning, duplicate-in-batch detection, rejected files, and batch manifests.
- Leaves original source files and existing Series Bible/world canon untouched; intake is a staging workflow, not automatic canon approval.
- Adds dependency-free tests for exact creature matching, safe review paths, ambiguous-name handling, menu wiring, and the `tempfile` import required by atomic JSON writes.


### v18.1 — Atomic JSON persistence
- Writes JSON to a temporary file in the target directory, flushes it to disk, then replaces the destination.
- Cleans up abandoned temporary files after failures.
- Prevents an interrupted JSON write from truncating the existing file when the final replacement fails.
- Adds runtime tests for successful writes and simulated replacement failure.

### v18.0 — Conflict-safe world-to-book reconciliation
- Adds a deliberate repair step for books explicitly registered in a Series Bible.
- Fills only missing project `world_id` and `universe_name` values when they agree with the canonical world.
- Repairs missing entries in the canonical world's `books` registry.
- Preserves conflicting non-empty world identities and reports conflicts rather than silently rewriting canon.
- Preserves existing `world_relationship` and `world_canon` flags.
- Refuses to create missing worlds, world records, or project folders.
- Includes repair outcomes in `LORE_REPAIR_REPORT.json`.

### Earlier branch work retained
- Selector selections persist while filtering; explicit book attachment is separate from candidate discovery.
- Read-only series continuity auditing checks project metadata, book numbering, world identity, and world registry links.
- Repair reports summarize findings and conflict counts.
- Canonical series-to-world repair is explicit and does not invent worlds.

## Recommended next upgrades

### Priority 1 — Release safety and recoverability
- **Preflight-only release mode:** show exact files, checks, blockers, and output destinations without changing production files.
- **Release change summary:** compare the last successful release with the current one; report changed artwork, pages, metadata, and package files.
- **Verified restore drill:** validate backup ZIP contents and hashes before offering restore; require a clear target and never overwrite silently.
- **Atomic JSON writes:** write temporary files, validate JSON, then replace originals to reduce corruption risk after interruptions.
- **Machine-readable diagnostics:** standard error codes and a single health report for missing dependencies, unreadable metadata, bad paths, and failed packages.

### Priority 2 — Book and lore quality
- **Schema-aware canon import:** map user-approved `APPROVED_LORE.json` entries into Series Bible/world records only after confirming each target schema and showing a before/after diff.
- **Lore intake approval workflow:** review staged items, correct matches, then explicitly register approved creatures/locations and record their source files in the Series Bible.
- **Lore consistency matrix:** compare each attached book against world rules, locations, entities, tone, and series canon, with evidence and severity.
- **Canon change log:** record who/what changed a Series Bible or world record, before/after values, and timestamp.
- **Conflict resolution queue:** let the user review each mismatch and choose preserve-project, use-series-canon, or leave-unresolved before any overwrite.
- **Entity reuse checks:** detect likely duplicate characters, creatures, locations, and objects across books without automatically merging them.
- **Book-to-series coverage report:** show which books are attached, numbered, missing metadata, missing lore pages, or not yet production-ready.

### Priority 3 — Production reliability
- **End-to-end test fixtures:** temporary sample projects and worlds that exercise real JSON repair, release packaging, and rollback behavior.
- **Package manifest verification:** check every expected artifact exists, hash files, and detect stale outputs before declaring a package ready.
- **Deterministic builds:** record inputs, settings, engine version, and source hashes so the same inputs can be compared between builds.
- **Dependency and capability check:** report available image/PDF engines and gracefully explain optional features that cannot run.
- **Project migration tooling:** preview schema/version changes, create a verified backup, migrate only known fields, then re-audit.

### Priority 4 — Faster publishing and business workflow
- **Platform upload readiness board:** clearly distinguish prepared packages from actually uploaded/published products.
- **Listing completeness checker:** validate title, subtitle, description, tags, price, license, preview images, and platform-specific requirements.
- **Marketing asset consistency:** tie product thumbnails, listing copy, and preview pages to the same release ID.
- **Production queue dashboard:** prioritize books by missing artwork, QA status, package readiness, and next required action.
- **Sales/expense tracker export:** optional CSV exports for per-book production cost, platform fees, and sales entries; no automatic financial-account access.

## Implementation rules
1. Preserve the current master and existing PDFs/artwork unless a feature explicitly requests a rebuild.
2. Audit first; mutate only through a clearly named repair or release action.
3. Never silently resolve conflicting world/series identity, renumber books, or change canon flags.
4. Do not claim a package is uploaded merely because it was generated.
5. Every meaningful change should include regression tests, a version/header update where appropriate, and a passing CI run before it is described as validated.
6. Keep PR #1 open and unmerged until the user explicitly authorizes merging.
