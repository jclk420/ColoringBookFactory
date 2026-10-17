"""Read-only publishing completion diagnostics for ColoringBookFactory."""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "2.5"
DEFAULT_PLATFORMS = {
    "KDP": {"folder": "KDP", "listing_folder": "KDP", "required_any": [["*interior*.pdf"], ["*cover*.pdf"]],
            "listing_any": [["*.json"], ["*.txt"]],
            "notes": "Print package; verify trim, bleed, cover template, and KDP preflight."},
    "Gumroad": {"folder": "GUMROAD", "listing_folder": "Gumroad", "required_any": [["*.pdf"], ["*cover*.png", "*cover*.jpg", "*thumbnail*.png"],
                ["*description*.txt", "*description*.md", "*metadata*.json"]],
                "listing_any": [["*.json"], ["*.txt"]],
                "notes": "Digital delivery; manually confirm previews, price, and product copy."},
    "Payhip": {"folder": "PAYHIP", "listing_folder": "Payhip", "required_any": [["*.pdf"], ["*cover*.png", "*cover*.jpg", "*thumbnail*.png"]],
               "listing_any": [["*.json"], ["*.txt"]],
               "notes": "Digital delivery; confirm upload file and storefront details."},
    "Digital PDF": {"folder": "DIGITAL", "listing_folder": "Digital_PDF", "required_any": [["*.pdf"], ["*cover*.png", "*cover*.jpg", "*thumbnail*.png"]],
                    "listing_any": [["*.json"], ["*.txt"]],
                    "notes": "Platform-neutral download package."},
}

def _count_pdf_page_markers(path: Path, chunk_size: int = 1024 * 1024) -> int:
    """Count uncompressed page-object markers across a file without loading it all into memory."""
    pattern = re.compile(rb"/Type\s*/Page(?!s)\b")
    overlap = b""
    count = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            data = overlap + chunk
            boundary = len(overlap)
            count += sum(1 for match in pattern.finditer(data) if match.end() > boundary)
            overlap = data[-64:]
    return count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pdf(path: Path) -> dict[str, Any]:
    """Check basic PDF signatures and page evidence without changing the source."""
    result = {"path": str(path), "exists": path.is_file() and not path.is_symlink(), "valid": False,
              "status": "BLOCKED", "errors": [], "warnings": [], "size_bytes": 0,
              "page_marker_count": 0}
    if path.is_symlink():
        result["errors"].append("PDF symbolic links are not accepted; use a regular file.")
        return result
    if not path.is_file():
        result["errors"].append("PDF file is missing.")
        return result
    try:
        size = path.stat().st_size
        result["size_bytes"] = size
        if size < 100:
            result["errors"].append(f"File is only {size} bytes; likely empty or incomplete.")
        with path.open("rb") as stream:
            head = stream.read(1024)
            stream.seek(max(0, size - 8192))
            tail = stream.read(8192)
        if b"%PDF-" not in head:
            result["errors"].append("PDF header signature is missing near the beginning.")
        if b"%%EOF" not in tail:
            result["errors"].append("PDF end-of-file marker is missing; file may be truncated.")
        # Scan the entire file so markers in large PDFs are not missed between the ends.
        pages = _count_pdf_page_markers(path)
        result["page_marker_count"] = pages
        if pages == 0:
            result["warnings"].append("Page count could not be confirmed by a lightweight scan; open the PDF or use a PDF parser.")
        if not result["errors"]:
            result["valid"] = True
            result["status"] = "NEEDS_REVIEW" if result["warnings"] else "BASIC_CHECK_PASS"
    except OSError as exc:
        result["errors"].append(f"Could not read PDF: {exc}")
    return result


def validate_image(path: Path) -> dict[str, Any]:
    """Perform a conservative signature/size check for supported cover image formats."""
    result = {"path": str(path), "exists": path.is_file() and not path.is_symlink(), "valid": False,
              "status": "BLOCKED", "errors": [], "size_bytes": 0}
    if path.is_symlink():
        result["errors"].append("Image symbolic links are not accepted; use a regular file.")
        return result
    if not path.is_file():
        result["errors"].append("Image file is missing.")
        return result
    try:
        size = path.stat().st_size
        result["size_bytes"] = size
        if size < 16:
            result["errors"].append(f"Image file is only {size} bytes; likely empty or incomplete.")
        with path.open("rb") as stream:
            head = stream.read(16)
        suffix = path.suffix.casefold()
        if suffix == ".png" and not head.startswith(b"\x89PNG\r\n\x1a\n"):
            result["errors"].append("PNG filename does not contain a PNG signature.")
        elif suffix in {".jpg", ".jpeg"} and not head.startswith(b"\xff\xd8\xff"):
            result["errors"].append("JPEG filename does not contain a JPEG signature.")
        if not result["errors"]:
            result["valid"] = True
            result["status"] = "BASIC_CHECK_PASS"
    except OSError as exc:
        result["errors"].append(f"Could not read image: {exc}")
    return result

def _matches_any(folder: Path, patterns: list[str]) -> list[str]:
    matches: set[Path] = set()
    if folder.is_dir():
        for pattern in patterns:
            matches.update(p for p in folder.rglob(pattern) if p.is_file() and not p.is_symlink())
    return sorted(p.relative_to(folder).as_posix() for p in matches)

def _master_candidates(project: Path) -> list[Path]:
    """Return unique master candidates, preferring files explicitly named MASTER."""
    candidates = []
    for directory in (project / "MASTER", project):
        if directory.is_dir():
            candidates.extend(p for p in directory.glob("*.pdf") if p.is_file() and not p.is_symlink())
    unique = sorted(set(candidates))
    preferred = [p for p in unique if "master" in p.stem.casefold()]
    return preferred or unique


def _find_master(project: Path) -> Path | None:
    candidates = _master_candidates(project)
    return candidates[0] if len(candidates) == 1 else None

def _verify_platform_manifest(package_dir: Path, master_sha256: str | None) -> dict[str, Any]:
    """Verify manifest inventory, file hashes, and source MASTER fingerprint."""
    manifest_path = package_dir / "PACKAGE_MANIFEST.json"
    result: dict[str, Any] = {"status": "READY", "path": str(manifest_path), "errors": [], "warnings": [],
                              "listed_files": [], "unexpected_files": [], "missing_files": [], "hash_mismatches": []}
    if manifest_path.is_symlink():
        result["status"] = "BLOCKED"
        result["errors"].append("PACKAGE_MANIFEST.json is a symbolic link.")
        return result
    if not manifest_path.is_file():
        result["status"] = "NEEDS_REVIEW"
        result["warnings"].append("Package manifest is missing; package integrity and source freshness are not fully evidenced.")
        return result
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        result["status"] = "BLOCKED"
        result["errors"].append(f"Package manifest cannot be read: {type(exc).__name__}: {exc}")
        return result
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        result["status"] = "BLOCKED"
        result["errors"].append("Package manifest schema is invalid; expected an object with a files list.")
        return result

    # Preserve the generator's declared readiness state. File hashes alone do
    # not make a package upload-ready if its own manifest says it was blocked.
    raw_status = manifest.get("status")
    manifest_status = str(raw_status).strip().upper() if isinstance(raw_status, str) else ""
    if manifest_status in {"BLOCKED", "FAILED", "ERROR", "NOT_READY"}:
        result["errors"].append(f"Package manifest declares non-ready status: {manifest_status}.")
    elif manifest_status in {"READY_WITH_WARNINGS", "NEEDS_REVIEW", "REVIEW", "WARNING", "WARNINGS"}:
        result["warnings"].append(f"Package manifest declares review status: {manifest_status}.")
    elif manifest_status not in {"READY", "PASS", "PASSED"}:
        result["warnings"].append("Package manifest has no recognized readiness status; review this legacy or custom package.")

    raw_warnings = manifest.get("warnings", [])
    if isinstance(raw_warnings, list):
        for warning in raw_warnings:
            if isinstance(warning, str) and warning.strip():
                result["warnings"].append("Package manifest warning: " + warning.strip())
            elif warning is not None:
                result["warnings"].append("Package manifest contains a malformed warning entry.")
    elif raw_warnings not in (None, ""):
        result["warnings"].append("Package manifest warnings field is malformed; review the package report.")

    names: set[str] = set()
    for raw in manifest["files"]:
        if not isinstance(raw, str) or not raw.strip():
            result["errors"].append(f"Invalid path in package manifest: {raw!r}")
            continue
        name = raw.replace("\\", "/")
        parts = name.split("/")
        if name.startswith("/") or any(part in {"", ".", ".."} for part in parts) or (len(parts[0]) > 1 and parts[0][1] == ":"):
            result["errors"].append(f"Unsafe path in package manifest: {raw!r}")
            continue
        if name in names:
            result["errors"].append(f"Duplicate path in package manifest: {name}")
            continue
        names.add(name)
    result["listed_files"] = sorted(names, key=str.casefold)
    expected = names - {"PACKAGE_MANIFEST.json"}
    actual: set[str] = set()
    try:
        for item in package_dir.rglob("*"):
            if item.is_file() and not item.is_symlink() and item != manifest_path:
                actual.add(item.relative_to(package_dir).as_posix())
    except (OSError, RuntimeError) as exc:
        result["errors"].append(f"Package inventory failed: {type(exc).__name__}: {exc}")
    result["unexpected_files"] = sorted(actual - expected, key=str.casefold)
    result["missing_files"] = sorted(expected - actual, key=str.casefold)
    if result["unexpected_files"]:
        result["errors"].append("Unlisted package files: " + ", ".join(result["unexpected_files"]))
    if result["missing_files"]:
        result["errors"].append("Manifest files missing from package: " + ", ".join(result["missing_files"]))
    hashes = manifest.get("file_hashes", {})
    if not isinstance(hashes, dict):
        result["errors"].append("Package manifest file_hashes must be an object.")
        hashes = {}
    for name in sorted(expected & actual, key=str.casefold):
        digest = hashes.get(name)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            result["warnings"].append(f"No valid SHA-256 recorded for package file: {name}")
            continue
        try:
            actual_digest = _sha256(package_dir.joinpath(*name.split("/")))
        except OSError as exc:
            result["errors"].append(f"Could not hash package file {name}: {type(exc).__name__}: {exc}")
            continue
        if actual_digest.casefold() != digest.casefold():
            result["hash_mismatches"].append(name)
    if result["hash_mismatches"]:
        result["errors"].append("Package file hashes do not match the manifest: " + ", ".join(result["hash_mismatches"]))
    recorded_master = manifest.get("master_sha256")
    if not isinstance(recorded_master, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", recorded_master):
        result["warnings"].append("Manifest does not contain a valid source MASTER SHA-256.")
    elif master_sha256 and recorded_master.casefold() != master_sha256.casefold():
        result["errors"].append("Manifest source MASTER SHA-256 differs from the current MASTER PDF.")
    if result["errors"]:
        result["status"] = "BLOCKED"
    elif result["warnings"]:
        result["status"] = "NEEDS_REVIEW"
    return result


def build_completion_report(project: str | Path, profiles: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return actionable readiness diagnostics; never rebuild or modify publishing assets."""
    root = Path(project).expanduser().resolve()
    report = {"schema_version": 1, "tool_version": VERSION,
              "generated_utc": datetime.now(timezone.utc).isoformat(), "project": str(root),
              "read_only_audit": True, "uploaded_or_published": False, "source_pdf": None,
              "overall_status": "BLOCKED", "source_pdf_candidates": [],
              "summary": {"READY_TO_UPLOAD": 0, "NEEDS_REVIEW": 0, "BLOCKED": 0},
              "platforms": {}, "actions": []}
    if not root.is_dir():
        report["actions"].append({"priority": "P0", "action": "Select an existing project folder.", "path": str(root)})
        return report
    candidates = _master_candidates(root)
    report["source_pdf_candidates"] = [str(path) for path in candidates]
    master = _find_master(root)
    master_sha256 = None
    if master is None:
        reason = "No master PDF was found." if not candidates else "Multiple master PDF candidates were found; select one and move/rename the others so the intended source is unambiguous."
        report["actions"].append({"priority": "P0", "action": reason + " Keep the selected source in MASTER and include MASTER in its filename.", "path": str(root / "MASTER"), "candidates": [str(path) for path in candidates]})
        source_status = "BLOCKED"
    else:
        check = validate_pdf(master)
        report["source_pdf"] = check
        if not check["errors"]:
            try:
                master_sha256 = _sha256(master)
                check["sha256"] = master_sha256
            except OSError as exc:
                check["errors"].append(f"Could not hash source MASTER PDF: {type(exc).__name__}: {exc}")
        source_status = "BLOCKED" if check["errors"] else ("NEEDS_REVIEW" if check["warnings"] else "BASIC_CHECK_PASS")
        for error in check["errors"]:
            report["actions"].append({"priority": "P0", "action": error, "path": str(master)})
        for warning in check["warnings"]:
            report["actions"].append({"priority": "P1", "action": warning, "path": str(master)})
    for name, profile in (profiles if profiles is not None else DEFAULT_PLATFORMS).items():
        if not profile.get("enabled", True):
            continue
        package_dir = root / "PLATFORMS" / str(profile.get("folder") or name.upper().replace(" ", "_"))
        package_paths = sorted(package_dir.rglob("*")) if package_dir.is_dir() else []
        package_symlinks = [p for p in package_paths if p.is_symlink()]
        package_files = sorted(p.relative_to(package_dir).as_posix() for p in package_paths if p.is_file() and not p.is_symlink())
        missing = []
        if not package_dir.is_dir():
            missing.append(f"Platform package folder is missing: {package_dir}")
        else:
            for group in profile.get("required_any", []):
                if not _matches_any(package_dir, group):
                    missing.append(f"Required package file missing in {package_dir}; expected one of: " + " OR ".join(group))
        manifest_check = _verify_platform_manifest(package_dir, master_sha256) if package_dir.is_dir() else {
            "status": "BLOCKED", "path": str(package_dir / "PACKAGE_MANIFEST.json"),
            "errors": ["Cannot verify package manifest because the package folder is missing."],
            "warnings": [], "listed_files": [], "unexpected_files": [], "missing_files": [], "hash_mismatches": []}
        listing_root = root / "MARKETING" / "LISTINGS"
        # Default profiles use platform-specific folders so one platform's drafts
        # cannot accidentally satisfy another platform's listing requirements.
        listing_dir = listing_root / str(profile.get("listing_folder", "")) if profile.get("listing_folder") else listing_root
        listing_paths = sorted(listing_dir.rglob("*")) if listing_dir.is_dir() else []
        listing_symlinks = [p for p in listing_paths if p.is_symlink()]
        listing_files = sorted(p.relative_to(listing_dir).as_posix() for p in listing_paths if p.is_file() and not p.is_symlink())
        for group in profile.get("listing_any", []):
            if not _matches_any(listing_dir, group):
                missing.append(f"Platform-specific listing draft missing in {listing_dir}; expected one of: " + " OR ".join(group))
        review_issues = list(manifest_check["warnings"])
        validation_errors = list(manifest_check["errors"])
        validation_errors.extend(f"Package contains a symbolic link; replace it with a regular file: {p.relative_to(package_dir).as_posix()}" for p in package_symlinks)
        validation_errors.extend(f"Listing folder contains a symbolic link; replace it with a regular file: {p.relative_to(listing_dir).as_posix()}" for p in listing_symlinks)
        package_file_checks = []
        if package_dir.is_dir():
            for package_path in sorted(p for p in package_dir.rglob("*") if p.is_file() and not p.is_symlink()):
                relative_path = package_path.relative_to(package_dir).as_posix()
                try:
                    if package_path.stat().st_size == 0:
                        validation_errors.append(f"Package file is empty: {relative_path}")
                    if package_path.suffix.casefold() in {".png", ".jpg", ".jpeg"}:
                        image_result = validate_image(package_path)
                        package_file_checks.append(image_result)
                        validation_errors.extend(
                            f"Package image {relative_path}: {error}"
                            for error in image_result["errors"]
                        )
                except OSError as exc:
                    validation_errors.append(
                        f"Could not inspect package file {relative_path}: {type(exc).__name__}: {exc}"
                    )
        json_listing_files = _matches_any(listing_dir, ["*.json"])
        if not json_listing_files:
            review_issues.append(
                "No structured JSON listing metadata was found; a text draft alone cannot verify title, author, description, or platform."
            )
        for relative in json_listing_files:
            listing_path = listing_dir / relative
            try:
                payload = json.loads(listing_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    validation_errors.append(f"Listing JSON must contain an object: {relative}")
                    continue
                listed_platform = payload.get("platform")
                if listed_platform and str(listed_platform).casefold() != str(name).casefold():
                    validation_errors.append(f"Listing platform mismatch in {relative}: expected {name}, found {listed_platform}.")
                fields = payload.get("fields", {})
                if not isinstance(fields, dict):
                    validation_errors.append(f"Listing fields must be an object: {relative}")
                    continue
                for required_field in ("title", "author", "description"):
                    if not str(fields.get(required_field, "")).strip():
                        review_issues.append(f"Listing field '{required_field}' is blank in {relative}.")
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                validation_errors.append(f"Listing JSON could not be read ({relative}): {type(exc).__name__}: {exc}")
        pdf_checks = []
        package_pdfs = _matches_any(package_dir, ["*.pdf"])
        comparable_interior_count = 0
        for relative in package_pdfs:
            package_pdf = package_dir / relative
            pdf_result = validate_pdf(package_pdf)
            pdf_checks.append(pdf_result)
            if pdf_result["errors"]:
                validation_errors.extend(f"Invalid package PDF {relative}: {error}" for error in pdf_result["errors"])
            review_issues.extend(f"Review package PDF {relative}: {warning}" for warning in pdf_result["warnings"])
            stem = package_pdf.stem.casefold().replace("_", "-").replace(" ", "-")
            is_interior_candidate = (
                stem in {"interior", "book", "master", "digital-interior"}
                or "interior" in stem
                or stem.endswith("-book")
                or stem.endswith("-master")
            )
            if is_interior_candidate:
                comparable_interior_count += 1
                if master_sha256 and not pdf_result["errors"]:
                    try:
                        package_digest = _sha256(package_pdf)
                        pdf_result["sha256"] = package_digest
                        pdf_result["matches_master"] = package_digest == master_sha256
                        if not pdf_result["matches_master"]:
                            review_issues.append(
                                f"Package interior PDF {relative} differs from the current MASTER PDF; rebuild or verify the intended platform-specific interior."
                            )
                    except OSError as exc:
                        validation_errors.append(
                            f"Could not verify package PDF freshness for {relative}: {type(exc).__name__}: {exc}"
                        )
                else:
                    pdf_result["matches_master"] = None
        if package_pdfs and comparable_interior_count == 0:
            review_issues.append(
                "Could not identify a package interior PDF by filename, so freshness against the current MASTER could not be confirmed."
            )
        if source_status == "NEEDS_REVIEW":
            review_issues.append("Source PDF passed basic checks but needs manual review.")
        if missing or validation_errors or source_status == "BLOCKED":
            status = "BLOCKED"
        elif review_issues:
            status = "NEEDS_REVIEW"
        else:
            status = "READY_TO_UPLOAD"
        report["summary"][status] += 1
        report["platforms"][name] = {"status": status, "package_folder": str(package_dir),
            "package_files": package_files, "listing_folder": str(listing_dir), "listing_files": listing_files,
            "missing_requirements": missing, "validation_errors": validation_errors,
            "manifest_verification": manifest_check,
            "review_issues": review_issues, "package_pdf_checks": pdf_checks,
            "package_image_checks": package_file_checks,
            "expected_deliverables": [
                {"kind": "package", "folder": str(package_dir), "any_of": list(group),
                 "present": bool(_matches_any(package_dir, group)) if package_dir.is_dir() else False}
                for group in profile.get("required_any", [])
            ] + [
                {"kind": "listing", "folder": str(listing_dir), "any_of": list(group),
                 "present": bool(_matches_any(listing_dir, group)) if listing_dir.is_dir() else False}
                for group in profile.get("listing_any", [])
            ],
            "notes": profile.get("notes", ""),
            "upload_confirmed": False, "next_step": "Resolve blockers, review marketplace-specific fields, then upload manually."}
        for issue in missing + validation_errors:
            report["actions"].append({"priority": "P0", "platform": name, "action": issue, "path": str(package_dir)})
        for issue in review_issues:
            report["actions"].append({"priority": "P1", "platform": name, "action": issue, "path": str(listing_dir)})
    if report["summary"]["BLOCKED"]:
        report["overall_status"] = "BLOCKED"
    elif report["summary"]["NEEDS_REVIEW"]:
        report["overall_status"] = "NEEDS_REVIEW"
    elif report["summary"]["READY_TO_UPLOAD"]:
        report["overall_status"] = "READY_TO_UPLOAD"
    else:
        report["overall_status"] = "BLOCKED"
        report["actions"].append({"priority": "P0", "action": "Enable at least one publishing platform."})
    report["actions"].sort(key=lambda x: ({"P0": 0, "P1": 1, "P2": 2}.get(x.get("priority"), 9), x.get("platform", ""), x.get("action", "")))
    return report

def write_report_no_clobber(project: str | Path, report: dict[str, Any]) -> Path:
    """Write a unique report without replacing any existing report."""
    root = Path(project).expanduser().resolve()
    reports = root / "REPORTS"
    reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    base = reports / f"PUBLISHING_COMPLETION_{stamp}.json"
    for suffix in range(1000):
        target = base if suffix == 0 else base.with_name(f"{base.stem}_{suffix}{base.suffix}")
        try:
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(report, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            return target
        except FileExistsError:
            continue
    raise FileExistsError("Could not allocate a unique publishing report filename.")

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only publishing completion check.")
    parser.add_argument("project", help="Path to a ColoringBookFactory project folder")
    parser.add_argument("--json", action="store_true", help="Print the complete report as JSON")
    args = parser.parse_args(argv)
    report = build_completion_report(args.project)
    try:
        saved = write_report_no_clobber(args.project, report)
        report["report_path"] = str(saved)
    except OSError as exc:
        print(f"Could not save report: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Publishing completion: {report['overall_status']}")
        print(f"Project: {report['project']}")
        for name, row in report["platforms"].items():
            print(f"- {name}: {row['status']}")
            for issue in row["missing_requirements"]:
                print(f"    MISSING: {issue}")
            for issue in row.get("validation_errors", []):
                print(f"    ERROR: {issue}")
            for issue in row.get("review_issues", []):
                print(f"    REVIEW: {issue}")
        print(f"Report: {saved}")
        print("Local preflight only. Nothing was uploaded or published.")
    return 1 if report["overall_status"] == "BLOCKED" else 0

if __name__ == "__main__":
    raise SystemExit(main())
