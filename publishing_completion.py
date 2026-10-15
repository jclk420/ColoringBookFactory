"""Read-only publishing completion diagnostics for ColoringBookFactory."""
from __future__ import annotations
import argparse, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "1.0"
DEFAULT_PLATFORMS = {
    "KDP": {"folder": "KDP", "required_any": [["*interior*.pdf"], ["*cover*.pdf"]],
            "listing_any": [["*.json"], ["*.txt"]],
            "notes": "Print package; verify trim, bleed, cover template, and KDP preflight."},
    "Gumroad": {"folder": "GUMROAD", "required_any": [["*.pdf"], ["*cover*.png", "*cover*.jpg", "*thumbnail*.png"],
                ["*description*.txt", "*description*.md", "*metadata*.json"]],
                "listing_any": [["*.json"], ["*.txt"]],
                "notes": "Digital delivery; manually confirm previews, price, and product copy."},
    "Payhip": {"folder": "PAYHIP", "required_any": [["*.pdf"], ["*cover*.png", "*cover*.jpg", "*thumbnail*.png"]],
               "listing_any": [["*listing*.json", "*metadata*.json"], ["*description*.txt", "*description*.md"]],
               "notes": "Digital delivery; confirm upload file and storefront details."},
    "Digital PDF": {"folder": "DIGITAL", "required_any": [["*.pdf"], ["*cover*.png", "*cover*.jpg", "*thumbnail*.png"]],
                    "listing_any": [["*metadata*.json", "*listing*.json"]],
                    "notes": "Platform-neutral download package."},
}

def validate_pdf(path: Path) -> dict[str, Any]:
    """Check basic PDF signatures and page evidence without changing the source."""
    result = {"path": str(path), "exists": path.is_file(), "valid": False,
              "status": "BLOCKED", "errors": [], "warnings": [], "size_bytes": 0,
              "page_marker_count": 0}
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
        data = path.read_bytes() if size <= 2_000_000 else head + tail
        pages = len(re.findall(rb"/Type\s*/Page(?!s)\b", data))
        result["page_marker_count"] = pages
        if pages == 0:
            result["warnings"].append("Page count could not be confirmed by a lightweight scan; open the PDF or use a PDF parser.")
        if not result["errors"]:
            result["valid"] = True
            result["status"] = "NEEDS_REVIEW" if result["warnings"] else "BASIC_CHECK_PASS"
    except OSError as exc:
        result["errors"].append(f"Could not read PDF: {exc}")
    return result

def _matches_any(folder: Path, patterns: list[str]) -> list[str]:
    matches: set[Path] = set()
    if folder.is_dir():
        for pattern in patterns:
            matches.update(p for p in folder.rglob(pattern) if p.is_file())
    return sorted(p.relative_to(folder).as_posix() for p in matches)

def _find_master(project: Path) -> Path | None:
    candidates = []
    for directory in (project / "MASTER", project):
        if directory.is_dir():
            candidates.extend(p for p in directory.glob("*.pdf") if p.is_file())
    preferred = [p for p in candidates if "master" in p.stem.casefold()]
    unique = sorted(set(preferred or candidates))
    return unique[0] if len(unique) == 1 else None

def build_completion_report(project: str | Path, profiles: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return actionable readiness diagnostics; never rebuild or modify publishing assets."""
    root = Path(project).expanduser().resolve()
    report = {"schema_version": 1, "tool_version": VERSION,
              "generated_utc": datetime.now(timezone.utc).isoformat(), "project": str(root),
              "read_only_audit": True, "uploaded_or_published": False, "source_pdf": None,
              "overall_status": "BLOCKED",
              "summary": {"READY_TO_UPLOAD": 0, "NEEDS_REVIEW": 0, "BLOCKED": 0},
              "platforms": {}, "actions": []}
    if not root.is_dir():
        report["actions"].append({"priority": "P0", "action": "Select an existing project folder.", "path": str(root)})
        return report
    master = _find_master(root)
    if master is None:
        report["actions"].append({"priority": "P0", "action": "Place one unambiguous master PDF in MASTER, preferably with MASTER in its filename.", "path": str(root / "MASTER")})
        source_status = "BLOCKED"
    else:
        check = validate_pdf(master)
        report["source_pdf"] = check
        source_status = "BLOCKED" if check["errors"] else ("NEEDS_REVIEW" if check["warnings"] else "BASIC_CHECK_PASS")
        for error in check["errors"]:
            report["actions"].append({"priority": "P0", "action": error, "path": str(master)})
        for warning in check["warnings"]:
            report["actions"].append({"priority": "P1", "action": warning, "path": str(master)})
    for name, profile in (profiles if profiles is not None else DEFAULT_PLATFORMS).items():
        if not profile.get("enabled", True):
            continue
        package_dir = root / "PLATFORMS" / str(profile.get("folder") or name.upper().replace(" ", "_"))
        package_files = sorted(p.relative_to(package_dir).as_posix() for p in package_dir.rglob("*") if p.is_file()) if package_dir.is_dir() else []
        missing = []
        if not package_dir.is_dir():
            missing.append(f"Platform package folder is missing: {package_dir}")
        else:
            for group in profile.get("required_any", []):
                if not _matches_any(package_dir, group):
                    missing.append("Required package file missing; expected one of: " + " OR ".join(group))
        listing_dir = root / "MARKETING" / "LISTINGS"
        listing_files = sorted(p.relative_to(listing_dir).as_posix() for p in listing_dir.rglob("*") if p.is_file()) if listing_dir.is_dir() else []
        for group in profile.get("listing_any", []):
            if not _matches_any(listing_dir, group):
                missing.append("Listing draft missing one of: " + " OR ".join(group))
        status = "BLOCKED" if source_status == "BLOCKED" or missing else "NEEDS_REVIEW"
        report["summary"][status] += 1
        report["platforms"][name] = {"status": status, "package_folder": str(package_dir),
            "package_files": package_files, "listing_folder": str(listing_dir), "listing_files": listing_files,
            "missing_requirements": missing, "notes": profile.get("notes", ""),
            "upload_confirmed": False, "next_step": "Resolve the listed requirements, review the files, then upload manually."}
        for issue in missing:
            report["actions"].append({"priority": "P0", "platform": name, "action": issue, "path": str(package_dir)})
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
        print(f"Report: {saved}")
        print("Local preflight only. Nothing was uploaded or published.")
    return 1 if report["overall_status"] == "BLOCKED" else 0

if __name__ == "__main__":
    raise SystemExit(main())
