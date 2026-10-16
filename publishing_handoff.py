"""Read-only, hash-backed publishing handoff inventory (v108-v112)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "1.1"
PLATFORM_ROOTS = ("KDP", "GUMROAD", "PAYHIP", "DIGITAL")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _case_collisions(paths: list[str]) -> list[list[str]]:
    """Return case-insensitive duplicate path groups, independent of host filesystem rules."""
    grouped: dict[str, list[str]] = {}
    for path in paths:
        grouped.setdefault(path.casefold(), []).append(path)
    return [variants for variants in grouped.values() if len(variants) > 1]


def build_handoff_manifest(project: str | Path, platform_folders: tuple[str, ...] = PLATFORM_ROOTS) -> dict[str, Any]:
    """Inventory package files and flag zero-byte files, case collisions, and unreadable paths."""
    root = Path(project).expanduser().resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "tool_version": VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "project": str(root),
        "read_only": True,
        "uploaded_or_published": False,
        "summary": {"files": 0, "bytes": 0, "zero_byte_files": 0, "case_collisions": 0, "symlink_files": 0, "read_errors": 0},
        "platforms": {},
        "actions": [],
    }
    if not root.is_dir():
        report["actions"].append({"priority": "P0", "action": "Project folder does not exist.", "path": str(root)})
        report["summary"]["read_errors"] += 1
        return report

    for folder_name in platform_folders:
        folder = root / "PLATFORMS" / folder_name
        row = {"folder": str(folder), "exists": folder.is_dir(), "files": [], "case_collisions": [],
               "zero_byte_files": [], "symlink_paths": [], "read_errors": []}
        if not folder.is_dir():
            report["actions"].append({"priority": "P1", "platform": folder_name,
                                      "action": "Package folder is missing.", "path": str(folder)})
            report["platforms"][folder_name] = row
            continue
        files = sorted(path for path in folder.rglob("*") if path.is_file() or path.is_symlink())
        relative_paths = [path.relative_to(folder).as_posix() for path in files]
        collisions = _case_collisions(relative_paths)
        for variants in collisions:
            row["case_collisions"].append(variants)
            report["summary"]["case_collisions"] += 1
            report["actions"].append({"priority": "P1", "platform": folder_name,
                                      "action": "Case-insensitive filename collision; may behave differently across systems.",
                                      "paths": variants})
        for path in files:
            relative = path.relative_to(folder).as_posix()
            # Never follow a package symlink: it could point outside PLATFORMS or be dangling.
            if path.is_symlink():
                row["symlink_paths"].append(relative)
                report["summary"]["symlink_files"] += 1
                report["actions"].append({
                    "priority": "P0", "platform": folder_name,
                    "action": "Package contains a symbolic link; replace it with a regular file before handoff.",
                    "path": str(path),
                })
                continue
            try:
                size = path.stat().st_size
                entry = {"path": relative, "size_bytes": size, "sha256": _sha256(path)}
                row["files"].append(entry)
                report["summary"]["files"] += 1
                report["summary"]["bytes"] += size
                if size == 0:
                    row["zero_byte_files"].append(relative)
                    report["summary"]["zero_byte_files"] += 1
                    report["actions"].append({"priority": "P0", "platform": folder_name,
                                              "action": "Package file is empty.", "path": str(path)})
            except OSError as exc:
                message = f"{relative}: {type(exc).__name__}: {exc}"
                row["read_errors"].append(message)
                report["summary"]["read_errors"] += 1
                report["actions"].append({"priority": "P0", "platform": folder_name,
                                          "action": "Could not read package file: " + message, "path": str(path)})
        report["platforms"][folder_name] = row
    report["actions"].sort(key=lambda item: (item.get("priority", "P9"), item.get("platform", ""), item.get("action", "")))
    return report


def write_handoff_manifest_no_clobber(project: str | Path, report: dict[str, Any]) -> Path:
    """Write a timestamped manifest without overwriting earlier reports."""
    reports = Path(project).expanduser().resolve() / "REPORTS"
    reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    base = reports / f"PUBLISHING_HANDOFF_{stamp}.json"
    for suffix in range(1000):
        target = base if suffix == 0 else base.with_name(f"{base.stem}_{suffix}.json")
        try:
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(report, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            return target
        except FileExistsError:
            continue
    raise FileExistsError("Could not allocate a unique publishing handoff manifest filename.")
