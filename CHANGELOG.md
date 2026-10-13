# Changelog

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
