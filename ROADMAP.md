# Coloring Book Factory — Upgrade Roadmap

This roadmap separates shipped work from future candidates. Planned items are not implemented until their code, tests, and release notes are committed.

## Implemented on the current upgrade branch

### v24.0 — Preview-First Lore Repair & Reconciliation
- Separates book attachment from repair: Nightmare Series reconciliation no longer opens the manual selector automatically or mistakes a cancelled/empty selection for a repair failure.
- Adds a read-only repair preview for each registered book, listing missing metadata fields, existing-value conflicts, and missing/unreadable project folders.
- Requires typing `REPAIR` before reconciliation writes; cancellation performs no repair writes.
- Proposes filling only missing known fields; conflicting series names/IDs, book numbers, and world identity values remain untouched and are reported for review.
- Saves the preview and continuity findings in the repair report; production PDFs and artwork are not rebuilt or modified.
- Adds regression tests for read-only preview behavior, conflict preservation, explicit confirmation, and separation of attachment from repair.


### v23.0 — Factory Reliability & Safe Migration Toolkit
- Adds a runtime capability report for optional image/PDF engines and drag-and-drop support without installing dependencies.
- Verifies enabled platform package manifests for missing files, SHA-256 mismatches, unsafe manifest paths, and unlisted files; writes a diagnostic report without changing package contents.
- Records a deterministic project-input fingerprint from metadata and source image/PDF hashes without rebuilding the MASTER PDF.
- Adds a read-only project metadata migration preview and an explicitly confirmed additive migration; existing values are preserved, the backup is hash-verified, and post-write verification/rollback are included.
- Adds disposable end-to-end fixtures that validate manifest checks, tamper detection, repeatable fingerprints, and backup-protected migration entirely in a temporary directory.
- Wires the toolkit into main-menu option 22 and adds regression tests for menu/function uniqueness, manifest tampering, and migration preview safety.

## Shipped on the current upgrade branch

### v21.0 — Canon Registry & Continuity Tools
- Adds a schema-aware preview/import for explicitly approved creature and location records from `INTAKE/APPROVED_LORE.json`; unsupported world/book shapes and name/context conflicts remain blocked for review.
- Requires the user to type `IMPORT` before changes, creates a timestamped Series Bible backup, and records before/after changes in `CANON_CHANGELOG.json`.
- Adds an interactive conflict-resolution queue; keeping canon is the default-safe option, while importing a conflicting entity as distinct requires an explicit choice.
- Adds exact and near-duplicate entity reuse suggestions without automatic merging or renaming.
- Adds a book-to-series coverage report for missing metadata, attachment state, and project-path existence.
- Adds menu wiring, version updates, and regression checks; diagnostics remain read-only unless the user explicitly confirms an import.


### v20.0 — Release Safety & Lore Diagnostics
- Adds a read-only release preflight listing MASTER integrity, enabled package contents, blockers, hashes, and output destinations without rebuilding production artifacts.
- Compares current package files against the last saved delivery audit and reports added, changed, and removed files.
- Validates safety ZIP readability/CRC and unsafe paths without extracting or restoring anything; flags whether a MASTER PDF is present.
- Produces standardized machine-readable diagnostics in `REPORTS/FACTORY_DIAGNOSTICS.json`.
- Adds a read-only lore consistency matrix for project title, world identity, location, and registered lore matches; it never rewrites canon.
- Adds a main-menu entry and integrity checks for the new workflow.

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
- **Atomic JSON writes:** write temporary files, validate JSON, then replace originals to reduce corruption risk after interruptions.

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


### v22.0 — Platform Listing Builder
- Generates a structured listing draft (LISTING.json), paste-ready field sheet (LISTING.txt), and project-wide LISTING_READINESS.json for each platform profile.
- Builds dedicated field sets for KDP, Gumroad, Payhip, and Digital PDF; other configured platform profiles receive a clearly marked generic draft for platform-specific review.
- Reuses the Gumroad Listing Studio output and project metadata; includes verified master-PDF page count and trim dimensions only when readable.
- Leaves prices, categories, and other account-dependent selections blank rather than guessing. Marks drafts as unpublished and never claims a package was uploaded.
- Writes listing files under each project's MARKETING/LISTINGS folder without rebuilding or modifying the master PDF.
- Adds source-integrity tests for unique function definitions, menu wiring, missing-price safety, and unpublished status.
