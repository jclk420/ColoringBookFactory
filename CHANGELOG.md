# Changelog

## v53.0 — Restore Safe Production Queue Path Handling

- Aligns queue records with the actual workflow: non-empty project path strings, not dictionaries.
- Validates queue paths remain inside the configured Projects folder before load or save.
- Rejects malformed, empty, and out-of-root queue entries without overwriting the stored queue.
- Adds regression coverage for queue round-trips, unsafe paths, and the production menu’s string-path format.


## v52.0 — Deep Persisted-State and World-Path Integrity

- Filters malformed build-history records and image-state entries in memory while preserving original JSON files.
- Validates nested build-state writes and world-index writes before replacing persisted data.
- Validates world collection fields and world identity on load; malformed collections fall back in memory only.
- Rejects unsafe world IDs that could escape the configured worlds directory.
- Adds runtime regression coverage for malformed records, rejected writes, and path traversal.


## v51.0 — JSON State and Production Queue Resilience

- Validates build-state root objects and key field types before callers consume them.
- Validates build-history lists and falls back in memory when persisted structure is malformed.
- Fails closed on malformed production queue roots, item collections, or item records.
- Rejects invalid queue saves before touching the existing queue file.
- Validates the world-index registry object while preserving unknown metadata fields.
- Adds runtime tests proving malformed files remain unchanged and valid queue saves remain versioned.
- Keeps fallback behavior explicit and avoids silent file repair or data deletion.

## v50.0 — OCR Batch Metadata Consistency

- Checks recorded OCR batch counts against the retained batch history.
- Cross-checks top-level latest-batch fields against the final batch record.
- Distinguishes exact duplicate page ranges from general overlapping ranges.
- Flags unsupported confidence labels, malformed warning lists, and invalid OCR method fields.
- Extends the dashboard warning gate and summary to show every new OCR integrity finding.
- Adds regression coverage for matching/mismatching metadata, duplicate ranges, and malformed fields.
- Keeps legacy metadata readable and all audits read-only.

## v49.0 — OCR Source Provenance and Warning Visibility

- Records the original intake SHA-256 on every newly attached OCR batch.
- Audits each retained batch's source digest against the pending intake record when available.
- Distinguishes malformed source digests from valid-but-mismatched source digests.
- Ensures duplicate-path, out-of-root, and source-hash findings trigger the dashboard warning summary.
- Keeps optional diagnostic counters backward-compatible with isolated dashboard/test contexts.
- Adds regression coverage for source-hash verification and warning activation.
- Preserves legacy batches, existing OCR evidence, and read-only/no-canon-write behavior.

## v48.0 — OCR Evidence Reference Integrity

- Detects when multiple OCR batches point to the same evidence file.
- Flags recorded OCR evidence paths that resolve outside the report directory and configured intake roots.
- Keeps out-of-root artifacts unverified rather than reading their contents for hash validation.
- Adds explicit dashboard counters for duplicate and out-of-root OCR paths.
- Adds regression coverage for duplicate references, out-of-root paths, and source-file non-mutation.
- Preserves legacy OCR metadata support and read-only/no-canon-write behavior.

## v47.0 — Intake Audit Resilience and Data-Shape Diagnostics

- Reports non-list record inputs and malformed graph entity/relationship collections instead of silently treating them as empty.
- Prevents near-duplicate suggestions from crashing when an entity's source-file field has the wrong type.
- Adds explicit actionable review guidance and summary counts for malformed top-level inputs.
- Treats placeholder evidence consistently and trims confidence labels before scoring.
- Replaces quadratic repeated-page counting with a linear-time count pass.
- Adds runtime regression tests for malformed inputs, input immutability, placeholder evidence, and confidence normalization.
- Keeps the audit advisory-only: no canon writes, auto-approval, or source-artwork changes.

## v46.0 — Non-Destructive OCR Evidence Writes

- Gives each OCR run a unique evidence filename, preserving prior files even when the same page range is rerun with identical text.
- Finalizes OCR text with a no-clobber hard link; an existing evidence path is never replaced.
- Migrates legacy single-batch OCR metadata into retained history before appending a new batch.
- Removes a newly written text file when the atomic report update fails, preventing orphaned evidence where possible.
- Adds tests proving existing OCR evidence is preserved and legacy page-range hints remain usable.

## v45.0 — OCR Source Identity Guard

- Verifies the selected OCR file and its staged intake copy against the recorded source SHA-256 before OCR begins.
- Rechecks both files after OCR and before saving any text or report changes, catching changes during processing.
- Refuses attachment when either file is missing, unreadable, malformed, or hash-mismatched; it never silently re-intakes or repairs the file.
- Adds runtime regression coverage for modified source and staged-copy rejection.
- Keeps source artwork, review decisions, approved registry, Series Bible, and canon unchanged.

## v44.0 — Persistent OCR Batch History and Range Safety

- Retains every OCR batch text path, page range, digest, confidence, method, warnings, and timestamp in the pending intake report.
- Adds a content-digest suffix to evidence filenames so changed OCR results cannot overwrite prior evidence.
- Suggests the next page after the highest saved range and requires explicit confirmation before repeating overlapping PDF pages.
- Refuses to proceed when existing OCR metadata or batch history is malformed rather than silently replacing it.
- Extends the read-only dashboard to verify every retained OCR batch and report overlapping ranges.
- Adds regression tests for batch-history hash verification, overlap detection, and next-page suggestions.
- Keeps OCR low-confidence and review-only; no canon write or automatic approval is added.

## v43.0 — Staged Artifact and OCR Provenance Audit

- Verifies staged review files still exist and match the intake record SHA-256 without modifying them.
- Audits OCR evidence text-file paths, file existence, recorded SHA-256, and requested page-range metadata.
- Distinguishes missing files, malformed hashes, hash mismatches, unreadable artifacts, and invalid page ranges in dashboard diagnostics.
- Corrects OCR text digest calculation to include the final newline actually persisted to disk.
- Adds runtime tests for artifact hash verification and report-relative path resolution.
- Keeps all checks read-only; no staged files are repaired, approvals are changed, or canon is written.

## v42.0 — Collision-Safe, Verified Intake Staging

- Reserves unique batch directories even when intake runs occur in the same second.
- Chooses a new staged filename when a destination already exists; existing staged files are never intentionally overwritten.
- Copies through a same-directory temporary file, verifies its SHA-256 against the source digest, and publishes it with a no-clobber hard link.
- Discards temporary copies when the source changes during staging or when the destination is claimed concurrently.
- Adds regression coverage for same-name/different-content files, same-second batch collisions, source preservation, and corrupt-copy rejection.
- Keeps source files and canon unchanged; all intake candidates remain review-only.

## v41.0 — OCR Evidence Provenance and Batch Safety

- Saves OCR/native-text evidence to a separate page-range-specific text file beside the matching intake report.
- Records the text path, page range, selected-page count, character count, and SHA-256 digest in report metadata.
- Adds optional PDF batch page-limit/start prompts with bounded validation and non-overlapping range support.
- Parses candidates only from the selected page range, preventing unrelated pages from leaking into a partial-batch candidate set.
- Uses atomic text writes; failed evidence persistence leaves the intake report unchanged.
- Adds page-range helper regression tests and preserves review-only, no-canon-write behavior.

## v40.0 — Comprehensive Intake Integrity Diagnostics

- Adds separate warnings for malformed classification and metadata fields.
- Counts malformed entity and relationship candidate entries instead of silently filtering them.
- Flags unknown status values, missing source paths, and malformed evidence collections.
- Detects when multiple manifest entries reuse the same report path.
- Prints expanded read-only diagnostics; does not auto-repair, approve items, modify source artwork, or write canon.


## v39.0 — Intake Data Validation and Diagnostics

- Rejects non-object intake manifests with a clear read-only diagnostic.
- Counts missing or invalid report paths separately from unreadable reports.
- Reports missing report files instead of treating them as generic read failures.
- Counts malformed item entries and items with missing status fields.
- Prints an actionable integrity warning summary without changing staged data or canon.

## v38.0 — Intake Dashboard Resilience

- Validates the manifest batch collection and reports malformed batch entries instead of iterating invalid data.
- Counts unreadable reports and malformed report structures so skipped data is visible to the user.
- Skips malformed report payloads safely without changing source files, staged records, approvals, or canon.
- Sanitizes extracted entity and relationship candidate collections before display, preventing malformed list fields or non-object entries from crashing the dashboard.
- Prints a concise warning summary while preserving the dashboard's normal review workflow.

## v37.0 — Intake Review Decisions and Complete Finding Summaries

- Extends plain-language review actions to all major finding groups, including context, evidence, relationship quality, repeated pages, and duplicate aliases.
- Adds advisory `recommended_status` values to review groups and queue items; these are guidance only and never approve or change records.
- Makes the audit-wide summary count every published finding group and exposes per-group counts for dashboard consistency.
- Defines totals as finding instances, explicitly allowing one underlying issue to appear in multiple groups.
- Adds regression tests for clean audits, malformed/conflicting source data, summary coverage, advisory holds, and no-mutation guarantees.

## v36.0 — Evidence Traceability and Ambiguity Review

- Flags identical normalized names used across different entity kinds and ambiguous relationship endpoints.
- Detects duplicate source-path references after case and slash normalization without changing the original paths.
- Checks extracted candidates for source-file, evidence, and page traceability.
- Flags placeholder evidence paired with high-confidence candidates or intake evidence.
- Adds audit-wide review summary totals and group counts while preserving review-only behavior.
- Adds regression coverage for ambiguous identities, traceability gaps, malformed top-level collections, and no-mutation guarantees.

## v35.0 — Lore Audit Actionability and Structural Integrity

- Detects malformed entity, relationship, and intake-record shapes without stopping the audit.
- Flags blank entity names, duplicate canonical entities, repeated/blank list entries, and aliases that collide with another entity's canonical name.
- Checks relationship field types and unsupported relationship confidence labels.
- Flags missing source filenames, malformed page/candidate lists, and placeholder evidence.
- Adds a prioritized, plain-language action list and summary counts to help users decide what to review next.
- Preserves all source records; no auto-merge, canon writes, artwork edits, or source-file changes.

## v33.0 — Lore Consistency Guards

- Flags one source file attributed to multiple distinct lore entities for review.
- Flags high-confidence intake records without usable evidence and invalid record-level page provenance.
- Highlights suspicious world/location placeholders and identical world/location values.
- Detects duplicate extracted candidates and malformed candidate-list structures.
- All checks remain read-only; no names, relationships, canon, or artwork are changed.

## v32.0 — Lore Provenance and Relationship Integrity

- Flags entities missing source-file, evidence, or page provenance and identifies invalid page numbers.
- Detects aliases mapped to multiple candidate entities without merging or renaming them.
- Reports incomplete/self-referential relationships and multiple targets for the same subject/relation.
- Extends the read-only audit summary; no canon, artwork, or source files are changed.

## v31.0 — Lore Evidence Quality Audit

- Adds a read-only quality score and prioritized review queue for staged lore candidates.
- Suggests near-duplicate names without merging them, reports conflicting name contexts/archive IDs, and flags invalid entity kinds and unresolved relationship endpoints.
- Keeps all findings advisory; no source files, artwork, Series Bible, or canon records are changed.


## v34.0 — Lore Review Data Hardening

- Flags unsupported confidence labels rather than silently treating them as valid evidence.
- Detects repeated source-page references in intake records, entities, and relationships.
- Identifies duplicate aliases within an entity and malformed alias fields.
- Checks relationships for missing source-file, evidence, or page provenance.
- Flags exact normalized duplicate relationship candidates without deleting or merging them.
- All checks are advisory and review-only; canon and source artwork are unchanged.

Release notes for the source-controlled ColoringBookFactory application. See `ROADMAP.md` for more implementation detail. These notes describe code capabilities; they do not certify any specific local book or marketplace package as released.

## v30.0 — Cross-Batch Lore Evidence Graph

- Consolidates staged intake classifications, extracted entity candidates, aliases, archive identifiers, and relationship candidates across readable intake batches for review.
- Preserves source-file provenance and confidence, deduplicates repeated evidence, and reports candidate-name conflicts, archive-ID conflicts, and unresolved relationship endpoints.
- Displays graph counts in the read-only lore intake dashboard without writing to a Series Bible or world canon.

## v29.0 — Platform Listing Quality Gate

- Adds field-level listing completeness checks, quality scores, readiness states, and explicit user actions.
- Blocks readiness when the master PDF is missing and avoids guessing prices or KDP categories.
- Adds project-wide readiness output and keeps drafts clearly unpublished.

## v28.0 — Accurate OCR Review Accounting

- Separates newly extracted candidates from duplicates and reports archive-record and review-only counts.
- Keeps OCR candidates low-confidence and preserves the primary classification and canon.

## v27.0–v27.9 — Contextual Intake and Archive-Aware OCR

- Adds contextual location evidence while leaving ambiguous matches unassigned.
- Adds optional review-only OCR, bounded extraction behavior, relative-path matching, archive heading and identifier recognition, structured archive-field capture, and candidate provenance.
- Keeps extracted names, aliases, and relationships as unapproved evidence.

## v26.0 — Lore Intake Review Dashboard

- Adds a read-only summary of staged batches, pending/approved/rejected items, unresolved classifications, and duplicate warnings.

## v23.0 — Reliability and Safe Migration Toolkit

- Adds package-manifest verification, tamper detection, migration previews, and conflict-safe repair/diagnostic tools.

## v22.0 — Platform Listing Builder

- Generates platform-specific listing JSON, paste-ready text, and project-wide readiness reports from available project metadata.
- Leaves prices, categories, and account-dependent choices for user review.

## v21.0 — Canon Registry and Continuity Tools

- Adds explicit review/preview tools for importing approved intake records, resolving conflicts, checking entity reuse, and auditing book-to-series coverage.
- Preserves backups and requires deliberate choices for canon changes.

## v20.0 — Release Safety and Lore Diagnostics

- Adds read-only release preflight checks and lore/continuity diagnostics.

## Earlier releases

Earlier production, PDF, packaging, world-engine, and publishing features remain part of the factory. Their detailed history is maintained in the project roadmap and source-control history.
