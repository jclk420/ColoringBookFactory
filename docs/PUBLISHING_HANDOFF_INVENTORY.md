# Publishing Handoff Inventory (v108–v112)

This companion tool inventories the files already present in each platform package. It does not create, rename, delete, upload, or publish package files.

## Run

From the ColoringBookFactory directory:

    python -c "from publishing_handoff import build_handoff_manifest, write_handoff_manifest_no_clobber; p=r'C:\\ColoringBookFactory\\Projects\\Your Book'; r=build_handoff_manifest(p); print(write_handoff_manifest_no_clobber(p, r))"

The timestamped JSON report is saved under the selected project's `REPORTS` folder. Existing reports are never overwritten.

## Five safety improvements

- **v108 — SHA-256 inventory:** every readable package file receives a streaming SHA-256 digest and exact byte count.
- **v109 — Memory-safe hashing:** files are hashed in 1 MiB chunks rather than loaded entirely into memory.
- **v110 — Empty-file detection:** zero-byte files are explicitly reported as high-priority actions.
- **v111 — Cross-platform filename collision detection:** names differing only by letter case are reported because they can behave differently on Windows and case-sensitive filesystems.
- **v112 — Safe manifest persistence:** timestamped exclusive-create writes preserve previous reports and include a regression test.

The manifest is evidence about the files currently on disk, not proof that a PDF is valid, that a marketplace accepts the package, or that upload/publication occurred. Hashes can be used later to identify changed files; they are not a backup.
