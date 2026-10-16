## Compatibility fix — Recover Missing MASTER from Recorded Original PDF (factory version unchanged)

- Repairs imported-finished-PDF projects where MASTER metadata survives but the copied *_MASTER.pdf is missing.
- If normal project PDF discovery finds no source, reads only the recorded source_pdf path from MASTER metadata and reuses it only when it exists and is a PDF.
- Rejects unreadable/zero-page source PDFs before creating a MASTER; never chooses a nearby interior PDF just to fill the gap.
- Keeps the original source unchanged and retains the existing no-overwrite behavior for an existing MASTER PDF.
- Repository changes alone do not restore files on the user's PC; the updated factory must be run on the affected project.
## v133.0–v136.0 — Large PDF Page-Marker Scan Fix

- **v133 — Full-file streaming scan:** page markers are counted across the whole PDF rather than only the first and last few kilobytes for large files.
- **v134 — Bounded memory:** scans in chunks with a small overlap instead of loading a multi-megabyte or multi-gigabyte PDF into memory.
- **v135 — Chunk-boundary safety:** markers split across read boundaries are still counted, without double-counting markers carried over from the previous chunk.
- **v136 — Regression test from a large fixture:** validates that a PDF larger than 2 MB with its page marker across the 1 MiB boundary no longer receives a false page-count warning. This remains a lightweight marker scan, not full PDF conformance validation.

## v128.0–v132.0 — Realistic Multi-Platform Preflight Test

- **v128 — Four-platform fixture:** added a synthetic book project with KDP, Gumroad, Payhip, and Digital PDF package folders and platform-specific listing drafts.
- **v129 — Default-profile integration coverage:** test exercises the production default platform profiles instead of a custom one-platform profile.
- **v130 — Deliverable matrix coverage:** fixture creates files matching each configured required-deliverable group and checks that missing-file reports remain empty.
- **v131 — Combined integrity coverage:** fixture runs PDF header/EOF/page-marker checks, image signature checks, package-file checks, and listing metadata validation together.
- **v132 — Readiness regression gate:** test asserts every default platform reaches READY_TO_UPLOAD only when its synthetic package and metadata satisfy current local checks. This is test data, not a real marketplace upload or a substitute for platform-specific preflight.

## v123.0–v127.0 — Package File Integrity Gate

- **v123 — Empty package-file blocker:** the publishing readiness report blocks any zero-byte file inside an enabled platform package, including non-PDF extras.
- **v124 — Cover image signature checks:** PNG and JPEG files are checked against their declared file extension's basic binary signature and minimum size.
- **v125 — Actionable image errors:** malformed cover-image findings identify the exact relative package path and are included in machine-readable validation errors.
- **v126 — Integrated diagnostics:** publishing readiness reports expose package image checks alongside existing PDF checks without modifying source assets.
- **v127 — Regression coverage:** tests cover invalid cover signatures and zero-byte package extras. This remains a lightweight local check, not full image decoding or marketplace acceptance.

## Publishing readiness hardening — v118–v122

- **v118 — Exact blocker paths:** missing package and platform-listing requirements now name the exact directory that needs attention.
- **v119 — Structured listing gate:** a text-only draft cannot receive READY_TO_UPLOAD because required metadata cannot be verified from the text file alone; the report explicitly requests JSON metadata review.
- **v120 — Strict listing field shape:** a present but non-object JSON `fields` value is a blocker instead of silently bypassing required-field checks.
- **v121 — Machine-readable deliverables:** each platform report includes an `expected_deliverables` matrix with the expected folder, accepted filename patterns, and whether each group is present.
- **v122 — Regression coverage:** adds tests for exact missing paths, text-only listings, malformed listing fields, and blank required metadata. Checks remain local and read-only; no upload or marketplace approval is implied.

## v113.0–v117.0 — Integrated Publishing Handoff Workflow

- Adds main-menu option 32 for the SHA-256 publishing handoff inventory.
- Prints file counts, byte totals, P0 empty/read-error findings, P1 filename collisions, and actionable paths.
- Keeps option 31 as the platform-specific publishing completion checklist.
- Adds integration regression tests and operator instructions.

## v103.0–v107.0 — Accurate Per-Platform Publishing Readiness

- **v103 — Platform-specific listing matching:** each enabled platform checks its own listing folder instead of borrowing any JSON/text file from the shared listing tree.
- **v104 — Listing structure validation:** malformed JSON, invalid field shapes, and explicit platform mismatches become actionable blockers; blank title/author/description fields remain review items rather than being invented.
- **v105 — Package PDF integrity checks:** every PDF discovered inside a platform package receives a lightweight header/EOF check; broken files block local readiness.
- **v106 — Real local readiness state:** complete package and listing sets can reach READY_TO_UPLOAD; missing/invalid assets block, and warnings require review. This never claims marketplace acceptance or publication.
- **v107 — Ambiguous source reporting:** reports all candidate master PDFs when selection is ambiguous, preventing a silent or arbitrary source choice.
- Adds regression tests for platform isolation, invalid PDFs, ready-state reachability, and no-upload claims. All audits remain read-only except for reports.

## v98.0–v102.0 — Publishing Completion Center

- **v98 — Source PDF integrity gate:** checks the candidate MASTER PDF for a readable file, PDF header, end-of-file marker, and page-marker evidence; ambiguous or damaged sources produce actionable blockers/review warnings.
- **v99 — Platform deliverables matrix:** checks enabled KDP, Gumroad, Payhip, and Digital PDF package folders against configurable expected-file groups.
- **v100 — Exact missing-file diagnostics:** reports the precise expected folder, missing file groups, listing-draft gaps, and prioritized next actions.
- **v101 — Safe reruns:** writes uniquely named timestamped reports using exclusive creation; never replaces existing reports or modifies artwork, packages, listings, or lore.
- **v102 — Main-menu Publishing Completion Center:** adds menu option 31 and a clear READY/NEEDS REVIEW/BLOCKED-style review outcome (this helper deliberately does not certify marketplace acceptance or claim upload status).
- Adds dependency-free regression tests and documentation. All uploads and publication remain manual.

## v88.0–v92.0 — Release Evidence History & Change Tracker

- **v88 — Release evidence snapshot:** records SHA-256 and size for the current MASTER, enabled platform package files, listing drafts, and core project metadata in a no-clobber timestamped history record.
- **v89 — Release-to-release comparison:** identifies added, changed, and removed files and changes in MASTER digest or readiness state against the previous snapshot.
- **v90 — Snapshot integrity audit:** verifies tracked files still match their captured hashes and rejects paths outside the selected project.
- **v91 — Release history trend:** summarizes recent readiness states, snapshot counts, and MASTER hashes.
- **v92 — One-click Release Evidence History & Change Tracker:** runs readiness, snapshot, comparison, integrity verification, and trend summary under main-menu option 29.
- Adds regression tests for evidence capture, changed-file detection, unsafe paths, readiness trends, and workflow orchestration.

## v83.0–v87.0 — Safe Artwork Import & Guided Production

- **v83 — Verified assembly INPUT backup:** before replacing existing INPUT images, creates a timestamped backup and verifies SHA-256 for every copy. Assembly stops if backup, removal, or staging fails; existing input images are never silently discarded.
- **v84 — Confirmed artwork import:** imports only from a READY_FOR_EXPLICIT_IMPORT preview after explicit confirmation, rechecks source hashes, refuses existing destination IDs, and rolls back newly copied files on copy failure.
- **v85 — Assembly INPUT preview:** lists approved art and current INPUT images and warns when replacement/backup will occur.
- **v86 — Production action plan:** prioritizes intake, QA, assembly gate, and INPUT replacement tasks.
- **v87 — Guided artwork production:** previews, optionally imports after confirmation, runs QA, and reports assembly readiness without starting assembly or publishing; main-menu option 28.
- Adds regression tests for verified backup, explicit confirmation, no-clobber import, stale preview detection, assembly preview, and safe build integration.

## v78.0–v82.0 — Final Release Integrity & Handoff Bundle

- **v78 — Listing metadata drift audit:** compares saved platform listing titles, authors, subtitles, and keywords with current project settings without rewriting drafts.
- **v79 — Package freshness audit:** verifies platform package manifests and hashes; compares conventional interior PDFs to the current MASTER when directly comparable.
- **v80 — Release handoff ZIP:** exports package folders, listing drafts, and release reports with SHA-256 inventory using no-clobber naming; refuses export when readiness is not READY_TO_UPLOAD or audits need review.
- **v81 — Upload-state audit:** validates manually recorded upload/published statuses and product URLs and flags conflicts with current package readiness.
- **v82 — Final Release Integrity & Handoff Center:** runs readiness, metadata drift, package freshness, upload-state audit, and gated offline ZIP export under main-menu option 27.
- Adds regression tests for metadata drift, stale package PDFs, gated/no-clobber export, upload-state inconsistencies, and release-center withholding.

## v73.0–v77.0 — Artwork Generation Handoff & Assembly Gate

- **v73 — Prompt lore continuity audit:** compares each prompt's World, location, and Series IDs against the saved blueprint; flags conflicts without changing canon.
- **v74 — Prompt generation batch export:** creates a collision-safe ZIP containing exported prompt text and a SHA-256 handoff manifest; does not generate artwork or upload the ZIP.
- **v75 — Generated-art intake preview:** maps external image files to stable queue IDs, checks technical readability, flags ambiguous/missing/unmatched assets, and copies nothing.
- **v76 — Assembly readiness gate:** blocks assembly unless every queue job is PASS and its approved file exists inside the project and passes technical validation.
- **v77 — One-click artwork handoff workflow:** combines continuity, prompt export, external-art preview, and assembly readiness under main-menu option 26.
- Adds regression tests for continuity conflicts, ZIP contents/no-clobber behavior, stable-ID mapping, duplicate file matching, assembly gating, and no-mutation guarantees.

## v68.0–v72.0 — Creation & Artwork Quality Bundle

- **v68 — Creation readiness audit:** checks required blueprint, prompt manifest, and artwork queue files; validates image counts, stable IDs, non-empty prompts, and world/series identity markers.
- **v69 — Artwork integrity audit:** inventories SOURCE/APPROVED/REVIEW/FAILED assets, checks readability and technical QA, records SHA-256, detects same-content assets across distinct image IDs, and flags missing approved outputs.
- **v70 — Prompt handoff audit:** compares each exported prompt text file to the current manifest, detects missing/stale exports and unsafe IDs, and never rewrites prompt files.
- **v71 — Prioritized creation action plan:** converts creation, artwork, and prompt findings into P0/P1/P2 tasks.
- **v72 — One-click Creation & Artwork Quality Center:** runs the audits and saves a combined summary under main-menu option 25.
- Adds regression tests for structural mismatch, duplicate IDs/assets, prompt drift, unsafe IDs, action priority, and no-mutation behavior.

## v63.0–v67.0 — Five-Stage Publishing Workflow Bundle

- **v63 — Source PDF provenance audit:** compares an imported PDF's recorded SHA-256 against the current source file without modifying either file; reports missing, changed, untracked, and verified states.
- **v64 — Manual platform upload checklist:** lists exact package/listing folders and upload steps; preserves matching platform statuses and product URLs between runs, defaults new platforms to NOT_UPLOADED, and never infers publication.
- **v65 — Prioritized release action plan:** converts blockers, warnings, upload readiness, and source-provenance findings into P0/P1/P2 tasks with report paths.
- **v66 — Release delivery map:** inventories exact package/listing folders and files and identifies candidate MASTER PDFs without copying or rebuilding artifacts.
- **v67 — One-click publishing run:** connects listing generation, readiness checks, provenance audit, checklist, action plan, delivery map, and a summary report under main-menu option 24. Listing drafts are preserved; upload and publication remain manual.

- Adds dependency-free regression coverage for digest verification, checklist persistence, task prioritization, path/file inventory, orchestration, versioning, and menu wiring.
- Does not overwrite existing listing drafts, rebuild the MASTER PDF, mutate lore canon, or perform online uploads/publication.

## v62.0 — Automatic Post-Import Publishing Preparation

- After finished-PDF intake builds platform packages, generate platform-specific listing drafts and a consolidated upload-readiness report.
- Existing listing drafts are preserved by calling the listing builder with overwrite disabled.
- Writes `REPORTS/POST_IMPORT_PUBLISHING_PREP.json` linking the listing and upload-readiness reports.
- Keeps the workflow local-only: no platform uploads or publication are performed.

## v61.0 — Consolidated Platform Upload Readiness Board

- Adds one read-only board that combines platform package-manifest verification with the current listing readiness report.
- Writes `REPORTS/UPLOAD_READINESS.json` with per-platform status, exact package/listing folder paths, blockers, and review warnings.
- Distinguishes `READY_TO_UPLOAD`, `NEEDS_REVIEW`, and `BLOCKED`; it never claims that a product was uploaded or published.
- Adds main-menu option 23 and preserves production files, artwork, listing drafts, and publishing state.

# Changelog

## v60.0 — Non-Destructive Listing Draft Generation

- Preserves existing platform listing JSON/text files by default instead of silently overwriting user edits on reruns.
- Requires an explicit typed `YES` confirmation in the interactive listing builder before replacing existing drafts.
- Preserves partial or malformed existing pairs for the read-only consistency audit to report; it does not silently repair them.
- Records per-platform draft preservation/write-policy status in the readiness report.
- Adds regression tests for existing pairs, partial pairs, explicit overwrite, and first-time draft creation.

## v59.0 — Listing Draft Consistency Audit

- Audits generated platform listing JSON and paste-ready text as a pair without modifying either artifact.
- Reports missing/empty/unreadable files, malformed JSON or field structures, and invalid quality-gate structures.
- Detects platform-header and product-title mismatches between JSON and text drafts.
- Adds consistency status, error/warning counts, and detailed findings to `LISTING_READINESS.json`.
- Prints actionable consistency findings after listing generation and adds regression tests for clean, mismatched, malformed, and non-mutating cases.
- Flags missing or empty platform-specific listing fields for review while leaving deliberate price/category decisions blank; a consistency PASS is not publication approval.
- Adds a top-level draft review gate and a regression test for incomplete required fields.
- Does not upload, publish, infer metadata, or repair user listing content.


## v58.0 — Publishing Content Audit & Snapshot Safety

- Restores advisory listing checks for invalid prices, duplicate tags/keywords, long titles, KDP keyword thresholds, and digital-download descriptions that may imply physical fulfillment.
- Includes audit results in per-platform listing drafts and the aggregate readiness report without rewriting listing text or inventing prices.
- Prevents same-second build snapshots from overwriting prior audit records by using exclusive creation and deterministic suffixes.
- Adds regression coverage for content-audit warnings/errors and immutable snapshot collision handling.
- Preserves v57 publishing readiness checks and does not change artwork, lore, or publication state.

## v57.0 — Platform Readiness & Upload Checklist

- Adds a platform-by-platform publishing checklist for each enabled platform.
- Checks required title/author metadata, listing-description completeness, KDP keyword/category presence, profile page-count/file-count/file-size limits, and package-manifest integrity.
- Detects stale platform packages when the recorded MASTER SHA-256 differs from the current MASTER; missing source fingerprints are flagged for review rather than treated as verified.
- Generates `REPORTS/PUBLISHING_READINESS_CHECKLIST.json` with READY / REVIEW / BLOCKED statuses and explicit manual upload/preview/live-product steps.
- Keeps uploads manual and honest: a local READY result is not represented as a platform acceptance or publication.
- Adds runtime tests for freshness, missing fingerprints, listing metadata warnings, and disabled platform configurations.

## v56.0 — Unified Publishing Release Audit

- Adds one publishing-menu action that runs the existing read-only release preflight and package-manifest verification together.
- Combines missing release prerequisites, package integrity errors, and non-blocking warnings into a single status and saved diagnostic report.
- Distinguishes READY, REVIEW, and BLOCKED; readiness never claims that a product was uploaded or published.
- Keeps MASTER PDFs, artwork, package contents, listing metadata, and upload records unchanged.
- Adds isolated runtime tests for clean packages, checksum errors, warnings, and missing-master blockers.

## v55.0 — Build Cache and Delivery Artifact Integrity

- Replaces the minimal cache check with verification of the interior PDF, successful report, KDP manifest, checklist, readiness report, and configured optional artifacts.
- Checks that packaged interior and build report match the authoritative outputs.
- Validates SHA-256 manifests and all listed package files when checksum verification is enabled.
- Commits the build fingerprint only after package, metadata, readiness, checksum, and snapshot generation finishes.
- Adds runtime regression tests for incomplete packages and tampered checksums.


## v54.0 — Resumable Production Queue and Explicit Build Results

- Returns explicit SUCCESS, SKIPPED, NOT_READY, or FAILED results from the build pipeline.
- Keeps failed, not-ready, unsafe, and missing queue entries for correction instead of silently clearing them.
- Removes successful queue entries and saves progress after each completed build, so interrupted runs can resume.
- Catches per-project exceptions and continues processing other queued projects.
- Prevents duplicate manual queue additions, merges “Add All” without duplicating paths, and lets users clear/review stale queues even when no projects remain.
- Adds runtime tests for resumability, duplicate prevention, stale queues, and build-result statuses.


## v53.0 — Restore Safe Production Queue Path Handling

- Aligns queue records with the actual workflow: non-empty project path strings, not dictionaries.
- Validates queue paths remain inside the configured Projects folder before load or save.
- Rejects malformed, empty, and out-of-root queue entries without overwriting the stored queue.
- Accepts the production pipeline's ISO timestamp string for build-state `last_build`, while rejecting malformed types.
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
