# Publishing Handoff Inventory

## Run it

1. Start the factory with `python -X utf8 .\\factory.py`.
2. Select **32. Publishing Handoff Inventory**.
3. Review the report saved in the active project's `REPORTS` folder.
4. Fix every P0 item and review P1 items before uploading.
5. Run **31. Publishing Completion Center** for the separate platform-specific requirements checklist.

The inventory scans `PLATFORMS/KDP`, `PLATFORMS/GUMROAD`, `PLATFORMS/PAYHIP`, and `PLATFORMS/DIGITAL`. Missing folders are reported; they are not silently created. Every readable file is recorded with size and SHA-256. Empty files and case-insensitive path collisions are called out. Reports use unique names and do not overwrite earlier evidence.

## Important limits

This is a local, read-only handoff check. It does not repair or move files, prove that a PDF is fully valid, log in to marketplaces, upload files, or confirm publication. A clean inventory is not marketplace acceptance. Use the existing PDF preflight and the Publishing Completion Center as well.
