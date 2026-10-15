# Publishing Completion Center (v98–v107)

This read-only helper checks a source PDF's basic structural signatures, inventories platform package files, identifies missing package/listing deliverables, validates listing JSON and package PDF signatures, reports ambiguous master candidates, and writes a timestamped JSON report without replacing earlier reports.

## Run it

From the ColoringBookFactory folder:

    python publishing_completion.py "C:\ColoringBookFactory\Projects\Your Book"

For the full machine-readable report:

    python publishing_completion.py "C:\ColoringBookFactory\Projects\Your Book" --json

Exit code is 1 when blocked and 0 when not blocked. A report-write failure returns 2.

## Safety and limits

- Does not edit the MASTER PDF, artwork, platform packages, listing drafts, metadata, or lore.
- Writes only a uniquely named report under the selected project's REPORTS folder.
- Does not upload or publish products and never marks a platform as uploaded.
- Uses a lightweight PDF signature/EOF check, not a full PDF conformance validator. Page-marker detection is heuristic and may require review for object-stream PDFs.
- The folder/file patterns are conservative defaults; marketplace requirements and the actual upload interface remain authoritative.
- READY_TO_UPLOAD means only that local file and listing checks passed. It does not mean marketplace approval, acceptance, successful upload, or publication. Actual marketplace-specific settings still require user review.

## Expected layout

- MASTER/ — one unambiguous master PDF, preferably with MASTER in its filename.
- PLATFORMS/KDP/, PLATFORMS/GUMROAD/, PLATFORMS/PAYHIP/, PLATFORMS/DIGITAL/ — generated package artifacts.
- MARKETING/LISTINGS/KDP/, MARKETING/LISTINGS/Gumroad/, MARKETING/LISTINGS/Payhip/, MARKETING/LISTINGS/Digital_PDF/ — platform-specific saved listing drafts. Custom profiles without a listing_folder can still use the root listing folder.
- REPORTS/ — timestamped audit output.

The helper supports passing custom profiles through Python for tests and future integration.
