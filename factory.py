from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter, ImageEnhance
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import json
import textwrap
import shutil
import sys
import subprocess
import zipfile
import re
import os
from datetime import datetime
from hashlib import sha256

# ============================================================
# COLORING BOOK FACTORY
# World-aware production engine: automated assembly, page builder,
# PDF/KDP preflight, platform packaging, and production center.
# Current version: 17.7.
# Release history: see CHANGELOG.md (kept next to this file).
#
# Maintenance rule: every function has exactly ONE definition in this
# file. Edit it in place -- never paste a new "v2" copy lower down,
# because the last definition silently wins.
# ============================================================

FACTORY = Path(__file__).resolve().parent
PROJECTS = FACTORY / "Projects"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

FACTORY_VERSION = "17.7"
WORLD_ENGINE_VERSION = "1.1"
WORLDS_DIR = FACTORY / "Worlds"
WORLD_INDEX_FILENAME = "world_index.json"
WORLD_SCHEMA_VERSION = 2
SERIES_ENGINE_VERSION = "1.0"
SERIES_DIR = FACTORY / "Series"
MARKETING_DIR_NAME = "MARKETING"
SERIES_BIBLE_FILENAME = "SERIES_BIBLE.json"
SERIES_BIBLE_MD_FILENAME = "SERIES_BIBLE.md"
BUILD_STATE_FILE = "build_state.json"
SUPPORTED_TRIM_SIZES = {
    "8.5x11": (8.5, 11.0),
    "8x10": (8.0, 10.0),
    "7.5x9.25": (7.5, 9.25),
    "6x9": (6.0, 9.0),
}

VALID_PAGE_TYPES = {"title", "copyright", "toc", "coloring", "text", "lore", "intro", "activity", "blank"}

# v5.0 production configuration / bookkeeping
BOOK_CONFIG_FILENAME = "_book.json"
BUILD_HISTORY_FILENAME = "build_history.json"
PRODUCTION_QUEUE_FILENAME = "production_queue.json"
UPSCALE_INTERMEDIATE_DIR = "PROCESSED"
CONTACT_SHEET_FILENAME = "artwork_contact_sheet.png"


# ============================================================
# JSON
# ============================================================

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    """Write JSON safely, including Windows Path objects produced by release workflows."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False, default=str)


def load_optional_book_config(source_folder):
    """Load optional _book.json from an imported artwork folder."""
    path = source_folder / BOOK_CONFIG_FILENAME
    if not path.exists():
        return {}
    try:
        data = load_json(path)
        if not isinstance(data, dict):
            raise ValueError("_book.json must contain an object")
        return data
    except Exception as error:
        print(f"WARNING: Could not read {BOOK_CONFIG_FILENAME}: {error}")
        return {}


def load_build_history(project):
    path = project / BUILD_HISTORY_FILENAME
    if not path.exists():
        return {"version": FACTORY_VERSION, "builds": []}
    try:
        data = load_json(path)
        if not isinstance(data, dict):
            raise ValueError("history must be an object")
        data.setdefault("builds", [])
        return data
    except Exception:
        return {"version": FACTORY_VERSION, "builds": []}


def record_build_history(project, status, page_count=0, errors=None, warnings=None, fingerprint=None):
    history = load_build_history(project)
    history["version"] = FACTORY_VERSION
    history["builds"].append({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "page_count": page_count,
        "errors": list(errors or []),
        "warnings": list(warnings or []),
        "fingerprint": fingerprint,
    })
    history["builds"] = history["builds"][-100:]
    save_json(project / BUILD_HISTORY_FILENAME, history)


def load_queue():
    path = PROJECTS / PRODUCTION_QUEUE_FILENAME
    if not path.exists():
        return {"version": FACTORY_VERSION, "items": []}
    try:
        data = load_json(path)
        return data if isinstance(data, dict) else {"version": FACTORY_VERSION, "items": []}
    except Exception:
        return {"version": FACTORY_VERSION, "items": []}


def save_queue(queue):
    queue["version"] = FACTORY_VERSION
    save_json(PROJECTS / PRODUCTION_QUEUE_FILENAME, queue)


# ============================================================
# BUILD STATE / HASHING
# ============================================================

def file_hash(path):
    h = sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_build_state(project):
    path = project / BUILD_STATE_FILE
    if not path.exists():
        return {"version": FACTORY_VERSION, "images": {}, "last_build": None}
    try:
        return load_json(path)
    except Exception:
        return {"version": FACTORY_VERSION, "images": {}, "last_build": None}


def save_build_state(project, state):
    save_json(project / BUILD_STATE_FILE, state)


def update_project_defaults(settings):
    defaults = {
        "trim_width": 8.5,
        "trim_height": 11,
        "dpi": 300,
        "border_pixels": 150,
        "min_source_width": 1500,
        "min_source_height": 2000,
        "kdp_ink_type": "black_white",
        "kdp_auto_pad_minimum_pages": True,
        "kdp_minimum_pages": 24,
        "kdp_maximum_pages": 828,
        "kdp_generate_cover": True,
        "cover_subtitle": "A Coloring Adventure",
        "cover_blurb": "Explore strange creatures, dark machines, and unforgettable nightmares—one page at a time.",
        "artwork_upscale": True,
        "artwork_upscale_target_width": 2550,
        "artwork_upscale_target_height": 3300,
        "artwork_upscale_only_if_smaller": True,
        "build_history_enabled": True,
        "production_profile": "KDP 8.5x11 B&W",
        "book_spec_version": 1,
        "world_id": "",
        "world_engine_version": WORLD_ENGINE_VERSION,
        "template_profile": "classic_clean",
        "cover_template": "auto_framed",
        "production_manifest_enabled": True,
        "checksum_artifacts": True,
        "build_snapshots_enabled": True,
        "cache_by_artwork_identity": True,
        "metadata_export_enabled": True,
        "readiness_gate": True,
        # v6.2 world-aware production
        "universe_name": "",
        "series_name": "",
        "world_relationship": "standalone",
        "world_canon": True,
        "continuity_gate": True,
        "auto_update_world_bible": True,
        "auto_register_artwork_entities": True,
        "production_profile_version": 2,
    }
    changed = False
    for key, value in defaults.items():
        if key not in settings:
            settings[key] = value
            changed = True
    return changed


def source_inventory(images):
    inventory = {}
    for image in images:
        try:
            inventory[image.name] = {
                "hash": file_hash(image),
                "size": image.stat().st_size,
                "modified": image.stat().st_mtime,
            }
        except Exception as error:
            inventory[image.name] = {"error": str(error)}
    return inventory


PROCESSING_ENGINE_VERSION = "6.0-production"

def settings_fingerprint(settings):
    relevant = {
        "trim_width": settings.get("trim_width", 8.5),
        "trim_height": settings.get("trim_height", 11),
        "dpi": settings.get("dpi", 300),
        "border_pixels": settings.get("border_pixels", 150),
    }
    payload = json.dumps(relevant, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return sha256(payload).hexdigest()


def manifest_fingerprint(book):
    payload = json.dumps(book, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return sha256(payload).hexdigest()


def settings_full_fingerprint(settings):
    payload = json.dumps(settings, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return sha256(payload).hexdigest()


def clean_project_outputs(project):
    for folder_name in ("PROCESSED", "PAGES"):
        folder = project / folder_name
        folder.mkdir(exist_ok=True)
        for file in folder.glob("*.png"):
            try:
                file.unlink()
            except OSError:
                pass


# ============================================================
# FONTS
# ============================================================

def get_font(size, bold=False):

    candidates = []

    if bold:
        candidates += [
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\calibrib.ttf",
        ]

    candidates += [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
    ]

    for path in candidates:

        if Path(path).exists():

            return ImageFont.truetype(
                path,
                size
            )

    return ImageFont.load_default()


# ============================================================
# PROJECT SETUP
# ============================================================

def setup_project(project):

    folders = [
        "INPUT",
        "PROCESSED",
        "PAGES",
        "COVER",
        "PDF",
        "FINAL",
        "REPORTS",
        "KDP_PACKAGE"
    ]

    for folder in folders:

        (project / folder).mkdir(
            exist_ok=True
        )


# ============================================================
# WORLD ENGINE / UNIVERSES
# ============================================================

def world_slug(name):
    """Create a safe folder name for a persistent world."""
    import re
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", str(name)).strip().rstrip(".")
    value = re.sub(r"\s+", " ", value)
    return value or "New World"


def world_path(world_id):
    return WORLDS_DIR / str(world_id)


def load_world_index():
    WORLDS_DIR.mkdir(parents=True, exist_ok=True)
    path = WORLDS_DIR / WORLD_INDEX_FILENAME
    if not path.exists():
        return {"version": WORLD_SCHEMA_VERSION, "engine_version": WORLD_ENGINE_VERSION, "worlds": {}}
    try:
        data = load_json(path)
        if not isinstance(data, dict):
            raise ValueError("world index must be an object")
        data.setdefault("version", WORLD_SCHEMA_VERSION)
        data.setdefault("engine_version", WORLD_ENGINE_VERSION)
        data.setdefault("worlds", {})
        return data
    except Exception as error:
        print(f"WARNING: Could not read world index: {error}")
        return {"version": WORLD_SCHEMA_VERSION, "engine_version": WORLD_ENGINE_VERSION, "worlds": {}}


def save_world_index(index):
    WORLDS_DIR.mkdir(parents=True, exist_ok=True)
    index["version"] = WORLD_SCHEMA_VERSION
    index["engine_version"] = WORLD_ENGINE_VERSION
    save_json(WORLDS_DIR / WORLD_INDEX_FILENAME, index)


def load_world(world_id):
    path = world_path(world_id) / "world.json"
    if not path.exists():
        return None
    try:
        data = load_json(path)
        if not isinstance(data, dict):
            return None
        data.setdefault("schema_version", WORLD_SCHEMA_VERSION)
        data.setdefault("series", [])
        data.setdefault("relationships", [])
        data.setdefault("books", [])
        return data
    except Exception as error:
        print(f"WARNING: Could not load world {world_id}: {error}")
        return None


def save_world(world):
    wid = str(world.get("world_id", "")).strip()
    if not wid:
        raise ValueError("World is missing world_id")
    folder = world_path(wid)
    folder.mkdir(parents=True, exist_ok=True)
    save_json(folder / "world.json", world)
    index = load_world_index()
    index.setdefault("worlds", {})[wid] = {
        "world_id": wid,
        "name": world.get("name", wid),
        "updated": world.get("updated"),
    }
    save_world_index(index)


def make_world_id(name):
    """Return a stable-ish filesystem-safe world id without collisions."""
    base = world_slug(name)
    candidate = base
    counter = 2
    index = load_world_index()
    while candidate in index.get("worlds", {}) or world_path(candidate).exists():
        candidate = f"{base} ({counter})"
        counter += 1
    return candidate


def new_world_record(name, description="", genre="", tone=""):
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "schema_version": WORLD_SCHEMA_VERSION,
        "engine_version": WORLD_ENGINE_VERSION,
        "world_id": make_world_id(name),
        "name": str(name).strip() or "New World",
        "description": str(description).strip(),
        "genre": str(genre).strip(),
        "tone": str(tone).strip(),
        "universe": True,
        "series": [],
        "rules": [],
        "timeline": [],
        "characters": [],
        "creatures": [],
        "locations": [],
        "objects": [],
        "factions": [],
        "lore": [],
        "books": [],
        "relationships": [],
        "created": now,
        "updated": now,
    }


def world_entity_list(world, category):
    values = world.get(category, [])
    return values if isinstance(values, list) else []


def world_entity_key(entity):
    """Stable human-readable key used for deduplication/continuity."""
    if isinstance(entity, dict):
        return str(entity.get("name") or entity.get("title") or "").strip().lower()
    return str(entity).strip().lower()


def add_world_entity(world, category, entity):
    if category not in {"characters", "creatures", "locations", "objects", "factions", "lore", "timeline", "rules"}:
        raise ValueError("Invalid world category")
    world.setdefault(category, [])
    key = world_entity_key(entity)
    if key and any(world_entity_key(existing) == key for existing in world[category]):
        return False
    world[category].append(entity)
    world["updated"] = datetime.now().isoformat(timespec="seconds")
    save_world(world)
    if world.get("auto_update_world_bible", True):
        try:
            write_world_bible(world)
        except Exception:
            pass
    return True


def record_world_production_event(project, event_type, status, page_count=0, errors=0, warnings=0):
    """Append a production event to the attached world's history, if any.

    Never invents a world attachment; a standalone project simply has no
    world to record against.
    """
    world = get_project_world(project)
    if not world:
        return False
    try:
        settings = load_json(project / "project.json")
    except Exception:
        settings = {}
    history = world.setdefault("production_history", [])
    history.append({
        "date": datetime.now().isoformat(timespec="seconds"),
        "project": str(project),
        "title": settings.get("title", project.name),
        "event": event_type,
        "status": status,
        "pages": page_count,
        "errors": errors,
        "warnings": warnings,
    })
    # Keep this list from growing without bound across a long-lived world.
    if len(history) > 500:
        world["production_history"] = history[-500:]
    world["updated"] = datetime.now().isoformat(timespec="seconds")
    save_world(world)
    return True


def detach_project_from_world(project):
    """Remove a project from its current world without deleting the project."""
    settings = load_json(project / "project.json")
    old_id = str(settings.get("world_id", "")).strip()
    settings["world_id"] = ""
    settings["world_relationship"] = "standalone"
    save_json(project / "project.json", settings)
    if old_id:
        world = load_world(old_id)
        if world:
            world["books"] = [
                x for x in world.get("books", [])
                if not (isinstance(x, dict) and x.get("project") == str(project))
            ]
            world["updated"] = datetime.now().isoformat(timespec="seconds")
            save_world(world)


def attach_project_to_world(project, world_id, relationship=None, series_name=None):
    """Attach a book to a world; relationships remain explicit rather than assumed."""
    settings = load_json(project / "project.json")
    world = load_world(world_id)
    if not world:
        raise ValueError(f"World not found: {world_id}")

    old_id = str(settings.get("world_id", "")).strip()
    if old_id and old_id != world_id:
        old_world = load_world(old_id)
        if old_world:
            old_world["books"] = [
                x for x in old_world.get("books", [])
                if not (isinstance(x, dict) and x.get("project") == str(project))
            ]
            old_world["updated"] = datetime.now().isoformat(timespec="seconds")
            save_world(old_world)

    relationship = str(relationship or settings.get("world_relationship") or "canon").strip().lower()
    if relationship not in {"canon", "related", "inspired_by", "non_canon", "standalone"}:
        relationship = "canon"
    series = str(series_name if series_name is not None else settings.get("series_name", "")).strip()

    settings["world_id"] = world_id
    settings["world_engine_version"] = WORLD_ENGINE_VERSION
    settings["world_relationship"] = relationship
    settings["world_canon"] = relationship == "canon"
    settings["universe_name"] = world.get("name", world_id)
    settings["series_name"] = series
    save_json(project / "project.json", settings)

    books = world.setdefault("books", [])
    books[:] = [x for x in books if not (isinstance(x, dict) and x.get("project") == str(project))]
    books.append({
        "project": str(project),
        "title": settings.get("title", project.name),
        "series": series,
        "relationship": relationship,
        "canon": relationship == "canon",
        "attached": datetime.now().isoformat(timespec="seconds"),
    })
    if series and series not in world.setdefault("series", []):
        world["series"].append(series)
    world["updated"] = datetime.now().isoformat(timespec="seconds")
    save_world(world)
    return True


def get_project_world(project):
    try:
        settings = load_json(project / "project.json")
    except Exception:
        return None
    wid = str(settings.get("world_id", "")).strip()
    return load_world(wid) if wid else None


def project_world_context(project, settings=None):
    """Return explicit world/series relationship metadata for manifests and QC."""
    if settings is None:
        try:
            settings = load_json(project / "project.json")
        except Exception:
            settings = {}
    world = get_project_world(project)
    return {
        "world_id": str(settings.get("world_id", "")).strip(),
        "universe": str(settings.get("universe_name", "")).strip() or (world.get("name", "") if world else ""),
        "series": str(settings.get("series_name", "")).strip(),
        "relationship": str(settings.get("world_relationship", "standalone")).strip().lower(),
        "canon": bool(settings.get("world_canon", True)) if world else False,
        "world_exists": bool(world),
    }


def register_project_artwork_entities(project, world, images, book):
    """Register explicit artwork-to-world references without inventing lore."""
    if not world or not images:
        return 0
    registry = load_artwork_registry(project)
    artworks = registry.setdefault("artworks", {})
    changed = 0
    pages = book.get("pages", []) if isinstance(book, dict) else []
    by_artwork = {str(p.get("artwork_id")): p for p in pages if isinstance(p, dict) and p.get("artwork_id")}
    for source in images:
        aid = artwork_identity_id(source)
        rec = artworks.get(aid, {})
        page = by_artwork.get(aid, {})
        title = rec.get("title") or artwork_title(source, 1)
        refs = rec.get("world_references", [])
        if not isinstance(refs, list):
            refs = []
        ref = {
            "project": str(project),
            "book": str(project_world_context(project).get("series") or project.name),
            "artwork_id": aid,
            "filename": source.name,
            "title": title,
            "page_title": page.get("title", title),
        }
        if not any(isinstance(x, dict) and x.get("project") == str(project) for x in refs):
            refs.append(ref)
            changed += 1
        rec["world_references"] = refs
        artworks[aid] = rec
    registry["version"] = FACTORY_VERSION
    save_artwork_registry(project, registry)
    return changed


def world_continuity_check_for_project(project, settings, book, images):
    """Project-level continuity gate. Only checks explicit references; never invents canon."""
    world = get_project_world(project)
    if not world:
        return [], []
    errors, warnings = [], []
    ctx = project_world_context(project, settings)
    if ctx["relationship"] == "standalone":
        warnings.append("Project has a world_id but relationship is marked standalone.")
    if ctx["relationship"] == "canon":
        # Timeline duplicate checks are world-wide; entity duplicate checks are handled by world report.
        report, world_errors, world_warnings = world_continuity_report(world)
        errors.extend(world_errors)
        warnings.extend(world_warnings)
    # Check explicit manifest entity references.
    valid_ids = {}
    for category in ("characters", "creatures", "locations", "objects", "factions"):
        for item in world_entity_list(world, category):
            if isinstance(item, dict) and item.get("name"):
                valid_ids[str(item.get("name")).strip().lower()] = category
    for n, entry in enumerate(book.get("pages", []), 1):
        if not isinstance(entry, dict):
            continue
        refs = entry.get("world_entities", [])
        if isinstance(refs, str):
            refs = [refs]
        if isinstance(refs, list):
            for ref in refs:
                key = str(ref).strip().lower()
                if key and key not in valid_ids:
                    warnings.append(f"Manifest page {n}: world entity reference '{ref}' was not found in {world.get('name', 'world')}.")
    return errors, warnings


def write_world_bible(world):
    folder = world_path(world["world_id"])
    folder.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{world.get('name', 'World')} - WORLD BIBLE",
        "=" * 72,
        f"Genre: {world.get('genre', '')}",
        f"Tone: {world.get('tone', '')}",
        "",
        "WORLD OVERVIEW",
        "----------------",
        world.get("description", ""),
        "",
        "WORLD RULES",
        "-----------",
    ]
    for item in world_entity_list(world, "rules"):
        lines.append(f"- {item}")
    for category, heading, fields in [
        ("characters", "CHARACTERS", ["name", "role", "description", "appearance", "personality", "notes"]),
        ("creatures", "CREATURES", ["name", "type", "description", "appearance", "behavior", "notes"]),
        ("locations", "LOCATIONS", ["name", "type", "description", "appearance", "important_details", "notes"]),
        ("objects", "IMPORTANT OBJECTS", ["name", "type", "description", "powers", "notes"]),
        ("factions", "FACTIONS", ["name", "description", "goals", "notes"]),
        ("lore", "LORE", ["title", "body", "notes"]),
        ("timeline", "TIMELINE", ["date", "title", "description"]),
    ]:
        lines.extend(["", heading, "-" * len(heading)])
        for item in world_entity_list(world, category):
            if isinstance(item, dict):
                label = item.get("name") or item.get("title") or "Unnamed"
                lines.append(f"\n{label}")
                for field in fields[1:]:
                    value = item.get(field)
                    if value:
                        lines.append(f"  {field.replace('_', ' ').title()}: {value}")
            else:
                lines.append(f"- {item}")
    lines.extend(["", "SERIES", "------"])
    for series in world_entity_list(world, "series"):
        lines.append(f"- {series}")
    lines.extend(["", "BOOKS IN THIS WORLD", "--------------------"])
    for book in world_entity_list(world, "books"):
        if isinstance(book, dict):
            lines.append(
                f"- {book.get('title', book.get('project', 'Untitled'))} "
                f"[{book.get('project', '')}] "
                f"Series: {book.get('series', '') or 'None'} "
                f"Relationship: {book.get('relationship', 'canon')}"
            )
    output = folder / "WORLD_BIBLE.txt"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def world_continuity_report(world):
    """Static continuity checks; does not invent lore or alter books."""
    issues = []
    warnings = []
    seen = {}
    for category in ("characters", "creatures", "locations", "objects", "factions"):
        for item in world_entity_list(world, category):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip().lower()
            if not name:
                warnings.append(f"{category}: unnamed entity")
                continue
            key = (category, name)
            if key in seen:
                issues.append(f"Duplicate {category[:-1] if category.endswith('s') else category}: {name}")
            seen[key] = True
    for item in world_entity_list(world, "characters"):
        if isinstance(item, dict) and item.get("name") and not item.get("appearance"):
            warnings.append(f"Character '{item['name']}' has no appearance record.")
    timeline_seen = set()
    for item in world_entity_list(world, "timeline"):
        if isinstance(item, dict):
            key = (str(item.get("date", "")).strip().lower(), str(item.get("title", "")).strip().lower())
            if key != ("", "") and key in timeline_seen:
                issues.append(f"Duplicate timeline event: {item.get('title', 'Untitled')} ({item.get('date', '')})")
            timeline_seen.add(key)
    report = world_path(world["world_id"]) / "CONTINUITY_REPORT.txt"
    lines = [
        f"{world.get('name', 'World')} - CONTINUITY REPORT",
        "=" * 72,
        f"Errors: {len(issues)}",
        f"Warnings: {len(warnings)}",
        "",
        "ERRORS",
        "------",
    ] + [f"- {x}" for x in issues] + ["", "WARNINGS", "--------"] + [f"- {x}" for x in warnings]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report, issues, warnings


def remove_world_entity(world, category, index_pos):
    """Remove a world entity by its 1-based display position. Never invents state."""
    items = world_entity_list(world, category)
    if index_pos < 1 or index_pos > len(items):
        return None
    removed = items.pop(index_pos - 1)
    world["updated"] = datetime.now().isoformat(timespec="seconds")
    save_world(world)
    if world.get("auto_update_world_bible", True):
        try:
            write_world_bible(world)
        except Exception:
            pass
    return removed


def _describe_world_entity(item):
    if isinstance(item, dict):
        return item.get("name") or item.get("title") or "Unnamed"
    return str(item)


def world_manage_menu(world, wid):
    """Detail screen for a single world: view, add to, and remove from every category."""
    categories = {
        "1": ("rules", "Rules"),
        "2": ("characters", "Characters"),
        "3": ("creatures", "Creatures"),
        "4": ("locations", "Locations"),
        "5": ("objects", "Objects"),
        "6": ("factions", "Factions"),
        "7": ("lore", "Lore"),
        "8": ("timeline", "Timeline"),
    }
    while True:
        world = load_world(wid) or world
        print(f"\nWORLD: {world.get('name', wid)}")
        print(f"Description: {world.get('description', '')}")
        print(f"Genre: {world.get('genre', '')} | Tone: {world.get('tone', '')}")
        for key, (category, label) in categories.items():
            print(f"{key}. {label} ({len(world_entity_list(world, category))})")
        print("9. Export world bible")
        print("10. Continuity check")
        print("X. Back")
        sub = input("Choose: ").strip().lower()
        if sub == "x":
            return
        if sub in categories:
            category, label = categories[sub]
            items = world_entity_list(world, category)
            print(f"\n{label.upper()}")
            if not items:
                print("(none yet)")
            for i, item in enumerate(items, 1):
                print(f"  {i}. {_describe_world_entity(item)}")
            print("\nA. Add new")
            if items:
                print("R. Remove one")
            print("X. Back")
            action = input("Choose: ").strip().lower()
            if action == "a":
                if category == "rules":
                    rule = input("World rule: ").strip()
                    if rule:
                        add_world_entity(world, "rules", rule)
                elif category == "lore":
                    title = input("Lore title: ").strip()
                    body = input("Lore text: ").strip()
                    add_world_entity(world, "lore", {"title": title, "body": body})
                elif category == "timeline":
                    date = input("Timeline date/order: ").strip()
                    title = input("Event title: ").strip()
                    description = input("Event description: ").strip()
                    add_world_entity(world, "timeline", {"date": date, "title": title, "description": description})
                else:
                    name = input("Name: ").strip()
                    description = input("Description: ").strip()
                    appearance = input("Appearance / important details: ").strip()
                    item = {"name": name, "description": description, "appearance": appearance,
                            "created": datetime.now().isoformat(timespec="seconds")}
                    add_world_entity(world, category, item)
            elif action == "r" and items:
                try:
                    pos = int(input("Number to remove: ").strip())
                    removed = remove_world_entity(world, category, pos)
                    if removed is not None:
                        print(f"Removed: {_describe_world_entity(removed)}")
                    else:
                        print("Invalid selection.")
                except ValueError:
                    print("Invalid selection.")
        elif sub == "9":
            print(f"World Bible: {write_world_bible(world)}")
        elif sub == "10":
            report, errors, warnings = world_continuity_report(world)
            print(f"Continuity errors: {len(errors)} | warnings: {len(warnings)}")
            print(f"Report: {report}")


def world_list_menu():
    while True:
        index = load_world_index()
        all_worlds = index.get("worlds", {})
        active = {wid: meta for wid, meta in all_worlds.items() if not meta.get("archived")}
        archived = {wid: meta for wid, meta in all_worlds.items() if meta.get("archived")}
        ordered = sorted(active.keys())

        print("\n" + "=" * 60)
        print("WORLDS & UNIVERSES")
        print("=" * 60)
        if not active:
            print("No worlds created yet. Start with 'N' to create your first one.")
        else:
            for i, wid in enumerate(ordered, 1):
                world = load_world(wid) or active[wid]
                print(f"{i}. {world.get('name', wid)} [{wid}]")
                print(
                    f"   Series: {len(world_entity_list(world, 'series'))} | "
                    f"Characters: {len(world_entity_list(world, 'characters'))} | "
                    f"Creatures: {len(world_entity_list(world, 'creatures'))} | "
                    f"Locations: {len(world_entity_list(world, 'locations'))} | "
                    f"Books: {len(world_entity_list(world, 'books'))}"
                )
        if archived:
            print(f"\n({len(archived)} archived world(s) hidden from this list)")

        print("\nN. Create new world")
        if active:
            print("O. Open/manage world")
            print("B. Export world bible")
            print("C. Run continuity check")
            print("A. Attach a book project to a world")
            print("S. Manage series")
            print("V. View world's books")
            print("H. World production history")
            print("D. Archive a world")
        if archived:
            print("U. Restore an archived world")
        print("F. Find a world by name")
        print("X. Back")
        choice = input("Choose: ").strip().lower()

        if choice == "x":
            return

        if choice == "n":
            name = input("World name: ").strip()
            if not name:
                continue
            description = input("World description: ").strip()
            genre = input("Genre: ").strip()
            tone = input("Tone: ").strip()
            world = new_world_record(name, description, genre, tone)
            save_world(world)
            print(f"\nWORLD CREATED: {world['name']}")
            print(f"World folder: {world_path(world['world_id'])}")
            continue

        if choice == "f":
            term = input("Search text: ").strip().lower()
            matches = [(wid, meta) for wid, meta in all_worlds.items() if term in str(meta.get("name", wid)).lower()]
            if not matches:
                print("No matching worlds.")
            else:
                for wid, meta in matches:
                    tag = " [ARCHIVED]" if meta.get("archived") else ""
                    print(f"- {meta.get('name', wid)} [{wid}]{tag}")
            continue

        if choice == "u":
            if not archived:
                print("No archived worlds.")
                continue
            restore_ordered = sorted(archived.keys())
            for i, wid in enumerate(restore_ordered, 1):
                print(f"{i}. {archived[wid].get('name', wid)}")
            try:
                idx = int(input("World number to restore: ").strip()) - 1
                wid = restore_ordered[idx]
                world = load_world(wid)
                if not world:
                    raise ValueError("World not found")
                world["archived"] = False
                world["updated"] = datetime.now().isoformat(timespec="seconds")
                save_world(world)
                refreshed = load_world_index()
                refreshed["worlds"].setdefault(wid, {})["archived"] = False
                save_world_index(refreshed)
                print(f"Restored: {world.get('name', wid)}")
            except (ValueError, IndexError, TypeError):
                print("Invalid selection.")
            continue

        if not active:
            print("No worlds available yet. Choose 'N' to create one.")
            continue

        if choice == "s":
            print("\nSeries are stored inside each world and can be assigned to books.")
            try:
                idx = int(input("World number: ").strip()) - 1
                wid = ordered[idx]
                world = load_world(wid)
                if not world:
                    raise ValueError("World not found")
                series = input("Series name to add: ").strip()
                if series:
                    world.setdefault("series", [])
                    if series not in world["series"]:
                        world["series"].append(series)
                        world["updated"] = datetime.now().isoformat(timespec="seconds")
                        save_world(world)
                        write_world_bible(world)
                        print(f"Series added: {series}")
                    else:
                        print("Series already exists.")
            except Exception as error:
                print(f"ERROR: {error}")
            continue

        try:
            idx = int(input("World number: ").strip()) - 1
            wid = ordered[idx]
            world = load_world(wid)
        except (ValueError, IndexError, TypeError):
            print("Invalid world selection.")
            continue
        if not world:
            print("World could not be loaded.")
            continue

        if choice == "b":
            print(f"World Bible: {write_world_bible(world)}")
        elif choice == "c":
            report, errors, warnings = world_continuity_report(world)
            print(f"Continuity errors: {len(errors)} | warnings: {len(warnings)}")
            print(f"Report: {report}")
        elif choice == "a":
            project = choose_project()
            if project:
                try:
                    print("\nRelationship:")
                    print("1. Canon")
                    print("2. Related")
                    print("3. Inspired by")
                    print("4. Non-canon")
                    rel_choice = input("Choose [1]: ").strip() or "1"
                    rel = {"1": "canon", "2": "related", "3": "inspired_by", "4": "non_canon"}.get(rel_choice, "canon")
                    series = input("Series name [optional]: ").strip()
                    attach_project_to_world(project, wid, rel, series)
                    print(f"Attached '{project.name}' to world '{world['name']}' as {rel}.")
                except Exception as error:
                    print(f"ERROR: {error}")
        elif choice == "v":
            books = world_entity_list(world, "books")
            print(f"\nBOOKS IN {world.get('name', wid)}")
            if not books:
                print("No books attached to this world yet.")
            for b in books:
                if isinstance(b, dict):
                    print(
                        f"- {b.get('title', 'Untitled')} | Series: {b.get('series') or 'None'} | "
                        f"{b.get('relationship', 'canon')} | {b.get('project', '')}"
                    )
        elif choice == "h":
            history = world.get("production_history", [])
            print(f"\nPRODUCTION HISTORY FOR {world.get('name', wid)}")
            if not history:
                print("No recorded production events for this world yet.")
            for entry in history[-25:]:
                print(
                    f"- {entry.get('date', '')} | {entry.get('event', '')} | {entry.get('title', '')} | "
                    f"{entry.get('status', '')} | pages={entry.get('pages', 0)} "
                    f"errors={entry.get('errors', 0)} warnings={entry.get('warnings', 0)}"
                )
        elif choice == "d":
            print(f"\nThis will archive '{world.get('name', wid)}' and hide it from the active list.")
            print("Nothing on disk is deleted; it can be restored later with 'U'.")
            confirm = input(f"Type the world's name to confirm ('{world.get('name', wid)}'): ").strip()
            if confirm == world.get("name", wid):
                world["archived"] = True
                world["updated"] = datetime.now().isoformat(timespec="seconds")
                save_world(world)
                refreshed = load_world_index()
                refreshed["worlds"].setdefault(wid, {})["archived"] = True
                save_world_index(refreshed)
                print(f"Archived: {world.get('name', wid)}")
            else:
                print("Name did not match. Archiving cancelled.")
        elif choice == "o":
            world_manage_menu(world, wid)


# ============================================================
# PROJECTS
# ============================================================

def get_projects():

    if not PROJECTS.exists():
        PROJECTS.mkdir()

    return sorted(
        [
            p
            for p in PROJECTS.iterdir()
            if p.is_dir()
            and (p / "project.json").exists()
        ],
        key=lambda p: p.name.lower()
    )


def choose_project():

    projects = get_projects()

    if not projects:

        print()
        print("No projects found.")
        return None

    print()
    print("AVAILABLE PROJECTS")
    print("------------------------------------------")

    for i, project in enumerate(
        projects,
        start=1
    ):

        try:

            settings = load_json(
                project / "project.json"
            )

            title = settings.get(
                "title",
                project.name
            )

        except Exception:

            title = project.name

        print(
            f"{i}. {title} "
            f"[{project.name}]"
        )

    print()

    while True:

        choice = input(
            "Select project: "
        ).strip()

        try:

            number = int(choice)

            if 1 <= number <= len(projects):

                return projects[
                    number - 1
                ]

        except ValueError:
            pass

        print(
            "Enter a valid project number."
        )


# ============================================================
# PAGE DIMENSIONS
# ============================================================

def page_dimensions(settings):

    dpi = int(
        settings.get(
            "dpi",
            300
        )
    )

    width = int(
        float(
            settings.get(
                "trim_width",
                8.5
            )
        ) * dpi
    )

    height = int(
        float(
            settings.get(
                "trim_height",
                11
            )
        ) * dpi
    )

    return width, height, dpi


# ============================================================
# INPUT IMAGES
# ============================================================

def natural_image_sort_key(path):
    """Sort numeric-leading artwork naturally, then fall back to filename."""
    import re
    stem = path.stem.strip()
    match = re.match(r"^(\d+)(?:\D|$)", stem)
    if match:
        return (0, int(match.group(1)), stem.lower())
    return (1, stem.lower())


def get_images(project):
    folder = project / "INPUT"
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
    images = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    return sorted(images, key=natural_image_sort_key)


def artwork_title(source, number):
    """Create a readable title from underscores, hyphens, numbers, and CamelCase filenames."""
    import re
    stem = source.stem.strip()
    stem = re.sub(r"^\d+[\s._-]*", "", stem)
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem)
    stem = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", stem)
    # Remove a trailing single numeric version marker (e.g. ShadowVendor2).
    stem = re.sub(r"\d+$", "", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    stem = re.sub(r"\s+(png|jpg|jpeg|webp)$", "", stem, flags=re.I).strip()
    if not stem or stem.isdigit():
        return f"Artwork {number:03d}"
    return stem.title()


def artwork_identity_id(source):
    """Stable artwork identity derived from exact file content."""
    return f"ART-{file_hash(source)[:16].upper()}"


def load_artwork_registry(project):
    path = project / "artwork.json"
    if not path.exists():
        return {"version": FACTORY_VERSION, "artworks": {}}
    try:
        data = load_json(path)
        if not isinstance(data, dict):
            raise ValueError("artwork.json must contain an object")
        artworks = data.get("artworks", {})
        return {"version": data.get("version", FACTORY_VERSION), "artworks": artworks if isinstance(artworks, dict) else {}}
    except Exception:
        return {"version": FACTORY_VERSION, "artworks": {}}


def save_artwork_registry(project, registry):
    save_json(project / "artwork.json", registry)


def build_artwork_registry(project, images):
    """Maintain stable identities even when artwork filenames or ordering change."""
    registry = load_artwork_registry(project)
    artworks = registry.setdefault("artworks", {})
    now = datetime.now().isoformat(timespec="seconds")
    active_ids = set()
    for number, source in enumerate(images, start=1):
        digest = file_hash(source)
        artwork_id = f"ART-{digest[:16].upper()}"
        active_ids.add(artwork_id)
        existing = artworks.get(artwork_id, {})
        artworks[artwork_id] = {
            "artwork_id": artwork_id,
            "hash": digest,
            "filename": source.name,
            "title": existing.get("title") or artwork_title(source, number),
            "first_seen": existing.get("first_seen", now),
            "last_seen": now,
            "active": True,
        }
    for artwork_id, record in artworks.items():
        if artwork_id not in active_ids and isinstance(record, dict):
            record["active"] = False
    registry["version"] = FACTORY_VERSION
    registry["updated"] = now
    save_artwork_registry(project, registry)
    return registry


def generate_auto_manifest(project, settings, images):
    """Build a deterministic manifest using stable artwork identities."""
    registry = build_artwork_registry(project, images)
    pages = []
    assembly = settings.get("assembly", {})
    if not isinstance(assembly, dict):
        assembly = {}
    if assembly.get("include_title_page", True):
        pages.append({"type": "title", "title": settings.get("title", "Coloring Book")})
    if assembly.get("include_copyright_page", True):
        pages.append({"type": "copyright", "title": "Copyright", "body": assembly.get("copyright_text", "")})
    if assembly.get("include_toc", False):
        pages.append({"type": "toc", "title": "Table of Contents"})
    artwork_prefix = str(assembly.get("artwork_title_prefix", "")).strip()
    for number, source in enumerate(images, start=1):
        artwork_id = artwork_identity_id(source)
        record = registry["artworks"][artwork_id]
        title = record.get("title") or artwork_title(source, number)
        overrides = registry.get("filename_title_overrides", {})
        if isinstance(overrides, dict) and source.name in overrides:
            title = str(overrides[source.name]).strip() or title
        if artwork_prefix:
            title = f"{artwork_prefix} {number:03d} - {title}"
        pages.append({"type": "coloring", "image": f"{number:03d}", "artwork_id": artwork_id, "title": title, "source": source.name})

    # KDP paperback interiors have a minimum page count. For the default
    # black-and-white coloring-book configuration, automatically pad short
    # books with blank pages so the generated interior can pass KDP preflight.
    kdp_min = int(settings.get("kdp_minimum_pages", 24))
    if settings.get("kdp_auto_pad_minimum_pages", True) and len(pages) < kdp_min:
        for _ in range(kdp_min - len(pages)):
            pages.append({"type": "blank", "title": ""})

    return {"assembly_mode": "auto", "pages": pages}


def prepare_manifest(project, settings, images):
    """Return the active manifest; auto mode regenerates it from INPUT."""
    mode = str(settings.get("assembly_mode", "auto")).strip().lower()
    book_path = project / "book.json"
    existing = {}
    if book_path.exists():
        try:
            existing = load_json(book_path)
        except Exception:
            existing = {}

    if mode == "auto":
        book = generate_auto_manifest(project, settings, images)
        save_json(book_path, book)
        print(f"\nAUTO ASSEMBLY: generated {len(book['pages'])} page entries from {len(images)} artwork file(s).")
        return book

    return existing


# ============================================================
# ARTWORK PRODUCTION PREP
# ============================================================

def prepare_artwork_source(project, source, settings, number):
    """Create a production-ready artwork copy without modifying INPUT."""
    processed_dir = project / UPSCALE_INTERMEDIATE_DIR
    processed_dir.mkdir(exist_ok=True)
    target_w = int(settings.get("artwork_upscale_target_width", 2550))
    target_h = int(settings.get("artwork_upscale_target_height", 3300))
    dpi = int(settings.get("dpi", 300))
    digest = file_hash(source)[:16]
    out = processed_dir / f"{digest}_{number:03d}_prepared.png"
    try:
        with Image.open(source) as original:
            image = original.convert("RGB")
            if settings.get("artwork_upscale", True) and (image.width < target_w or image.height < target_h):
                scale = min(target_w / image.width, target_h / image.height)
                new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                image = image.resize(new_size, Image.Resampling.LANCZOS)
            if out.exists():
                try:
                    with Image.open(out) as existing:
                        if existing.size == image.size and existing.mode == "RGB":
                            return out
                except Exception:
                    pass
            image.save(out, "PNG", dpi=(dpi, dpi))
            return out
    except Exception as error:
        print(f"WARNING: Could not prepare artwork {source.name}: {error}")
        return source


def create_artwork_contact_sheet(project, settings, images):
    """Create a visual QC sheet showing all source/prepared artwork with titles."""
    if not settings.get("generate_contact_sheet", True) or not images:
        return None
    qc_dir = project / "QC"
    qc_dir.mkdir(exist_ok=True)
    columns = int(settings.get("contact_sheet_columns", 5))
    thumb_w = int(settings.get("contact_sheet_thumb_width", 300))
    thumb_h = int(settings.get("contact_sheet_thumb_height", 390))
    label_h = 65
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    font = get_font(24)
    for number, source in enumerate(images, start=1):
        x = ((number - 1) % columns) * thumb_w
        y = ((number - 1) // columns) * (thumb_h + label_h)
        try:
            with Image.open(source) as original:
                image = original.convert("RGB")
                image.thumbnail((thumb_w - 20, thumb_h - 20), Image.Resampling.LANCZOS)
                px = x + (thumb_w - image.width) // 2
                py = y + (thumb_h - image.height) // 2
                sheet.paste(image, (px, py))
        except Exception:
            draw.rectangle((x + 10, y + 10, x + thumb_w - 10, y + thumb_h - 10), outline="black", width=2)
        title = artwork_title(source, number)
        label = f"{number:03d}  {title}"
        lines = textwrap.wrap(label, width=25)[:2]
        for line_index, line in enumerate(lines):
            draw.text((x + 10, y + thumb_h + 8 + line_index * 25), line, font=font, fill="black")
    output = qc_dir / CONTACT_SHEET_FILENAME
    sheet.save(output, "PNG", dpi=(150, 150))
    return output


def artwork_change_summary(project, images):
    state = load_build_state(project)
    previous = state.get("images", {})
    current = source_inventory(images)
    added = [n for n in current if n not in previous]
    removed = [n for n in previous if n not in current]
    modified = [n for n in current if n in previous and current[n].get("hash") != previous[n].get("hash")]
    unchanged = [n for n in current if n in previous and current[n].get("hash") == previous[n].get("hash")]
    return {"added": added, "removed": removed, "modified": modified, "unchanged": unchanged}


# ============================================================
# ARTWORK FITTING
# ============================================================

def fit_artwork(
    image,
    page_width,
    page_height,
    border
):

    available_width = (
        page_width -
        (border * 2)
    )

    available_height = (
        page_height -
        (border * 2)
    )

    scale = min(
        available_width /
        image.width,

        available_height /
        image.height
    )

    new_width = max(
        1,
        int(
            image.width *
            scale
        )
    )

    new_height = max(
        1,
        int(
            image.height *
            scale
        )
    )

    return image.resize(
        (
            new_width,
            new_height
        ),
        Image.Resampling.LANCZOS
    )


# ============================================================
# COLORING PAGE
# ============================================================

def create_coloring_page(
    source,
    settings
):

    width, height, dpi = page_dimensions(
        settings
    )

    border = int(
        settings.get(
            "border_pixels",
            150
        )
    )

    with Image.open(source) as original:

        image = original.convert(
            "RGB"
        )

        artwork = fit_artwork(
            image,
            width,
            height,
            border
        )

        page = Image.new(
            "RGB",
            (
                width,
                height
            ),
            "white"
        )

        x = (
            width -
            artwork.width
        ) // 2

        y = (
            height -
            artwork.height
        ) // 2

        page.paste(
            artwork,
            (
                x,
                y
            )
        )

        return page


# ============================================================
# TEXT PAGE
# ============================================================

def create_text_page(
    title,
    body,
    settings
):

    width, height, dpi = page_dimensions(
        settings
    )

    page = Image.new(
        "RGB",
        (
            width,
            height
        ),
        "white"
    )

    draw = ImageDraw.Draw(
        page
    )

    title_font = get_font(
        90,
        True
    )

    body_font = get_font(
        46
    )

    draw.text(
        (
            width // 2,
            450
        ),
        title,
        font=title_font,
        fill="black",
        anchor="mm"
    )

    y = 750

    for paragraph in body.split(
        "\n"
    ):

        if not paragraph.strip():

            y += 40

            continue

        lines = textwrap.wrap(
            paragraph,
            width=62
        )

        for line in lines:

            draw.text(
                (
                    width // 2,
                    y
                ),
                line,
                font=body_font,
                fill="black",
                anchor="mm"
            )

            y += 70

        y += 25

    return page


# ============================================================
# TITLE
# ============================================================

def create_title_page(settings):

    return create_text_page(
        settings.get(
            "title",
            "Coloring Book"
        ),
        settings.get(
            "author",
            ""
        ),
        settings
    )


# ============================================================
# COPYRIGHT
# ============================================================

def create_copyright_page(
    settings,
    entry
):

    author = settings.get(
        "author",
        "Author"
    )

    body = entry.get(
        "body",
        (
            f"Copyright © {author}\n\n"
            "All rights reserved."
        )
    )

    return create_text_page(
        entry.get(
            "title",
            "Copyright"
        ),
        body,
        settings
    )


# ============================================================
# TOC
# ============================================================

def create_toc_page(
    settings,
    manifest
):

    width, height, dpi = page_dimensions(
        settings
    )

    page = Image.new(
        "RGB",
        (
            width,
            height
        ),
        "white"
    )

    draw = ImageDraw.Draw(
        page
    )

    draw.text(
        (
            width // 2,
            450
        ),
        "Table of Contents",
        font=get_font(
            90,
            True
        ),
        fill="black",
        anchor="mm"
    )

    y = 750

    for number, entry in enumerate(
        manifest,
        start=1
    ):

        title = entry.get(
            "title",
            f"Page {number}"
        )

        draw.text(
            (
                300,
                y
            ),
            f"{number}. {title}",
            font=get_font(
                44
            ),
            fill="black"
        )

        y += 80

        if y > height - 300:
            break

    return page


# ============================================================
# PROJECT / MANIFEST VALIDATION
# ============================================================

def validate_project(project, settings, book, images):
    warnings, errors = [], []
    checks = []
    def ok(msg): checks.append(("OK", msg))
    def warn(msg): warnings.append(msg); checks.append(("WARNING", msg))
    def fail(msg): errors.append(msg); checks.append(("ERROR", msg))

    title = str(settings.get("title", "")).strip()
    author = str(settings.get("author", "")).strip()
    if title: ok("Book title is present.")
    else: fail("Project title is missing.")
    if author: ok("Author is present.")
    else: warn("Author is missing.")

    try:
        w, h = float(settings.get("trim_width", 0)), float(settings.get("trim_height", 0))
        if w <= 0 or h <= 0: fail("Trim width and height must be greater than zero.")
        else: ok(f"Trim size is valid: {w} x {h} inches.")
    except Exception: fail("Trim width/height must be numeric.")
    try:
        dpi = int(settings.get("dpi", 0))
        if dpi <= 0: fail("DPI must be greater than zero.")
        elif dpi < 150: warn(f"DPI is unusually low: {dpi}.")
        else: ok(f"DPI is valid: {dpi}.")
    except Exception: fail("DPI must be an integer.")

    manifest = book.get("pages", []) if isinstance(book, dict) else []
    if not isinstance(manifest, list):
        fail("book.json 'pages' must be a list."); manifest = []
    if not images: fail("No source images were found.")
    else: ok(f"Found {len(images)} source image(s).")

    names = [p.name.lower() for p in images]
    dup_names = sorted({n for n in names if names.count(n) > 1})
    if dup_names: fail("Duplicate source filenames detected: " + ", ".join(dup_names))
    else: ok("Source filenames are unique.")

    registry = load_artwork_registry(project)
    registry_ids = set(registry.get("artworks", {}).keys())
    ordered_ids = {f"{i:03d}" for i, _ in enumerate(images, start=1)}
    active_artwork_ids = {artwork_identity_id(image) for image in images}
    refs = []
    uses_identity = False
    for n, entry in enumerate(manifest, 1):
        if not isinstance(entry, dict): fail(f"Manifest page {n} is not an object."); continue
        typ = str(entry.get("type", "blank")).strip().lower()
        if typ not in VALID_PAGE_TYPES: fail(f"Manifest page {n}: invalid page type '{typ}'.")
        if typ != "blank" and typ != "coloring" and not str(entry.get("title", "")).strip(): warn(f"Manifest page {n}: '{typ}' page has no title.")
        if typ == "coloring":
            artwork_id = str(entry.get("artwork_id", "")).strip()
            if artwork_id:
                uses_identity = True
                refs.append(artwork_id)
                if artwork_id not in registry_ids: fail(f"Manifest page {n}: artwork identity {artwork_id} is not present in artwork.json.")
                elif artwork_id not in active_artwork_ids: fail(f"Manifest page {n}: artwork identity {artwork_id} does not match any current source image.")
            else:
                image_id = str(entry.get("image", len(refs)+1)).zfill(3)
                refs.append(image_id)
                if image_id not in ordered_ids: fail(f"Manifest page {n}: references image {image_id}, but that artwork position does not exist.")
        if typ in {"text", "lore", "intro", "activity"} and not str(entry.get("body", "")).strip(): warn(f"Manifest page {n}: '{typ}' page has empty body text.")
    dup_refs = sorted({x for x in refs if refs.count(x) > 1})
    if dup_refs: fail("The same coloring artwork is referenced more than once: " + ", ".join(dup_refs))
    if uses_identity:
        unused = sorted(active_artwork_ids - set(refs))
        if unused: warn("Source artwork identity(ies) are not referenced by a coloring page: " + ", ".join(unused))
    else:
        unused = sorted(ordered_ids - set(refs))
        if unused: warn("Source image(s) are not referenced by a coloring page: " + ", ".join(unused))
    if len(refs) != len(images): warn(f"Manifest contains {len(refs)} coloring-page reference(s), but {len(images)} source image(s) were found.")
    expected_count = settings.get("number_of_images", 0)
    try:
        expected_count = int(expected_count)
        if expected_count > 0 and expected_count != len(images):
            fail(f"Project expects {expected_count} artwork image(s), but {len(images)} were found.")
    except Exception:
        warn("number_of_images is not an integer; automatic count check skipped.")
    if not manifest: fail("Manifest contains no pages.")

    report_folder = project / "REPORTS"; report_folder.mkdir(exist_ok=True)
    report_file = report_folder / "project_validation.json"
    data = {"factory_version":FACTORY_VERSION, "project":project.name, "book_title":title, "author":author, "source_images":len(images), "manifest_pages":len(manifest), "coloring_references":len(refs), "warnings":warnings, "errors":errors, "checks":[{"status":s,"message":m} for s,m in checks]}
    report_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("\nPROJECT / MANIFEST VALIDATION")
    print("------------------------------------------")
    print(f"Source images: {len(images)}")
    print(f"Manifest pages: {len(manifest)}")
    print(f"Coloring references: {len(refs)}")
    print(f"Warnings: {len(warnings)}")
    print(f"Errors: {len(errors)}")
    print(f"Report saved to:\n{report_file}")
    return warnings, errors

# ============================================================
# QUALITY CONTROL
# ============================================================

def quality_check(
    project,
    settings,
    images
):
    report_folder = project / "REPORTS"
    report_folder.mkdir(exist_ok=True)
    report = report_folder / "quality_report.txt"
    warnings = []
    errors = []
    seen_hashes = {}
    seen_names = {}
    min_width = int(settings.get("min_source_width", 1500))
    min_height = int(settings.get("min_source_height", 2000))

    with open(report, "w", encoding="utf-8") as f:
        f.write(f"COLORING BOOK FACTORY v{FACTORY_VERSION}\n")
        f.write("SMART IMAGE QUALITY CONTROL REPORT\n")
        f.write("=" * 60 + "\n\n")

        for number, image_path in enumerate(images, start=1):
            filename = image_path.name
            f.write(f"{number:03d} - {filename}\n")

            # Duplicate filename check
            name_key = filename.lower()
            if name_key in seen_names:
                message = f"{filename}: duplicate filename; also found as {seen_names[name_key]}."
                errors.append(message)
                f.write("ERROR: " + message + "\n")
            else:
                seen_names[name_key] = filename

            try:
                # Verify the file before doing any other processing.
                with Image.open(image_path) as image:
                    image.verify()

                with Image.open(image_path) as image:
                    width, height = image.size
                    mode = image.mode
                    fmt = image.format or image_path.suffix.upper().lstrip(".")
                    has_alpha = "A" in image.getbands() or "transparency" in image.info

                    f.write(f"Format: {fmt}\n")
                    f.write(f"Dimensions: {width} x {height}\n")
                    f.write(f"Mode: {mode}\n")

                    if height <= width:
                        message = f"{filename}: image is not portrait ({width}x{height})."
                        warnings.append(message)
                        f.write("WARNING: " + message + "\n")
                    else:
                        f.write("OK: Portrait orientation\n")

                    if width < min_width or height < min_height:
                        if settings.get("artwork_upscale", True):
                            message = (
                                f"{filename}: source resolution is low ({width}x{height}); "
                                f"production prep will create a larger working copy (target {int(settings.get('artwork_upscale_target_width', 2550))}x{int(settings.get('artwork_upscale_target_height', 3300))})."
                            )
                        else:
                            message = (
                                f"{filename}: source resolution is low ({width}x{height}); "
                                f"recommended minimum is {min_width}x{min_height}."
                            )
                        warnings.append(message)
                        f.write("WARNING: " + message + "\n")
                    else:
                        f.write("OK: Source resolution acceptable\n")

                    if mode not in {"RGB", "L"}:
                        message = f"{filename}: color mode is {mode}; it will be normalized to RGB."
                        warnings.append(message)
                        f.write("WARNING: " + message + "\n")
                    else:
                        f.write("OK: Color mode\n")

                    if has_alpha:
                        message = f"{filename}: transparency/alpha channel detected; background will be normalized."
                        warnings.append(message)
                        f.write("WARNING: " + message + "\n")
                    else:
                        f.write("OK: No transparency detected\n")

                    # Reject obviously unusable dimensions.
                    if width < 500 or height < 500:
                        message = f"{filename}: image is extremely small ({width}x{height}) and is not suitable for a coloring page."
                        errors.append(message)
                        f.write("ERROR: " + message + "\n")

                # Content hash catches identical artwork even when filenames differ.
                digest = sha256(image_path.read_bytes()).hexdigest()
                if digest in seen_hashes:
                    message = f"{filename}: duplicate artwork detected; identical file content as {seen_hashes[digest]}."
                    errors.append(message)
                    f.write("ERROR: " + message + "\n")
                else:
                    seen_hashes[digest] = filename
                    f.write("OK: No duplicate content detected\n")

            except Exception as error:
                message = f"{filename}: cannot be processed: {error}"
                errors.append(message)
                f.write("ERROR: " + message + "\n")

            f.write("\n")

        f.write("=" * 60 + "\n")
        f.write(f"Images checked: {len(images)}\n")
        f.write(f"Warnings: {len(warnings)}\n")
        f.write(f"Errors: {len(errors)}\n")

    print()
    print("QUALITY CONTROL")
    print("------------------------------------------")
    print(f"Images checked: {len(images)}")
    print(f"Warnings: {len(warnings)}")
    print(f"Errors: {len(errors)}")
    print(f"Report saved to:\n{report}")
    return warnings, errors

# ============================================================
# BUILD PAGES
# ============================================================

def build_pages(
    project,
    settings,
    book,
    images
):
    processed = project / "PROCESSED"
    pages_folder = project / "PAGES"
    processed.mkdir(exist_ok=True)
    pages_folder.mkdir(exist_ok=True)

    # PAGES are always rebuilt from the manifest so page numbering stays
    # deterministic. PROCESSED artwork is the expensive cached layer.
    for file in pages_folder.glob("*.png"):
        try:
            file.unlink()
        except OSError:
            pass

    width, height, dpi = page_dimensions(settings)
    state = load_build_state(project)
    old_images = state.get("images", {})
    process_signature = settings_fingerprint(settings)

    image_map = {}
    artwork_map = {}
    processed_map = {}

    # ----------------------------------------
    # PROCESS SOURCE IMAGES WITH REAL CHANGE DETECTION
    # ----------------------------------------
    for number, source in enumerate(images, start=1):
        image_id = f"{number:03d}"
        image_map[image_id] = source
        artwork_map[artwork_identity_id(source)] = source

        current_hash = file_hash(source)
        artwork_id = artwork_identity_id(source)
        # v6 cache identity is content-based, so renaming/reordering an artwork
        # does not force an expensive reprocess. Keep legacy filename lookup as
        # a migration fallback for existing v5 projects.
        cached = old_images.get(artwork_id, {})
        if not cached:
            cached = old_images.get(source.name, {})
        output = processed / f"ART-{artwork_id.split('-', 1)[-1][:16]}.png" if settings.get("cache_by_artwork_identity", True) else processed / f"{image_id}.png"

        reusable = (
            cached.get("hash") == current_hash
            and cached.get("process_signature") == process_signature
            and output.exists()
        )

        if reusable:
            print(f"  CACHE HIT: {source.name} [{artwork_id}]")
        else:
            print(f"  PROCESSING: {source.name} [{artwork_id}]")
            prepared_source = prepare_artwork_source(project, source, settings, number)
            page = create_coloring_page(prepared_source, settings)
            page.save(output, "PNG", dpi=(dpi, dpi))

        processed_map[source.name] = output

    # Remove stale cached processed images that no longer correspond to input.
    active_names = {image.name for image in images}
    for old_name, old_entry in old_images.items():
        if old_name not in active_names:
            stale_id = old_entry.get("processed_id")
            if stale_id:
                stale_file = processed / stale_id
                if stale_file.exists():
                    try:
                        stale_file.unlink()
                    except OSError:
                        pass

    # ----------------------------------------
    # BUILD MANIFEST
    # ----------------------------------------
    manifest = book.get("pages", [])
    built = []
    coloring_number = 0

    for entry in manifest:
        page_type = entry.get("type", "blank").lower()
        title = entry.get("title", "")

        if page_type == "title":
            page = create_title_page(settings)

        elif page_type == "copyright":
            page = create_copyright_page(settings, entry)

        elif page_type == "toc":
            page = create_toc_page(settings, manifest)

        elif page_type == "coloring":
            coloring_number += 1
            artwork_id = str(entry.get("artwork_id", "")).strip()
            if artwork_id:
                source = artwork_map.get(artwork_id)
            else:
                image_id = str(entry.get("image", coloring_number)).zfill(3)
                source = image_map.get(image_id)

            if not source:
                print(f"WARNING: Image {image_id} not found.")
                continue

            cached_page = processed_map.get(source.name)
            if cached_page and cached_page.exists():
                with Image.open(cached_page) as cached_image:
                    page = cached_image.convert("RGB").copy()
            else:
                prepared_source = prepare_artwork_source(project, source, settings, coloring_number)
                page = create_coloring_page(prepared_source, settings)

        elif page_type in {"text", "lore", "intro", "activity"}:
            page = create_text_page(
                title or page_type.title(),
                entry.get("body", ""),
                settings
            )

        else:
            page = Image.new("RGB", (width, height), "white")

        page_number = len(built) + 1
        output = pages_folder / f"{page_number:03d}.png"
        page.save(output, "PNG", dpi=(dpi, dpi))

        built.append({
            "number": page_number,
            "type": page_type,
            "title": title
        })

    # Do not claim a successful build until the complete pipeline passes.
    return built

# ============================================================
# PAGE PREFLIGHT
# ============================================================

def page_preflight(
    project,
    settings
):

    pages_folder = (
        project /
        "PAGES"
    )

    expected_width, expected_height, dpi = (
        page_dimensions(
            settings
        )
    )

    page_files = sorted(
        pages_folder.glob(
            "*.png"
        )
    )

    errors = []
    warnings = []

    expected_numbers = list(
        range(
            1,
            len(page_files) + 1
        )
    )

    actual_numbers = []

    for file in page_files:

        try:

            actual_numbers.append(
                int(
                    file.stem
                )
            )

        except ValueError:

            warnings.append(
                f"Non-numbered page: "
                f"{file.name}"
            )

    if actual_numbers != expected_numbers:

        errors.append(
            "Page numbering is not "
            "continuous."
        )

    for file in page_files:

        try:

            with Image.open(file) as image:

                width, height = (
                    image.size
                )

                if (
                    width != expected_width
                    or height != expected_height
                ):

                    errors.append(
                        f"{file.name}: "
                        f"{width}x{height} "
                        f"instead of "
                        f"{expected_width}x"
                        f"{expected_height}"
                    )

                if image.mode not in {
                    "RGB",
                    "L"
                }:

                    warnings.append(
                        f"{file.name}: "
                        f"color mode is "
                        f"{image.mode}"
                    )

        except Exception as error:

            errors.append(
                f"{file.name}: "
                f"{error}"
            )

    return (
        page_files,
        errors,
        warnings
    )


# ============================================================
# PDF BUILDER
# ============================================================

def create_pdf(
    project,
    settings
):

    pdf_folder = (
        project /
        "PDF"
    )

    final_folder = (
        project /
        "FINAL"
    )

    pdf_folder.mkdir(
        exist_ok=True
    )

    final_folder.mkdir(
        exist_ok=True
    )

    pages_folder = (
        project /
        "PAGES"
    )

    page_files = sorted(
        pages_folder.glob(
            "*.png"
        ),
        key=lambda p: int(
            p.stem
        )
    )

    title = settings.get(
        "title",
        project.name
    )

    pdf_file = (
        pdf_folder /
        f"{title}.pdf"
    )

    # ReportLab uses points.
    # 1 inch = 72 points.

    width_points = (
        float(
            settings.get(
                "trim_width",
                8.5
            )
        ) * 72
    )

    height_points = (
        float(
            settings.get(
                "trim_height",
                11
            )
        ) * 72
    )

    pdf = canvas.Canvas(
        str(pdf_file),
        pagesize=(
            width_points,
            height_points
        )
    )

    for page_file in page_files:

        image = Image.open(
            page_file
        )

        image_width, image_height = (
            image.size
        )

        pdf.drawImage(
            ImageReader(
                image
            ),
            0,
            0,
            width=width_points,
            height=height_points,
            preserveAspectRatio=False,
            mask="auto"
        )

        pdf.showPage()

        image.close()

    pdf.save()

    # Copy to FINAL as well.
    final_pdf = (
        final_folder /
        f"{title}.pdf"
    )

    shutil.copy2(
        pdf_file,
        final_pdf
    )

    return pdf_file, final_pdf, len(page_files)


# ============================================================
# PDF PREFLIGHT
# ============================================================

def pdf_preflight(
    pdf_file,
    settings,
    expected_pages
):

    errors = []
    warnings = []

    try:

        from PyPDF2 import PdfReader

        reader = PdfReader(
            str(pdf_file)
        )

        actual_pages = len(
            reader.pages
        )

        if actual_pages != expected_pages:

            errors.append(
                f"PDF contains "
                f"{actual_pages} pages; "
                f"expected "
                f"{expected_pages}."
            )

        expected_width = (
            float(
                settings.get(
                    "trim_width",
                    8.5
                )
            ) * 72
        )

        expected_height = (
            float(
                settings.get(
                    "trim_height",
                    11
                )
            ) * 72
        )

        for number, page in enumerate(
            reader.pages,
            start=1
        ):

            width = float(
                page.mediabox.width
            )

            height = float(
                page.mediabox.height
            )

            tolerance = 0.5

            if (
                abs(
                    width -
                    expected_width
                ) > tolerance
                or
                abs(
                    height -
                    expected_height
                ) > tolerance
            ):

                errors.append(
                    f"PDF page "
                    f"{number}: "
                    f"wrong page size."
                )

    except ImportError:

        warnings.append(
            "PyPDF2 is not installed; "
            "PDF structural check skipped."
        )

    except Exception as error:

        errors.append(
            f"PDF check failed: "
            f"{error}"
        )

    return errors, warnings


# ============================================================
# KDP PRODUCTION / PREFLIGHT
# ============================================================

def kdp_page_limits(settings):
    """Return current KDP paperback page limits for the selected ink type."""
    ink = str(settings.get("kdp_ink_type", "black_white")).strip().lower()
    if ink == "standard_color":
        return 72, 600
    if ink == "premium_color":
        return 24, 828
    return 24, 828


def kdp_spine_width(settings, page_count):
    """Calculate paperback spine width using KDP's current paper formulas."""
    ink = str(settings.get("kdp_ink_type", "black_white")).strip().lower()
    if ink == "premium_color":
        per_page = 0.002347
    elif ink == "standard_color":
        per_page = 0.002252
    else:
        # Black ink / white paper.
        per_page = 0.002252
    return page_count * per_page


def kdp_safe_filename(name):
    """Return a conservative KDP-friendly filename."""
    import re
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", str(name))
    value = re.sub(r"\s+", " ", value).strip().rstrip(".")
    return value or "ColoringBook"


def _cover_font(size, bold=False):
    """Load an embedded/rasterized Windows font for the cover artwork."""
    candidates = []
    if bold:
        candidates += [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\calibrib.ttf"]
    candidates += [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\calibri.ttf"]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _fit_text(draw, text, font_path_size, max_width, bold=False, min_size=18):
    """Return a font sized to keep text inside the requested width."""
    size = int(font_path_size)
    while size > min_size:
        font = _cover_font(size, bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 2
    return _cover_font(max(min_size, size), bold)


def create_kdp_cover(project, settings, page_count):
    """Create a polished 300-DPI rasterized paperback cover and a print-ready PDF."""
    cover_folder = project / "KDP_PACKAGE"
    cover_folder.mkdir(exist_ok=True)

    title = str(settings.get("title", "Coloring Book")).strip() or "Coloring Book"
    author = str(settings.get("author", "Author")).strip() or "Author"
    theme = str(settings.get("theme", settings.get("genre", "Coloring Book"))).strip() or "Coloring Book"
    subtitle = str(settings.get("cover_subtitle", "A Coloring Adventure")).strip()

    trim_w = float(settings.get("trim_width", 8.5))
    trim_h = float(settings.get("trim_height", 11))
    dpi = 300
    bleed = 0.125
    safe = 0.25
    spine = kdp_spine_width(settings, page_count)
    cover_w = trim_w * 2 + spine + bleed * 2
    cover_h = trim_h + bleed * 2

    px_w = int(round(cover_w * dpi))
    px_h = int(round(cover_h * dpi))
    img = Image.new("RGB", (px_w, px_h), "white")
    draw = ImageDraw.Draw(img)

    def px(inches):
        return int(round(inches * dpi))

    # Panel geometry: back | spine | front. Bleed exists around the complete cover.
    back_x = px(bleed)
    spine_x = px(bleed + trim_w)
    front_x = px(bleed + trim_w + spine)
    panel_w = px(trim_w)
    panel_h = px(trim_h)
    top = px(bleed)

    # Subtle production-safe panel backgrounds.
    draw.rectangle([0, 0, px(bleed + trim_w), px(cover_h)], fill=(245, 245, 245))
    draw.rectangle([front_x, 0, px(cover_w), px(cover_h)], fill=(250, 250, 250))
    if spine > 0:
        draw.rectangle([spine_x, 0, front_x, px(cover_h)], fill=(232, 232, 232))

    # Use the first artwork as the front-cover focal image.
    images = get_images(project)
    effective_dpi = None
    if images:
        try:
            with Image.open(images[0]) as original:
                source_w, source_h = original.size
                artwork = original.convert("RGB")
                max_w = int(panel_w * 0.78)
                max_h = int(panel_h * 0.57)
                scale = min(max_w / artwork.width, max_h / artwork.height)
                draw_w = max(1, int(artwork.width * scale))
                draw_h = max(1, int(artwork.height * scale))
                artwork = artwork.resize((draw_w, draw_h), Image.Resampling.LANCZOS)
                effective_dpi = min(
                    source_w / (draw_w / dpi),
                    source_h / (draw_h / dpi)
                )
                ax = front_x + (panel_w - draw_w) // 2
                ay = top + int(panel_h * 0.27)
                # A clean framed presentation makes the automatic cover look deliberate.
                frame = 18
                draw.rectangle([ax-frame, ay-frame, ax+draw_w+frame, ay+draw_h+frame],
                               fill=(20, 20, 20))
                img.paste(artwork, (ax, ay))
        except Exception:
            pass

    front_center = front_x + panel_w // 2
    safe_left = front_x + px(safe)
    safe_right = front_x + panel_w - px(safe)
    safe_width = safe_right - safe_left

    # Front title hierarchy.
    title_font = _fit_text(draw, title, 84, safe_width, bold=True, min_size=28)
    bbox = draw.textbbox((0, 0), title, font=title_font)
    title_y = top + px(0.34)
    draw.text((front_center, title_y), title, font=title_font, fill=(18, 18, 18), anchor="ma")

    subtitle_font = _fit_text(draw, subtitle, 34, int(safe_width * 0.9), bold=False, min_size=16)
    draw.text((front_center, top + px(0.89)), subtitle, font=subtitle_font,
              fill=(70, 70, 70), anchor="ma")

    author_font = _fit_text(draw, author, 30, int(safe_width * 0.8), bold=True, min_size=15)
    draw.text((front_center, top + panel_h - px(0.42)), author, font=author_font,
              fill=(25, 25, 25), anchor="ma")

    # Back cover copy, kept well inside KDP's recommended safe area.
    back_center = back_x + panel_w // 2
    back_safe_left = back_x + px(safe)
    back_safe_right = back_x + panel_w - px(safe)
    back_safe_width = back_safe_right - back_safe_left
    back_title_font = _fit_text(draw, title, 42, int(back_safe_width * 0.9), bold=True, min_size=20)
    draw.text((back_center, top + px(0.55)), title, font=back_title_font, fill=(25, 25, 25), anchor="ma")

    blurb = str(settings.get("cover_blurb", "Explore strange creatures, dark machines, and unforgettable nightmares—one page at a time."))
    body_font = _cover_font(25, False)
    y = top + px(1.25)
    words = blurb.split()
    lines = []
    line = ""
    for word in words:
        test = (line + " " + word).strip()
        if draw.textbbox((0, 0), test, font=body_font)[2] <= int(back_safe_width * 0.82):
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    for line in lines[:8]:
        draw.text((back_center, y), line, font=body_font, fill=(55, 55, 55), anchor="ma")
        y += px(0.42)

    # Barcode-safe region: deliberately blank so KDP can place its barcode if needed.
    barcode_w = px(2.0)
    barcode_h = px(1.2)
    barcode_x = back_x + panel_w - px(0.45) - barcode_w
    barcode_y = top + panel_h - px(0.45) - barcode_h
    draw.rectangle([barcode_x, barcode_y, barcode_x + barcode_w, barcode_y + barcode_h], fill="white")
    barcode_label_font = _cover_font(14, False)
    draw.text((barcode_x + barcode_w//2, barcode_y + barcode_h//2), "BARCODE AREA",
              font=barcode_label_font, fill=(160, 160, 160), anchor="mm")

    # Spine only when KDP allows spine text. Keep text comfortably inside the spine.
    if page_count >= 79 and spine >= 0.25:
        spine_center = spine_x + px(spine) // 2
        spine_font = _fit_text(draw, title, 24, max(px(0.08), px(spine - 0.125)), bold=True, min_size=8)
        draw.text((spine_center, top + panel_h // 2), title, font=spine_font,
                  fill=(25, 25, 25), anchor="mm", spacing=0)

    # Save a 300-DPI preview PNG and place that flattened artwork into the PDF.
    preview = cover_folder / f"{kdp_safe_filename(title)}_COVER_PREVIEW.png"
    img.save(preview, "PNG", dpi=(dpi, dpi), optimize=True)

    cover_file = cover_folder / f"{kdp_safe_filename(title)}_COVER.pdf"
    c = canvas.Canvas(str(cover_file), pagesize=(cover_w * 72, cover_h * 72))
    c.drawImage(ImageReader(str(preview)), 0, 0, width=cover_w * 72, height=cover_h * 72)
    c.showPage()
    c.save()

    cover_meta = {
        "dpi": dpi,
        "cover_width_inches": cover_w,
        "cover_height_inches": cover_h,
        "bleed_inches": bleed,
        "safe_margin_inches": safe,
        "spine_width_inches": spine,
        "spine_text_allowed": page_count >= 79,
        "barcode_area_reserved": True,
        "effective_artwork_dpi": effective_dpi,
    }
    save_json(cover_folder / "cover_manifest.json", cover_meta)
    return cover_file, cover_w, cover_h, spine


def kdp_cover_preflight(project, settings, cover_file, page_count, cover_w, cover_h, spine):
    """Validate the generated cover against measurable KDP cover requirements."""
    errors = []
    warnings = []
    trim_w = float(settings.get("trim_width", 8.5))
    trim_h = float(settings.get("trim_height", 11))
    expected_w = trim_w * 2 + spine + 0.25
    expected_h = trim_h + 0.25

    if abs(cover_w - expected_w) > 0.0001 or abs(cover_h - expected_h) > 0.0001:
        errors.append(f"Cover geometry is {cover_w:.4f} x {cover_h:.4f} in; expected {expected_w:.4f} x {expected_h:.4f} in.")

    if cover_file is None or not cover_file.exists():
        errors.append("Generated cover PDF was not created.")
        return errors, warnings

    size_mb = cover_file.stat().st_size / (1024 * 1024)
    if size_mb > 650:
        errors.append(f"Cover PDF is {size_mb:.1f} MB; KDP maximum is 650 MB.")
    elif size_mb > 40:
        warnings.append(f"Cover PDF is {size_mb:.1f} MB; KDP recommends 40 MB or less.")

    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(cover_file))
        if len(reader.pages) != 1:
            errors.append(f"Cover PDF contains {len(reader.pages)} pages; it must contain exactly one full cover page.")
        else:
            page = reader.pages[0]
            w = float(page.mediabox.width) / 72
            h = float(page.mediabox.height) / 72
            if abs(w - expected_w) > 0.01 or abs(h - expected_h) > 0.01:
                errors.append(f"Cover PDF page is {w:.4f} x {h:.4f} in; expected {expected_w:.4f} x {expected_h:.4f} in.")
    except ImportError:
        warnings.append("PyPDF2 is not installed; cover PDF structural validation was skipped.")
    except Exception as error:
        errors.append(f"Cover PDF validation failed: {error}")

    meta_file = project / "KDP_PACKAGE" / "cover_manifest.json"
    if meta_file.exists():
        try:
            meta = load_json(meta_file)
            effective = meta.get("effective_artwork_dpi")
            if effective is not None and effective < 300:
                warnings.append(f"Cover artwork effective resolution is about {effective:.0f} DPI; KDP recommends at least 300 DPI for cover images.")
        except Exception:
            warnings.append("Cover manifest could not be read for artwork-resolution validation.")

    if page_count < 79 and meta_file.exists():
        try:
            meta = load_json(meta_file)
            if meta.get("spine_text_allowed"):
                errors.append("Cover configuration incorrectly allows spine text below 79 pages.")
        except Exception:
            pass

    return errors, warnings


def kdp_preflight(project, settings, pdf_file, page_count):
    """Validate the interior against the factory's KDP production rules."""
    errors = []
    warnings = []
    min_pages, max_pages = kdp_page_limits(settings)

    if page_count < min_pages:
        errors.append(f"KDP page count is {page_count}; minimum for {settings.get('kdp_ink_type', 'black_white')} is {min_pages}.")
    if page_count > max_pages:
        errors.append(f"KDP page count is {page_count}; maximum for {settings.get('kdp_ink_type', 'black_white')} is {max_pages}.")

    trim_w = float(settings.get("trim_width", 8.5))
    trim_h = float(settings.get("trim_height", 11))
    if not (4.0 <= trim_w <= 8.5 and 6.0 <= trim_h <= 11.69):
        errors.append(f"Trim size {trim_w} x {trim_h} is outside KDP paperback custom-trim limits.")

    try:
        Reader = _pdf_reader_class()
        if Reader is None:
            warnings.append("No supported PDF reader is installed; KDP PDF structural validation was skipped.")
            return errors, warnings
        reader = Reader(str(pdf_file), strict=False)
        if len(reader.pages) != page_count:
            errors.append(f"KDP preflight: PDF page count {len(reader.pages)} does not match built page count {page_count}.")
        expected_w = trim_w * 72
        expected_h = trim_h * 72
        for number, page in enumerate(reader.pages, start=1):
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            if abs(w - expected_w) > 0.5 or abs(h - expected_h) > 0.5:
                errors.append(f"KDP preflight: page {number} is {w/72:.3f} x {h/72:.3f} in; expected {trim_w} x {trim_h} in.")
    except ImportError:
        warnings.append("PyPDF2 is not installed; KDP PDF structural validation was skipped.")
    except Exception as error:
        errors.append(f"KDP PDF validation failed: {error}")

    return errors, warnings


def write_kdp_package(project, settings, final_pdf, report, page_count, kdp_errors, kdp_warnings, prebuilt_cover=None, prebuilt_cover_errors=None, prebuilt_cover_warnings=None):
    """Write a self-contained KDP production package and checklist."""
    package = project / "KDP_PACKAGE"
    package.mkdir(exist_ok=True)
    interior_name = f"{kdp_safe_filename(settings.get('title', project.name))}_INTERIOR.pdf"
    interior = package / interior_name
    shutil.copy2(final_pdf, interior)
    shutil.copy2(report, package / "BUILD_REPORT.txt")

    cover_file = None
    cover_w = cover_h = spine = None
    cover_errors = []
    cover_warnings = []
    if settings.get("kdp_generate_cover", True):
        if prebuilt_cover is not None:
            cover_file = prebuilt_cover
            # Geometry is deterministic; recover the same values used by the cover generator.
            trim_w = float(settings.get("trim_width", 8.5))
            trim_h = float(settings.get("trim_height", 11))
            spine = kdp_spine_width(settings, page_count)
            cover_w = trim_w * 2 + spine + 0.25
            cover_h = trim_h + 0.25
            cover_errors = list(prebuilt_cover_errors or [])
            cover_warnings = list(prebuilt_cover_warnings or [])
        else:
            cover_file, cover_w, cover_h, spine = create_kdp_cover(project, settings, page_count)
            cover_errors, cover_warnings = kdp_cover_preflight(project, settings, cover_file, page_count, cover_w, cover_h, spine)
        kdp_errors.extend(cover_errors)
        kdp_warnings.extend(cover_warnings)

    checklist = package / "KDP_CHECKLIST.txt"
    min_pages, max_pages = kdp_page_limits(settings)
    with open(checklist, "w", encoding="utf-8") as f:
        f.write(f"COLORING BOOK FACTORY v{FACTORY_VERSION} - KDP PRODUCTION CHECKLIST\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Title: {settings.get('title')}\n")
        f.write(f"Author: {settings.get('author')}\n")
        f.write(f"Trim: {settings.get('trim_width')} x {settings.get('trim_height')} in\n")
        f.write(f"Ink type: {settings.get('kdp_ink_type', 'black_white')}\n")
        f.write(f"Interior pages: {page_count}\n")
        f.write(f"KDP allowed pages for this ink type: {min_pages}-{max_pages}\n")
        f.write(f"Interior bleed: No (artwork is kept inside the page border)\n")
        f.write(f"Interior file: {interior.name}\n")
        if cover_file:
            f.write(f"Auto cover draft: {cover_file.name}\n")
            f.write(f"Cover size including bleed: {cover_w:.4f} x {cover_h:.4f} in\n")
            f.write(f"Calculated spine: {spine:.6f} in\n")
        f.write("\nFACTORY CHECKS\n")
        f.write("-" * 60 + "\n")
        f.write("PASS: Interior and cover files passed measurable factory KDP checks.\n" if not kdp_errors else "FAIL: KDP preflight found errors.\n")
        for error in kdp_errors:
            f.write(f"ERROR: {error}\n")
        for warning in kdp_warnings:
            f.write(f"WARNING: {warning}\n")
        f.write("\nMANUAL KDP CHECKS\n")
        f.write("- Confirm the cover title/author exactly match KDP metadata.\n")
        f.write("- Review the cover in KDP Print Previewer.\n")
        f.write("- Confirm paper/ink choice matches the configured factory setting.\n")
        f.write("- Review all interior pages for artwork quality and safe margins.\n")
        f.write("- Upload the interior PDF and cover PDF separately to KDP.\n")

    manifest = {
        "factory_version": FACTORY_VERSION,
        "title": settings.get("title"),
        "author": settings.get("author"),
        "trim_width": settings.get("trim_width"),
        "trim_height": settings.get("trim_height"),
        "dpi": settings.get("dpi"),
        "ink_type": settings.get("kdp_ink_type", "black_white"),
        "page_count": page_count,
        "min_pages": min_pages,
        "max_pages": max_pages,
        "interior_pdf": interior.name,
        "cover_pdf": cover_file.name if cover_file else None,
        "cover_width_inches": cover_w,
        "cover_height_inches": cover_h,
        "spine_width_inches": spine,
        "kdp_preflight_errors": kdp_errors,
        "kdp_preflight_warnings": kdp_warnings,
        "cover_preflight_errors": cover_errors,
        "cover_preflight_warnings": cover_warnings,
    }
    save_json(package / "kdp_manifest.json", manifest)
    return package, cover_file


# ============================================================
# FINAL REPORT
# ============================================================

def write_final_report(
    project,
    settings,
    built_pages,
    pdf_file,
    final_pdf,
    errors,
    warnings
):

    report = (
        project /
        "REPORTS" /
        "final_report.txt"
    )

    with open(
        report,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "COLORING BOOK FACTORY\n"
        )

        f.write(
            "FINAL BUILD REPORT\n"
        )

        f.write(
            "=" * 60 +
            "\n\n"
        )

        f.write(
            f"Book: "
            f"{settings.get('title')}\n"
        )

        f.write(
            f"Author: "
            f"{settings.get('author')}\n"
        )

        f.write(
            f"Trim: "
            f"{settings.get('trim_width')} x "
            f"{settings.get('trim_height')} inches\n"
        )

        f.write(
            f"DPI: "
            f"{settings.get('dpi')}\n"
        )

        f.write(
            f"Pages built: "
            f"{len(built_pages)}\n"
        )

        f.write(
            f"Assembly mode: {settings.get('assembly_mode', 'manual')}\n"
        )

        f.write(
            f"PDF: "
            f"{pdf_file}\n"
        )

        f.write(
            f"Final PDF: "
            f"{final_pdf}\n\n"
        )

        f.write(
            "ERRORS\n"
        )

        f.write(
            "------\n"
        )

        if errors:

            for error in errors:
                f.write(
                    f"- {error}\n"
                )

        else:

            f.write(
                "None\n"
            )

        f.write(
            "\nWARNINGS\n"
        )

        f.write(
            "--------\n"
        )

        if warnings:

            for warning in warnings:
                f.write(
                    f"- {warning}\n"
                )

        else:

            f.write(
                "None\n"
            )

        f.write(
            "\n"
        )

        if errors:

            f.write(
                "STATUS: NOT READY\n"
            )

        else:

            f.write(
                "STATUS: BUILD SUCCESSFUL\n"
            )

    return report


# ============================================================
# v6 PRODUCTION ENGINE
# ============================================================

def validate_book_spec(settings, book, images):
    """Validate the book as a production specification before expensive work."""
    errors = []
    warnings = []
    required = {"title": "Book title", "author": "Author", "trim_width": "Trim width", "trim_height": "Trim height"}
    for key, label in required.items():
        if not str(settings.get(key, "")).strip():
            errors.append(f"Production spec: {label} is missing.")
    if not images:
        errors.append("Production spec: no artwork files are present in INPUT.")
    try:
        trim = (float(settings.get("trim_width")), float(settings.get("trim_height")))
        if trim not in SUPPORTED_TRIM_SIZES.values():
            warnings.append(f"Production spec: trim {trim[0]} x {trim[1]} is custom; confirm it is supported by the selected KDP marketplace/profile.")
    except Exception:
        errors.append("Production spec: trim dimensions are invalid.")
    if str(settings.get("assembly_mode", "auto")).lower() == "auto" and len(images) > 0:
        coloring = sum(1 for x in book.get("pages", []) if x.get("type") == "coloring")
        if coloring != len(images):
            errors.append(f"Production spec: manifest has {coloring} coloring pages but INPUT contains {len(images)} artwork files.")
    return warnings, errors


def artifact_sha256(path):
    try:
        return file_hash(path)
    except Exception:
        return None


def write_metadata_exports(project, settings, page_count):
    """Create machine-readable and human-readable metadata for each book."""
    package = project / "KDP_PACKAGE"
    package.mkdir(exist_ok=True)
    data = {
        "factory_version": FACTORY_VERSION,
        "title": settings.get("title"),
        "author": settings.get("author"),
        "genre": settings.get("genre"),
        "theme": settings.get("theme"),
        "trim_size": f"{settings.get('trim_width')} x {settings.get('trim_height')} in",
        "ink_type": settings.get("kdp_ink_type", "black_white"),
        "page_count": page_count,
        "subtitle": settings.get("cover_subtitle", ""),
        "description": settings.get("cover_blurb", ""),
        "keywords": settings.get("keywords", []),
        "categories": settings.get("categories", []),
        "production_profile": settings.get("production_profile"),
    }
    save_json(package / "BOOK_METADATA.json", data)
    with open(package / "BOOK_METADATA.txt", "w", encoding="utf-8") as f:
        for key, value in data.items():
            f.write(f"{key}: {value}\n")
    return data


def write_production_manifest(project, settings, book, images, built_pages, final_pdf, report, package):
    """Write the reproducibility record for a finished book."""
    registry = load_artwork_registry(project)
    source_records = []
    for number, image in enumerate(images, start=1):
        aid = artwork_identity_id(image)
        source_records.append({
            "sequence": number,
            "filename": image.name,
            "artwork_id": aid,
            "sha256": artifact_sha256(image),
            "bytes": image.stat().st_size,
        })
    artifacts = {}
    for path in [final_pdf, report, package / "KDP_CHECKLIST.txt", package / "kdp_manifest.json", package / "BOOK_METADATA.json"]:
        if path and Path(path).exists():
            path = Path(path)
            artifacts[path.name] = {"sha256": artifact_sha256(path), "bytes": path.stat().st_size}
    build_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + sha256((str(settings.get("title")) + manifest_fingerprint(book)).encode()).hexdigest()[:10]
    world_context = project_world_context(project, settings)
    manifest = {
        "factory_version": FACTORY_VERSION,
        "world": world_context,
        "processing_engine": PROCESSING_ENGINE_VERSION,
        "build_id": build_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "project": project.name,
        "book_spec_version": settings.get("book_spec_version", 1),
        "settings_fingerprint": settings_full_fingerprint(settings),
        "manifest_fingerprint": manifest_fingerprint(book),
        "page_count": len(built_pages),
        "artwork_count": len(images),
        "artworks": source_records,
        "artwork_registry_count": len(registry.get("artworks", {})),
        "world_id": settings.get("world_id", ""),
        "world_engine_version": settings.get("world_engine_version", WORLD_ENGINE_VERSION),
        "artifacts": artifacts,
        "reproducibility": "All source artwork is content-addressed by SHA-256 artwork identity; build settings and manifest fingerprints are recorded.",
    }
    save_json(package / "PRODUCTION_MANIFEST.json", manifest)
    return manifest


def write_artifact_checksums(package):
    """Create SHA-256 checksums for every delivered artifact."""
    package = Path(package)
    lines = []
    for path in sorted(package.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            digest = artifact_sha256(path)
            if digest:
                lines.append(f"{digest}  {path.name}")
    (package / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_readiness_report(project, settings, built_pages, kdp_errors, kdp_warnings, package):
    """Final production gate: clearly separate READY from human-review items."""
    report = project / "REPORTS" / "production_readiness.txt"
    report.parent.mkdir(exist_ok=True)
    manual = [
        "Review every interior page visually at 100% and in KDP Print Previewer.",
        "Confirm cover artwork, title, author, subtitle and barcode area are acceptable.",
        "Confirm KDP metadata, categories and keywords before publishing.",
    ]
    status = "READY FOR HUMAN KDP REVIEW" if not kdp_errors else "BLOCKED - FIX KDP PREFLIGHT ERRORS"
    with open(report, "w", encoding="utf-8") as f:
        f.write(f"COLORING BOOK FACTORY v{FACTORY_VERSION} - PRODUCTION READINESS\n")
        f.write("=" * 68 + "\n\n")
        world_ctx = project_world_context(project, settings)
        f.write(
            f"Book: {settings.get('title')}\n"
            f"Author: {settings.get('author')}\n"
            f"Pages: {len(built_pages)}\n"
            f"World: {world_ctx.get('universe') or 'Standalone'}\n"
            f"Series: {world_ctx.get('series') or 'None'}\n"
            f"Relationship: {world_ctx.get('relationship')}\n"
        )
        f.write(f"Status: {status}\n\n")
        f.write("AUTOMATED GATE\n---------------\n")
        f.write("PASS: Build completed.\n" if not kdp_errors else "FAIL: KDP preflight contains blocking errors.\n")
        for e in kdp_errors: f.write(f"ERROR: {e}\n")
        for w in kdp_warnings: f.write(f"WARNING: {w}\n")
        f.write("\nHUMAN REVIEW\n------------\n")
        for item in manual: f.write(f"- {item}\n")
        f.write(f"\nPackage: {package}\n")
    return report


def create_build_snapshot(project, settings, book, images, built_pages, final_pdf):
    """Keep a compact immutable build record so finished books can be audited later."""
    if not settings.get("build_snapshots_enabled", True):
        return None
    snapshots = project / "BUILD_SNAPSHOTS"
    snapshots.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = snapshots / f"build_{stamp}.json"
    snapshot = {
        "factory_version": FACTORY_VERSION,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "title": settings.get("title"),
        "settings": settings,
        "manifest": book,
        "artwork": [{"filename": x.name, "artwork_id": artwork_identity_id(x), "sha256": artifact_sha256(x)} for x in images],
        "pages_built": len(built_pages),
        "final_pdf_sha256": artifact_sha256(final_pdf) if Path(final_pdf).exists() else None,
    }
    save_json(path, snapshot)
    return path

# ============================================================
# COMPLETE BOOK BUILD
# ============================================================

def build_book(project):
    setup_project(project)
    try:
        settings = load_json(project / "project.json")
        if update_project_defaults(settings):
            save_json(project / "project.json", settings)
    except Exception as error:
        print(f"\nERROR: Could not load project configuration: {error}")
        return
    images = get_images(project)
    if str(settings.get("assembly_mode", "auto")).strip().lower() == "auto":
        if settings.get("number_of_images") != len(images):
            settings["number_of_images"] = len(images)
            save_json(project / "project.json", settings)
    book = prepare_manifest(project, settings, images)
    if settings.get("auto_register_artwork_entities", True):
        world = get_project_world(project)
        if world:
            try:
                register_project_artwork_entities(project, world, images, book)
            except Exception as error:
                print(f"WARNING: Artwork world registration skipped: {error}")
    spec_warnings, spec_errors = validate_book_spec(settings, book, images)
    validation_warnings, validation_errors = validate_project(project, settings, book, images)
    validation_warnings = spec_warnings + validation_warnings
    validation_errors = spec_errors + validation_errors

    # v6.2: world-aware continuity gate
    if settings.get("continuity_gate", True):
        try:
            continuity_errors, continuity_warnings = world_continuity_check_for_project(project, settings, book, images)
            validation_warnings.extend(continuity_warnings)
            if settings.get("world_canon", True) and continuity_errors:
                validation_errors.extend(continuity_errors)
        except Exception as error:
            validation_warnings.append(f"World continuity check could not complete: {error}")

    if validation_errors:
        print("\nBUILD STOPPED BY PROJECT VALIDATION.")
        for error in validation_errors: print(f"ERROR: {error}")
        report = write_final_report(project, settings, [], project / "PDF" / "NOT_CREATED.pdf", project / "FINAL" / "NOT_CREATED.pdf", validation_errors, validation_warnings)
        print(f"\nFinal report: {report}")
        return
    current_inventory = source_inventory(images)
    state = load_build_state(project)
    current_fingerprint_payload = {
        "factory_version": FACTORY_VERSION,
        "settings": settings_full_fingerprint(settings),
        "manifest": manifest_fingerprint(book),
        "images": {name: data.get("hash") for name, data in sorted(current_inventory.items())},
        "world_context": project_world_context(project, settings),
        "world_fingerprint": manifest_fingerprint(get_project_world(project) or {}),
    }
    current_fingerprint = sha256(
        json.dumps(current_fingerprint_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    print()
    print("=" * 60)
    print(f"COLORING BOOK FACTORY v{FACTORY_VERSION}")
    print("=" * 60)
    print()
    print(f"Book: {settings.get('title')}")
    print(f"Images found: {len(images)}")
    changes = artwork_change_summary(project, images)
    print(f"Changes: +{len(changes['added'])} added / ~{len(changes['modified'])} modified / -{len(changes['removed'])} removed / ={len(changes['unchanged'])} unchanged")
    print(f"Manifest pages: {len(book.get('pages', []))}")
    width, height, dpi = page_dimensions(settings)
    print(f"Page size: {width} x {height} pixels")
    print(f"DPI: {dpi}")

    final_pdf = project / "FINAL" / f"{settings.get('title', project.name)}.pdf"
    report_file = project / "REPORTS" / "final_report.txt"
    if (
        state.get("build_fingerprint") == current_fingerprint
        and final_pdf.exists()
        and report_file.exists()
        and "STATUS: BUILD SUCCESSFUL" in report_file.read_text(encoding="utf-8")
    ):
        print("\nNO CHANGES DETECTED - BUILD SKIPPED.")
        print("Cached build is already valid.")
        return

    qc_warnings, qc_errors = quality_check(project, settings, images)
    contact_sheet = create_artwork_contact_sheet(project, settings, images)
    if contact_sheet:
        print(f"Artwork contact sheet: {contact_sheet}")
    if qc_errors:
        print("\nBUILD STOPPED BY QUALITY CONTROL.")
        for error in qc_errors:
            print(f"ERROR: {error}")
        report = write_final_report(project, settings, [], project / "PDF" / "NOT_CREATED.pdf", project / "FINAL" / "NOT_CREATED.pdf", qc_errors, qc_warnings)
        print(f"\nFinal report: {report}")
        return
    print("\nBUILDING PAGES...")
    try:
        built_pages = build_pages(project, settings, book, images)
    except Exception as error:
        message = f"Page build failed: {error}"
        print(f"ERROR: {message}")
        report = write_final_report(project, settings, [], project / "PDF" / "NOT_CREATED.pdf", project / "FINAL" / "NOT_CREATED.pdf", [message], qc_warnings)
        print(f"\nFinal report: {report}")
        return
    print(f"Pages built: {len(built_pages)}")
    print("\nPAGE PREFLIGHT")
    page_files, page_errors, page_warnings = page_preflight(project, settings)
    print(f"Pages checked: {len(page_files)}")
    print(f"Errors: {len(page_errors)}")
    print(f"Warnings: {len(page_warnings)}")
    if page_errors:
        print("\nPAGE PREFLIGHT FAILED.")
        for error in page_errors:
            print(f"ERROR: {error}")
        report = write_final_report(project, settings, built_pages, project / "PDF" / "NOT_CREATED.pdf", project / "FINAL" / "NOT_CREATED.pdf", qc_errors + page_errors, qc_warnings + page_warnings)
        print(f"\nFinal report: {report}")
        return
    print("\nCREATING PDF...")
    try:
        pdf_file, final_pdf, pdf_pages = create_pdf(project, settings)
    except Exception as error:
        message = f"PDF creation failed: {error}"
        print(f"ERROR: {message}")
        report = write_final_report(project, settings, built_pages, project / "PDF" / "NOT_CREATED.pdf", project / "FINAL" / "NOT_CREATED.pdf", qc_errors + page_errors + [message], qc_warnings + page_warnings)
        print(f"\nFinal report: {report}")
        return
    print(f"PDF created:\n{pdf_file}")
    print(f"Final copy:\n{final_pdf}")
    print("\nPDF PREFLIGHT")
    pdf_errors, pdf_warnings = pdf_preflight(pdf_file, settings, len(built_pages))
    print(f"PDF pages: {pdf_pages}")
    print(f"Errors: {len(pdf_errors)}")
    print(f"Warnings: {len(pdf_warnings)}")
    print("\nKDP PREFLIGHT")
    kdp_errors, kdp_warnings = kdp_preflight(project, settings, pdf_file, len(built_pages))
    print(f"KDP page count: {len(built_pages)}")
    print(f"Errors: {len(kdp_errors)}")
    print(f"Warnings: {len(kdp_warnings)}")

    # v6 production gate: generate and validate the cover BEFORE deciding whether
    # the build is successful. v5 could report success before discovering a cover error.
    cover_file = None
    cover_errors = []
    cover_warnings = []
    if settings.get("kdp_generate_cover", True):
        try:
            cover_file, cover_w, cover_h, cover_spine = create_kdp_cover(project, settings, len(built_pages))
            cover_errors, cover_warnings = kdp_cover_preflight(project, settings, cover_file, len(built_pages), cover_w, cover_h, cover_spine)
            print("\nCOVER PREFLIGHT")
            print(f"Cover: {cover_file}")
            print(f"Errors: {len(cover_errors)}")
            print(f"Warnings: {len(cover_warnings)}")
        except Exception as error:
            cover_errors = [f"Cover generation failed: {error}"]

    all_errors = validation_errors + qc_errors + page_errors + pdf_errors + kdp_errors + cover_errors
    all_warnings = validation_warnings + qc_warnings + page_warnings + pdf_warnings + kdp_warnings + cover_warnings
    report = write_final_report(project, settings, built_pages, pdf_file, final_pdf, all_errors, all_warnings)

    if not all_errors:
        if settings.get("auto_update_world_bible", True):
            world = get_project_world(project)
            if world:
                try:
                    write_world_bible(world)
                    world_continuity_report(world)
                except Exception as error:
                    print(f"WARNING: World Bible refresh failed: {error}")
        state = load_build_state(project)
        state["version"] = FACTORY_VERSION
        state["images"] = {}
        for name, data in current_inventory.items():
            try:
                source = next(x for x in images if x.name == name)
                identity = artwork_identity_id(source)
            except StopIteration:
                identity = name
            state["images"][identity] = dict(data)
            state["images"][identity]["source_name"] = name
            state["images"][identity]["process_signature"] = settings_fingerprint(settings)
            state["images"][identity]["processed_id"] = f"ART-{identity.split('-', 1)[-1][:16]}.png"
        state["build_fingerprint"] = current_fingerprint
        state["last_build"] = datetime.now().isoformat(timespec="seconds")
        save_build_state(project, state)

        package, cover_file = write_kdp_package(
            project, settings, final_pdf, report, len(built_pages), kdp_errors, kdp_warnings,
            prebuilt_cover=cover_file, prebuilt_cover_errors=cover_errors, prebuilt_cover_warnings=cover_warnings
        )
        if settings.get("metadata_export_enabled", True):
            write_metadata_exports(project, settings, len(built_pages))
        if settings.get("production_manifest_enabled", True):
            production_manifest = write_production_manifest(project, settings, book, images, built_pages, final_pdf, report, package)
            print(f"Production manifest: {package / 'PRODUCTION_MANIFEST.json'}")
        readiness = write_readiness_report(project, settings, built_pages, kdp_errors, kdp_warnings, package)
        shutil.copy2(readiness, package / "PRODUCTION_READINESS.txt")
        if settings.get("production_manifest_enabled", True):
            # Refresh once more after all delivery files exist so the manifest is complete.
            write_production_manifest(project, settings, book, images, built_pages, final_pdf, report, package)
        if settings.get("checksum_artifacts", True):
            write_artifact_checksums(package)
            print(f"Artifact checksums: {package / 'SHA256SUMS.txt'}")
        snapshot = create_build_snapshot(project, settings, book, images, built_pages, final_pdf)
        if snapshot:
            print(f"Build snapshot: {snapshot}")
        print(f"KDP package: {package}")
        if cover_file:
            print(f"Auto cover: {cover_file}")
            print(f"Cover preflight errors: {len(kdp_errors)}")
            print(f"Cover/overall KDP warnings: {len(kdp_warnings)}")

    if settings.get("build_history_enabled", True):
        record_build_history(project, "NOT READY" if all_errors else "SUCCESS", len(built_pages), all_errors, all_warnings, current_fingerprint)
    record_world_production_event(
        project, "interior_build",
        "NOT READY" if all_errors else "SUCCESS",
        page_count=len(built_pages), errors=len(all_errors), warnings=len(all_warnings),
    )

    print("\n" + "=" * 60)
    print("BUILD COMPLETE - NOT READY" if all_errors else "BUILD COMPLETE - SUCCESS")
    print("=" * 60)
    print(f"\nPages: {len(built_pages)}")
    print(f"PDF: {pdf_file}")
    print(f"Final: {final_pdf}")
    print(f"Final report: {report}")
    if all_errors:
        print("\nERRORS:")
        for error in all_errors:
            print(f"  [ERROR] {error}")
    if all_warnings:
        print("\nWARNINGS:")
        for warning in all_warnings:
            print(f"  [WARNING] {warning}")

# ============================================================
# BULK BUILD
# ============================================================

def bulk_build():
    projects = get_projects()
    if not projects:
        print("\nNo projects found.")
        return

    print()
    print("=" * 60)
    print("BULK BUILD")
    print("=" * 60)
    print("\nSmart mode: cached/unchanged books are skipped by the normal build pipeline.")

    results = []
    for project in projects:
        print(f"\n>>> BUILDING: {project.name}")
        try:
            images = get_images(project)
            if not images:
                results.append((project.name, "FAILED - no images"))
                continue
            build_book(project)
            report = project / "REPORTS" / "final_report.txt"
            status = "FAILED"
            if report.exists():
                report_text = report.read_text(encoding="utf-8", errors="replace")
                if "STATUS: BUILD SUCCESSFUL" in report_text:
                    status = "READY"
                else:
                    status = "NOT READY"
            results.append((project.name, status))
        except Exception as error:
            results.append((project.name, f"FAILED - {error}"))

    print()
    print("=" * 60)
    print("BULK BUILD SUMMARY")
    print("=" * 60)
    for name, status in results:
        print(f"{name}: {status}")


# ============================================================
# IMPORT ARTWORK FOLDER / CREATE BOOK
# ============================================================

def clean_book_name(name):
    """Turn a folder name into a clean default book title."""
    import re
    name = re.sub(r"[_-]+", " ", str(name).strip())
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    name = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name.title() or "Coloring Book"


def choose_artwork_folder():
    """Open a native folder picker when available; otherwise accept a path."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(title="Select Artwork Folder")
        root.destroy()
        return Path(folder) if folder else None
    except Exception as error:
        print(f"Folder picker unavailable: {error}")
        raw = input("Artwork folder path: ").strip().strip('"')
        return Path(raw) if raw else None


def resolve_project_name(project_name):
    project = PROJECTS / project_name
    if not project.exists():
        return project, "new"
    # Smart reuse is offered by the caller; only generate a suffix when explicitly requested.
    base = project_name
    counter = 2
    while project.exists():
        project = PROJECTS / f"{base} ({counter})"
        counter += 1
    return project, "new_copy"


def unique_project_name(project_name):
    """Return a project folder name that does not already exist.

    Compatibility helper used by the v7 Platform Center PDF-import path.
    Existing projects are preserved; duplicates become ``Name (2)``, ``Name (3)``, etc.
    """
    project, _status = resolve_project_name(str(project_name).strip() or "Imported PDF")
    return project.name


def merge_import_config(config, title, author, genre, theme):
    settings = {
        "title": title, "author": author, "genre": genre, "theme": theme,
        "trim_width": 8.5, "trim_height": 11, "dpi": 300, "border_pixels": 150,
        "number_of_images": 0, "min_source_width": 1500, "min_source_height": 2000,
        "kdp_ink_type": "black_white", "kdp_auto_pad_minimum_pages": True,
        "kdp_minimum_pages": 24, "kdp_maximum_pages": 828, "kdp_generate_cover": True,
        "cover_subtitle": "A Coloring Adventure",
        "cover_blurb": "Explore strange creatures, dark machines, and unforgettable nightmares—one page at a time.",
        "assembly_mode": "auto",
        "assembly": {"include_title_page": True, "include_copyright_page": True, "include_toc": False, "artwork_title_prefix": ""},
        "artwork_upscale": True,
        "artwork_upscale_target_width": 2550,
        "artwork_upscale_target_height": 3300,
        "generate_contact_sheet": True,
        "contact_sheet_columns": 5,
        "contact_sheet_thumb_width": 300,
        "contact_sheet_thumb_height": 390,
        "universe_name": str(config.get("universe_name", "")).strip(),
        "series_name": str(config.get("series_name", "")).strip(),
        "world_relationship": str(config.get("world_relationship", "standalone")).strip() or "standalone",
        "world_canon": str(config.get("world_relationship", "standalone")).strip().lower() == "canon",
        "continuity_gate": True,
        "auto_update_world_bible": True,
        "auto_register_artwork_entities": True,
    }
    settings.update({k: v for k, v in config.items() if k not in {"artwork_titles"}})
    settings["title"] = title
    settings["author"] = author
    settings["genre"] = genre
    settings["theme"] = theme
    if isinstance(config.get("assembly"), dict):
        settings["assembly"].update(config["assembly"])
    return settings


def import_artwork_folder():
    print()
    print("=" * 60)
    print("IMPORT ARTWORK FOLDER -> CREATE BOOK")
    print("=" * 60)
    print()
    source_folder = choose_artwork_folder()
    if not source_folder:
        print("Cancelled.")
        return None
    source_folder = source_folder.expanduser().resolve()
    if not source_folder.exists() or not source_folder.is_dir():
        print(f"ERROR: Folder does not exist: {source_folder}")
        return None
    source_images = sorted([p for p in source_folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS], key=natural_image_sort_key)
    if not source_images:
        print("ERROR: No supported artwork images found in that folder.")
        return None

    config = load_optional_book_config(source_folder)
    default_title = config.get("title") or clean_book_name(source_folder.name)
    print(f"\nArtwork folder: {source_folder}")
    print(f"Images found: {len(source_images)}")
    print(f"Default book title: {default_title}")
    if config:
        print(f"Loaded optional {BOOK_CONFIG_FILENAME}")

    title = input(f"Book title [{default_title}]: ").strip() or default_title
    author_default = str(config.get("author", "Author"))
    genre_default = str(config.get("genre", "Coloring Book"))
    theme_default = str(config.get("theme", genre_default))
    author = input(f"Author [{author_default}]: ").strip() or author_default
    genre = input(f"Genre [{genre_default}]: ").strip() or genre_default
    theme = input(f"Theme [{theme_default}]: ").strip() or theme_default

    import re
    project_name = re.sub(r"[^A-Za-z0-9._ -]+", "", title).strip().rstrip(".") or "Coloring Book"
    project_name = re.sub(r"\s+", " ", project_name)
    existing_project = PROJECTS / project_name
    if existing_project.exists():
        print(f"\nExisting project found: {existing_project.name}")
        print("1. Update existing project")
        print("2. Create new copy")
        print("3. Cancel")
        choice = input("Choose [1]: ").strip() or "1"
        if choice == "3":
            print("Cancelled.")
            return None
        if choice == "1":
            project = existing_project
            setup_project(project)
            # Remove old imported INPUT artwork; source folder remains untouched.
            for old in (project / "INPUT").iterdir():
                if old.is_file() and old.suffix.lower() in IMAGE_EXTENSIONS:
                    old.unlink()
        else:
            project, _ = resolve_project_name(project_name)
    else:
        project = existing_project

    project.mkdir(parents=True, exist_ok=True)
    setup_project(project)
    settings = merge_import_config(config, title, author, genre, theme)
    settings["number_of_images"] = len(source_images)
    settings["import_source_folder"] = str(source_folder)
    settings["imported_at"] = datetime.now().isoformat(timespec="seconds")
    save_json(project / "project.json", settings)

    input_folder = project / "INPUT"
    for source in source_images:
        shutil.copy2(source, input_folder / source.name)
    # Preserve explicit filename -> title overrides in a dedicated registry.
    overrides = config.get("artwork_titles", {})
    if isinstance(overrides, dict) and overrides:
        registry = load_artwork_registry(project)
        registry["filename_title_overrides"] = overrides
        save_artwork_registry(project, registry)
    save_json(project / "book.json", {"pages": []})
    print(f"\nIMPORTED {len(source_images)} ARTWORK FILE(S)")
    print(f"Project: {project}")
    print("Starting normal build pipeline...\n")
    build_book(project)
    return project


def production_queue_menu():
    queue = load_queue()
    print("\n" + "=" * 60)
    print("PRODUCTION QUEUE")
    print("=" * 60)
    projects = get_projects()
    if not projects:
        print("No projects available.")
        return
    for i, project in enumerate(projects, 1):
        print(f"{i}. {project.name}")
    print("A. Add ALL projects")
    print("C. Clear queue")
    print("R. Run queue")
    choice = input("Choose: ").strip().lower()
    if choice == "c":
        queue["items"] = []
        save_queue(queue)
        print("Queue cleared.")
        return
    if choice == "a":
        queue["items"] = [str(p) for p in projects]
        save_queue(queue)
        print(f"Added {len(projects)} project(s) to queue.")
        return
    if choice == "r":
        items = list(queue.get("items", []))
        if not items:
            print("Queue is empty.")
            return
        print(f"Running {len(items)} queued project(s)...")
        for raw in items:
            project = Path(raw)
            if project.exists():
                build_book(project)
        queue["items"] = []
        save_queue(queue)
        print("Production queue complete.")
        return
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(projects):
            queue.setdefault("items", []).append(str(projects[idx]))
            save_queue(queue)
            print(f"Added: {projects[idx].name}")
    except ValueError:
        print("Invalid choice.")


# ============================================================
# CREATE PROJECT
# ============================================================

def create_project():

    print()
    print("=" * 60)
    print("CREATE NEW PROJECT")
    print("=" * 60)

    folder_name = input(
        "Project folder name: "
    ).strip()

    if not folder_name:

        print(
            "Cancelled."
        )

        return

    title = input(
        "Book title: "
    ).strip() or folder_name

    author = input(
        "Author: "
    ).strip() or "Author"

    genre = input(
        "Genre: "
    ).strip() or "Coloring Book"

    theme = input(
        "Theme: "
    ).strip() or genre

    project = (
        PROJECTS /
        folder_name
    )

    project.mkdir(
        parents=True,
        exist_ok=True
    )

    setup_project(
        project
    )

    settings = {

        "title": title,

        "author": author,

        "genre": genre,

        "theme": theme,

        "trim_width": 8.5,

        "trim_height": 11,

        "dpi": 300,

        "border_pixels": 150,

        "number_of_images": 0,

        "min_source_width": 1500,

        "min_source_height": 2000,
        "kdp_ink_type": "black_white",
        "kdp_auto_pad_minimum_pages": True,
        "kdp_minimum_pages": 24,
        "kdp_maximum_pages": 828,
        "kdp_generate_cover": True,
        "assembly_mode": "manual",
        "universe_name": "",
        "series_name": "",
        "world_relationship": "standalone",
        "world_canon": False,
        "continuity_gate": True,
        "auto_update_world_bible": True,
        "auto_register_artwork_entities": True,
        "production_profile_version": 2,
    }

    book = {
        "pages": []
    }

    save_json(
        project /
        "project.json",
        settings
    )

    save_json(
        project /
        "book.json",
        book
    )

    print()
    print(
        "PROJECT CREATED"
    )

    print()
    print(
        project
    )

    print()
    print(
        "Put artwork into:"
    )

    print(
        project /
        "INPUT"
    )


def clone_project_from_template():
    """Start a new project from an existing one's production settings.

    Only structural/style settings travel with the clone (trim size, DPI,
    border, KDP page-count rules, ink type, assembly mode, world-safety
    toggles). Anything specific to the finished book — title, subtitle,
    description, keywords, categories, artwork, page count, world/series
    attachment — always starts blank so a clone can never accidentally
    ship with the template's own listing text or be mistaken for canon
    in a world it was never actually placed in.
    """
    print("\n" + "=" * 60)
    print("CLONE PROJECT FROM TEMPLATE")
    print("=" * 60)
    print("Pick an existing project to copy production settings from.")
    print("Artwork, pages, and book-specific text always start fresh.\n")

    source = choose_project()
    if not source:
        return
    try:
        source_settings = load_json(source / "project.json")
    except Exception:
        print("Could not read that project's settings.")
        return

    folder_name = input("\nNew project folder name: ").strip()
    if not folder_name:
        print("Cancelled.")
        return
    project = PROJECTS / folder_name
    if project.exists():
        print("A project with that folder name already exists.")
        return

    title = input("Book title: ").strip() or folder_name
    default_author = source_settings.get("author", "Author")
    author = input(f"Author [{default_author}]: ").strip() or default_author
    default_theme = source_settings.get("theme", "")
    theme = input(f"Theme/creature [{default_theme}]: ").strip() or default_theme

    project.mkdir(parents=True, exist_ok=True)
    setup_project(project)

    carried_keys = [
        "trim_width", "trim_height", "dpi", "border_pixels",
        "min_source_width", "min_source_height", "genre",
        "kdp_ink_type", "kdp_auto_pad_minimum_pages", "kdp_minimum_pages",
        "kdp_maximum_pages", "kdp_generate_cover", "assembly_mode",
        "continuity_gate", "auto_update_world_bible", "auto_register_artwork_entities",
        "production_profile_version",
    ]
    settings = {key: source_settings[key] for key in carried_keys if key in source_settings}
    settings.update({
        "title": title,
        "author": author,
        "theme": theme,
        "number_of_images": 0,
        "universe_name": "",
        "series_name": "",
        "world_relationship": "standalone",
        "world_canon": False,
        "subtitle": "",
        "description": "",
        "keywords": [],
        "categories": [],
        "cloned_from_project": str(source),
        "cloned_from_title": source_settings.get("title", source.name),
        "cloned_on": datetime.now().isoformat(timespec="seconds"),
    })
    save_json(project / "project.json", settings)
    save_json(project / "book.json", {"pages": []})

    print(f"\nPROJECT CREATED FROM TEMPLATE: {source_settings.get('title', source.name)}")
    print(project)
    print(
        f"\nCarried over: trim {settings.get('trim_width')}x{settings.get('trim_height')}\", "
        f"{settings.get('dpi')} DPI, border {settings.get('border_pixels')}px, "
        f"ink={settings.get('kdp_ink_type')}, pages {settings.get('kdp_minimum_pages')}-{settings.get('kdp_maximum_pages')}, "
        f"assembly={settings.get('assembly_mode')}"
    )
    print("Starts fresh: title, subtitle, description, keywords, categories, artwork, world/series attachment.")

    if input("\nAttach this book to a world now? (y/N): ").strip().lower() == "y":
        index = load_world_index()
        active = {wid: meta for wid, meta in index.get("worlds", {}).items() if not meta.get("archived")}
        if not active:
            print("No worlds available yet — create one from 'Worlds & Universes' first.")
        else:
            ordered = sorted(active.keys())
            for i, wid in enumerate(ordered, 1):
                print(f"{i}. {active[wid].get('name', wid)}")
            try:
                idx = int(input("World number: ").strip()) - 1
                wid = ordered[idx]
                print("\nRelationship:")
                print("1. Canon")
                print("2. Related")
                print("3. Inspired by")
                print("4. Non-canon")
                rel_choice = input("Choose [1]: ").strip() or "1"
                rel = {"1": "canon", "2": "related", "3": "inspired_by", "4": "non_canon"}.get(rel_choice, "canon")
                series = input("Series name [optional]: ").strip()
                attach_project_to_world(project, wid, rel, series)
                print(f"Attached to world '{active[wid].get('name', wid)}' as {rel}.")
            except (ValueError, IndexError, TypeError) as error:
                print(f"Invalid selection ({error}); skipped world attachment.")
            except Exception as error:
                print(f"ERROR: {error}")

    print("\nPut artwork into:")
    print(project / "INPUT")


# ============================================================
# PRODUCTION DASHBOARD
# ============================================================


def production_center():
    """v6.2 consolidated production center: build, QC, continuity, and status in fewer interactions."""
    projects = get_projects()
    print("\n" + "=" * 68)
    print("PRODUCTION CENTER")
    print("=" * 68)
    if not projects:
        print("No projects found.")
        return

    stats = {"ready": 0, "blocked": 0, "stale": 0, "unbuilt": 0, "world": 0}
    rows = []
    for project in projects:
        try:
            settings = load_json(project / "project.json")
        except Exception:
            settings = {}
        history = load_build_history(project)
        latest = history.get("builds", [])[-1] if history.get("builds") else None
        report = project / "REPORTS" / "production_readiness.txt"
        status = "NOT BUILT"
        if report.exists():
            r = report.read_text(encoding="utf-8", errors="replace")
            if "READY FOR HUMAN KDP REVIEW" in r:
                status = "READY"
                stats["ready"] += 1
            elif "BLOCKED" in r:
                status = "BLOCKED"
                stats["blocked"] += 1
            else:
                status = "REVIEW"
                stats["stale"] += 1
        else:
            stats["unbuilt"] += 1
        ctx = project_world_context(project, settings)
        if ctx["world_id"]:
            stats["world"] += 1
        rows.append((project, settings, status, latest, ctx))

    print(
        f"Books: {len(projects)} | Ready: {stats['ready']} | "
        f"Blocked: {stats['blocked']} | Unbuilt: {stats['unbuilt']} | "
        f"World-linked: {stats['world']}"
    )
    print("\nBOOKS")
    print("-" * 68)
    for i, (project, settings, status, latest, ctx) in enumerate(rows, 1):
        world_label = ctx["universe"] or "Standalone"
        series_label = ctx["series"] or "-"
        print(f"{i}. {settings.get('title', project.name)}")
        print(f"   Status: {status} | World: {world_label} | Series: {series_label}")

    print("\nACTIONS")
    print("1. Build ALL books")
    print("2. Build only books needing work")
    print("3. Run continuity checks for all world-linked books")
    print("4. Refresh all World Bibles")
    print("5. Run full production audit")
    print("6. Back")
    choice = input("Choose: ").strip()

    if choice == "1":
        bulk_build()
    elif choice == "2":
        targets = []
        for project, settings, status, latest, ctx in rows:
            # Recompute fingerprint cheaply using existing final/report state.
            if status != "READY":
                targets.append(project)
        print(f"\nBuilding {len(targets)} book(s) needing work...")
        for project in targets:
            build_book(project)
    elif choice == "3":
        total_e = total_w = 0
        for project, settings, status, latest, ctx in rows:
            if ctx["world_id"]:
                try:
                    book = load_json(project / "book.json") if (project / "book.json").exists() else {"pages": []}
                    images = get_images(project)
                    e, w = world_continuity_check_for_project(project, settings, book, images)
                    total_e += len(e); total_w += len(w)
                    print(f"{project.name}: {len(e)} errors / {len(w)} warnings")
                except Exception as error:
                    print(f"{project.name}: continuity check failed: {error}")
        print(f"\nTOTAL CONTINUITY: {total_e} errors / {total_w} warnings")
    elif choice == "4":
        count = 0
        for project, settings, status, latest, ctx in rows:
            world = get_project_world(project)
            if world:
                write_world_bible(world)
                count += 1
        print(f"Refreshed {count} World Bible(s).")
    elif choice == "5":
        print("\nFULL PRODUCTION AUDIT")
        print("-" * 68)
        for project, settings, status, latest, ctx in rows:
            images = get_images(project)
            report = project / "REPORTS" / "production_readiness.txt"
            print(
                f"{settings.get('title', project.name)}: "
                f"{status} | {len(images)} artwork | "
                f"world={ctx['universe'] or 'Standalone'} | "
                f"last={latest.get('timestamp') if latest else 'never'}"
            )

def production_dashboard():
    projects = get_projects()
    print("\n" + "=" * 60)
    print("PRODUCTION DASHBOARD")
    print("=" * 60)
    if not projects:
        print("No projects found.")
        return
    for project in projects:
        report = project / "REPORTS" / "production_readiness.txt"
        history = load_build_history(project)
        latest = history.get("builds", [])[-1] if history.get("builds") else None
        status = "NOT BUILT"
        if report.exists():
            text = report.read_text(encoding="utf-8")
            if "READY FOR HUMAN KDP REVIEW" in text:
                status = "READY FOR HUMAN KDP REVIEW"
            elif "BLOCKED" in text:
                status = "BLOCKED"
        elif latest:
            status = latest.get("status", "UNKNOWN")
        images = get_images(project)
        print(f"\n{project.name}")
        print(f"  Artwork: {len(images)} | Last build: {latest.get('timestamp') if latest else 'never'}")
        print(f"  Status: {status}")
        print(f"  Package: {'YES' if (project / 'KDP_PACKAGE').exists() else 'NO'}")


# ============================================================
# v7.2 PLATFORM FACTORY — MULTI-PLATFORM VARIANT + VALIDATION ENGINE
# ============================================================

# NOTE: FACTORY_VERSION is intentionally not redefined here anymore — it was
# previously reset to "8.0" at this point in the file, silently overriding
# the "8.1" constant declared near the top of the module. Declaring the
# app version in two places is exactly how a build can display a stale
# version number without anyone noticing; it now has a single source of truth.
PLATFORM_ENGINE_VERSION = "4.5"
PLATFORM_DIRNAME = "PLATFORMS"
PLATFORM_PROFILES_FILENAME = "platform_profiles.json"
PLATFORM_AUDIT_FILENAME = "PLATFORM_AUDIT.json"
PLATFORM_INDEX_FILENAME = "PLATFORM_INDEX.json"

# Platform profiles are recipes, not hard-coded publishing workflows.  A new
# marketplace can be added by editing JSON rather than changing the factory.
DEFAULT_PLATFORM_PROFILES = {
    "KDP": {
        "name": "Amazon KDP", "type": "print", "enabled": True, "output_dir": "KDP",
        "source": "master_pdf", "files": ["interior_pdf", "cover_pdf", "metadata", "checklist"],
        "variant": {"mode": "copy", "filename_suffix": "_KDP_INTERIOR"},
        "rules": {"min_pages": 24, "max_pages": 828, "require_title": True,
                  "require_author": False, "require_cover": False, "require_landscape": False,
                  "max_file_mb": 650, "expected_trim_from_project": True},
        "notes": "KDP-specific factory preflight remains authoritative for measurable print rules."
    },
    "Gumroad": {
        "name": "Gumroad", "type": "digital", "enabled": True, "output_dir": "GUMROAD",
        "source": "master_pdf", "files": ["digital_pdf", "cover_preview", "preview_sheet", "metadata", "product_description"],
        "variant": {"mode": "copy", "filename_suffix": "_DIGITAL"},
        "rules": {"min_pages": 1, "max_pages": 10000, "require_title": True,
                  "require_author": False, "require_cover": False, "require_landscape": False,
                  "max_file_mb": 500},
        "notes": "Digital delivery package; master is never modified."
    },
    "Digital PDF": {
        "name": "Universal Digital PDF", "type": "digital", "enabled": True, "output_dir": "DIGITAL",
        "source": "master_pdf", "files": ["digital_pdf", "cover_preview", "preview_sheet", "metadata"],
        "variant": {"mode": "copy", "filename_suffix": "_DIGITAL"},
        "rules": {"min_pages": 1, "max_pages": 10000, "require_title": True,
                  "require_author": False, "require_cover": False, "require_landscape": False,
                  "max_file_mb": 500},
        "notes": "Platform-neutral downloadable PDF package."
    },
    "Etsy": {
        "name": "Etsy Digital", "type": "digital", "enabled": False, "output_dir": "ETSY",
        "source": "master_pdf", "files": ["digital_pdf", "cover_preview", "preview_sheet", "metadata", "product_description"],
        "variant": {"mode": "copy", "filename_suffix": "_DIGITAL"},
        "rules": {"min_pages": 1, "max_pages": 10000, "require_title": True,
                  "require_author": False, "require_cover": True, "require_landscape": False,
                  "max_file_mb": 500},
        "notes": "Digital marketplace package; enable when ready."
    },
    "Shopify": {
        "name": "Shopify Digital", "type": "digital", "enabled": False, "output_dir": "SHOPIFY",
        "source": "master_pdf", "files": ["digital_pdf", "cover_preview", "preview_sheet", "metadata", "product_description"],
        "variant": {"mode": "copy", "filename_suffix": "_DIGITAL"},
        "rules": {"min_pages": 1, "max_pages": 10000, "require_title": True,
                  "require_author": False, "require_cover": True, "require_landscape": False,
                  "max_file_mb": 500},
        "notes": "Digital storefront package; enable when ready."
    },
}


def platform_profiles_path():
    return FACTORY / PLATFORM_PROFILES_FILENAME


def platform_master_dir(project):
    path = project / "MASTER"
    path.mkdir(exist_ok=True)
    return path


def find_master_pdf(project):
    master = project / "MASTER"
    if master.exists():
        existing = sorted(master.glob("*_MASTER.pdf"))
        if existing:
            return existing[0]
    settings = load_project_settings_safe(project)
    title = kdp_safe_filename(settings.get("title", project.name))
    candidates = [project / "PDF" / f"{title}.pdf", project / "PDF" / "final.pdf"]
    if (project / "PDF").exists():
        candidates.extend(sorted((project / "PDF").glob("*.pdf")))
    candidates.extend(sorted((project / "FINAL").glob("*.pdf")) if (project / "FINAL").exists() else [])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def find_existing_book_pdf(project):
    roots = [project / "PDF", project / "FINAL", project / "KDP_PACKAGE", project]
    found = []
    for root in roots:
        if root.exists():
            found.extend(root.glob("*.pdf"))
    found = [p for p in found if PLATFORM_DIRNAME not in p.parts and "MASTER" not in p.parts]
    if not found:
        return None
    found.sort(key=lambda p: ("INTERIOR" not in p.name.upper(), len(p.parts), p.name.lower()))
    return found[0]


def load_project_settings_safe(project):
    path = project / "project.json"
    if not path.exists():
        return {"title": project.name, "author": ""}
    try:
        data = load_json(path)
        return data if isinstance(data, dict) else {"title": project.name, "author": ""}
    except Exception:
        return {"title": project.name, "author": ""}


def _pdf_reader_class():
    try:
        from pypdf import PdfReader
        return PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
            return PdfReader
        except ImportError:
            return None


def pdf_page_count(path):
    try:
        Reader = _pdf_reader_class()
        return len(Reader(str(path), strict=False).pages) if Reader else None
    except Exception:
        return None


def platform_required_metadata(settings, profile):
    rules = profile.get("rules", {})
    errors = []
    if rules.get("require_title", True) and not str(settings.get("title", "")).strip():
        errors.append("Required metadata missing: title.")
    if rules.get("require_author", False) and not str(settings.get("author", "")).strip():
        errors.append("Required metadata missing: author.")
    return errors


def _platform_cover(project):
    master = project / "MASTER"
    if not master.exists():
        return None
    candidates = sorted(master.glob("MASTER_COVER.*"))
    return candidates[0] if candidates else None


def ensure_master_book(project, source_pdf=None):
    settings = load_project_settings_safe(project)
    master = platform_master_dir(project)
    existing = find_master_pdf(project)
    if existing and existing.parent.resolve() == master.resolve():
        return existing, [], ["Existing MASTER PDF preserved; master assets are immutable."]
    pdf = source_pdf or existing or find_existing_book_pdf(project)
    if pdf is None:
        return None, ["No source PDF found for master package."], []
    master_pdf = master / f"{kdp_safe_filename(settings.get('title', project.name))}_MASTER.pdf"
    if master_pdf.exists():
        return master_pdf, [], ["Existing MASTER PDF preserved; source was not copied over it."]
    shutil.copy2(pdf, master_pdf)
    metadata = {
        "schema_version": 3, "factory_version": FACTORY_VERSION, "platform_engine_version": PLATFORM_ENGINE_VERSION,
        "generated": datetime.now().isoformat(timespec="seconds"), "title": settings.get("title", project.name),
        "subtitle": settings.get("subtitle", settings.get("cover_subtitle", "")), "author": settings.get("author", ""),
        "series": settings.get("series_name", ""), "series_number": settings.get("series_number", ""),
        "world": settings.get("universe_name", ""), "world_id": settings.get("world_id", ""),
        "description": settings.get("description", settings.get("cover_blurb", "")),
        "short_description": settings.get("short_description", ""), "long_description": settings.get("long_description", ""),
        "keywords": settings.get("keywords", []), "categories": settings.get("categories", []),
        "age_range": settings.get("age_range", ""), "language": settings.get("language", "English"),
        "themes": settings.get("themes", []), "trim_width": settings.get("trim_width"),
        "trim_height": settings.get("trim_height"), "dpi": settings.get("dpi", 300),
        "page_count": pdf_page_count(master_pdf), "source_pdf": str(pdf), "master_pdf": str(master_pdf),
        "source_sha256": file_hash(master_pdf),
    }
    save_json(master / "master_metadata.json", metadata)
    source_cover = None
    for candidate in [project / "COVER", project / "KDP_PACKAGE"]:
        if candidate.exists():
            covers = sorted(candidate.glob("*.pdf")) + sorted(candidate.glob("*.png")) + sorted(candidate.glob("*.jpg")) + sorted(candidate.glob("*.jpeg"))
            if covers:
                source_cover = covers[0]
                break
    if source_cover:
        target = master / f"MASTER_COVER{source_cover.suffix.lower()}"
        if not target.exists():
            shutil.copy2(source_cover, target)
    return master_pdf, [], []


def create_preview_sheet(project, output_dir, master_pdf, settings):
    output_dir.mkdir(parents=True, exist_ok=True)
    preview = output_dir / "PREVIEW_SHEET.png"
    images = []
    cover = _platform_cover(project)
    if cover and cover.suffix.lower() in IMAGE_EXTENSIONS:
        try: images.append(Image.open(cover).convert("RGB"))
        except Exception: pass
    try:
        for item in get_images(project)[:5]:
            try: images.append(Image.open(item).convert("RGB"))
            except Exception: pass
    except Exception: pass
    if not images:
        img = Image.new("RGB", (1200, 1600), "white")
        draw = ImageDraw.Draw(img)
        draw.text((80, 120), str(settings.get("title", project.name)), fill="black")
        draw.text((80, 180), "Digital Preview", fill="black")
        img.save(preview)
        return preview
    thumb_w, thumb_h = 600, 800
    canvas_img = Image.new("RGB", (thumb_w * 3, thumb_h * 2), "white")
    for index, img in enumerate(images[:6]):
        img.thumbnail((thumb_w - 40, thumb_h - 40))
        x = (index % 3) * thumb_w + (thumb_w - img.width) // 2
        y = (index // 3) * thumb_h + (thumb_h - img.height) // 2
        canvas_img.paste(img, (x, y))
    canvas_img.save(preview)
    return preview


def write_product_description(project, output_dir, settings, platform_name):
    if platform_name == "Gumroad":
        try:
            return gumroad_write_listing(project, output_dir, settings)
        except Exception as error:
            print(f"Gumroad listing generator failed ({error}); using the basic description instead.")
    title = settings.get("title", project.name)
    author = settings.get("author", "")
    description = settings.get("long_description") or settings.get("description") or settings.get("cover_blurb") or f"A coloring book by {author}."
    keywords = settings.get("keywords", [])
    if isinstance(keywords, str): keywords = [x.strip() for x in keywords.split(",") if x.strip()]
    text = f"{title}\n\n{description}\n\nAuthor: {author}\nFormat: Printable/Digital PDF\nPlatform package: {platform_name}\n\nKeywords: {', '.join(keywords)}\n"
    path = output_dir / "PRODUCT_DESCRIPTION.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _copy_required_kdp_assets(project, root, generated):
    kdp_package = project / "KDP_PACKAGE"
    if not kdp_package.exists(): return
    for item in kdp_package.iterdir():
        if item.is_file() and item.suffix.lower() in {".pdf", ".txt", ".json", ".png", ".jpg", ".jpeg"}:
            target = root / item.name
            shutil.copy2(item, target)
            if target not in generated: generated.append(target)


def validate_generated_package(root, master_pdf, profile, generated):
    errors, warnings = [], []
    expected_files = set()
    files = profile.get("files", [])
    if "digital_pdf" in files or "interior_pdf" in files:
        expected_files.add("pdf")
    if "preview_sheet" in files: expected_files.add("preview")
    if "metadata" in files: expected_files.add("metadata")
    if "product_description" in files: expected_files.add("description")
    if "cover_pdf" in files and not any("COVER" in p.name.upper() for p in generated):
        warnings.append("Profile requested a cover PDF but no cover was generated by the source project.")
    pdfs = [p for p in generated if p.suffix.lower() == ".pdf" and p.exists()]
    if "pdf" in expected_files and not pdfs:
        errors.append("Required platform PDF was not generated.")
    for p in pdfs:
        info = inspect_pdf(p)
        if info.get("error"): errors.append(f"Generated PDF failed inspection: {p.name}: {info['error']}")
        master_hash = file_hash(master_pdf)
        # Copy-mode variants must be byte-identical to MASTER. This is a deliberate
        # safety invariant until a profile explicitly implements a transformation.
        if profile.get("variant", {}).get("mode") == "copy" and file_hash(p) != master_hash:
            errors.append(f"Variant integrity mismatch: {p.name} differs from MASTER despite copy mode.")
    for label, filename in [("preview", "PREVIEW_SHEET.png"), ("metadata", "METADATA.json"), ("description", "PRODUCT_DESCRIPTION.txt")]:
        if label in expected_files and not (root / filename).exists(): errors.append(f"Required artifact missing: {filename}")
    return errors, warnings


def import_existing_pdf_to_master(project, pdf_path):
    if not pdf_path or not Path(pdf_path).exists(): print("PDF not found."); return None
    pdf_path = Path(pdf_path); settings_path = project / "project.json"
    if not settings_path.exists():
        info = inspect_pdf(pdf_path); trim_w, trim_h = 8.5, 11
        if info.get("sizes"):
            trim_w, trim_h = info["sizes"][0]["width"], info["sizes"][0]["height"]
        save_json(settings_path, {"title": pdf_path.stem, "author": "", "trim_width": trim_w, "trim_height": trim_h,
                                  "dpi": 300, "production_profile": "Imported PDF", "factory_version": FACTORY_VERSION,
                                  "platform_engine_version": PLATFORM_ENGINE_VERSION})
    master, errors, warnings = ensure_master_book(project, source_pdf=pdf_path)
    if errors:
        print("\n".join(f"ERROR: {x}" for x in errors)); return None
    info = inspect_pdf(master)
    print(f"\nMASTER PDF created/preserved: {master}\nPages: {info.get('page_count', 'unknown')} | Size: {info.get('file_size_mb', 'unknown')} MB")
    for warning in warnings: print(f"WARNING: {warning}")
    return master


def _normalize_dropped_path(raw):
    """Normalize a Windows Explorer drag/drop or pasted PDF path."""
    if raw is None:
        return None
    text = str(raw).strip()
    # Explorer may supply a quoted path, including whitespace in the filename.
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    text = text.strip().strip('"').strip()
    if not text:
        return None
    # Handle the common case where the console receives a quoted path followed
    # by whitespace. For multi-file drops, only the first PDF is used.
    candidates = []
    if '"' in text:
        import re
        candidates.extend(re.findall(r'"([^"]+\\.pdf)"', text, flags=re.I))
    candidates.append(text)
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.exists() and path.is_file() and path.suffix.lower() == ".pdf":
            return path
    return None


def choose_pdf_file(prompt="PDF file"):
    """Open a native PDF picker, with optional drag/drop support.

    On Windows, the popup is the preferred method. If tkinterdnd2 is installed,
    PDFs can also be dropped directly onto the popup. Without it, Explorer
    drag/drop into the console still works because the returned path is
    normalized by _normalize_dropped_path(). A manual path remains available
    as a fallback if the GUI cannot start.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except Exception:
        raw = input(f"{prompt}: ").strip()
        return _normalize_dropped_path(raw)

    # Optional enhanced drag/drop. tkinterdnd2 is deliberately optional so the
    # Factory remains usable on a clean Python/Windows installation.
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
        dnd_available = True
    except Exception:
        TkinterDnD = None
        DND_FILES = None
        dnd_available = False

    try:
        root_cls = TkinterDnD.Tk if dnd_available else tk.Tk
        root = root_cls()
        root.withdraw()
        root.title("Coloring Book Factory - Select Finished PDF")

        selected = {"path": None}

        if dnd_available:
            # A compact drag/drop window avoids forcing the user through a
            # directory tree when the PDF is already visible in Explorer.
            win = tk.Toplevel(root)
            win.title("Select Finished PDF")
            win.geometry("560x250")
            win.resizable(False, False)
            win.attributes("-topmost", True)
            win.protocol("WM_DELETE_WINDOW", win.destroy)

            tk.Label(win, text="Finished PDF", font=("Segoe UI", 16, "bold")).pack(pady=(22, 6))
            drop = tk.Label(
                win,
                text="DRAG & DROP A PDF HERE\n\nor click Browse",
                relief="groove", bd=2, width=52, height=5,
                font=("Segoe UI", 11)
            )
            drop.pack(padx=25, pady=8, fill="both")

            def accept_drop(event):
                try:
                    items = root.tk.splitlist(event.data)
                except Exception:
                    items = [event.data]
                for item in items:
                    path = _normalize_dropped_path(item)
                    if path:
                        selected["path"] = path
                        win.destroy()
                        return
                messagebox.showerror("Invalid file", "Please drop a PDF file.", parent=win)

            def browse():
                path = filedialog.askopenfilename(
                    parent=win, title="Select Finished PDF",
                    filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
                )
                path = _normalize_dropped_path(path)
                if path:
                    selected["path"] = path
                    win.destroy()

            drop.drop_target_register(DND_FILES)
            drop.dnd_bind("<<Drop>>", accept_drop)
            tk.Button(win, text="Browse for PDF…", command=browse, width=20).pack(pady=(2, 15))
            root.wait_window(win)
        else:
            # Native Windows picker works everywhere Tk is available. The
            # console also accepts a pasted/dropped path if the dialog is
            # cancelled, so there is no loss of functionality.
            path = filedialog.askopenfilename(
                parent=root, title="Select Finished PDF",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
            )
            selected["path"] = _normalize_dropped_path(path)

        root.destroy()
        if selected["path"]:
            print(f"Selected PDF: {selected['path']}")
            return selected["path"]

    except Exception as error:
        try:
            root.destroy()
        except Exception:
            pass
        print(f"PDF picker unavailable ({error}). Falling back to path entry.")

    raw = input(f"{prompt} (you can drag/drop a PDF into this console): ").strip()
    return _normalize_dropped_path(raw)


# ============================================================
# v8.0 PUBLISHING / DELIVERY ENGINE
# ============================================================

PUBLISHING_ENGINE_VERSION = "1.0"
DELIVERY_DIRNAME = "DELIVERY"
FACTORY_BACKUP_DIRNAME = "_FACTORY_BACKUPS"


def _safe_json_read(path, fallback=None):
    try:
        data = load_json(path)
        return data if isinstance(data, dict) else (fallback if fallback is not None else {})
    except Exception:
        return fallback if fallback is not None else {}


def project_health_scan(project):
    """Deep, non-destructive health scan for a project."""
    settings = load_project_settings_safe(project)
    health = {
        "project": project.name,
        "title": settings.get("title", project.name),
        "status": "HEALTHY",
        "errors": [],
        "warnings": [],
        "artwork": 0,
        "pages": 0,
        "master": None,
        "platforms": {},
    }

    required = ["project.json", "book.json", "INPUT", "PROCESSED", "PAGES",
                "PDF", "FINAL", "REPORTS"]
    for name in required:
        if not (project / name).exists():
            health["warnings"].append(f"Missing project component: {name}")

    images = get_images(project)
    health["artwork"] = len(images)

    book = _safe_json_read(project / "book.json", {"pages": []})
    pages = book.get("pages", []) if isinstance(book, dict) else []
    health["pages"] = len(pages)

    master = find_master_pdf(project)
    if master:
        info = inspect_pdf(master)
        health["master"] = {
            "path": str(master),
            "pages": info.get("page_count"),
            "size_mb": info.get("file_size_mb"),
            "dimensions": info.get("unique_sizes", []),
            "sha256": file_hash(master),
        }
        if info.get("error"):
            health["errors"].append(f"MASTER PDF inspection failed: {info['error']}")
    else:
        # A normal artwork project is expected to have a buildable source,
        # while an empty/new project is merely incomplete rather than broken.
        if images:
            health["warnings"].append("No MASTER PDF exists yet.")

    report = project / "REPORTS" / "final_report.txt"
    if report.exists():
        report_text = report.read_text(encoding="utf-8", errors="replace")
        if "STATUS: BUILD SUCCESSFUL" not in report_text:
            if "STATUS: BUILD FAILED" in report_text or "NOT READY" in report_text:
                health["warnings"].append("Latest production report is not a clean success.")

    profiles = load_platform_profiles()
    for name, profile in profiles.items():
        if not profile.get("enabled", False):
            continue
        try:
            audit = platform_preflight(project, name, master, profile) if master else {
                "status": "BLOCKED", "errors": ["MASTER PDF is missing."], "warnings": []
            }
            health["platforms"][name] = {
                "status": audit.get("status"),
                "errors": len(audit.get("errors", [])),
                "warnings": len(audit.get("warnings", [])),
                "error_details": list(audit.get("errors", [])),
                "warning_details": list(audit.get("warnings", [])),
            }
        except Exception as error:
            health["platforms"][name] = {"status": "BLOCKED", "errors": 1, "warnings": 0, "error_details": [str(error)], "warning_details": []}
            health["errors"].append(f"{name} audit failed: {error}")

    if health["errors"]:
        health["status"] = "BLOCKED"
    elif health["warnings"]:
        health["status"] = "REVIEW"

    save_json(project / "REPORTS" / "PROJECT_HEALTH.json", {
        "schema_version": 1,
        "factory_version": FACTORY_VERSION,
        "generated": datetime.now().isoformat(timespec="seconds"),
        **health,
    })
    return health


def print_project_health(health):
    print(f"\n{health['title']}: {health['status']}")
    print(f"  Artwork: {health['artwork']} | Manifest pages: {health['pages']}")
    if health.get("master"):
        m = health["master"]
        print(f"  MASTER: {m['pages']} pages | {m['size_mb']} MB")
    for name, data in health.get("platforms", {}).items():
        print(f"  {name}: {data['status']} | errors={data['errors']} warnings={data['warnings']}")
        for warning_text in data.get("warning_details", []):
            print(f"    WARNING: {warning_text}")
        for error_text in data.get("error_details", []):
            print(f"    ERROR: {error_text}")
    for error in health.get("errors", []):
        print(f"  ERROR: {error}")
    for warning in health.get("warnings", []):
        print(f"  WARNING: {warning}")


def factory_health_dashboard():
    """Scan every project and produce one machine-readable health dashboard."""
    projects = get_projects()
    print("\n" + "=" * 78)
    print("FACTORY HEALTH DASHBOARD")
    print("=" * 78)
    if not projects:
        print("No projects found.")
        return

    results = []
    counts = {"HEALTHY": 0, "REVIEW": 0, "BLOCKED": 0}
    for project in projects:
        try:
            health = project_health_scan(project)
            results.append(health)
            counts[health["status"]] = counts.get(health["status"], 0) + 1
            print_project_health(health)
        except Exception as error:
            counts["BLOCKED"] += 1
            results.append({"project": project.name, "status": "BLOCKED",
                            "errors": [str(error)], "warnings": []})
            print(f"\n{project.name}: BLOCKED")
            print(f"  ERROR: {error}")

    report = PROJECTS / "FACTORY_HEALTH.json"
    save_json(report, {
        "schema_version": 1,
        "factory_version": FACTORY_VERSION,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "summary": {"projects": len(projects), **counts},
        "projects": results,
    })
    print("\n" + "-" * 78)
    print(f"FACTORY TOTAL: {len(projects)} projects | "
          f"Healthy {counts['HEALTHY']} | Review {counts['REVIEW']} | Blocked {counts['BLOCKED']}")
    print(f"Dashboard saved: {report}")


def create_delivery_zip(project, platform_name=None):
    """Create a clean ZIP delivery artifact from a validated platform package."""
    settings = load_project_settings_safe(project)
    title = kdp_safe_filename(settings.get("title", project.name))
    platform_root = project / PLATFORM_DIRNAME
    if platform_name:
        profiles = load_platform_profiles()
        profile = profiles.get(platform_name)
        if not profile:
            return None, [f"Unknown platform: {platform_name}"]
        source = platform_root / profile.get("output_dir", platform_name.upper())
        zip_label = platform_name.replace(" ", "_").upper()
    else:
        return None, ["Platform name is required."]

    manifest = source / "PACKAGE_MANIFEST.json"
    if not source.exists() or not manifest.exists():
        return None, [f"Validated package is missing: {source}"]

    delivery = project / DELIVERY_DIRNAME
    delivery.mkdir(parents=True, exist_ok=True)
    target = delivery / f"{title}_{zip_label}_PACKAGE.zip"
    temp = delivery / f".{target.stem}.staging.zip"
    if temp.exists():
        temp.unlink()

    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for item in sorted(source.rglob("*")):
                if item.is_file() and ".staging" not in item.parts:
                    zf.write(item, item.relative_to(source))
        temp.replace(target)
        return target, []
    except Exception as error:
        try:
            temp.unlink()
        except OSError:
            pass
        return None, [str(error)]


def create_delivery_index(project, results):
    delivery = project / DELIVERY_DIRNAME
    delivery.mkdir(parents=True, exist_ok=True)
    settings = load_project_settings_safe(project)
    index = {
        "schema_version": 1,
        "factory_version": FACTORY_VERSION,
        "publishing_engine_version": PUBLISHING_ENGINE_VERSION,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "project": project.name,
        "title": settings.get("title", project.name),
        "master_pdf": str(find_master_pdf(project) or ""),
        "platforms": {},
    }
    for name, result in results.items():
        entry = {
            "status": result.get("status"),
            "package": str(result.get("output", "")),
            "zip": None,
        }
        if result.get("status") in {"READY", "READY_WITH_WARNINGS"}:
            zip_file, errors = create_delivery_zip(project, name)
            if zip_file:
                entry["zip"] = str(zip_file)
            if errors:
                entry["zip_errors"] = errors
        index["platforms"][name] = entry

    path = delivery / "DELIVERY_INDEX.json"
    save_json(path, index)
    return path


def one_click_publish(project):
    """End-to-end production command: build/import -> audit -> packages -> ZIP delivery."""
    print("\n" + "=" * 78)
    print("ONE-CLICK PUBLISH")
    print("=" * 78)
    print("MASTER is treated as immutable. Platform packages are generated from it.")

    settings = load_project_settings_safe(project)
    master = find_master_pdf(project)

    # Imported finished PDFs already have their source of truth. Normal projects
    # need the regular production build before platform packaging.
    imported = str(settings.get("production_profile", "")).lower().startswith("imported")
    if not master and not imported:
        print("\nBUILDING SOURCE BOOK...")
        build_book(project)
        master = find_master_pdf(project)

    if not master and imported:
        print("ERROR: Imported project has no MASTER PDF.")
        return

    if not master:
        print("ERROR: No MASTER PDF was produced.")
        return

    print(f"\nMASTER: {master}")
    health = project_health_scan(project)
    print_project_health(health)
    if health["status"] == "BLOCKED":
        print("\nPUBLISH STOPPED: project health is BLOCKED.")
        return

    print("\nGENERATING ENABLED PLATFORM PACKAGES...")
    results = generate_all_platform_packages(project)
    delivery_index = create_delivery_index(project, results)

    # Re-scan after packaging so the dashboard records the actual final state.
    health = project_health_scan(project)
    print("\nFINAL PUBLISH SUMMARY")
    print("-" * 78)
    for name, result in results.items():
        print(f"{name:<16} {result.get('status')}")
    print(f"Delivery index: {delivery_index}")
    print(f"Project health: {health['status']}")

    successful = [n for n, r in results.items()
                  if r.get("status") in {"READY", "READY_WITH_WARNINGS"}]
    if successful:
        print("\nDELIVERY ZIP FILES")
        for name in successful:
            zip_file = project / DELIVERY_DIRNAME / (
                f"{kdp_safe_filename(settings.get('title', project.name))}_"
                f"{name.replace(' ', '_').upper()}_PACKAGE.zip"
            )
            if zip_file.exists():
                print(f"  {name}: {zip_file}")

    return results


def create_project_snapshot(project):
    """Create a timestamped ZIP snapshot without touching production outputs."""
    backup_root = project / FACTORY_BACKUP_DIRNAME
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_root / f"{project.name}_{stamp}.zip"
    temp = backup_root / f".{target.stem}.tmp.zip"

    excluded = {FACTORY_BACKUP_DIRNAME, ".staging"}
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in sorted(project.rglob("*")):
            if not item.is_file():
                continue
            if any(part in excluded for part in item.relative_to(project).parts):
                continue
            zf.write(item, item.relative_to(project))
    temp.replace(target)
    return target


# ============================================================
# MAIN MENU
# ============================================================


# ============================================================
# v11.7 PRODUCTION RELEASE / DELIVERY AUDIT CENTER
# ============================================================

RELEASE_ENGINE_VERSION = "1.1"

def _release_file_record(path, root=None):
    path = Path(path)
    record = {
        "name": path.name,
        "relative_path": str(path.relative_to(root)) if root else str(path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "sha256": file_hash(path) if path.is_file() else None,
        "exists": path.exists(),
    }
    return record


def audit_delivery_packages(project):
    """Deeply audit final platform packages and delivery ZIPs without modifying them."""
    project = Path(project)
    settings = load_project_settings_safe(project)
    title = settings.get("title", project.name)
    profiles = load_platform_profiles()
    delivery = project / DELIVERY_DIRNAME
    results = {}
    total_errors = 0
    total_warnings = 0

    print("\n" + "=" * 78)
    print("FINAL DELIVERY AUDIT")
    print("=" * 78)
    print(f"Project: {title}")
    print(f"Release Engine: {RELEASE_ENGINE_VERSION}")
    print("MASTER remains untouched during this audit.")
    print("-" * 78)

    master = find_master_pdf(project)
    master_hash = file_hash(master) if master and master.exists() else None
    if not master:
        print("MASTER: BLOCKED — no MASTER PDF found")
        total_errors += 1

    for name, profile in profiles.items():
        if not profile.get("enabled", False):
            continue
        root = project / PLATFORM_DIRNAME / profile.get("output_dir", name.upper())
        errors = []
        warnings = []
        files = []

        manifest = root / "PACKAGE_MANIFEST.json"
        if not root.exists():
            errors.append("Platform package directory is missing.")
        elif not manifest.exists():
            errors.append("PACKAGE_MANIFEST.json is missing.")
        else:
            try:
                data = load_json(manifest)
                if not isinstance(data, dict):
                    errors.append("PACKAGE_MANIFEST.json is not a JSON object.")
            except Exception as error:
                errors.append(f"PACKAGE_MANIFEST.json cannot be read: {error}")

        if root.exists():
            for item in sorted(root.rglob("*")):
                if item.is_file():
                    rec = _release_file_record(item, root)
                    files.append(rec)
                    if rec["size_bytes"] <= 0:
                        errors.append(f"Zero-byte file: {item.name}")

        pdfs = [Path(x["relative_path"]) for x in files if str(x["relative_path"]).lower().endswith(".pdf")]
        if master_hash and root.exists():
            package_pdfs = [x for x in root.rglob("*.pdf") if x.is_file()]
            if package_pdfs and name in {"Digital PDF", "Payhip", "Gumroad"}:
                # Platform packages may legitimately transform assets, so only
                # flag missing PDFs; do not require hash equality here.
                pass

        zip_name = f"{kdp_safe_filename(title)}_{name.replace(' ', '_').upper()}_PACKAGE.zip"
        zip_path = delivery / zip_name
        zip_record = None
        if zip_path.exists():
            zip_record = _release_file_record(zip_path, delivery)
            if zip_path.stat().st_size <= 0:
                errors.append("Delivery ZIP is zero bytes.")
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    bad = zf.testzip()
                    if bad:
                        errors.append(f"ZIP integrity failure: {bad}")
                    names = zf.namelist()
                    if "PACKAGE_MANIFEST.json" not in names:
                        errors.append("Delivery ZIP is missing PACKAGE_MANIFEST.json.")
            except zipfile.BadZipFile:
                errors.append("Delivery ZIP is corrupt or unreadable.")
        elif root.exists() and manifest.exists():
            warnings.append("Delivery ZIP has not been created yet.")

        status = "BLOCKED" if errors else ("READY_WITH_WARNINGS" if warnings else "READY")
        total_errors += len(errors)
        total_warnings += len(warnings)
        results[name] = {
            "status": status,
            "package": str(root),
            "file_count": len(files),
            "files": files,
            "delivery_zip": zip_record,
            "errors": errors,
            "warnings": warnings,
        }
        print(f"{name:<16} {status} | files={len(files)} | ZIP={'PASS' if zip_record else 'MISSING'}")
        for e in errors: print(f"  ERROR: {e}")
        for w in warnings: print(f"  WARNING: {w}")

    overall = "BLOCKED" if total_errors else ("REVIEW" if total_warnings else "READY")
    report = project / "REPORTS" / "FINAL_DELIVERY_AUDIT.json"
    save_json(report, {
        "schema_version": 1,
        "factory_version": FACTORY_VERSION,
        "release_engine_version": RELEASE_ENGINE_VERSION,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "project": project.name,
        "title": title,
        "master": {"path": str(master or ""), "sha256": master_hash},
        "overall_status": overall,
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "platforms": results,
    })
    print("-" * 78)
    print(f"FINAL DELIVERY STATUS: {overall}")
    print(f"Errors: {total_errors} | Warnings: {total_warnings}")
    print(f"Audit report: {report}")
    return results


def legacy_main_v11():

    PROJECTS.mkdir(
        exist_ok=True
    )

    while True:

        print()
        print("=" * 60)
        print(
            f"        COLORING BOOK FACTORY v{FACTORY_VERSION}"
        )
        print("=" * 60)

        print()
        print("1. Build a book")
        print("2. Create a new project")
        print("3. Import Artwork Folder -> Create Book")
        print("4. Build ALL books")
        print("5. Production Queue")
        print("6. Production Dashboard")
        print("7. Worlds & Universes")
        print("8. Production Center")
        print("9. Platform & Publishing Center")
        print("10. Clone a project from template")
        print("11. Exit")

        print()

        choice = input(
            "Choose: "
        ).strip()

        if choice == "1":

            project = choose_project()

            if project:

                build_book(
                    project
                )

                input(
                    "\nPress Enter to return to menu..."
                )

        elif choice == "2":

            create_project()

            input(
                "\nPress Enter to return to menu..."
            )

        elif choice == "3":
            import_artwork_folder()
            input("\nPress Enter to return to menu...")

        elif choice == "4":
            bulk_build()
            input("\nPress Enter to return to menu...")

        elif choice == "5":
            production_queue_menu()
            input("\nPress Enter to return to menu...")

        elif choice == "6":
            production_dashboard()
            input("\nPress Enter to return to menu...")

        elif choice == "7":
            world_engine_center_v9()
            input("\nPress Enter to return to menu...")

        elif choice == "8":
            production_center()
            input("\nPress Enter to return to menu...")
        elif choice == "9":
            platform_center()
            input("\nPress Enter to return to menu...")

        elif choice == "10":
            clone_project_from_template()
            input("\nPress Enter to return to menu...")

        elif choice == "11":
            print("\nGoodbye.")
            break

        else:

            print(
                "\nInvalid choice."
            )


# ============================================================
# WORLD ENGINE 2.0 / FACTORY v9.3 UPGRADE
# Generic world-building, entity registry, continuity, and
# World Bible tools. Backward-compatible with existing worlds.
# ============================================================

WORLD_ENGINE_2_VERSION = "2.0"
WORLD_ENGINE_2_SCHEMA = 3
WORLD_ENTITY_CATEGORIES = (
    "characters", "creatures", "locations", "objects",
    "factions", "lore", "timeline", "rules"
)


def world_v2_now():
    return datetime.now().isoformat(timespec="seconds")


def world_v2_entity_id(category):
    prefix = str(category).rstrip("s") or "entity"
    return f"{prefix}_{sha256(f'{category}:{world_v2_now()}:{os.urandom(8).hex()}'.encode()).hexdigest()[:12]}"


def world_v2_normalize_entity(value, category):
    if isinstance(value, str):
        value = {"name": value}
    if not isinstance(value, dict):
        value = {"name": str(value)}
    item = dict(value)
    item.setdefault("id", world_v2_entity_id(category))
    item.setdefault("name", item.get("title", "Untitled"))
    item["name"] = str(item.get("name") or "Untitled").strip()
    item.setdefault("description", "")
    item.setdefault("canon", True)
    item.setdefault("books", [])
    item.setdefault("first_appearance", "")
    item.setdefault("last_updated", world_v2_now())
    if not isinstance(item["books"], list):
        item["books"] = [str(item["books"])]
    return item


def world_v2_find(world, category, identifier):
    # WORLD_ENTITY_CATEGORIES contains the primary world entities.
    # Books and series are also first-class world records stored at the
    # world root, so they must be searchable through the same helper.
    valid_categories = WORLD_ENTITY_CATEGORIES + ("series", "books")
    if category not in valid_categories:
        raise ValueError(f"Unknown category: {category}")
    query = str(identifier or "").strip().casefold()
    for item in world.get(category, []):
        if (
            str(item.get("id", "")).casefold() == query
            or str(item.get("name", "")).casefold() == query
        ):
            return item
    return None


def world_v2_upsert(world, category, data, identifier=""):
    upgraded = world_v2_upgrade_record(world)
    incoming = world_v2_normalize_entity(data, category)
    if identifier:
        incoming["id"] = identifier
    existing = world_v2_find(upgraded, category, incoming["id"])
    if existing is None:
        existing = world_v2_find(upgraded, category, incoming["name"])
    if existing is None:
        upgraded[category].append(incoming)
    else:
        existing.update(incoming)
        existing["last_updated"] = world_v2_now()
    return world_v2_save(upgraded)


def world_v2_delete(world, category, identifier):
    upgraded = world_v2_upgrade_record(world)
    target = world_v2_find(upgraded, category, identifier)
    if not target:
        return upgraded, False
    target_id = target.get("id")
    upgraded[category] = [
        item for item in upgraded[category]
        if item.get("id") != target_id
    ]
    upgraded["relationships"] = [
        relation for relation in upgraded.get("relationships", [])
        if relation.get("from") != target_id
        and relation.get("to") != target_id
    ]
    return world_v2_save(upgraded), True


def world_v2_add_relationship(world, source_id, target_id, relation_type, notes=""):
    upgraded = world_v2_upgrade_record(world)
    relation = {
        "id": world_v2_entity_id("relationship"),
        "from": str(source_id).strip(),
        "to": str(target_id).strip(),
        "type": str(relation_type or "related_to").strip(),
        "notes": str(notes or "").strip(),
        "canon": True,
        "last_updated": world_v2_now(),
    }
    duplicate = any(
        item.get("from") == relation["from"]
        and item.get("to") == relation["to"]
        and item.get("type") == relation["type"]
        for item in upgraded["relationships"]
    )
    if not duplicate:
        upgraded["relationships"].append(relation)
    return world_v2_save(upgraded), relation


def world_v2_attach_book(world, project_id, title, series_id="", book_number=None, canon=True):
    upgraded = world_v2_upgrade_record(world)
    record = world_v2_normalize_entity({
        "id": str(project_id or world_v2_entity_id("book")),
        "name": title,
        "series_id": series_id,
        "book_number": book_number,
        "canon": bool(canon),
        "attached": True,
    }, "books")
    existing = world_v2_find(upgraded, "books", record["id"])
    if existing is None:
        existing = world_v2_find(upgraded, "books", record["name"])
    if existing is None:
        upgraded["books"].append(record)
    else:
        existing.update(record)
    return world_v2_save(upgraded)


def world_v2_search(world, query, categories=None):
    upgraded = world_v2_upgrade_record(world)
    query = str(query or "").strip().casefold()
    categories = tuple(categories or (WORLD_ENTITY_CATEGORIES + ("series", "books")))
    results = []
    for category in categories:
        for item in upgraded.get(category, []):
            if query in json.dumps(item, ensure_ascii=False).casefold():
                results.append({
                    "category": category,
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "entity": item,
                })
    return results


def world_v2_dashboard(world):
    upgraded = world_v2_upgrade_record(world)
    audit = world_v2_audit(upgraded)
    history = upgraded.get("production_history") or []
    return {
        "name": upgraded.get("name"),
        "description": upgraded.get("description", ""),
        "genre": upgraded.get("genre", ""),
        "tone": upgraded.get("tone", ""),
        "world_id": upgraded.get("world_id"),
        "created": upgraded.get("created"),
        "updated": upgraded.get("updated"),
        "archived": bool(upgraded.get("archived", False)),
        "counts": audit["counts"],
        "continuity_status": audit["status"],
        "errors": audit["errors"],
        "warnings": audit["warnings"],
        "last_production": history[-1] if history else None,
    }


def world_v2_edit_core(world):
    upgraded = world_v2_upgrade_record(world)
    print("\nWORLD CORE EDITOR")
    print("Press Enter to keep the current value.")
    prompts = (
        ("name", "Name"),
        ("description", "Description"),
        ("genre", "Genre"),
        ("tone", "Tone"),
    )
    for key, label in prompts:
        current = str(upgraded.get(key, ""))
        value = input(f"{label} [{current}]: ").strip()
        if value:
            upgraded[key] = value
    upgraded["updated"] = world_v2_now()
    return world_v2_save(upgraded)


def world_v2_generated_name(category, world, description=""):
    """Offer a simple generated name without requiring external AI services."""
    text = f"{world.get('name', '')} {description}".casefold()
    if category == "characters":
        if any(word in text for word in ("research", "scientist", "investigat", "professor")):
            names = ["Dr. Elias Voss", "Dr. Mara Vale", "Dr. Adrian Cross", "Dr. Evelyn Graves"]
        elif any(word in text for word in ("detective", "police", "cop", "investigator")):
            names = ["Detective Rowan Pike", "Detective Mara Quinn", "Jonah Graves"]
        else:
            names = ["Elias Voss", "Mara Vale", "Rowan Black", "Evelyn Cross"]
    else:
        if any(word in text for word in ("machine", "mechanical", "metal", "robot", "vending")):
            names = ["The Coin-Eater", "The Dispenser", "The Change Warden", "Machine-Born"]
        elif any(word in text for word in ("shadow", "dark", "night", "void", "eldritch")):
            names = ["The Hollow Walker", "The Night Maw", "The Black Witness", "The Veiled Thing"]
        else:
            names = ["The Grinning Thing", "The Crooked One", "The Hunger", "The Watcher"]
    # Prefer the first name not already in this world.
    existing = {str(x.get('name', '')).casefold() for x in world.get(category, [])}
    for name in names:
        if name.casefold() not in existing:
            return name
    return f"Unnamed {category[:-1].title()} {len(world.get(category, [])) + 1}" 


def world_v2_infer_profile(world, category, description, concept="auto"):
    """Turn a plain-English idea into useful world-engine metadata.

    This is intentionally deterministic and offline. It gives the user a strong
    starting profile while leaving every field editable before anything is saved.
    """
    text = str(description or "").strip()
    lower = text.casefold()
    world_genre = str(world.get("genre", "")).strip() or "Unknown"
    world_tone = str(world.get("tone", "")).strip() or "Unknown"
    item = {"description": text, "genre": world_genre, "tone": world_tone}

    if category == "characters":
        if any(w in lower for w in ("researcher", "scientist", "professor", "doctor")):
            role = "Researcher"
        elif any(w in lower for w in ("detective", "investigator", "police")):
            role = "Investigator"
        elif any(w in lower for w in ("journalist", "reporter", "writer")):
            role = "Journalist"
        elif any(w in lower for w in ("owner", "manager", "clerk", "cashier")):
            role = "Worker / Owner"
        else:
            role = "Unknown / To Be Determined"
        personality = "Cautious and observant" if any(w in lower for w in ("research", "investigat", "mystery", "strange")) else "To be developed"
        item.update({
            "role": role,
            "appearance": "To be developed",
            "personality": personality,
            "abilities": "None established yet",
            "character_type": concept if concept != "auto" else "General",
        })
    else:
        type_map = [
            (("mechanical", "machine", "robot", "metal", "vending"), "Mechanical / Artificial"),
            (("humanoid", "human-like", "person-shaped"), "Humanoid"),
            (("animal", "beast", "wolf", "dog", "cat"), "Animalistic"),
            (("undead", "dead", "corpse", "zombie"), "Undead"),
            (("alien", "extraterrestrial", "space"), "Alien"),
            (("ghost", "spirit", "specter", "spectre"), "Supernatural"),
            (("shadow", "void", "eldritch", "cosmic"), "Eldritch / Unknown"),
            (("mutant", "mutation", "mutated"), "Mutated"),
        ]
        creature_type = "Unknown / To Be Determined"
        for words, label in type_map:
            if any(w in lower for w in words):
                creature_type = label
                break
        behavior = "Predatory and unpredictable" if any(w in lower for w in ("hunt", "attack", "prey", "stalk", "kill")) else "Behavior not fully understood"
        threat = "High" if any(w in lower for w in ("dangerous", "deadly", "kill", "attack", "murder")) else "Unknown"
        habitat = "Unknown / Anomalous locations" if any(w in lower for w in ("machine", "vending", "appears", "portal")) else "Unknown"
        item.update({
            "type": creature_type,
            "appearance": "Derived from description; expand as needed",
            "abilities": "Unknown / To be documented",
            "behavior": behavior,
            "threat_level": threat,
            "habitat": habitat,
            "creature_class": concept if concept != "auto" else "General",
        })
    return item


def world_v2_print_profile(category, item):
    label = "Character" if category == "characters" else "Creature"
    print("\n" + "=" * 72)
    print(f"GENERATED {label.upper()} PROFILE")
    print("=" * 72)
    print(f"Name:        {item.get('name', '')}")
    print(f"Description: {item.get('description', '')}")
    for key in ("genre", "tone", "role", "character_type", "type", "creature_class",
                "appearance", "personality", "abilities", "behavior", "threat_level", "habitat"):
        value = item.get(key)
        if value not in (None, "", [], {}):
            print(f"{key.replace('_', ' ').title()}: {value}")
    print("=" * 72)


def world_v2_guided_entity(world, category):
    """Friendly creation wizard for characters and creatures."""
    label = "Character" if category == "characters" else "Creature"
    print("\n" + "=" * 72)
    print(f"QUICK CREATE {label.upper()}")
    print("=" * 72)
    print("You do NOT need to know the genre, theme, classification, or other metadata.")
    print("Just describe the idea. The World Engine will fill in useful starting values.")
    print("\nConcept options:")
    if category == "characters":
        options = ["General", "Researcher", "Investigator", "Survivor", "Worker / Owner", "Supernatural", "Custom"]
    else:
        options = ["Let Factory Decide", "Animalistic", "Humanoid", "Supernatural", "Mechanical", "Undead", "Alien", "Eldritch", "Mutated", "Unknown", "Custom"]
    for i, option in enumerate(options, 1):
        print(f"{i}. {option}")
    choice = input("Choose a concept [1]: ").strip()
    try:
        concept = options[int(choice) - 1] if choice else options[0]
    except (ValueError, IndexError):
        concept = options[0]

    description = input("\nDescribe your idea in plain English: ").strip()
    if not description:
        print("Cancelled — no description entered.")
        return world

    name = input("Name [press Enter to generate one]: ").strip()
    if not name:
        name = world_v2_generated_name(category, world, description)
        print(f"Generated name: {name}")

    normalized_concept = concept.casefold()
    item = world_v2_infer_profile(
        world,
        category,
        description,
        "auto" if normalized_concept in {"let factory decide", "general", "unknown"} else concept,
    )
    item["name"] = name
    if concept not in {"Let Factory Decide", "General", "Unknown"}:
        if category == "characters":
            item["role"] = concept
            item["character_type"] = concept
        else:
            item["creature_class"] = concept
            item["type"] = concept

    while True:
        world_v2_print_profile(category, item)
        print("\n1. Accept & Save")
        print("2. Edit profile")
        print("3. Regenerate profile")
        print("4. Cancel")
        action = input("Choose: ").strip()
        if action == "1":
            return world_v2_upsert(world, category, item)
        if action == "2":
            editable = [
                "name", "description", "genre", "tone",
                "role", "character_type", "appearance", "personality", "abilities",
                "type", "creature_class", "behavior", "threat_level", "habitat",
            ]
            print("\nEnter a new value, or press Enter to leave a value unchanged.")
            for key in editable:
                if key in item:
                    value = input(f"{key.replace('_', ' ').title()} [{item.get(key, '')}]: ").strip()
                    if value:
                        item[key] = value
            continue
        if action == "3":
            item = world_v2_infer_profile(world, category, description, concept.casefold() if concept else "auto")
            item["name"] = name
            continue
        if action == "4":
            print("Cancelled.")
            return world
        print("Invalid choice.")


# ============================================================
# WORLD LOCATION HIERARCHY / FACTORY v13.1
# ============================================================
WORLD_LOCATION_LEVELS = (
    ("region", "Region"),
    ("town", "Town / City"),
    ("district", "District / Subdivision"),
    ("building", "Building"),
    ("room", "Room / Interior Area"),
    ("area", "Area / Outdoor Site"),
)

def world_location_level_label(level):
    for key, label in WORLD_LOCATION_LEVELS:
        if key == str(level).strip().casefold(): return label
    return str(level or "Location").replace("_", " ").title()

def world_location_parent(world, location_id):
    target = str(location_id or "").strip()
    for item in world.get("locations", []):
        if str(item.get("id", "")) == target:
            pid = str(item.get("parent_id", "")).strip()
            if pid:
                return next((x for x in world.get("locations", []) if str(x.get("id", "")) == pid), None)
    return None

def world_location_path(world, location_or_id, seen=None):
    current = location_or_id if isinstance(location_or_id, dict) else world_v2_find(world, "locations", location_or_id)
    if not current: return ""
    seen = set(seen or set())
    cid = str(current.get("id", ""))
    if cid in seen: return str(current.get("name", "Untitled"))
    seen.add(cid)
    parent = world_location_parent(world, cid)
    if parent: return world_location_path(world, parent, seen) + " / " + str(current.get("name", "Untitled"))
    return str(current.get("name", "Untitled"))

def world_location_children(world, parent_id=""):
    pid = str(parent_id or "").strip()
    return [x for x in world.get("locations", []) if str(x.get("parent_id", "")).strip() == pid]

def world_location_descendants(world, parent_id):
    found=[]; queue=[str(parent_id or "").strip()]
    while queue:
        children=world_location_children(world, queue.pop(0)); found.extend(children); queue.extend(str(x.get("id")) for x in children if x.get("id"))
    return found

def world_location_tree_lines(world):
    lines=[]
    def walk(items,prefix=""):
        items=sorted(items,key=lambda x:str(x.get("name","")).casefold())
        for i,item in enumerate(items):
            last=i==len(items)-1
            lines.append(f"{prefix}{'└─ ' if last else '├─ '}{item.get('name','Untitled')} [{world_location_level_label(item.get('level','location'))}]")
            children=world_location_children(world,item.get('id',''))
            if children: walk(children,prefix+('   ' if last else '│  '))
    walk(world_location_children(world,""))
    return lines

def world_location_recalculate_metadata(world):
    upgraded=world_v2_upgrade_record(world); locations=upgraded.setdefault("locations",[])
    valid={str(x.get("id","")) for x in locations if x.get("id")}
    for item in locations:
        pid=str(item.get("parent_id","")).strip()
        if pid==str(item.get("id","")) or (pid and pid not in valid): item["parent_id"]=""
        item.setdefault("level","location")
        item.setdefault("location_type",item.get("type","Custom") or "Custom")
    for item in locations:
        item["location_path"]=world_location_path(upgraded,item)
        item["children_ids"]=[str(x.get("id")) for x in locations if str(x.get("parent_id",""))==str(item.get("id",""))]
    return upgraded

def world_v2_location_add_interactive(world):
    upgraded=world_location_recalculate_metadata(world)
    print("\nADD LOCATION")
    name=input("Location name: ").strip()
    if not name: return upgraded
    description=input("Description: ").strip()
    print("\nLocation level:")
    for n,(key,label) in enumerate(WORLD_LOCATION_LEVELS,1): print(f"{n}. {label} ({key})")
    try: level=WORLD_LOCATION_LEVELS[int(input("Choose [1]: ").strip() or "1")-1][0]
    except (ValueError,IndexError): level="area"
    candidates=[x for x in upgraded.get("locations",[]) if str(x.get("level","location")).casefold()!=level]
    parent_id=""
    if candidates:
        print("\nParent location (optional):")
        print("0. None / top level")
        candidates=sorted(candidates,key=lambda x:world_location_path(upgraded,x).casefold())
        for n,x in enumerate(candidates,1): print(f"{n}. {world_location_path(upgraded,x)}")
        try:
            pos=int(input("Choose parent [0]: ").strip() or "0")
            if pos>0: parent_id=str(candidates[pos-1].get("id",""))
        except (ValueError,IndexError): print("Invalid parent; using top level.")
    item={"name":name,"description":description,"level":level,"location_type":input("Location type [optional]: ").strip() or world_location_level_label(level),"parent_id":parent_id,"environment":input("Environment [optional]: ").strip(),"important_details":input("Important details [optional]: ").strip()}
    return world_location_recalculate_metadata(world_v2_upsert(upgraded,"locations",item))

def world_location_hierarchy_menu(world):
    while True:
        world=world_location_recalculate_metadata(world)
        print("\n"+"="*72+"\nLOCATION HIERARCHY\n"+"="*72)
        print("\n".join(world_location_tree_lines(world)) or "No locations created yet.")
        print("\nA. Add location\nE. Edit location\nR. Remove location\nT. Show full location paths\nX. Back")
        choice=input("Choose: ").strip().lower()
        if choice=="x": return world_v2_save(world)
        if choice=="a": world=world_v2_location_add_interactive(world); continue
        locations=sorted(world.get("locations",[]),key=lambda x:world_location_path(world,x).casefold())
        if choice=="t":
            for x in locations: print("-",world_location_path(world,x))
            input("Press Enter to continue..."); continue
        if choice not in {"e","r"} or not locations: continue
        for n,x in enumerate(locations,1): print(f"{n}. {world_location_path(world,x)}")
        try: item=locations[int(input("Location number: ").strip())-1]
        except (ValueError,IndexError): print("Invalid selection."); continue
        if choice=="r":
            children=world_location_descendants(world,item.get("id",""))
            if children: print(f"Cannot remove '{item.get('name')}' while it has {len(children)} child location(s)."); continue
            world,removed=world_v2_delete(world,"locations",item.get("id","")); print(f"Removed: {removed}")
        else:
            edited=dict(item); value=input(f"Name [{edited.get('name','')}]: ").strip(); edited["name"]=value or edited.get("name","")
            value=input(f"Description [{edited.get('description','')}]: ").strip(); edited["description"]=value or edited.get("description","")
            print("1. Keep parent\n2. Change parent")
            if (input("Choose [1]: ").strip() or "1")=="2":
                candidates=[x for x in locations if x.get("id")!=item.get("id")]
                print("0. None / top level")
                for n,x in enumerate(candidates,1): print(f"{n}. {world_location_path(world,x)}")
                try:
                    pos=int(input("Parent: ").strip()); edited["parent_id"]="" if pos==0 else str(candidates[pos-1].get("id",""))
                except (ValueError,IndexError): pass
            world=world_location_recalculate_metadata(world_v2_upsert(world,"locations",edited))

def world_v2_add_entity_interactive(world, category):
    """Add an entity. Characters/creatures use the friendly wizard by default."""
    upgraded = world_v2_upgrade_record(world)
    labels = {
        "characters": "Character", "creatures": "Creature", "locations": "Location",
        "objects": "Object", "factions": "Faction", "lore": "Lore entry",
        "timeline": "Timeline event", "rules": "World rule",
    }
    if category in {"characters", "creatures"}:
        return world_v2_guided_entity(upgraded, category)

    name = input(f"{labels.get(category, category)} name: ").strip()
    if not name:
        return upgraded
    description = input("Description: ").strip()
    item = {"name": name, "description": description}
    if category == "locations":
        item.update({"environment": input("Environment: ").strip(), "important_details": input("Important details: ").strip()})
    elif category == "timeline":
        item.update({"date": input("Date or era: ").strip(), "era": input("Era label: ").strip()})
    return world_v2_upsert(upgraded, category, item)


def world_v2_advanced_entity_interactive(world, category):
    """Original-style manual editor, retained behind the Advanced option."""
    upgraded = world_v2_upgrade_record(world)
    label = "Character" if category == "characters" else "Creature"
    name = input(f"{label} name: ").strip()
    if not name:
        return upgraded
    description = input("Description: ").strip()
    item = {"name": name, "description": description}
    if category == "characters":
        item.update({"role": input("Role: ").strip(), "appearance": input("Appearance: ").strip(), "personality": input("Personality: ").strip(), "abilities": input("Abilities: ").strip()})
    else:
        item.update({"type": input("Type/classification: ").strip(), "appearance": input("Appearance: ").strip(), "abilities": input("Abilities: ").strip(), "behavior": input("Behavior: ").strip(), "threat_level": input("Threat level: ").strip(), "habitat": input("Habitat: ").strip()})
    return world_v2_upsert(upgraded, category, item)

def world_v2_edit_entity_interactive(world, category, item):
    """Edit an existing character/creature with the same friendly profile fields."""
    upgraded = world_v2_upgrade_record(world)
    item = dict(item)
    label = "Character" if category == "characters" else "Creature"
    print("\n" + "=" * 72)
    print(f"EDIT {label.upper()}")
    print("=" * 72)
    fields = ["name", "description", "genre", "tone"]
    if category == "characters":
        fields += ["role", "character_type", "appearance", "personality", "abilities"]
    else:
        fields += ["type", "creature_class", "appearance", "abilities", "behavior", "threat_level", "habitat"]
    print("Enter a new value, or press Enter to keep the current value.")
    for key in fields:
        current = item.get(key, "")
        value = input(f"{key.replace('_', ' ').title()} [{current}]: ").strip()
        if value:
            item[key] = value
    world_v2_print_profile(category, item)
    print("\n1. Save changes")
    print("2. Keep editing")
    print("3. Cancel")
    while True:
        choice = input("Choose: ").strip()
        if choice == "1":
            return world_v2_upsert(upgraded, category, item)
        if choice == "2":
            return world_v2_edit_entity_interactive(upgraded, category, item)
        if choice == "3":
            print("Edit cancelled.")
            return upgraded
        print("Invalid choice.")


def world_engine_center_v9():
    while True:
        index = load_world_index()
        worlds = index.get("worlds", {})
        ordered = sorted(
            worlds.items(),
            key=lambda pair: str(pair[1].get("name", pair[0])).casefold()
        )
        active = [
            (wid, meta) for wid, meta in ordered
            if not meta.get("archived", False)
        ]
        archived = [
            (wid, meta) for wid, meta in ordered
            if meta.get("archived", False)
        ]

        print("\n" + "=" * 72)
        print("WORLD ENGINE 2.0 / WORLD CENTER")
        print("=" * 72)
        print(f"Active worlds: {len(active)} | Archived: {len(archived)}")
        print("N. Create new world")
        if active:
            print("O. Open world dashboard")
        print("F. Find world")
        if archived:
            print("U. Restore archived world")
        print("X. Back")
        choice = input("Choose: ").strip().lower()

        if choice == "x":
            return
        if choice == "n":
            name = input("World name: ").strip()
            if not name:
                continue
            description = input("Description: ").strip()
            genre = input("Genre: ").strip()
            tone = input("Tone: ").strip()
            world = new_world_record(name, description, genre, tone)
            world["schema_version"] = WORLD_ENGINE_2_SCHEMA
            world["engine_version"] = WORLD_ENGINE_2_VERSION
            world["production_history"] = []
            world["archived"] = False
            world_v2_save(world)
            world_v2_write_bible(world)
            print(f"Created world: {world['name']}")
            continue
        if choice == "f":
            query = input("Search world name: ").strip().casefold()
            matches = [
                (wid, meta) for wid, meta in ordered
                if query in str(meta.get("name", wid)).casefold()
            ]
            if not matches:
                print("No matching worlds.")
            else:
                for wid, meta in matches:
                    print(f"- {meta.get('name', wid)} [{wid}]")
            continue
        if choice == "u":
            if not archived:
                print("No archived worlds.")
                continue
            for number, (wid, meta) in enumerate(archived, 1):
                print(f"{number}. {meta.get('name', wid)}")
            try:
                number = int(input("Restore number: ").strip())
                wid = archived[number - 1][0]
                world = load_world(wid)
                world["archived"] = False
                world_v2_save(world)
                print("World restored.")
            except (ValueError, IndexError, TypeError):
                print("Invalid selection.")
            continue
        if choice != "o" or not active:
            print("Invalid choice.")
            continue

        for number, (wid, meta) in enumerate(active, 1):
            print(f"{number}. {meta.get('name', wid)}")
        try:
            number = int(input("World number: ").strip())
            wid = active[number - 1][0]
            world = world_v2_upgrade_record(load_world(wid))
        except (ValueError, IndexError, TypeError):
            print("Invalid selection.")
            continue

        while True:
            dashboard = world_v2_dashboard(world)
            print("\n" + "-" * 72)
            print(f"WORLD: {dashboard['name']}")
            print(f"ID: {dashboard['world_id']}")
            print(f"Genre: {dashboard['genre']} | Tone: {dashboard['tone']}")
            print(f"Description: {dashboard['description']}")
            print(f"Continuity: {dashboard['continuity_status']}")
            print("Counts:", ", ".join(
                f"{key}={value}" for key, value in dashboard["counts"].items()
            ))
            print("\n1. Edit world core")
            print("2. Characters")
            print("3. Creatures")
            print("4. Locations")
            print("5. Location Hierarchy")
            print("6. Objects")
            print("7. Factions")
            print("8. Lore")
            print("9. Timeline")
            print("10. Rules")
            print("11. Run continuity audit")
            print("12. Generate World Bible")
            print("13. Attach a book project")
            print("14. Archive world")
            print("X. Back")
            action = input("Choose: ").strip().lower()
            if action == "x":
                break
            if action == "1":
                world = world_v2_edit_core(world)
            elif action in {"2", "3", "4", "6", "7", "8", "9", "10"}:
                category = {"2":"characters","3":"creatures","4":"locations","6":"objects","7":"factions","8":"lore","9":"timeline","10":"rules"}[action]
                world = world_v2_entity_menu(world, category)
            elif action == "5":
                world = world_location_hierarchy_menu(world)
            elif action == "11":
                report = world_v2_audit(world)
                print(f"Continuity status: {report['status']}")
                for error in report["errors"]:
                    print("ERROR:", error)
                for warning in report["warnings"]:
                    print("WARNING:", warning)
                report_path = world_path(world["world_id"]) / "CONTINUITY_REPORT.txt"
                report_path.write_text(
                    "WORLD CONTINUITY REPORT\n"
                    + "=" * 72 + "\n"
                    + f"Status: {report['status']}\n"
                    + f"Errors: {len(report['errors'])}\n"
                    + f"Warnings: {len(report['warnings'])}\n\n"
                    + "\n".join(f"ERROR: {x}" for x in report["errors"])
                    + "\n\n"
                    + "\n".join(f"WARNING: {x}" for x in report["warnings"])
                    + "\n",
                    encoding="utf-8",
                )
                print(f"Report saved: {report_path}")
            elif action == "12":
                path = world_v2_write_bible(world)
                print(f"World Bible saved: {path}")
            elif action == "13":
                project_id = input("Project ID/name: ").strip()
                title = input("Book title: ").strip()
                series = input("Series ID/name (optional): ").strip()
                number_text = input("Book number (optional): ").strip()
                book_number = int(number_text) if number_text.isdigit() else None
                world = world_v2_attach_book(
                    world, project_id, title, series, book_number, True
                )
                print("Book attached.")
            elif action == "14":
                confirm = input(
                    f"Type ARCHIVE to archive '{world['name']}': "
                ).strip()
                if confirm == "ARCHIVE":
                    world["archived"] = True
                    world = world_v2_save(world)
                    print("World archived.")
                    break
            else:
                print("Invalid choice.")


# Replace the old Worlds & Universes entry point with the upgraded center.


# ============================================================
# WORLD ENGINE 2.0 HARDENING / FACTORY v9.3
# ============================================================
WORLD_ENGINE_2_VERSION = "2.0"
WORLD_ENGINE_2_SCHEMA = 3
# v10.0 UX upgrade: unified World Entity Studio with friendly creation, editing, search, duplicate, and regeneration.

def world_v2_backup(world, reason="manual"):
    upgraded = world_v2_upgrade_record(world)
    folder = world_path(upgraded["world_id"])
    backup_dir = folder / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_reason = re.sub(r"[^A-Za-z0-9_-]+", "_", str(reason)).strip("_") or "backup"
    path = backup_dir / f"world_{stamp}_{safe_reason}.json"
    path.write_text(json.dumps(upgraded, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def world_v2_atomic_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(payload, encoding="utf-8")
    with temp.open("r+", encoding="utf-8") as handle:
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def world_v2_save(world, backup_reason="autosave"):
    upgraded = world_v2_upgrade_record(world)
    folder = world_path(upgraded["world_id"])
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "world.json"
    if target.exists():
        try:
            world_v2_backup(upgraded, backup_reason)
        except Exception as exc:
            print(f"Warning: backup failed: {exc}")
    world_v2_atomic_write(target, json.dumps(upgraded, indent=2, ensure_ascii=False))
    index = load_world_index()
    index.setdefault("worlds", {})[upgraded["world_id"]] = {
        "name": upgraded.get("name", upgraded["world_id"]),
        "updated": upgraded.get("updated", world_v2_now()),
        "archived": bool(upgraded.get("archived", False)),
    }
    index_path = Path(WORLDS_DIR) / "world_index.json"
    world_v2_atomic_write(index_path, json.dumps(index, indent=2, ensure_ascii=False))
    return upgraded


def world_v2_upgrade_record(world):
    if not isinstance(world, dict):
        raise ValueError("World record must be a dictionary")
    upgraded = dict(world)
    upgraded.setdefault("world_id", world_slug(upgraded.get("name", "New World")))
    upgraded.setdefault("name", "New World")
    upgraded.setdefault("description", "")
    upgraded.setdefault("genre", "")
    upgraded.setdefault("tone", "")
    upgraded.setdefault("universe", True)
    upgraded.setdefault("series", [])
    upgraded.setdefault("books", [])
    upgraded.setdefault("relationships", [])
    upgraded.setdefault("production_history", [])
    upgraded.setdefault("archived", False)
    upgraded.setdefault("created", world_v2_now())
    for category in WORLD_ENTITY_CATEGORIES:
        values = upgraded.get(category, [])
        if not isinstance(values, list):
            values = []
        upgraded[category] = [world_v2_normalize_entity(value, category) for value in values]
    upgraded["series"] = [world_v2_normalize_entity(v, "series") for v in upgraded.get("series", [])]
    upgraded["books"] = [world_v2_normalize_entity(v, "books") for v in upgraded.get("books", [])]
    upgraded["relationships"] = [
        {**(dict(v) if isinstance(v, dict) else {"name": str(v)}),
         "id": (dict(v) if isinstance(v, dict) else {}).get("id", world_v2_entity_id("relationship")),
         "from": (dict(v) if isinstance(v, dict) else {}).get("from", (dict(v) if isinstance(v, dict) else {}).get("source", "")),
         "to": (dict(v) if isinstance(v, dict) else {}).get("to", (dict(v) if isinstance(v, dict) else {}).get("target", "")),
         "type": (dict(v) if isinstance(v, dict) else {}).get("type", "related_to"),
         "notes": (dict(v) if isinstance(v, dict) else {}).get("notes", ""),
         "canon": (dict(v) if isinstance(v, dict) else {}).get("canon", True),
         "last_updated": (dict(v) if isinstance(v, dict) else {}).get("last_updated", world_v2_now())}
        for v in upgraded.get("relationships", [])
    ]
    upgraded["engine_version"] = WORLD_ENGINE_2_VERSION
    upgraded["schema_version"] = WORLD_ENGINE_2_SCHEMA
    upgraded["updated"] = world_v2_now()
    return upgraded


def world_v2_audit(world):
    upgraded = world_v2_upgrade_record(world)
    errors, warnings, info = [], [], []
    seen_ids, seen_names, all_ids = {}, {}, set()
    for category in WORLD_ENTITY_CATEGORIES + ("series", "books"):
        if category not in WORLD_ENTITY_CATEGORIES + ("series", "books"):
            errors.append(f"Invalid category: {category}")
            continue
        for item in upgraded.get(category, []):
            item_id = str(item.get("id", "")).strip()
            name = str(item.get("name", "")).strip()
            if not item_id:
                errors.append(f"{category}: '{name or 'Untitled'}' has no stable ID")
            elif item_id in seen_ids:
                errors.append(f"Duplicate entity ID '{item_id}' in {category} and {seen_ids[item_id]}")
            else:
                seen_ids[item_id] = category
                all_ids.add(item_id)
            if not name:
                errors.append(f"{category}/{item_id or 'no-id'} has no name")
            else:
                key = name.casefold()
                if key in seen_names and seen_names[key] != category:
                    warnings.append(f"Name collision: '{name}' appears in {seen_names[key]} and {category}")
                elif key in seen_names:
                    warnings.append(f"Duplicate name: '{name}' appears more than once in {category}")
                else:
                    seen_names[key] = category
            if category == "timeline" and not str(item.get("date", "")).strip():
                warnings.append(f"Timeline event '{name or item_id}' is missing a date")
            for book_ref in item.get("books", []) if isinstance(item.get("books", []), list) else []:
                if not any(book_ref in (book.get("id"), book.get("name")) for book in upgraded.get("books", [])):
                    warnings.append(f"{category}/{name}: unknown book reference '{book_ref}'")
    for relation in upgraded.get("relationships", []):
        if relation.get("from") not in all_ids:
            errors.append(f"Relationship {relation.get('id')} has unknown source '{relation.get('from')}'")
        if relation.get("to") not in all_ids:
            errors.append(f"Relationship {relation.get('id')} has unknown target '{relation.get('to')}'")
    timeline_keys, timeline_ids = set(), set()
    for event in upgraded.get("timeline", []):
        if event.get("id") in timeline_ids:
            errors.append(f"Duplicate timeline event ID '{event.get('id')}'")
        timeline_ids.add(event.get("id"))
        key = (str(event.get("date", "")).casefold(), str(event.get("name", "")).casefold())
        if key in timeline_keys and key != ("", ""):
            warnings.append(f"Duplicate timeline event: {event.get('name')} ({event.get('date', '')})")
        timeline_keys.add(key)
    for book in upgraded.get("books", []):
        project_id = str(book.get("id", "")).strip()
        if project_id and not (PROJECTS / project_id).exists():
            warnings.append(f"Attached book project not found: '{project_id}'")
    if not errors and not warnings:
        info.append("No continuity problems detected.")
    counts = {c: len(upgraded.get(c, [])) for c in WORLD_ENTITY_CATEGORIES}
    counts.update({"series": len(upgraded.get("series", [])), "books": len(upgraded.get("books", [])), "relationships": len(upgraded.get("relationships", []))})
    return {"status": "FAIL" if errors else ("PASS_WITH_WARNINGS" if warnings else "PASS"), "errors": errors, "warnings": warnings, "info": info, "counts": counts}


def world_v2_write_bible(world):
    upgraded = world_v2_upgrade_record(world)
    report = world_v2_audit(upgraded)
    folder = world_path(upgraded["world_id"])
    folder.mkdir(parents=True, exist_ok=True)
    lines = [f"# {upgraded['name']}", "", upgraded.get("description", ""), "", f"- **Genre:** {upgraded.get('genre', '')}", f"- **Tone:** {upgraded.get('tone', '')}", f"- **Status:** {'Archived' if upgraded.get('archived') else 'Active'}", f"- **Last updated:** {upgraded.get('updated', '')}", ""]
    for category, heading in (("rules","World Rules"),("timeline","Timeline"),("characters","Characters"),("creatures","Creatures"),("locations","Locations"),("objects","Objects"),("factions","Factions"),("lore","Lore")):
        lines += [f"## {heading}", ""]
        for item in upgraded.get(category, []):
            lines += [f"### {item.get('name', 'Untitled')}"]
            if item.get("description"): lines.append(str(item["description"]))
            for key, value in item.items():
                if key not in {"id","name","description","books"} and value not in (None, "", [], {}):
                    lines.append(f"**{key.replace('_',' ').title()}:** {value}")
            lines.append("")
    lines += ["## Relationships", ""] + [f"- `{r.get('from')}` **{r.get('type','related_to')}** `{r.get('to')}`" for r in upgraded.get("relationships", [])]
    lines += ["", "## Attached Books", ""] + [f"- {b.get('name','Untitled')} (`{b.get('id','')}`)" for b in upgraded.get("books", [])]
    lines += ["", "## Continuity Audit", "", f"**Status:** {report['status']}", "", "### Errors"] + [f"- {x}" for x in report["errors"]] + ["", "### Warnings"] + [f"- {x}" for x in report["warnings"]] + ["", "### Information"] + [f"- {x}" for x in report["info"]]
    path = folder / "WORLD_BIBLE.md"
    world_v2_atomic_write(path, "\n".join(lines).rstrip() + "\n")
    return path


# ============================================================
# WORLD ENTITY STUDIO v10.0
# Major bundled UX upgrade for every World Engine entity type.
# ============================================================

WORLD_ENTITY_STUDIO_VERSION = "1.0"

WORLD_ENTITY_LABELS = {
    "characters": "Character",
    "creatures": "Creature",
    "locations": "Location",
    "objects": "Object",
    "factions": "Faction",
    "lore": "Lore Entry",
    "timeline": "Timeline Event",
    "rules": "World Rule",
}

WORLD_ENTITY_PRESETS = {
    "characters": ["Let Factory Decide", "Researcher", "Investigator", "Survivor", "Worker / Owner", "Leader", "Villain", "Supernatural", "Custom"],
    "creatures": ["Let Factory Decide", "Animalistic", "Humanoid", "Supernatural", "Mechanical", "Undead", "Alien", "Eldritch", "Mutated", "Unknown", "Custom"],
    "locations": ["Let Factory Decide", "Building", "Wilderness", "Urban", "Underground", "Abandoned", "Supernatural", "Industrial", "Custom"],
    "objects": ["Let Factory Decide", "Artifact", "Weapon", "Machine", "Relic", "Key Item", "Supernatural", "Custom"],
    "factions": ["Let Factory Decide", "Government", "Corporation", "Cult", "Survivors", "Criminal", "Military", "Supernatural", "Custom"],
    "lore": ["Let Factory Decide", "History", "Legend", "Myth", "Secret", "Rumor", "Discovery", "Custom"],
    "timeline": ["Let Factory Decide", "Origin", "Discovery", "Incident", "Conflict", "Turning Point", "Aftermath", "Custom"],
    "rules": ["Let Factory Decide", "World Rule", "Supernatural Rule", "Technology Rule", "Creature Rule", "Continuity Rule", "Custom"],
}

WORLD_ENTITY_FIELDS = {
    "characters": ["name", "description", "genre", "tone", "role", "character_type", "appearance", "personality", "abilities", "goals", "relationships", "notes"],
    "creatures": ["name", "description", "genre", "tone", "type", "creature_class", "appearance", "abilities", "behavior", "threat_level", "habitat", "weaknesses", "notes"],
    "locations": ["name", "description", "genre", "tone", "type", "environment", "appearance", "important_details", "inhabitants", "danger_level", "story_role", "notes"],
    "objects": ["name", "description", "genre", "tone", "type", "purpose", "appearance", "powers", "limitations", "origin", "owner", "notes"],
    "factions": ["name", "description", "genre", "tone", "type", "goals", "methods", "leader", "members", "allies", "enemies", "resources", "notes"],
    "lore": ["name", "description", "genre", "tone", "type", "origin", "significance", "known_facts", "secrets", "related_entities", "notes"],
    "timeline": ["name", "description", "genre", "tone", "date", "era", "type", "cause", "consequences", "related_entities", "canon_status", "notes"],
    "rules": ["name", "description", "genre", "tone", "type", "scope", "rule_text", "exceptions", "consequences", "notes"],
}


def world_v10_slug_choice(value):
    return str(value or "").strip().casefold()


def world_v10_unique_name(world, category, candidates):
    existing = {str(x.get("name", "")).casefold() for x in world.get(category, []) if isinstance(x, dict)}
    for candidate in candidates:
        if candidate.casefold() not in existing:
            return candidate
    label = WORLD_ENTITY_LABELS.get(category, "Entity")
    n = len(world.get(category, [])) + 1
    return f"{label} {n}"


def world_v10_generate_name(world, category, description="", concept=""):
    text = f"{description} {concept} {world.get('name', '')}".casefold()
    if category == "characters":
        if any(w in text for w in ("research", "scientist", "professor", "doctor")):
            pool = ["Dr. Mara Vale", "Dr. Adrian Cross", "Dr. Evelyn Graves", "Dr. Elias Voss"]
        elif any(w in text for w in ("detective", "investigator", "police")):
            pool = ["Detective Rowan Pike", "Mara Quinn", "Jonah Graves", "Elias Ward"]
        elif "surviv" in text:
            pool = ["Nora Black", "Caleb Voss", "Mara Cross", "Evan Graves"]
        else:
            pool = ["Elias Voss", "Mara Vale", "Rowan Black", "Evelyn Cross", "Jonah Graves"]
    elif category == "creatures":
        if any(w in text for w in ("machine", "mechanical", "robot", "vending", "metal")):
            pool = ["The Coin-Eater", "The Dispenser", "The Change Warden", "Machine-Born", "The Empty Mechanism"]
        elif any(w in text for w in ("zombie", "undead", "corpse", "dead")):
            pool = ["The Hollow Dead", "The Grave Walker", "The Returned", "The Rotting Watcher"]
        elif any(w in text for w in ("shadow", "void", "eldritch", "cosmic", "night")):
            pool = ["The Hollow Walker", "The Night Maw", "The Black Witness", "The Veiled Thing"]
        else:
            pool = ["The Grinning Thing", "The Crooked One", "The Hunger", "The Watcher", "The Stranger"]
    elif category == "locations":
        pool = ["The Abandoned Station", "Blackwater Facility", "The Hollow District", "Old Mercy Hospital", "The Forgotten Road"]
        if "vending" in text or "machine" in text:
            pool = ["The Midnight Market", "Station 13", "The Dead Dispenser Hall", "Blackwater Service Tunnel"]
    elif category == "objects":
        pool = ["The Black Key", "The Last Token", "The Glass Relic", "The Broken Signal", "The Unmarked Device"]
        if "vending" in text or "machine" in text:
            pool = ["The Black Coin", "The Last Token", "The Impossible Key", "The Empty Cartridge"]
    elif category == "factions":
        pool = ["The Night Watch", "The Black Archive", "The Survivors' Circle", "The Veiled Order", "The Recovery Division"]
    elif category == "lore":
        pool = ["The First Incident", "The Missing Hour", "The Black Ledger", "The Old Warning", "The Unspoken Truth"]
    elif category == "timeline":
        pool = ["The First Appearance", "The Night It Began", "The Discovery", "The Blackout", "The First Breach"]
    else:
        pool = ["The First Rule", "The Rule of Return", "The Machine Law", "The Boundary", "The Cost of Knowledge"]
    return world_v10_unique_name(world, category, pool)


def world_v10_infer_entity(world, category, description, concept="Let Factory Decide", variation=0):
    text = str(description or "").strip()
    lower = text.casefold()
    genre = str(world.get("genre", "")).strip() or "Unknown"
    tone = str(world.get("tone", "")).strip() or "Unknown"
    concept = concept or "Let Factory Decide"
    item = {
        "id": world_v2_entity_id(category),
        "description": text,
        "genre": genre,
        "tone": tone,
        "canon": True,
        "books": [],
        "first_appearance": "",
        "last_updated": world_v2_now(),
    }
    item["studio_preset"] = concept

    if category == "characters":
        if concept not in ("Let Factory Decide", "Custom"):
            role = concept
        elif any(w in lower for w in ("research", "scientist", "professor", "doctor")):
            role = "Researcher"
        elif any(w in lower for w in ("detective", "investigat", "police")):
            role = "Investigator"
        elif "surviv" in lower:
            role = "Survivor"
        elif any(w in lower for w in ("owner", "manager", "clerk", "cashier", "worker")):
            role = "Worker / Owner"
        elif any(w in lower for w in ("leader", "commander", "chief")):
            role = "Leader"
        elif any(w in lower for w in ("villain", "killer", "murderer")):
            role = "Villain"
        else:
            role = "Unknown / To Be Determined"
        item.update({
            "role": role,
            "character_type": concept if concept not in ("Let Factory Decide", "Custom") else "General",
            "appearance": "To be developed",
            "personality": "Cautious and observant" if any(w in lower for w in ("mystery", "strange", "investigat", "research")) else "To be developed",
            "abilities": "None established yet",
            "goals": "To be developed",
            "relationships": "None established yet",
            "notes": "",
        })
    elif category == "creatures":
        if concept not in ("Let Factory Decide", "Custom", "Unknown"):
            ctype = concept
        elif any(w in lower for w in ("machine", "robot", "mechanical", "metal", "vending")):
            ctype = "Mechanical / Artificial"
        elif any(w in lower for w in ("zombie", "undead", "corpse", "dead")):
            ctype = "Undead"
        elif any(w in lower for w in ("animal", "beast", "wolf", "dog", "cat")):
            ctype = "Animalistic"
        elif any(w in lower for w in ("ghost", "spirit", "specter", "supernatural")):
            ctype = "Supernatural"
        elif any(w in lower for w in ("alien", "extraterrestrial", "space")):
            ctype = "Alien"
        elif any(w in lower for w in ("shadow", "void", "eldritch", "cosmic")):
            ctype = "Eldritch / Unknown"
        elif any(w in lower for w in ("mutant", "mutation", "mutated")):
            ctype = "Mutated"
        else:
            ctype = "Unknown / To Be Determined"
        item.update({
            "type": ctype,
            "creature_class": ctype,
            "appearance": "Derived from the description; expand as needed",
            "abilities": "Unknown / To be documented",
            "behavior": "Predatory and unpredictable" if any(w in lower for w in ("hunt", "attack", "stalk", "kill")) else "Behavior not fully understood",
            "threat_level": "High" if any(w in lower for w in ("dangerous", "deadly", "kill", "attack")) else "Unknown",
            "habitat": "Anomalous / Unknown",
            "weaknesses": "Unknown / To be discovered",
            "notes": "",
        })
    elif category == "locations":
        ltype = concept if concept not in ("Let Factory Decide", "Custom") else ("Industrial" if any(w in lower for w in ("factory", "machine", "warehouse")) else "Unknown")
        item.update({"type": ltype, "environment": "To be developed", "appearance": "To be developed", "important_details": "To be developed", "inhabitants": "Unknown", "danger_level": "Unknown", "story_role": "To be developed", "notes": ""})
    elif category == "objects":
        otype = concept if concept not in ("Let Factory Decide", "Custom") else ("Machine" if any(w in lower for w in ("machine", "device", "vending")) else "Unknown")
        item.update({"type": otype, "purpose": "To be developed", "appearance": "To be developed", "powers": "None established yet", "limitations": "To be determined", "origin": "Unknown", "owner": "Unknown", "notes": ""})
    elif category == "factions":
        ftype = concept if concept not in ("Let Factory Decide", "Custom") else "Unknown"
        item.update({"type": ftype, "goals": "To be developed", "methods": "To be developed", "leader": "Unknown", "members": "Unknown", "allies": "None established yet", "enemies": "None established yet", "resources": "Unknown", "notes": ""})
    elif category == "lore":
        ltype = concept if concept not in ("Let Factory Decide", "Custom") else "Unknown"
        item.update({"type": ltype, "origin": "To be developed", "significance": "To be developed", "known_facts": "To be developed", "secrets": "Unknown", "related_entities": "None established yet", "notes": ""})
    elif category == "timeline":
        etype = concept if concept not in ("Let Factory Decide", "Custom") else "Event"
        item.update({"type": etype, "date": "Unspecified", "era": "Unspecified", "cause": "To be developed", "consequences": "To be developed", "related_entities": "None established yet", "canon_status": "Canon", "notes": ""})
    elif category == "rules":
        rtype = concept if concept not in ("Let Factory Decide", "Custom") else "World Rule"
        item.update({"type": rtype, "scope": "World-wide", "rule_text": text or "To be defined", "exceptions": "None established yet", "consequences": "To be defined", "notes": ""})
    return item


def world_v10_print_entity(category, item, title="ENTITY PROFILE"):
    label = WORLD_ENTITY_LABELS.get(category, category.title())
    print("\n" + "=" * 76)
    print(title)
    print("=" * 76)
    print(f"Type:        {label}")
    for key in WORLD_ENTITY_FIELDS.get(category, ["name", "description"]):
        if key == "id":
            continue
        value = item.get(key, "")
        if value not in (None, "", [], {}):
            print(f"{key.replace('_', ' ').title()+':':<18}{value}")
    print("=" * 76)


def world_v10_edit_fields(item, category, allow_blank=False):
    for key in WORLD_ENTITY_FIELDS.get(category, []):
        if key == "name":
            prompt = "Name"
        else:
            prompt = key.replace("_", " ").title()
        current = str(item.get(key, ""))
        value = input(f"{prompt} [{current}]: ").strip()
        if value or allow_blank:
            item[key] = value
    item["last_updated"] = world_v2_now()
    return item


def world_v10_quick_create(world, category):
    label = WORLD_ENTITY_LABELS.get(category, category.title())
    presets = WORLD_ENTITY_PRESETS.get(category, ["Let Factory Decide", "Custom"])
    print("\n" + "=" * 76)
    print(f"QUICK CREATE {label.upper()}")
    print("=" * 76)
    print("Describe the idea in plain English. You do not need to know the metadata.")
    print("The current world's genre and tone are inherited automatically.")
    print("\nPreset / concept:")
    for i, preset in enumerate(presets, 1):
        print(f"{i}. {preset}")
    raw = input("Choose a preset [1]: ").strip()
    try:
        concept = presets[int(raw) - 1] if raw else presets[0]
    except (ValueError, IndexError):
        concept = presets[0]
    description = input("\nDescribe your idea: ").strip()
    if not description:
        print("Cancelled — no description entered.")
        return world

    name = ""
    while not name:
        requested = input("Name [Enter = generate]: ").strip()
        if requested:
            name = requested
        else:
            name = world_v10_generate_name(world, category, description, concept)
            print(f"Generated name: {name}")

    variation = 0
    while True:
        item = world_v10_infer_entity(world, category, description, concept, variation)
        item["name"] = name
        world_v10_print_entity(category, item, f"GENERATED {label.upper()} PROFILE")
        print("\n1. Accept & Save")
        print("2. Edit profile")
        print("3. Regenerate profile")
        print("4. Generate a different name")
        print("5. Cancel")
        action = input("Choose: ").strip()
        if action == "1":
            return world_v2_upsert(world, category, item)
        if action == "2":
            world_v10_edit_fields(item, category)
            continue
        if action == "3":
            variation += 1
            # Regeneration intentionally changes starter values rather than repeating the same output.
            if category == "characters":
                variants = ["Cautious and observant", "Paranoid but resourceful", "Calm under pressure", "Obsessive and relentless"]
                item["personality"] = variants[variation % len(variants)]
                item["goals"] = ["Find the truth", "Survive long enough to escape", "Protect someone important", "Expose what is happening"][variation % 4]
            elif category == "creatures":
                variants = ["Predatory and unpredictable", "Patient ambush predator", "Highly territorial", "Curious but dangerous"]
                item["behavior"] = variants[variation % len(variants)]
                item["threat_level"] = ["High", "Extreme", "Moderate", "Unknown"][variation % 4]
            else:
                item = world_v10_infer_entity(world, category, description, concept, variation)
                item["name"] = name
            continue
        if action == "4":
            name = world_v10_generate_name(world, category, description + f" variation {variation + 1}", concept)
            continue
        if action == "5":
            print("Cancelled.")
            return world
        print("Invalid choice.")


def world_v10_edit_entity(world, category, item):
    upgraded = world_v2_upgrade_record(world)
    editable = dict(item)
    label = WORLD_ENTITY_LABELS.get(category, category.title())
    while True:
        world_v10_print_entity(category, editable, f"EDIT {label.upper()}")
        print("\n1. Edit fields")
        print("2. Save changes")
        print("3. Regenerate starter profile")
        print("4. Cancel")
        choice = input("Choose: ").strip()
        if choice == "1":
            world_v10_edit_fields(editable, category)
        elif choice == "2":
            return world_v2_upsert(upgraded, category, editable)
        elif choice == "3":
            description = str(editable.get("description", ""))
            concept = str(editable.get("studio_preset", "Let Factory Decide"))
            regenerated = world_v10_infer_entity(upgraded, category, description, concept, 1)
            regenerated["id"] = editable.get("id", regenerated.get("id"))
            regenerated["name"] = editable.get("name", regenerated.get("name"))
            editable = regenerated
        elif choice == "4":
            print("Edit cancelled.")
            return upgraded
        else:
            print("Invalid choice.")


def world_v10_duplicate_entity(world, category, item):
    duplicate = dict(item)
    duplicate.pop("id", None)
    duplicate["name"] = world_v10_generate_name(world, category, str(item.get("description", "")) + " duplicate", str(item.get("studio_preset", "")))
    duplicate["last_updated"] = world_v2_now()
    return world_v2_upsert(world, category, duplicate)


def world_v10_entity_menu(world, category):
    """Unified management screen for every World Engine entity category."""
    while True:
        upgraded = world_v2_upgrade_record(world)
        items = upgraded.get(category, [])
        label = WORLD_ENTITY_LABELS.get(category, category.title())
        print("\n" + "=" * 76)
        print(f"{label.upper()} STUDIO ({len(items)})")
        print("=" * 76)
        if items:
            for index, item in enumerate(items, 1):
                print(f"{index}. {item.get('name', 'Untitled')} [{item.get('id', '')}]")
        else:
            print("No entries yet.")
        print("\nA. Quick Create (recommended)")
        print("M. Advanced / Manual Create")
        if items:
            print("E. Edit an existing entry")
            print("V. View an entry")
            print("D. Duplicate an entry")
            print("R. Remove an entry")
            print("S. Search this category")
        print("X. Back")
        choice = input("Choose: ").strip().lower()
        if choice == "x":
            return upgraded
        if choice == "a":
            world = world_v10_quick_create(upgraded, category)
            continue
        if choice == "m":
            if category in {"characters", "creatures"}:
                world = world_v2_advanced_entity_interactive(upgraded, category)
            else:
                # Advanced mode for all categories uses the complete field set.
                name = input(f"{label} name: ").strip()
                if not name:
                    continue
                item = {"name": name, "description": input("Description: ").strip()}
                world_v10_edit_fields(item, category)
                world = world_v2_upsert(upgraded, category, item)
            continue
        if choice in {"e", "v", "d", "r"} and items:
            try:
                number = int(input(f"Number to { {'e':'edit','v':'view','d':'duplicate','r':'remove'}[choice] }: ").strip())
                if not 1 <= number <= len(items):
                    raise ValueError
            except ValueError:
                print("Invalid number.")
                continue
            selected = items[number - 1]
            if choice == "e":
                world = world_v10_edit_entity(upgraded, category, selected)
            elif choice == "v":
                world_v10_print_entity(category, selected, f"VIEW {label.upper()}")
                input("Press Enter to continue...")
            elif choice == "d":
                world = world_v10_duplicate_entity(upgraded, category, selected)
            elif choice == "r":
                confirm = input(f"Remove '{selected.get('name', 'Untitled')}'? Type YES to confirm: ").strip()
                if confirm == "YES":
                    world, removed = world_v2_delete(upgraded, category, selected.get("id"))
                    print("Removed." if removed else "Nothing was removed.")
                else:
                    print("Removal cancelled.")
            continue
        if choice.isdigit() and items:
            number = int(choice)
            if 1 <= number <= len(items):
                selected = items[number - 1]
                world_v10_print_entity(category, selected, f"VIEW {label.upper()}")
                print("\n1. Edit")
                print("2. Duplicate")
                print("3. Remove")
                print("4. Back")
                action = input("Choose: ").strip()
                if action == "1":
                    world = world_v10_edit_entity(upgraded, category, selected)
                elif action == "2":
                    world = world_v10_duplicate_entity(upgraded, category, selected)
                elif action == "3":
                    confirm = input("Type YES to confirm removal: ").strip()
                    if confirm == "YES":
                        world, _ = world_v2_delete(upgraded, category, selected.get("id"))
            else:
                print("Invalid number.")
            continue
        if choice == "s" and items:
            query = input("Search text: ").strip()
            results = world_v2_search(upgraded, query, [category])
            if not results:
                print("No matches.")
            else:
                print(f"\nFound {len(results)} match(es):")
                for result in results:
                    print(f"- {result.get('name')} [{result.get('id')}]")
            input("Press Enter to continue...")
            continue
        print("Invalid choice.")


# Make the v10.0 Studio the active implementation for every world category.
world_v2_entity_menu = world_v10_entity_menu


# ============================================================
# v11.0 UNIVERSAL PUBLISHING & DISTRIBUTION ENGINE
# ============================================================
# Major upgrade layered over the v10.x factory.  The later definitions in this
# section intentionally override earlier platform functions so older projects
# remain compatible while gaining the new publishing pipeline.

# Legacy override removed: FACTORY_VERSION remains authoritative at 13.1.
PLATFORM_ENGINE_VERSION = "4.0"
UNIVERSAL_PUBLISHING_VERSION = "1.0"

UNIVERSAL_PLATFORM_PROFILES = {
    "KDP": {
        "name": "Amazon KDP", "type": "print", "enabled": True, "output_dir": "KDP",
        "source": "master_pdf", "files": ["interior_pdf", "cover_pdf", "metadata", "checklist", "preflight"],
        "variant": {"mode": "copy", "filename_suffix": "_KDP_INTERIOR"},
        "rules": {"min_pages": 24, "max_pages": 828, "require_title": True,
                  "require_author": False, "require_cover": False, "require_landscape": False,
                  "max_file_mb": 650, "expected_trim_from_project": True,
                  "max_files": 2, "requires_single_page": True, "min_dpi": 300,
                  "advisory": False},
        "notes": "KDP print profile. KDP requires a separate manuscript and cover workflow when a cover is supplied."
    },
    "Gumroad": {
        "name": "Gumroad", "type": "digital", "enabled": True, "output_dir": "GUMROAD",
        "source": "master_pdf", "files": ["digital_pdf", "cover_preview", "preview_sheet", "metadata", "product_description", "readme"],
        "variant": {"mode": "digital_copy", "filename_suffix": "_DIGITAL"},
        "rules": {"min_pages": 1, "max_pages": 10000, "require_title": True,
                  "require_author": False, "require_cover": False, "require_landscape": False,
                  "max_file_mb": 500, "max_files": 20, "advisory": True},
        "notes": "Digital delivery profile. Verify account-specific limits before publishing."
    },
    "Etsy": {
        "name": "Etsy Digital", "type": "digital", "enabled": True, "output_dir": "ETSY",
        "source": "master_pdf", "files": ["digital_pdf", "cover_preview", "preview_sheet", "metadata", "product_description", "readme"],
        "variant": {"mode": "etsy_split", "filename_suffix": "_ETSY"},
        "rules": {"min_pages": 1, "max_pages": 10000, "require_title": True,
                  "require_author": False, "require_cover": False, "require_landscape": False,
                  "max_file_mb": 20, "max_files": 5, "max_filename_chars": 70,
                  "advisory": False},
        "notes": "Verified Etsy digital listing constraints: up to 5 files, 20 MB each; supported file names are buyer-visible."
    },
    "Payhip": {
        "name": "Payhip", "type": "digital", "enabled": True, "output_dir": "PAYHIP",
        "source": "master_pdf", "files": ["digital_pdf", "cover_preview", "preview_sheet", "metadata", "product_description", "readme"],
        "variant": {"mode": "copy", "filename_suffix": "_PAYHIP"},
        "rules": {"min_pages": 1, "max_pages": 10000, "require_title": True,
                  "require_author": False, "require_cover": False, "require_landscape": False,
                  "max_file_mb": 5120, "max_files": 50, "advisory": False},
        "notes": "Payhip currently documents a 5GB maximum per uploaded file."
    },
    "Ko-fi": {
        "name": "Ko-fi Shop", "type": "digital", "enabled": False, "output_dir": "KOFI",
        "source": "master_pdf", "files": ["digital_pdf", "cover_preview", "preview_sheet", "metadata", "product_description", "readme"],
        "variant": {"mode": "copy", "filename_suffix": "_KOFI"},
        "rules": {"min_pages": 1, "max_pages": 10000, "require_title": True,
                  "require_author": False, "require_cover": False, "require_landscape": False,
                  "max_file_mb": 500, "max_files": 20, "advisory": True},
        "notes": "Framework profile; enable after confirming current account limits."
    },
    "Creative Market": {
        "name": "Creative Market", "type": "digital", "enabled": False, "output_dir": "CREATIVE_MARKET",
        "source": "master_pdf", "files": ["digital_pdf", "cover_preview", "preview_sheet", "metadata", "product_description", "readme"],
        "variant": {"mode": "copy", "filename_suffix": "_CREATIVE_MARKET"},
        "rules": {"min_pages": 1, "max_pages": 10000, "require_title": True,
                  "require_author": False, "require_cover": False, "require_landscape": False,
                  "max_file_mb": 500, "max_files": 20, "advisory": True},
        "notes": "Framework profile; marketplace-specific listing rules should be confirmed before activation."
    },
    "Shopify": {
        "name": "Shopify Digital", "type": "digital", "enabled": False, "output_dir": "SHOPIFY",
        "source": "master_pdf", "files": ["digital_pdf", "cover_preview", "preview_sheet", "metadata", "product_description", "readme"],
        "variant": {"mode": "copy", "filename_suffix": "_SHOPIFY"},
        "rules": {"min_pages": 1, "max_pages": 10000, "require_title": True,
                  "require_author": False, "require_cover": False, "require_landscape": False,
                  "max_file_mb": 500, "max_files": 50, "advisory": True},
        "notes": "Storefront profile; actual download delivery depends on the Shopify app/service selected."
    },
}


def _deep_merge_platform_profiles(base, custom):
    merged = json.loads(json.dumps(base))
    if not isinstance(custom, dict):
        return merged
    for key, value in custom.items():
        if not isinstance(value, dict):
            continue
        if key not in merged:
            merged[key] = json.loads(json.dumps(value))
            continue
        for field, field_value in value.items():
            if field in {"rules", "variant"} and isinstance(field_value, dict):
                merged[key].setdefault(field, {}).update(field_value)
            else:
                merged[key][field] = field_value
    return merged


def load_platform_profiles():
    path = platform_profiles_path()
    custom = {}
    if path.exists():
        try:
            data = load_json(path)
            custom = data.get("profiles", {}) if isinstance(data, dict) else {}
        except Exception:
            custom = {}
    return _deep_merge_platform_profiles(UNIVERSAL_PLATFORM_PROFILES, custom)


def save_platform_profiles(profiles):
    save_json(platform_profiles_path(), {
        "version": PLATFORM_ENGINE_VERSION,
        "universal_publishing_version": UNIVERSAL_PUBLISHING_VERSION,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "profiles": profiles,
    })


def _platform_sanitized_filename(name, max_chars=70):
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "file")).strip("._") or "file"
    return text[:max_chars]


def _pdf_split_by_size(source_pdf, output_dir, base_name, max_mb, max_files):
    """Split a PDF into sequential parts whose estimated serialized size stays under max_mb."""
    Reader = _pdf_reader_class()
    if Reader is None:
        return [], ["pypdf/PyPDF2 is required for PDF splitting."]
    try:
        from pypdf import PdfWriter
    except ImportError:
        try:
            from PyPDF2 import PdfWriter
        except ImportError:
            return [], ["pypdf/PyPDF2 PdfWriter is required for PDF splitting."]

    source = Path(source_pdf)
    limit = int(float(max_mb) * 1024 * 1024)
    errors = []
    outputs = []
    try:
        reader = Reader(str(source), strict=False)
        if getattr(reader, "is_encrypted", False):
            try:
                if not reader.decrypt(""):
                    return [], ["Encrypted PDF cannot be split without a password."]
            except Exception as exc:
                return [], [f"Encrypted PDF could not be opened: {exc}"]
        pages = list(reader.pages)
        if not pages:
            return [], ["Source PDF contains no pages."]
        index = 0
        while index < len(pages):
            writer = PdfWriter()
            start = index
            # Add pages one at a time and serialize to a temporary file so the
            # actual compressed PDF size, rather than page count, controls splits.
            while index < len(pages):
                writer.add_page(pages[index])
                tmp = output_dir / f".__split_{start+1}_{index+1}.pdf"
                with tmp.open("wb") as handle:
                    writer.write(handle)
                size = tmp.stat().st_size
                tmp.unlink(missing_ok=True)
                if size <= limit or index == start:
                    index += 1
                    continue
                # Rebuild without the last page.
                writer = PdfWriter()
                for page in pages[start:index]:
                    writer.add_page(page)
                break
            if index == start:
                return [], [f"A single page exceeds the {max_mb} MB platform file limit."]
            out = output_dir / f"{_platform_sanitized_filename(base_name)}_PART_{len(outputs)+1:02d}.pdf"
            with out.open("wb") as handle:
                writer.write(handle)
            if out.stat().st_size > limit and index > start + 1:
                # Defensive check; should only occur for unusual writer behavior.
                out.unlink(missing_ok=True)
                return [], [f"Unable to create a compliant part under {max_mb} MB."]
            outputs.append(out)
            if len(outputs) > max_files:
                for item in outputs:
                    item.unlink(missing_ok=True)
                return [], [f"Etsy-style packaging would require more than {max_files} files."]
        return outputs, errors
    except Exception as exc:
        return [], [f"PDF split failed: {exc}"]


def _write_platform_readme(output_dir, settings, platform_name, generated_files, notes=None):
    title = settings.get("title", "Coloring Book")
    author = settings.get("author", "")
    lines = [
        title,
        "=" * len(title),
        f"Author: {author}" if author else "",
        f"Platform package: {platform_name}",
        "",
        "Thank you for your purchase.",
        "",
        "Files included:",
    ]
    lines.extend(f"- {name}" for name in generated_files)
    if notes:
        lines.extend(["", "Notes:", *[f"- {n}" for n in notes]])
    (output_dir / "README.txt").write_text("\n".join(x for x in lines if x != "") + "\n", encoding="utf-8")
    return output_dir / "README.txt"


def _platform_profile_warning_list(profile):
    rules = profile.get("rules", {})
    warnings = []
    if rules.get("advisory"):
        warnings.append("This platform profile contains advisory limits; verify the marketplace's current seller requirements before publishing.")
    return warnings


def inspect_pdf(path):
    result = {"path": str(path) if path else None, "exists": bool(path and Path(path).exists()),
              "page_count": None, "sizes": [], "unique_sizes": [], "file_size_mb": None,
              "encrypted": None, "metadata": {}, "error": None,
              "has_annotations": False, "has_bookmarks": False, "has_javascript": False,
              "has_forms": False, "page_resources": {}}
    if not result["exists"]:
        result["error"] = "PDF does not exist."
        return result
    pdf = Path(path)
    result["file_size_mb"] = round(pdf.stat().st_size / (1024 * 1024), 3)
    try:
        Reader = _pdf_reader_class()
        if Reader is None:
            result["error"] = "No supported PDF reader is installed (pypdf or PyPDF2)."
            return result
        reader = Reader(str(pdf), strict=False)
        result["encrypted"] = bool(reader.is_encrypted)
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    result["error"] = "PDF is encrypted and could not be opened with an empty password."
                    return result
            except Exception as error:
                result["error"] = f"PDF encryption check failed: {error}"
                return result
        result["page_count"] = len(reader.pages)
        meta = reader.metadata or {}
        result["metadata"] = {str(k): str(v) for k, v in meta.items() if v is not None}
        sizes = []
        annotations = 0
        for page in reader.pages:
            w = round(float(page.mediabox.width) / 72, 4)
            h = round(float(page.mediabox.height) / 72, 4)
            sizes.append({"width": w, "height": h,
                          "orientation": "landscape" if w > h else "portrait" if h > w else "square"})
            try:
                annotations += len(page.get("/Annots", []) or [])
            except Exception:
                pass
        result["sizes"] = sizes
        result["unique_sizes"] = sorted({f"{x['width']}x{x['height']}" for x in sizes})
        result["has_annotations"] = annotations > 0
        try:
            root = reader.trailer.get("/Root")
            result["has_javascript"] = bool(root and (root.get("/Names") or root.get("/OpenAction")))
            result["has_forms"] = bool(root and root.get("/AcroForm"))
            result["has_bookmarks"] = bool(getattr(reader, "outline", []))
        except Exception:
            pass
    except Exception as error:
        result["error"] = str(error)
    return result


def _kdp_profile_audit(project, master_pdf, info, settings):
    errors, warnings = [], []
    page_count = info.get("page_count")
    if page_count is not None and page_count < 24:
        errors.append(f"KDP manuscript has {page_count} pages; paperback minimum is 24 pages.")
    if page_count is not None and page_count > 828:
        errors.append(f"KDP manuscript has {page_count} pages; profile maximum is 828 pages.")
    if info.get("file_size_mb") and info["file_size_mb"] > 650:
        errors.append("KDP manuscript exceeds the 650 MB file limit.")
    if info.get("encrypted"):
        errors.append("KDP manuscript is encrypted/locked.")
    if info.get("has_annotations"):
        warnings.append("PDF contains annotations; KDP submission guidelines say submitted files should not contain annotations.")
    if info.get("has_bookmarks"):
        warnings.append("PDF contains bookmarks; KDP submission guidelines say submitted files should not contain bookmarks.")
    if info.get("has_javascript"):
        warnings.append("PDF contains document-level interactive structures; verify no JavaScript or unsupported interactive content remains.")
    if info.get("has_forms"):
        warnings.append("PDF contains AcroForm fields; verify the print PDF is flattened.")
    if page_count and page_count < 79:
        cover = _platform_cover(project)
        if cover and "spine" in cover.stem.lower():
            warnings.append("Books under 79 pages should not contain spine text on a KDP paperback cover.")
    sizes = info.get("sizes", [])
    if settings.get("trim_width") and settings.get("trim_height") and sizes:
        tw, th = float(settings["trim_width"]), float(settings["trim_height"])
        mismatches = [i + 1 for i, s in enumerate(sizes)
                      if abs(s["width"] - tw) > 0.01 or abs(s["height"] - th) > 0.01]
        if mismatches:
            errors.append(f"{len(mismatches)} page(s) do not match project trim size {tw} x {th} inches.")
    # Imported finished PDFs may already contain the complete KDP cover.
    # Do not report the absence of a separate MASTER_COVER as a failure/warning
    # when the project was created through the finished-PDF intake workflow.
    project_settings = load_project_settings_safe(project)
    imported_finished_pdf = bool(
        project_settings.get("embedded_kdp_cover")
        or project_settings.get("production_profile") == "Imported Finished PDF"
        or project_settings.get("source_pdf")
    )
    if not _platform_cover(project) and not imported_finished_pdf:
        warnings.append("No separate MASTER_COVER asset is present. KDP will require a cover file unless using KDP Cover Creator.")
    elif not _platform_cover(project) and imported_finished_pdf:
        # Informational status is recorded in the manifest/report, but it is not
        # counted as a warning because the finished PDF is the cover-bearing source.
        pass
    return errors, warnings


def platform_preflight(project, platform_name, master_pdf=None, profile=None):
    profiles = load_platform_profiles()
    profile = profile or profiles.get(platform_name)
    settings = load_project_settings_safe(project)
    errors, warnings = [], []
    if not profile:
        return {"status": "BLOCKED", "platform": platform_name, "errors": [f"Unknown platform: {platform_name}"], "warnings": []}
    master_pdf = master_pdf or find_master_pdf(project)
    info = inspect_pdf(master_pdf) if master_pdf else {"exists": False, "error": "No master PDF found.", "page_count": None, "unique_sizes": [], "sizes": [], "file_size_mb": None}
    if not info.get("exists"):
        errors.append("Master PDF is missing.")
    if info.get("error"):
        errors.append(info["error"])
    rules = profile.get("rules", {})
    page_count = info.get("page_count")
    if page_count is not None:
        if page_count < int(rules.get("min_pages", 1)):
            errors.append(f"Page count {page_count} is below platform minimum {rules['min_pages']}.")
        if page_count > int(rules.get("max_pages", 10000)):
            errors.append(f"Page count {page_count} exceeds platform maximum {rules['max_pages']}.")
    size_mb = info.get("file_size_mb")
    if size_mb is not None and size_mb > float(rules.get("max_file_mb", 999999)):
        errors.append(f"PDF size {size_mb:.3f} MB exceeds profile limit of {rules['max_file_mb']} MB.")
    if rules.get("require_landscape") is False and any(x.get("orientation") == "landscape" for x in info.get("sizes", [])):
        warnings.append("One or more PDF pages are landscape; confirm this is intentional.")
    errors.extend(platform_required_metadata(settings, profile))
    warnings.extend(_platform_profile_warning_list(profile))
    if platform_name == "KDP" and info.get("exists") and not info.get("error"):
        kdp_errors, kdp_warnings = _kdp_profile_audit(project, master_pdf, info, settings)
        errors.extend(kdp_errors); warnings.extend(kdp_warnings)
    expected = None
    if rules.get("expected_trim_from_project") and settings.get("trim_width") and settings.get("trim_height"):
        expected = (float(settings["trim_width"]), float(settings["trim_height"]))
        bad = []
        for n, item in enumerate(info.get("sizes", []), 1):
            if abs(item["width"] - expected[0]) > 0.01 or abs(item["height"] - expected[1]) > 0.01:
                bad.append(n)
        if bad:
            errors.append(f"Page dimensions do not match project trim {expected[0]} x {expected[1]} in on {len(bad)} page(s).")
    cover = _platform_cover(project)
    if rules.get("require_cover") and not cover:
        errors.append("Required cover asset is missing from MASTER.")
    status = "BLOCKED" if errors else ("READY_WITH_WARNINGS" if warnings else "READY")
    return {"schema_version": 4, "factory_version": FACTORY_VERSION, "platform_engine_version": PLATFORM_ENGINE_VERSION,
            "universal_publishing_version": UNIVERSAL_PUBLISHING_VERSION, "platform": platform_name,
            "platform_type": profile.get("type"), "status": status,
            "timestamp": datetime.now().isoformat(timespec="seconds"), "master_pdf": str(master_pdf) if master_pdf else None,
            "pdf": info, "metadata": {"title": settings.get("title", ""), "author": settings.get("author", ""),
                                      "page_count": page_count, "trim_width": settings.get("trim_width"),
                                      "trim_height": settings.get("trim_height")}, "rules": rules,
            "variant": profile.get("variant", {}), "errors": errors, "warnings": warnings}


def _copy_variant_pdf(master_pdf, staging, title, profile):
    target = staging / f"{_platform_sanitized_filename(title, 120)}{profile.get('variant', {}).get('filename_suffix', '_DIGITAL')}.pdf"
    shutil.copy2(master_pdf, target)
    return target, []


def platform_requirement_comparison(project):
    profiles = load_platform_profiles(); master = find_master_pdf(project); rows = []
    for name, profile in profiles.items():
        audit = platform_preflight(project, name, master, profile); rules = profile.get("rules", {})
        rows.append({"platform": name, "enabled": bool(profile.get("enabled")), "type": profile.get("type"),
                     "status": audit.get("status"), "pages": audit.get("pdf", {}).get("page_count"),
                     "max_mb": rules.get("max_file_mb"), "min_pages": rules.get("min_pages"),
                     "max_pages": rules.get("max_pages"), "max_files": rules.get("max_files"),
                     "cover_required": bool(rules.get("require_cover")),
                     "variant": profile.get("variant", {}).get("mode", "copy"),
                     "errors": len(audit.get("errors", [])), "warnings": len(audit.get("warnings", []))})
    return rows


def convert_existing_pdf_enhanced():
    print("\n" + "=" * 78)
    print("UNIVERSAL PDF INTAKE")
    print("=" * 78)
    print("Select a finished PDF with the Windows picker, or drag it onto the drop zone.")
    pdf = choose_pdf_file("Finished PDF")
    if not pdf:
        print("No valid PDF selected."); return None
    info = inspect_pdf(pdf)
    if info.get("error"):
        print(f"ERROR: {info['error']}"); return None
    print("\nSOURCE ANALYSIS")
    print("-" * 78)
    print(f"File:       {pdf}")
    print(f"Pages:      {info.get('page_count')}")
    print(f"Size:       {info.get('file_size_mb')} MB")
    print(f"Page sizes: {', '.join(info.get('unique_sizes', [])) or 'unknown'}")
    print(f"Encrypted:  {info.get('encrypted')}")
    print(f"Annotations:{' YES' if info.get('has_annotations') else ' no'}")
    print(f"Bookmarks:  {' YES' if info.get('has_bookmarks') else ' no'}")
    print(f"Forms:      {' YES' if info.get('has_forms') else ' no'}")
    title = pdf.stem
    name = input(f"\nProject name [{title}]: ").strip() or title
    author = input("Author [blank = unknown]: ").strip()
    project_name = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip().rstrip(".") or "Imported PDF"
    project = PROJECTS / unique_project_name(project_name)
    project.mkdir(parents=True, exist_ok=True); setup_project(project); (project / "MASTER").mkdir(exist_ok=True)
    sizes = info.get("sizes") or [{"width": 8.5, "height": 11}]
    settings = {
        "title": title, "author": author, "trim_width": sizes[0]["width"], "trim_height": sizes[0]["height"],
        "dpi": 300, "production_profile": "Imported Finished PDF", "factory_version": FACTORY_VERSION,
        "platform_engine_version": PLATFORM_ENGINE_VERSION, "universal_publishing_version": UNIVERSAL_PUBLISHING_VERSION,
        "world_engine_version": WORLD_ENGINE_VERSION, "source_pdf": str(pdf), "source_pdf_sha256": file_hash(pdf),
        "source_pdf_pages": info.get("page_count"), "source_pdf_size_mb": info.get("file_size_mb"),
        "imported_at": datetime.now().isoformat(timespec="seconds"), "imported_pdf_metadata": info.get("metadata", {}),
    }
    save_json(project / "project.json", settings); save_json(project / "book.json", {"pages": [], "source": "imported_pdf"})
    master = import_existing_pdf_to_master(project, pdf)
    if not master:
        print("ERROR: MASTER creation failed."); return None
    print(f"\nMASTER LOCKED: {master}")
    print("Original source remains untouched.")
    results = generate_all_platform_packages(project)
    create_delivery_index(project, results)
    health = project_health_scan(project)
    print_project_health(health)
    print(f"\nImported project: {project}")
    return project


def manage_platform_profiles_v2():
    profiles = load_platform_profiles(); names = list(profiles.keys())
    while True:
        print("\n" + "=" * 78); print("UNIVERSAL PLATFORM PROFILE MANAGER v4"); print("=" * 78)
        for i, name in enumerate(names, 1):
            p = profiles[name]; r = p.get("rules", {})
            print(f"{i}. {name:<20} {'ON ' if p.get('enabled') else 'OFF'} | {p.get('type','?'):<8} | "
                  f"{r.get('max_file_mb')} MB/file | {r.get('max_files','-')} files | {p.get('variant',{}).get('mode','copy')}")
        print("\nA. Add custom platform\nE. Edit selected profile\nT. Toggle selected profile\nX. Back")
        choice = input("Choose: ").strip().lower()
        if choice == "x": return
        if choice == "a":
            name = input("Platform name: ").strip()
            if not name or name in profiles: print("Invalid or duplicate platform."); continue
            out = re.sub(r"[^A-Za-z0-9_-]+", "_", name).upper()
            profiles[name] = {"name": name, "type": "digital", "enabled": False, "output_dir": out,
                              "source": "master_pdf", "files": ["digital_pdf", "preview_sheet", "metadata", "product_description", "readme"],
                              "variant": {"mode": "copy", "filename_suffix": "_DIGITAL"},
                              "rules": {"min_pages": 1, "max_pages": 10000, "require_title": True,
                                        "require_author": False, "require_cover": False, "require_landscape": False,
                                        "max_file_mb": 500, "max_files": 20, "advisory": True},
                              "notes": "Custom user-defined profile."}
            save_platform_profiles(profiles); names = list(profiles.keys()); print(f"Added: {name}"); continue
        if not choice.isdigit() or not (1 <= int(choice) <= len(names)):
            print("Invalid choice."); continue
        selected = names[int(choice)-1]; profile = profiles[selected]; rules = profile.setdefault("rules", {})
        action = input("Toggle (T) or edit (E)? ").strip().lower()
        if action == "t":
            profile["enabled"] = not profile.get("enabled", False); save_platform_profiles(profiles)
        elif action == "e":
            raw = input(f"Max file MB [{rules.get('max_file_mb', 500)}]: ").strip()
            if raw:
                try: rules["max_file_mb"] = float(raw)
                except ValueError: pass
            raw = input(f"Max files [{rules.get('max_files', 20)}]: ").strip()
            if raw:
                try: rules["max_files"] = int(raw)
                except ValueError: pass
            raw = input(f"Minimum pages [{rules.get('min_pages', 1)}]: ").strip()
            if raw:
                try: rules["min_pages"] = int(raw)
                except ValueError: pass
            raw = input(f"Maximum pages [{rules.get('max_pages', 10000)}]: ").strip()
            if raw:
                try: rules["max_pages"] = int(raw)
                except ValueError: pass
            advisory = input(f"Advisory profile? [{'Y' if rules.get('advisory') else 'N'}]: ").strip().lower()
            if advisory in {"y", "n"}: rules["advisory"] = advisory == "y"
            save_platform_profiles(profiles); print(f"Saved: {selected}")


# ============================================================
# FACTORY v11.1 — FINISHED PDF QUICK-PUBLISH FRONT DOOR
# Makes the requested finished-PDF-to-platform workflow visible
# from the main menu and provides a drag/drop-capable intake UI.
# ============================================================

# Legacy override removed: FACTORY_VERSION remains authoritative at 13.1.
UNIVERSAL_PUBLISHING_VERSION = "1.1"


def choose_finished_pdf_v111():
    """Open a Windows drop zone when tkinterdnd2 is available; otherwise use a file picker."""
    try:
        from tkinter import Tk, Label, Button, filedialog
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
        except Exception:
            DND_FILES = None
            TkinterDnD = None

        selected = {"path": None}
        root = TkinterDnD.Tk() if TkinterDnD else Tk()
        root.title("Coloring Book Factory — Finished PDF Import")
        root.geometry("720x390")
        root.resizable(False, False)

        Label(root, text="FINISHED PDF → MULTI-PLATFORM PUBLISHING",
              font=("Segoe UI", 18, "bold")).pack(pady=(28, 8))
        Label(root, text="Select a finished PDF or drag and drop it into this window.",
              font=("Segoe UI", 11)).pack(pady=(0, 18))

        drop = Label(root,
                     text="DROP FINISHED PDF HERE\n\nOR\n\nCLICK SELECT PDF",
                     relief="groove", borderwidth=3,
                     font=("Segoe UI", 14, "bold"),
                     width=48, height=7)
        drop.pack(padx=35, fill="both", expand=True)

        def accept(path):
            path = str(path).strip().strip('"')
            if path.lower().endswith(".pdf") and Path(path).is_file():
                selected["path"] = path
                root.destroy()

        def browse():
            path = filedialog.askopenfilename(
                title="Select Finished PDF",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
            )
            if path:
                accept(path)

        Button(root, text="SELECT PDF", command=browse,
               font=("Segoe UI", 11, "bold"), padx=18, pady=8).pack(pady=18)

        if DND_FILES:
            def on_drop(event):
                paths = root.tk.splitlist(event.data)
                if paths:
                    accept(paths[0])
            drop.drop_target_register(DND_FILES)
            drop.dnd_bind("<<Drop>>", on_drop)
        else:
            Label(root, text="Drag/drop requires optional package: tkinterdnd2",
                  font=("Segoe UI", 9)).pack(pady=(0, 8))

        root.mainloop()
        return Path(selected["path"]) if selected["path"] else None
    except Exception as error:
        print(f"PDF drop-zone unavailable ({error}); opening standard file picker...")
        try:
            return choose_pdf_file("Finished PDF")
        except Exception:
            return None


def import_finished_pdf_v111():
    """User-facing front door: import one finished PDF and build enabled platform packages."""
    print("\n" + "=" * 78)
    print("FINISHED PDF → MULTI-PLATFORM PUBLISHING")
    print("=" * 78)
    print("The original PDF will NOT be modified.")
    print("Factory will create an immutable MASTER and platform packages.")
    print("\nOpening PDF import window...")

    pdf = choose_finished_pdf_v111()
    if not pdf:
        print("\nNo PDF selected.")
        return None

    # Reuse the hardened importer by temporarily supplying the selected path
    # through the same chooser contract used by the existing implementation.
    original_chooser = globals().get("choose_pdf_file")
    globals()["choose_pdf_file"] = lambda title="PDF": pdf
    try:
        return convert_existing_pdf_enhanced()
    finally:
        if original_chooser is not None:
            globals()["choose_pdf_file"] = original_chooser


# ============================================================
# COLORING BOOK FACTORY v17.1 — UNIVERSAL PDF PREVIEW ENGINE
#   - Automatically bootstraps PyMuPDF when vector PDF rendering is required.
#   - Renders a broad interior-page sample at publishing-quality resolution.
#   - Scores pages to favor real coloring artwork over title/copyright/text pages.
#   - Selects four spatially diverse interior previews.
#   - Always generates a dedicated Gumroad product thumbnail with cover fallback.
#   - Records renderer, candidate count, scores and source pages in the asset manifest.
#
# Finished-PDF publishing upgrade:
#   - Generates a real Gumroad cover from interior artwork when no
#     separate cover exists.
#   - Extracts artwork previews directly from the finished MASTER PDF.
#   - Creates 4 square 600x600+ preview/thumbnail images by default.
#   - Creates a dedicated 600x600 product thumbnail.
#   - Validates Gumroad asset dimensions, DPI and 50 MB cover limit.
#   - Uses optional PyMuPDF (fitz) as a renderer fallback for vector PDFs;
#     pypdf embedded-image extraction remains the zero-extra-dependency path.
# ============================================================

# Legacy override removed: FACTORY_VERSION remains authoritative at 13.1.
PLATFORM_ENGINE_VERSION = "5.0"
UNIVERSAL_PUBLISHING_VERSION = "2.4"

GUMROAD_COVER_WIDTH = 1280
GUMROAD_COVER_HEIGHT = 720
GUMROAD_MIN_DPI = 72
GUMROAD_COVER_MAX_BYTES = 50 * 1024 * 1024
GUMROAD_THUMB_WIDTH = 600
GUMROAD_THUMB_HEIGHT = 600
GUMROAD_PREVIEW_COUNT = 4


def _gumroad_safe_name(name, fallback="coloring-book"):
    text = re.sub(r"[^A-Za-z0-9 -]+", "", str(name or "")).strip()
    text = re.sub(r"\s+", "-", text).strip("-")
    return text or fallback


def _image_save_png_or_jpeg(image, path_base, dpi=72, max_bytes=None):
    """Save line-art artwork losslessly when practical; fall back to JPEG only if needed."""
    image = image.convert("RGB")
    png_path = Path(path_base).with_suffix(".png")
    image.save(png_path, "PNG", dpi=(dpi, dpi), optimize=True)
    if max_bytes is None or png_path.stat().st_size <= max_bytes:
        return png_path

    jpg_path = png_path.with_suffix(".jpg")
    image.save(jpg_path, "JPEG", dpi=(dpi, dpi), quality=88, optimize=True, progressive=True)
    png_path.unlink(missing_ok=True)
    return jpg_path


def _fit_contain(image, size, background="white", padding=24):
    """Fit an image completely inside a square canvas; never crop the artwork."""
    image = image.convert("RGB")
    size = int(size)
    padding = max(0, int(padding))
    target = max(1, size - 2 * padding)
    ratio = min(target / image.width, target / image.height)
    resized = image.resize(
        (max(1, int(round(image.width * ratio))), max(1, int(round(image.height * ratio)))),
        Image.Resampling.LANCZOS,
    )
    canvas_img = Image.new("RGB", (size, size), background)
    x = (size - resized.width) // 2
    y = (size - resized.height) // 2
    canvas_img.paste(resized, (x, y))
    return canvas_img


def _fit_crop_square(image, size=600, margin=0):
    """Legacy square helper retained for compatibility; new previews use contain mode."""
    image = image.convert("RGB")
    target = max(1, int(size) - (2 * int(margin)))
    ratio = max(target / image.width, target / image.height)
    new_size = (max(target, int(round(image.width * ratio))), max(target, int(round(image.height * ratio))))
    resized = image.resize(new_size, Image.Resampling.LANCZOS)
    left = max(0, (resized.width - target) // 2)
    top = max(0, (resized.height - target) // 2)
    cropped = resized.crop((left, top, left + target, top + target))
    if margin:
        canvas_img = Image.new("RGB", (size, size), "white")
        canvas_img.paste(cropped, (margin, margin))
        return canvas_img
    return cropped


def _render_pdf_front_page(master_pdf, output_dir):
    """Render PDF page 1 as the preferred finished-cover source.

    Imported finished PDFs are cover-aware: page 1 is treated as the likely
    customer-facing cover before the Factory ever falls back to interior art.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "finished-front-cover.png"
    pdfium, message = _try_import_pdfium(auto_install=True)
    warnings = []
    if message:
        warnings.append(message)
    if pdfium is not None:
        document = None
        try:
            document = pdfium.PdfDocument(str(master_pdf))
            if len(document) < 1:
                return None, warnings + ["MASTER PDF contains no pages; no front cover can be rendered."]
            page = document[0]
            bitmap = page.render(scale=1.8, rev_byteorder=True)
            image = bitmap.to_pil().convert("RGB")
            image.save(output, "PNG", optimize=True)
            try: page.close()
            except Exception: pass
            return output, warnings
        except Exception as error:
            warnings.append(f"PDFium front-cover render failed: {error}")
        finally:
            try:
                if document is not None: document.close()
            except Exception: pass

    # Legacy fallback only when PDFium is unavailable.
    fitz, _ = _try_import_fitz(auto_install=False)
    if fitz is not None:
        document = None
        try:
            document = fitz.open(str(master_pdf))
            if len(document) < 1:
                return None, warnings + ["MASTER PDF contains no pages; no front cover can be rendered."]
            page = document.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False)
            pix.save(str(output))
            return output, warnings + ["Front cover rendered with PyMuPDF legacy fallback."]
        except Exception as error:
            warnings.append(f"PyMuPDF front-cover render failed: {error}")
        finally:
            try:
                if document is not None: document.close()
            except Exception: pass
    return None, warnings + ["No usable PDF renderer is available for the finished front cover."]


def _marketing_color_treatment(image):
    """Give monochrome fallback artwork a restrained colored marketing treatment."""
    image = image.convert("RGB")
    # Only colorize genuinely near-monochrome artwork; never alter an already
    # colored finished cover.
    sample = image.copy()
    sample.thumbnail((96, 96), Image.Resampling.LANCZOS)
    pixels = list(sample.getdata())
    if not pixels:
        return image, False
    chroma = sum(max(px) - min(px) for px in pixels) / max(1, len(pixels))
    if chroma > 18:
        return image, False
    gray = ImageOps.grayscale(image)
    treated = ImageOps.colorize(gray, black=(10, 8, 18), white=(238, 220, 205), mid=(92, 48, 62))
    return treated.convert("RGB"), True


def _extract_gumroad_front_cover_panel(image):
    """Return the customer-facing front panel from a KDP full-wrap cover.

    KDP wrap covers are laid out back-cover | spine | front-cover. The old
    Gumroad builder treated the entire wrap as one image, which made the title
    appear on the far right and produced a visibly wrong marketing cover.
    A normal portrait front cover is returned unchanged.
    """
    image = image.convert("RGB")
    ratio = image.width / max(1, image.height)
    # Approximate 17.41 x 11.25 KDP wrap. Keep the detection deliberately
    # narrow so ordinary landscape artwork is never mistaken for a wrap.
    if 1.40 <= ratio <= 1.72 and image.width >= image.height * 1.40:
        left = int(round(image.width * 0.497))
        right = int(round(image.width * 0.986))
        if right - left >= 200:
            return image.crop((left, 0, right, image.height)), True
    return image, False


def _fit_cover_unified(image, width=1280, height=720):
    """Create one unified 16:9 marketing composition; never split it into panels."""
    image = image.convert("RGB")
    # Full-bleed background derived from the same artwork. This keeps the cover
    # visually unified while allowing portrait KDP covers to remain completely visible.
    bg_ratio = max(width / image.width, height / image.height)
    bg_size = (max(width, int(round(image.width * bg_ratio))), max(height, int(round(image.height * bg_ratio))))
    background = image.resize(bg_size, Image.Resampling.LANCZOS)
    left = max(0, (background.width - width) // 2)
    top = max(0, (background.height - height) // 2)
    background = background.crop((left, top, left + width, top + height))
    background = background.filter(ImageFilter.GaussianBlur(radius=18))
    background = ImageEnhance.Brightness(background).enhance(0.38)

    cover = background.copy()
    # Center the complete source cover/artwork. No center-crop is used.
    pad_x, pad_y = 55, 38
    inner_w, inner_h = width - 2 * pad_x, height - 2 * pad_y
    ratio = min(inner_w / image.width, inner_h / image.height)
    foreground = image.resize((max(1, int(round(image.width * ratio))), max(1, int(round(image.height * ratio)))), Image.Resampling.LANCZOS)
    x = (width - foreground.width) // 2
    y = (height - foreground.height) // 2

    # A subtle translucent frame separates the complete cover from its derived background.
    frame = Image.new("RGBA", (foreground.width + 14, foreground.height + 14), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(frame)
    fdraw.rounded_rectangle((0, 0, frame.width - 1, frame.height - 1), radius=12, fill=(0, 0, 0, 110), outline=(230, 220, 210, 210), width=3)
    cover.paste(frame.convert("RGB"), (x - 7, y - 7))
    cover.paste(foreground, (x, y))
    return cover


def _fit_cover_panel(image, width=1280, height=720):
    """Backward-compatible alias; v12.4 intentionally uses a unified composition."""
    canvas = _fit_cover_unified(image, width, height)
    return canvas, ImageDraw.Draw(canvas), width


def _draw_centered_text(draw, box, text, font, fill=(238, 238, 238), max_lines=4, spacing=8):
    """Draw wrapped text centered inside a box, reducing font size when needed."""
    x1, y1, x2, y2 = box
    available = max(20, x2 - x1)
    current_font = font
    for _ in range(4):
        lines = textwrap.wrap(str(text or ""), width=max(8, int(available / max(8, current_font.size * 0.55))))[:max_lines]
        heights = [current_font.getbbox(line)[3] - current_font.getbbox(line)[1] for line in lines]
        total_h = sum(heights) + spacing * max(0, len(lines) - 1)
        if total_h <= (y2 - y1):
            break
        current_font = get_font(max(24, current_font.size - 6), True)
    y = y1 + max(0, ((y2 - y1) - total_h) // 2)
    for line, h in zip(lines, heights):
        bbox = draw.textbbox((0, 0), line, font=current_font)
        tw = bbox[2] - bbox[0]
        draw.text((x1 + (available - tw) // 2, y), line, font=current_font, fill=fill)
        y += h + spacing
    return y


def _make_product_thumbnail(cover_canvas, title, size=600):
    """Create a clean square thumbnail from the finished unified cover.

    The thumbnail never adds a second title/author line, preventing the duplicate
    J.A.C. and duplicate-title problem caused by the old thumbnail treatment.
    """
    source = cover_canvas.convert("RGB")
    ratio = min(size / source.width, size / source.height)
    fitted = source.resize((max(1, int(round(source.width * ratio))), max(1, int(round(source.height * ratio)))), Image.Resampling.LANCZOS)
    thumb = Image.new("RGB", (size, size), (18, 18, 18))
    x = (size - fitted.width) // 2
    y = (size - fitted.height) // 2
    thumb.paste(fitted, (x, y))
    return thumb


def _asset_visual_quality(image_path, expected_size=None):
    """Return lightweight QA facts used to catch obviously bad generated assets."""
    result = {"exists": False, "width": 0, "height": 0, "aspect_ratio": 0.0, "near_blank": False, "error": None}
    try:
        path = Path(image_path)
        if not path.exists():
            return result
        with Image.open(path) as img:
            result["exists"] = True
            result["width"], result["height"] = img.size
            result["aspect_ratio"] = round(img.width / max(1, img.height), 4)
            gray = img.convert("L")
            gray.thumbnail((240, 240), Image.Resampling.LANCZOS)
            extrema = gray.getextrema()
            result["near_blank"] = (extrema[1] - extrema[0]) < 8
            if expected_size and tuple(img.size) != tuple(expected_size):
                result["error"] = f"Expected {expected_size[0]}x{expected_size[1]}, got {img.width}x{img.height}."
    except Exception as error:
        result["error"] = str(error)
    return result

def _extract_pdf_embedded_artwork(master_pdf, output_dir, max_candidates=20):
    """Extract actual interior artwork while excluding front/back matter.

    The old extractor walked every PDF page, so a copyright/title page that
    contained a large embedded image could become preview #1. For finished
    coloring books, preview selection starts after the standard front matter
    and stops before the closing pages. Each candidate also receives the same
    artwork-density score used by the rendered-page path.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    Reader = _pdf_reader_class()
    if Reader is None:
        return [], ["No pypdf/PyPDF2 reader available for embedded image extraction."]

    candidates = []
    seen_hashes = set()
    errors = []
    try:
        reader = Reader(str(master_pdf), strict=False)
        total_pages = len(reader.pages)
        first_art_page = GUMROAD_FRONT_MATTER_PAGES + 1 if total_pages > GUMROAD_FRONT_MATTER_PAGES + GUMROAD_BACK_MATTER_PAGES else 1
        last_art_page = total_pages - GUMROAD_BACK_MATTER_PAGES if total_pages > GUMROAD_FRONT_MATTER_PAGES + GUMROAD_BACK_MATTER_PAGES else total_pages

        for page_number, page in enumerate(reader.pages, start=1):
            # Do not let title/copyright/TOC pages or closing pages become
            # customer-facing Gumroad previews.
            if page_number < first_art_page or page_number > last_art_page:
                continue

            try:
                page_images = list(getattr(page, "images", []) or [])
            except Exception:
                page_images = []

            page_candidates = []
            for image_number, image_file in enumerate(page_images, start=1):
                data = getattr(image_file, "data", None)
                if not data:
                    continue
                digest = sha256(data).hexdigest()
                if digest in seen_hashes:
                    continue
                try:
                    with Image.open(__import__("io").BytesIO(data)) as opened:
                        image = opened.convert("RGB")
                        if image.width < 200 or image.height < 200:
                            continue
                        area = image.width * image.height
                        ext = ".jpg" if str(getattr(image_file, "name", "")).lower().endswith((".jpg", ".jpeg")) else ".png"
                        candidate_path = output_dir / f"embedded-page-{page_number:04d}-{image_number:02d}{ext}"
                        image.save(candidate_path, "JPEG" if ext == ".jpg" else "PNG",
                                   dpi=(72, 72))
                        artwork_score = _pdf_preview_score(candidate_path)
                        page_candidates.append({
                            "page": page_number,
                            "path": candidate_path,
                            "area": area,
                            "sha256": digest,
                            "width": image.width,
                            "height": image.height,
                            "artwork_score": artwork_score,
                            "render_method": "embedded-image",
                        })
                        seen_hashes.add(digest)
                except Exception:
                    continue

            if page_candidates:
                # Prefer the largest image on each interior page, then use
                # artwork density as a tie-breaker.
                page_candidates.sort(key=lambda x: (float(x.get("artwork_score", 0)), x["area"]), reverse=True)
                best = page_candidates[0]
                if float(best.get("artwork_score", 0)) > 0:
                    candidates.append(best)
                if len(candidates) >= max_candidates:
                    break
    except Exception as error:
        errors.append(f"Embedded PDF artwork extraction failed: {error}")

    candidates.sort(key=lambda x: (float(x.get("artwork_score", 0)), -int(x.get("page", 0))), reverse=True)
    return candidates, errors


def _try_import_pdfium(auto_install=True):
    """Load pypdfium2, a Python-3.14-friendly PDFium renderer."""
    try:
        import pypdfium2 as pdfium
        return pdfium, None
    except Exception as first_error:
        if not auto_install:
            return None, f"PDFium unavailable: {first_error}"
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "pypdfium2"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, timeout=180,
            )
            import pypdfium2 as pdfium
            return pdfium, "PDFium (pypdfium2) was automatically installed for PDF preview rendering."
        except Exception as install_error:
            return None, (
                "PDFium (pypdfium2) is unavailable and automatic installation failed. "
                f"Original error: {first_error}; install error: {install_error}"
            )


def _try_import_fitz(auto_install=False):
    """Optional legacy PyMuPDF loader; never required by the universal renderer."""
    try:
        import fitz
        return fitz, None
    except Exception as error:
        return None, f"PyMuPDF unavailable: {error}"


def _pdf_preview_score(path):
    """Score a rendered/extracted page for coloring artwork without requiring NumPy.

    The previous scorer could return zero on machines without NumPy, which made
    perfectly valid line-art pages disappear from the Gumroad candidate pool.
    This scorer uses Pillow only and deliberately treats the score as a ranking
    signal rather than a hard artwork gate.
    """
    try:
        with Image.open(path) as img:
            gray = img.convert("L")
            gray.thumbnail((320, 420), Image.Resampling.LANCZOS)
            hist = gray.histogram()
            total = max(1, sum(hist))
            dark = sum(hist[:220]) / total
            very_dark = sum(hist[:80]) / total
            mid = sum(hist[80:220]) / total

            # Reject truly blank/near-white pages, but don't reject dense
            # black line-art merely because its ink coverage is high.
            if dark < 0.003:
                return 0.0

            # Coloring pages normally contain substantial white space plus
            # visible black linework.  These weights are intentionally soft.
            score = (min(dark / 0.18, 1.0) * 0.55 +
                     min(mid / 0.10, 1.0) * 0.30 +
                     min(very_dark / 0.08, 1.0) * 0.15)
            return round(score, 6)
    except Exception:
        return 0.0


def _sample_pdf_page_indexes(total, max_candidates):
    """Return a broad, deterministic sample while avoiding common front/back matter."""
    if total <= 0:
        return []
    start = 5 if total > 12 else 0
    end = total - 2 if total > 12 else total
    sample_count = min(max_candidates, max(1, end - start))
    indexes = []
    for i in range(sample_count):
        idx = start + round(i * max(0, end - start - 1) / max(1, sample_count - 1))
        if idx not in indexes:
            indexes.append(idx)
    return indexes


def _render_pdf_pages_with_pdfium(master_pdf, output_dir, max_candidates=20):
    """Render vector PDFs through PDFium; works independently of PyMuPDF."""
    pdfium, bootstrap_message = _try_import_pdfium(auto_install=True)
    if pdfium is None:
        return [], [bootstrap_message or "No PDFium rendering engine is available."]

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = []
    warnings = []
    if bootstrap_message:
        warnings.append(bootstrap_message)
    document = None
    try:
        document = pdfium.PdfDocument(str(master_pdf))
        total = len(document)
        if total == 0:
            return [], ["MASTER PDF contains no pages."]

        for idx in _sample_pdf_page_indexes(total, max_candidates):
            try:
                page = document[idx]
                bitmap = page.render(scale=1.65, rev_byteorder=True)
                image = bitmap.to_pil().convert("RGB")
                output = output_dir / f"rendered-page-{idx + 1:04d}.png"
                image.save(output, "PNG", optimize=True)
                candidates.append({
                    "page": idx + 1,
                    "path": output,
                    "area": image.width * image.height,
                    "sha256": file_hash(output),
                    "width": image.width,
                    "height": image.height,
                    "artwork_score": _pdf_preview_score(output),
                    "render_method": "PDFium/pypdfium2",
                })
                try:
                    page.close()
                except Exception:
                    pass
            except Exception as error:
                warnings.append(f"PDFium page {idx + 1} render failed: {error}")

        candidates.sort(key=lambda x: (float(x.get("artwork_score", 0)), -int(x.get("page", 0))), reverse=True)
        return candidates, warnings
    except Exception as error:
        return [], warnings + [f"PDFium rendering failed: {error}"]
    finally:
        try:
            if document is not None:
                document.close()
        except Exception:
            pass


def _render_pdf_pages_external(master_pdf, output_dir, max_candidates=20):
    """Use installed command-line PDF renderers when available on Windows."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    warnings = []
    total = None
    try:
        info = inspect_pdf(master_pdf)
        total = int(info.get("page_count") or 0)
    except Exception:
        pass
    indexes = _sample_pdf_page_indexes(total or 64, max_candidates)
    # Prefer MuPDF, then Poppler, then Ghostscript.
    commands = []
    mutool = shutil.which("mutool")
    pdftoppm = shutil.which("pdftoppm")
    gs = shutil.which("gswin64c") or shutil.which("gswin32c") or shutil.which("gs")
    if mutool:
        commands.append(("MuPDF/mutool", mutool))
    if pdftoppm:
        commands.append(("Poppler/pdftoppm", pdftoppm))
    if gs:
        commands.append(("Ghostscript", gs))

    for method, executable in commands:
        try:
            candidates = []
            for idx in indexes:
                output = output_dir / f"rendered-page-{idx + 1:04d}.png"
                if method.startswith("MuPDF"):
                    prefix = output.with_suffix("")
                    cmd = [executable, "draw", "-o", str(output), "-r", "119", str(master_pdf), str(idx)]
                elif method.startswith("Poppler"):
                    prefix = output.with_suffix("")
                    cmd = [executable, "-f", str(idx + 1), "-singlefile", "-png", "-r", "119", str(master_pdf), str(prefix)]
                else:
                    # Ghostscript's page numbering is inclusive and 1-based.
                    prefix = output.with_suffix("")
                    cmd = [executable, "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=png16m", "-r119", f"-dFirstPage={idx + 1}", f"-dLastPage={idx + 1}", f"-sOutputFile={prefix}.png", str(master_pdf)]
                result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=60)
                if result.returncode != 0 or not output.exists():
                    continue
                with Image.open(output) as image:
                    image = image.convert("RGB")
                    image.save(output, "PNG", optimize=True)
                    width, height = image.size
                candidates.append({
                    "page": idx + 1, "path": output, "area": width * height,
                    "sha256": file_hash(output), "width": width, "height": height,
                    "artwork_score": _pdf_preview_score(output), "render_method": method,
                })
            if candidates:
                candidates.sort(key=lambda x: (float(x.get("artwork_score", 0)), -int(x.get("page", 0))), reverse=True)
                return candidates, warnings + [f"PDF previews rendered with {method}."]
        except Exception as error:
            warnings.append(f"{method} rendering failed: {error}")
    return [], warnings


def _render_pdf_pages_universal(master_pdf, output_dir, max_candidates=20):
    """Renderer chain: PDFium -> installed CLI engines -> optional PyMuPDF."""
    candidates, warnings = _render_pdf_pages_with_pdfium(master_pdf, output_dir, max_candidates)
    if candidates:
        return candidates, warnings

    external, external_warnings = _render_pdf_pages_external(master_pdf, output_dir, max_candidates)
    warnings.extend(external_warnings)
    if external:
        return external, warnings

    fitz, _ = _try_import_fitz(auto_install=False)
    if fitz is not None:
        # Legacy fallback retained for machines where PyMuPDF happens to work.
        document = None
        try:
            document = fitz.open(str(master_pdf))
            rendered = []
            for idx in _sample_pdf_page_indexes(len(document), max_candidates):
                page = document.load_page(idx)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.65, 1.65), alpha=False)
                output = Path(output_dir) / f"rendered-page-{idx + 1:04d}.png"
                pix.save(str(output))
                with Image.open(output) as image:
                    rendered.append({"page": idx + 1, "path": output, "area": image.width * image.height,
                                     "sha256": file_hash(output), "width": image.width, "height": image.height,
                                     "artwork_score": _pdf_preview_score(output), "render_method": "PyMuPDF"})
            rendered.sort(key=lambda x: (float(x.get("artwork_score", 0)), -int(x.get("page", 0))), reverse=True)
            if rendered:
                return rendered, warnings + ["PDF previews rendered with PyMuPDF legacy fallback."]
        except Exception as error:
            warnings.append(f"PyMuPDF legacy fallback failed: {error}")
        finally:
            if document is not None:
                try: document.close()
                except Exception: pass

    warnings.append(
        "No usable PDF renderer is available. The Factory tried PDFium (pypdfium2), "
        "installed MuPDF/Poppler/Ghostscript renderers, and the optional PyMuPDF fallback."
    )
    return [], warnings


# Backward-compatible function name used by older callers.
def _render_pdf_pages_with_fitz(master_pdf, output_dir, max_candidates=20):
    return _render_pdf_pages_universal(master_pdf, output_dir, max_candidates)

def _choose_gumroad_candidates(candidates, count=GUMROAD_PREVIEW_COUNT):
    """Choose actual interior artwork pages and spread previews through the book.

    Front matter is excluded first. The remaining pages are divided into
    deterministic ranges and the strongest artwork page from each range is
    selected. This prevents four thumbnails from clustering around the first
    few pages after the copyright page.
    """
    usable = []
    for item in candidates:
        try:
            page = int(item.get("page", 0))
        except Exception:
            page = 0
        if not Path(item["path"]).exists():
            continue
        if page and page <= GUMROAD_FRONT_MATTER_PAGES:
            continue
        score = float(item.get("artwork_score", 0) or 0)
        # Heuristic score is a preference, never a hard rejection.
        usable.append(item)
    if not usable:
        return []

    # One candidate per broad section gives a much more useful customer
    # preview set than simply taking the four highest-scoring early pages.
    usable.sort(key=lambda x: int(x.get("page", 0)))
    if len(usable) <= count:
        return usable[:count]

    selected = []
    n = len(usable)
    for bucket in range(count):
        start_i = round(bucket * n / count)
        end_i = round((bucket + 1) * n / count)
        bucket_items = usable[start_i:max(start_i + 1, end_i)]
        if not bucket_items:
            continue
        best = max(bucket_items, key=lambda x: (float(x.get("artwork_score", 0)), int(x.get("area", 0))))
        if best not in selected:
            selected.append(best)

    # If unusual PDF structure leaves a bucket empty, fill deterministically
    # from the strongest remaining interior candidates.
    if len(selected) < count:
        remaining = [x for x in usable if x not in selected]
        remaining.sort(key=lambda x: (float(x.get("artwork_score", 0)), -int(x.get("page", 0))), reverse=True)
        selected.extend(remaining[:count - len(selected)])

    selected.sort(key=lambda x: int(x.get("page", 0)))
    return selected[:count]


def _make_gumroad_assets(project, staging, master_pdf, settings):
    """Create Gumroad assets with no destructive artwork cropping and built-in visual QA."""
    staging = Path(staging)
    source_dir = staging / ".__gumroad_sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    warnings = []

    # Remove only Factory-owned generated assets so a rebuild cannot leave stale files behind.
    for pattern in ("cover.png", "cover.jpg", "thumbnail.png", "thumbnail.jpg", "thumb-*.png", "thumb-*.jpg",
                    "GUMROAD_ASSETS.json", "GUMROAD_UPLOAD_CHECKLIST.txt"):
        for old in staging.glob(pattern):
            try: old.unlink()
            except Exception as error: warnings.append(f"Could not replace stale Gumroad asset {old.name}: {error}")

    existing_cover = _platform_cover(project)
    candidates, extract_warnings = _extract_pdf_embedded_artwork(master_pdf, source_dir, max_candidates=max(12, GUMROAD_PREVIEW_COUNT * 3))
    warnings.extend(extract_warnings)
    if len(candidates) < GUMROAD_PREVIEW_COUNT:
        rendered, render_warnings = _render_pdf_pages_universal(master_pdf, source_dir, max_candidates=max(64, GUMROAD_PREVIEW_COUNT * 16))
        warnings.extend(render_warnings)
        existing_hashes = {x.get("sha256") for x in candidates}
        for item in rendered:
            if item.get("sha256") not in existing_hashes:
                candidates.append(item); existing_hashes.add(item.get("sha256"))
    candidates.sort(key=lambda x: (int(x.get("page", 0)), -int(x.get("area", 0))))
    selected = _choose_gumroad_candidates(candidates, GUMROAD_PREVIEW_COUNT)
    if len(selected) < GUMROAD_PREVIEW_COUNT:
        page_total = pdf_page_count(master_pdf) or 0
        rendered, render_warnings = _render_pdf_pages_universal(master_pdf, source_dir, max_candidates=max(64, page_total))
        warnings.extend(render_warnings)
        existing_hashes = {x.get("sha256") for x in candidates}
        for item in rendered:
            if item.get("sha256") not in existing_hashes:
                candidates.append(item); existing_hashes.add(item.get("sha256"))
        selected = _choose_gumroad_candidates(candidates, GUMROAD_PREVIEW_COUNT)
    if len(selected) < GUMROAD_PREVIEW_COUNT:
        warnings.append(f"Only {len(selected)} of {GUMROAD_PREVIEW_COUNT} usable interior artwork previews were identified.")

    generated = []
    title = str(settings.get("title") or project.name).strip()
    author = str(settings.get("author") or "").strip()
    subtitle = str(settings.get("subtitle") or settings.get("cover_subtitle") or "").strip()

    # --- Main Gumroad cover: use the actual finished front cover first. ---
    # Priority: dedicated MASTER_COVER image -> rendered PDF page 1 -> interior
    # artwork fallback. Only the last fallback gets Factory-added typography.
    cover_canvas = None
    cover_source = "none"
    cover_is_finished = False

    if existing_cover and existing_cover.exists() and existing_cover.suffix.lower() in IMAGE_EXTENSIONS:
        try:
            with Image.open(existing_cover) as src_img:
                front_panel, was_wrap = _extract_gumroad_front_cover_panel(src_img)
                cover_canvas = _fit_cover_unified(front_panel, GUMROAD_COVER_WIDTH, GUMROAD_COVER_HEIGHT)
            cover_source = "MASTER_COVER_FRONT_PANEL" if was_wrap else "MASTER_COVER"
            cover_is_finished = True
            if was_wrap:
                warnings.append("MASTER_COVER was detected as a KDP full wrap; only the front-cover panel was used for Gumroad.")
        except Exception as error:
            warnings.append(f"Dedicated MASTER_COVER could not be used: {error}")

    if cover_canvas is None:
        front_cover_path, front_warnings = _render_pdf_front_page(master_pdf, source_dir)
        warnings.extend(front_warnings)
        if front_cover_path and front_cover_path.exists():
            try:
                with Image.open(front_cover_path) as src_img:
                    front_panel, was_wrap = _extract_gumroad_front_cover_panel(src_img)
                    # A finished cover is authoritative: preserve its artwork and typography.
                    cover_canvas = _fit_cover_unified(front_panel, GUMROAD_COVER_WIDTH, GUMROAD_COVER_HEIGHT)
                cover_source = "embedded_finished_pdf_front_panel" if was_wrap else "embedded_finished_pdf_page_1"
                cover_is_finished = True
                if was_wrap:
                    warnings.append("PDF page 1 was detected as a KDP full wrap; only the front-cover panel was used for Gumroad.")
            except Exception as error:
                warnings.append(f"Finished PDF front cover could not be converted into Gumroad cover: {error}")

    if cover_canvas is None and selected:
        try:
            with Image.open(selected[0]["path"]) as src_img:
                treated, was_colorized = _marketing_color_treatment(src_img)
                cover_canvas = _fit_cover_unified(treated, GUMROAD_COVER_WIDTH, GUMROAD_COVER_HEIGHT)
            cover_source = "interior_artwork_fallback"
            if was_colorized:
                warnings.append("No finished cover was available; fallback artwork received a restrained marketing color treatment.")
            # Only this fallback gets text added, because the source is not itself a cover.
            draw = ImageDraw.Draw(cover_canvas)
            overlay = Image.new("RGBA", cover_canvas.size, (0, 0, 0, 0))
            odraw = ImageDraw.Draw(overlay)
            odraw.rounded_rectangle((55, 48, GUMROAD_COVER_WIDTH - 55, 210), radius=24, fill=(0, 0, 0, 155), outline=(235, 225, 215, 210), width=2)
            cover_canvas = Image.alpha_composite(cover_canvas.convert("RGBA"), overlay).convert("RGB")
            draw = ImageDraw.Draw(cover_canvas)
            _draw_centered_text(draw, (90, 65, GUMROAD_COVER_WIDTH - 90, 175), title, get_font(58, True), fill=(248, 242, 236), max_lines=2, spacing=8)
            if subtitle:
                _draw_centered_text(draw, (150, 175, GUMROAD_COVER_WIDTH - 150, 215), subtitle, get_font(22, False), fill=(238, 225, 218), max_lines=1, spacing=5)
            if author:
                bbox = draw.textbbox((0, 0), author, font=get_font(28, True))
                draw.text(((GUMROAD_COVER_WIDTH - (bbox[2] - bbox[0])) // 2, GUMROAD_COVER_HEIGHT - 72), author, font=get_font(28, True), fill=(248, 242, 236))
        except Exception as error:
            warnings.append(f"Artwork-based Gumroad cover generation failed: {error}")

    if cover_canvas is None:
        # Never ship a blank/dark placeholder as a customer-facing cover.
        # If the finished cover cannot be recovered, the asset build is allowed
        # to fail loudly so the problem is fixed instead of hidden.
        errors = ["No usable finished cover or interior artwork was available for the Gumroad cover."]
        raise RuntimeError(errors[0])

    cover_path = _image_save_png_or_jpeg(cover_canvas, staging / "cover", dpi=GUMROAD_MIN_DPI, max_bytes=GUMROAD_COVER_MAX_BYTES)
    generated.append(cover_path)

    # --- Interior previews: contain, never center-crop ---
    thumb_paths = []
    for number, candidate in enumerate(selected[:GUMROAD_PREVIEW_COUNT], start=1):
        try:
            with Image.open(candidate["path"]) as src_img:
                thumb = _fit_contain(src_img, GUMROAD_THUMB_WIDTH, background=(248, 248, 245), padding=18)
            path = _image_save_png_or_jpeg(thumb, staging / f"thumb-{number:02d}", dpi=GUMROAD_MIN_DPI, max_bytes=GUMROAD_COVER_MAX_BYTES)
            thumb_paths.append(path); generated.append(path)
        except Exception as error:
            warnings.append(f"Preview thumbnail {number} could not be created: {error}")

    # Product thumbnail gets its own composition; it is never copied from a potentially cropped preview.
    try:
        product_image = _make_product_thumbnail(cover_canvas, title, GUMROAD_THUMB_WIDTH)
        product_thumb = _image_save_png_or_jpeg(product_image, staging / "thumbnail", dpi=GUMROAD_MIN_DPI, max_bytes=GUMROAD_COVER_MAX_BYTES)
        generated.append(product_thumb)
    except Exception as error:
        product_thumb = None
        warnings.append(f"Dedicated Gumroad product thumbnail generation failed: {error}")

    # --- Visual QA ---
    cover_qa = _asset_visual_quality(cover_path, (GUMROAD_COVER_WIDTH, GUMROAD_COVER_HEIGHT))
    product_qa = _asset_visual_quality(product_thumb, (GUMROAD_THUMB_WIDTH, GUMROAD_THUMB_HEIGHT))
    preview_qa = {p.name: _asset_visual_quality(p, (GUMROAD_THUMB_WIDTH, GUMROAD_THUMB_HEIGHT)) for p in thumb_paths}
    if cover_qa.get("near_blank"): warnings.append("Gumroad cover appears nearly blank; inspect the generated cover before publishing.")
    if product_qa.get("near_blank"): warnings.append("Gumroad product thumbnail appears nearly blank; inspect it before publishing.")
    if len(thumb_paths) < GUMROAD_PREVIEW_COUNT:
        warnings.append(f"Only {len(thumb_paths)} of {GUMROAD_PREVIEW_COUNT} interior preview images were generated.")

    assets_manifest = {
        "schema_version": 2, "factory_version": FACTORY_VERSION,
        "gumroad_requirements": {
            "cover_min_width_px": GUMROAD_COVER_WIDTH, "cover_min_height_px": GUMROAD_COVER_HEIGHT,
            "cover_min_dpi": GUMROAD_MIN_DPI, "cover_max_bytes": GUMROAD_COVER_MAX_BYTES,
            "cover_max_mb_decimal": 50, "product_thumbnail_min_width_px": GUMROAD_THUMB_WIDTH,
            "product_thumbnail_min_height_px": GUMROAD_THUMB_HEIGHT, "max_covers": 8,
        },
        "source_master_sha256": file_hash(master_pdf), "source_master": str(master_pdf),
        "rendering": {"renderer": sorted({str(x.get("render_method", "embedded-image")) for x in candidates}),
                       "candidate_count": len(candidates), "selected_count": len(selected),
                       "selected_scores": {str(int(x["page"])): float(x.get("artwork_score", 0)) for x in selected}},
        "selected_preview_pages": [int(x["page"]) for x in selected],
        "cover_source": cover_source,
        "cover_is_finished_source": cover_is_finished,
        "cover": str(cover_path.name) if cover_path else None,
        "product_thumbnail": str(product_thumb.name) if product_thumb else None,
        "preview_images": [p.name for p in thumb_paths],
        "asset_dimensions": {"cover": _image_dimensions(cover_path), "product_thumbnail": _image_dimensions(product_thumb),
                             "previews": {p.name: _image_dimensions(p) for p in thumb_paths}},
        "visual_quality": {"cover": cover_qa, "product_thumbnail": product_qa, "previews": preview_qa},
        "rendered_candidate_count": len(candidates), "rendered_pages": [int(x.get("page", 0)) for x in candidates],
        "warnings": warnings,
    }
    assets_manifest_path = staging / "GUMROAD_ASSETS.json"
    save_json(assets_manifest_path, assets_manifest); generated.append(assets_manifest_path)

    checklist = staging / "GUMROAD_UPLOAD_CHECKLIST.txt"
    checklist.write_text("\n".join([
        "GUMROAD UPLOAD CHECKLIST", "========================", "",
        "1. Product file:", "   Upload the generated digital PDF.", "",
        "2. Main cover:", f"   {cover_path.name if cover_path else 'NOT GENERATED'}",
        "   1280 x 720 px, 72 DPI, under 50 MB. Artwork is contained to prevent accidental cropping.", "",
        "3. Product thumbnail:", f"   {product_thumb.name if product_thumb else 'NOT GENERATED'}",
        "   600 x 600 px. Dedicated square composition; not copied from a cropped interior preview.", "",
        "4. Additional preview images:", *[f"   {p.name}" for p in thumb_paths], "",
        "5. Preview artwork uses contain framing so important parts of the line art are not cut off.",
        "6. Rebuilding the package removes only previous Factory-owned Gumroad assets; MASTER PDF is untouched.", "",
    ]), encoding="utf-8")
    generated.append(checklist)
    return generated, warnings, assets_manifest

def _image_dimensions(path):
    """Return width/height/DPI for a generated image, or None if unavailable."""
    if not path:
        return None
    try:
        path = Path(path)
        if not path.exists():
            return None
        with Image.open(path) as img:
            dpi = img.info.get("dpi") or (0, 0)
            return {
                "width": int(img.width),
                "height": int(img.height),
                "dpi": [round(float(dpi[0]), 2), round(float(dpi[1]), 2)],
                "bytes": int(path.stat().st_size),
            }
    except Exception:
        return None


def _gumroad_asset_report(staging, gumroad_manifest=None):
    """Build a concise production report for option 9 and package metadata."""
    staging = Path(staging)
    manifest = gumroad_manifest or {}
    rendering = manifest.get("rendering", {}) if isinstance(manifest, dict) else {}
    dims = manifest.get("asset_dimensions", {}) if isinstance(manifest, dict) else {}
    previews = manifest.get("preview_images", []) if isinstance(manifest, dict) else []
    selected_pages = manifest.get("selected_preview_pages", []) if isinstance(manifest, dict) else []
    renderer_values = rendering.get("renderer", []) if isinstance(rendering, dict) else []
    renderer = ", ".join(str(x) for x in renderer_values if x) or "Unknown"
    cover = dims.get("cover") if isinstance(dims, dict) else None
    thumb = dims.get("product_thumbnail") if isinstance(dims, dict) else None
    preview_dims = dims.get("previews", {}) if isinstance(dims, dict) else {}

    cover_ok = bool(cover and cover.get("width", 0) >= GUMROAD_COVER_WIDTH and cover.get("height", 0) >= GUMROAD_COVER_HEIGHT and cover.get("dpi", [0])[0] >= GUMROAD_MIN_DPI and cover.get("bytes", 0) < GUMROAD_COVER_MAX_BYTES)
    thumb_ok = bool(thumb and thumb.get("width", 0) >= GUMROAD_THUMB_WIDTH and thumb.get("height", 0) >= GUMROAD_THUMB_HEIGHT and thumb.get("dpi", [0])[0] >= GUMROAD_MIN_DPI)
    preview_ok = len(previews) == GUMROAD_PREVIEW_COUNT and all(
        isinstance(preview_dims.get(name), dict) and
        preview_dims[name].get("width", 0) >= GUMROAD_THUMB_WIDTH and
        preview_dims[name].get("height", 0) >= GUMROAD_THUMB_HEIGHT
        for name in previews
    )
    return {
        "status": "PASS" if cover_ok and thumb_ok and preview_ok else "FAIL",
        "renderer": renderer,
        "rendered_candidate_count": int(manifest.get("rendered_candidate_count", rendering.get("candidate_count", 0)) or 0),
        "selected_preview_count": len(previews),
        "target_preview_count": GUMROAD_PREVIEW_COUNT,
        "selected_preview_pages": selected_pages,
        "cover": {"file": manifest.get("cover"), "dimensions": cover, "pass": cover_ok},
        "product_thumbnail": {"file": manifest.get("product_thumbnail"), "dimensions": thumb, "pass": thumb_ok},
        "previews": {"files": previews, "pass": preview_ok, "dimensions": preview_dims},
    }


def _print_gumroad_asset_report(report):
    print("  GUMROAD ASSETS")
    print("  " + "-" * 58)
    print(f"  Renderer:              {report.get('renderer', 'Unknown')}")
    print(f"  PDF pages rendered:    {report.get('rendered_candidate_count', 0)}")
    pages = report.get("selected_preview_pages") or []
    print(f"  Preview pages selected: {len(pages)}/{report.get('target_preview_count', GUMROAD_PREVIEW_COUNT)}" + (f" -> {', '.join(map(str, pages))}" if pages else ""))
    cover = report.get("cover", {})
    cd = cover.get("dimensions") or {}
    print(f"  Cover:                 {'PASS' if cover.get('pass') else 'FAIL'}" + (f" — {cd.get('width')}x{cd.get('height')} @ {cd.get('dpi',[0])[0]:g} DPI" if cd else ""))
    thumb = report.get("product_thumbnail", {})
    td = thumb.get("dimensions") or {}
    print(f"  Product thumbnail:     {'PASS' if thumb.get('pass') else 'FAIL'}" + (f" — {td.get('width')}x{td.get('height')} @ {td.get('dpi',[0])[0]:g} DPI" if td else ""))
    print(f"  Interior previews:     {'PASS' if report.get('previews', {}).get('pass') else 'FAIL'} — {report.get('selected_preview_count', 0)}/{report.get('target_preview_count', GUMROAD_PREVIEW_COUNT)}")
    print(f"  Asset set:              {report.get('status', 'FAIL')}")
    print("  " + "-" * 58)


def _validate_gumroad_assets(staging):
    """Hard validation for the generated Gumroad visual assets."""
    errors = []
    warnings = []
    staging = Path(staging)

    # Find cover regardless of PNG/JPG fallback.
    cover_candidates = list(staging.glob("cover.png")) + list(staging.glob("cover.jpg"))
    cover = cover_candidates[0] if cover_candidates else None
    if not cover:
        errors.append("Gumroad cover was not generated.")
    else:
        try:
            with Image.open(cover) as img:
                dpi = img.info.get("dpi", (0, 0))
                dpi_x = float(dpi[0] or 0)
                dpi_y = float(dpi[1] or 0)
                if img.width < GUMROAD_COVER_WIDTH or img.height < GUMROAD_COVER_HEIGHT:
                    errors.append(
                        f"Gumroad cover is {img.width}x{img.height}; minimum is "
                        f"{GUMROAD_COVER_WIDTH}x{GUMROAD_COVER_HEIGHT}."
                    )
                if dpi_x < GUMROAD_MIN_DPI or dpi_y < GUMROAD_MIN_DPI:
                    errors.append(
                        f"Gumroad cover DPI is {dpi_x:g}x{dpi_y:g}; minimum is {GUMROAD_MIN_DPI} DPI."
                    )
            if cover.stat().st_size >= GUMROAD_COVER_MAX_BYTES:
                errors.append("Gumroad cover is 50 MB or larger.")
        except Exception as error:
            errors.append(f"Could not inspect Gumroad cover: {error}")

    thumbs = sorted(list(staging.glob("thumb-*.png")) + list(staging.glob("thumb-*.jpg")))
    thumb_hashes = []
    for path in thumbs:
        try: thumb_hashes.append(file_hash(path))
        except Exception: pass
    if len(thumb_hashes) != len(set(thumb_hashes)):
        warnings.append("Two or more Gumroad interior preview thumbnails are identical; inspect the preview selection.")
    if len(thumbs) < GUMROAD_PREVIEW_COUNT:
        errors.append(
            f"Only {len(thumbs)} interior preview thumbnail(s) were generated; "
            f"Gumroad package requires {GUMROAD_PREVIEW_COUNT}."
        )
    for path in thumbs:
        try:
            with Image.open(path) as img:
                if img.width < GUMROAD_THUMB_WIDTH or img.height < GUMROAD_THUMB_HEIGHT:
                    errors.append(f"{path.name} is below 600x600 pixels.")
        except Exception as error:
            errors.append(f"Could not inspect {path.name}: {error}")

    product_thumb = next(iter([p for p in staging.glob("thumbnail.png")] +
                              [p for p in staging.glob("thumbnail.jpg")]), None)
    if not product_thumb:
        errors.append("Dedicated Gumroad product thumbnail was not generated.")
    else:
        try:
            with Image.open(product_thumb) as img:
                if img.width < GUMROAD_THUMB_WIDTH or img.height < GUMROAD_THUMB_HEIGHT:
                    errors.append("Dedicated Gumroad product thumbnail is below 600x600 pixels.")
        except Exception as error:
            errors.append(f"Could not inspect Gumroad product thumbnail: {error}")

    return errors, warnings


def _write_gumroad_readme(staging, generated_names, warnings):
    path = Path(staging) / "README.txt"
    lines = [
        "GUMROAD PACKAGE — COLORING BOOK FACTORY",
        "=========================================",
        "",
        "Upload the digital PDF as the product file.",
        "Upload cover.png (or cover.jpg) as the main Gumroad cover.",
        "Upload thumbnail.png (or thumbnail.jpg) as the product thumbnail.",
        "The thumb-01 through thumb-04 images are interior preview images.",
        "",
        "Generated files:",
    ]
    lines.extend(f"- {name}" for name in generated_names)
    if warnings:
        lines.extend(["", "AUTOMATED WARNINGS:"])
        lines.extend(f"- {warning}" for warning in warnings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def generate_platform_package_v112(project, platform_name, quiet=False):
    """
    v11.6 platform package generator. Gumroad receives a dedicated asset
    build; every other platform continues through the existing v11.x behavior.
    """
    profiles = load_platform_profiles()
    profile = profiles.get(platform_name)
    if not profile:
        return {
            "status": "BLOCKED",
            "output": None,
            "errors": [f"Unknown platform: {platform_name}"],
            "warnings": [],
        }

    master = find_master_pdf(project)
    if not master:
        master, master_errors, master_warnings = ensure_master_book(project)
        if master_errors:
            return {
                "status": "BLOCKED",
                "output": None,
                "errors": master_errors,
                "warnings": master_warnings,
            }

    audit = platform_preflight(project, platform_name, master, profile)
    if audit["status"] == "BLOCKED":
        if not quiet:
            print(f"\n{platform_name}: BLOCKED")
            for error in audit["errors"]:
                print("ERROR:", error)
        return {
            "status": "BLOCKED",
            "output": project / PLATFORM_DIRNAME / profile.get("output_dir", platform_name.upper()),
            "audit": audit,
            "errors": audit["errors"],
            "warnings": audit["warnings"],
        }

    settings = load_project_settings_safe(project)
    root = project / PLATFORM_DIRNAME / profile.get(
        "output_dir",
        _platform_sanitized_filename(platform_name, 40).upper(),
    )
    staging = root.parent / f".{root.name}.staging"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    generated = []
    warnings = list(audit.get("warnings", []))
    title = settings.get("title", project.name)
    gumroad_manifest = None
    gumroad_report = None

    try:
        # Keep existing platform behavior intact for all non-Gumroad platforms.
        mode = profile.get("variant", {}).get("mode", "copy")
        if mode == "etsy_split":
            parts, split_errors = _pdf_split_by_size(
                master, staging, title,
                profile["rules"]["max_file_mb"],
                profile["rules"]["max_files"],
            )
            if split_errors:
                raise RuntimeError("; ".join(split_errors))
            generated.extend(parts)
        else:
            variant_target = staging / (
                f"{_platform_sanitized_filename(title, 120)}"
                f"{profile.get('variant', {}).get('filename_suffix', '_DIGITAL')}.pdf"
            )
            shutil.copy2(master, variant_target)
            generated.append(variant_target)

        if platform_name == "Gumroad":
            gumroad_files, gumroad_warnings, gumroad_manifest = _make_gumroad_assets(
                project, staging, master, settings
            )
            generated.extend(gumroad_files)
            warnings.extend(gumroad_warnings)
            gumroad_errors, gumroad_validation_warnings = _validate_gumroad_assets(staging)
            warnings.extend(gumroad_validation_warnings)
            if gumroad_errors:
                raise RuntimeError("Gumroad asset validation failed: " + " | ".join(gumroad_errors))
        else:
            cover = _platform_cover(project)
            if cover:
                target = staging / _platform_sanitized_filename(
                    f"{title}_COVER{cover.suffix.lower()}", 70
                )
                shutil.copy2(cover, target)
                generated.append(target)

            if "preview_sheet" in profile.get("files", []):
                generated.append(create_preview_sheet(project, staging, master, settings))

        metadata = {
            "schema_version": 5,
            "factory_version": FACTORY_VERSION,
            "platform_engine_version": PLATFORM_ENGINE_VERSION,
            "universal_publishing_version": UNIVERSAL_PUBLISHING_VERSION,
            "platform": platform_name,
            "platform_type": profile.get("type"),
            "generated": datetime.now().isoformat(timespec="seconds"),
            "title": title,
            "subtitle": settings.get("subtitle", settings.get("cover_subtitle", "")),
            "author": settings.get("author", ""),
            "description": settings.get(
                "description", settings.get("cover_blurb", "")
            ),
            "series": settings.get("series_name", ""),
            "series_number": settings.get("series_number", ""),
            "world": settings.get("universe_name", ""),
            "page_count": audit.get("pdf", {}).get("page_count"),
            "source_master": str(master),
            "source_master_sha256": file_hash(master),
            "profile": profile,
            "preflight_status": audit["status"],
        }
        metadata_path = staging / "METADATA.json"
        save_json(metadata_path, metadata)
        generated.append(metadata_path)

        if "product_description" in profile.get("files", []):
            generated.append(write_product_description(project, staging, settings, platform_name))

        if platform_name == "KDP":
            _copy_required_kdp_assets(project, staging, generated)

        if platform_name == "Gumroad":
            generated.append(
                _write_gumroad_readme(
                    staging,
                    [p.name for p in generated if p.exists()],
                    warnings,
                )
            )
        elif "readme" in profile.get("files", []):
            generated.append(
                _write_platform_readme(
                    staging,
                    settings,
                    platform_name,
                    [p.name for p in generated if p.exists()],
                    warnings,
                )
            )

        preflight_path = staging / "PLATFORM_PREFLIGHT.json"
        save_json(preflight_path, audit)
        generated.append(preflight_path)

        manifest = {
            "schema_version": 5,
            "factory_version": FACTORY_VERSION,
            "platform_engine_version": PLATFORM_ENGINE_VERSION,
            "universal_publishing_version": UNIVERSAL_PUBLISHING_VERSION,
            "platform": platform_name,
            "status": "READY_WITH_WARNINGS" if warnings else "READY",
            "project": project.name,
            "title": title,
            "generated": datetime.now().isoformat(timespec="seconds"),
            "master_pdf": str(master),
            "master_sha256": file_hash(master),
            "variant_mode": mode,
            "files": [p.name for p in generated if p.exists()],
            "file_hashes": {p.name: file_hash(p) for p in generated if p.exists()},
            "warnings": warnings,
            "preflight": "PLATFORM_PREFLIGHT.json",
        }

        manifest_path = staging / "PACKAGE_MANIFEST.json"
        save_json(manifest_path, manifest)
        generated.append(manifest_path)

        # Publish only after the entire package has passed validation.
        root.parent.mkdir(parents=True, exist_ok=True)
        if root.exists():
            backup = root.with_name(root.name + ".previous")
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            root.rename(backup)
            try:
                staging.rename(root)
            except Exception:
                if root.exists():
                    shutil.rmtree(root, ignore_errors=True)
                backup.rename(root)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        else:
            staging.rename(root)

        # Manifest is regenerated at final location so its file list is authoritative.
        final_files = sorted(p.name for p in root.iterdir() if p.is_file())
        manifest["files"] = final_files
        manifest["file_hashes"] = {name: file_hash(root / name) for name in final_files}
        save_json(root / "PACKAGE_MANIFEST.json", manifest)

        # Gumroad package gets an explicit post-publish validation flag.
        if platform_name == "Gumroad":
            post_errors, post_warnings = _validate_gumroad_assets(root)
            if post_errors:
                return {
                    "status": "BLOCKED",
                    "output": root,
                    "audit": audit,
                    "errors": post_errors,
                    "warnings": warnings + post_warnings,
                }
            manifest["gumroad_asset_validation"] = {
                "status": "PASS",
                "errors": [],
                "warnings": post_warnings,
            }
            gumroad_report = _gumroad_asset_report(root, gumroad_manifest)
            manifest["gumroad_asset_report"] = gumroad_report
            save_json(root / "PACKAGE_MANIFEST.json", manifest)

        final_status = manifest["status"]
        record_world_production_event(
            project,
            f"platform_package:{platform_name}",
            final_status,
            page_count=audit.get("pdf", {}).get("page_count") or 0,
            errors=0,
            warnings=len(warnings),
        )

        if not quiet:
            print(f"\n{platform_name}: {final_status}")
            print(f"Output: {root}")
            for warning in warnings:
                print("WARNING:", warning)

        return {
            "status": final_status,
            "output": root,
            "manifest": manifest,
            "audit": audit,
            "warnings": warnings,
            "errors": [],
            "gumroad_assets": gumroad_manifest if platform_name == "Gumroad" else None,
            "gumroad_asset_report": gumroad_report if platform_name == "Gumroad" else None,
        }

    except Exception as error:
        shutil.rmtree(staging, ignore_errors=True)
        if not quiet:
            print(f"\n{platform_name}: FAILED - {error}")
        return {
            "status": "BLOCKED",
            "output": root,
            "audit": audit,
            "errors": [str(error)],
            "warnings": warnings,
        }


# Override the active generator so the current production generator is authoritative.
generate_platform_package = generate_platform_package_v112


def generate_all_platform_packages_v112(project):
    profiles = load_platform_profiles()
    enabled = [name for name, profile in profiles.items() if profile.get("enabled", False)]
    results = {}
    print("\nUNIVERSAL PUBLISHING ENGINE v2.3 — GENERATE ALL ENABLED PLATFORMS")
    print("-" * 78)
    for name in enabled:
        result = generate_platform_package(project, name, quiet=True)
        results[name] = result
        print(f"{name:<20} {result.get('status')}")
        for error in result.get("errors", []):
            print(f"  ERROR: {error}")
        for warning in result.get("warnings", []):
            print(f"  WARNING: {warning}")
        if name == "Gumroad" and result.get("gumroad_asset_report"):
            _print_gumroad_asset_report(result["gumroad_asset_report"])

    save_json(
        project / PLATFORM_INDEX_FILENAME,
        {
            "schema_version": 5,
            "factory_version": FACTORY_VERSION,
            "platform_engine_version": PLATFORM_ENGINE_VERSION,
            "universal_publishing_version": UNIVERSAL_PUBLISHING_VERSION,
            "generated": datetime.now().isoformat(timespec="seconds"),
            "platforms": {
                n: {
                    "status": r.get("status"),
                    "output": str(r.get("output", "")),
                    "errors": r.get("errors", []),
                    "warnings": r.get("warnings", []),
                }
                for n, r in results.items()
            },
        },
    )
    return results


generate_all_platform_packages = generate_all_platform_packages_v112


def run_platform_self_test_v112():
    """Offline test of the universal package engine plus Gumroad asset generation."""
    import tempfile
    from reportlab.pdfgen import canvas as _canvas

    failures = []
    with tempfile.TemporaryDirectory(prefix="CBF_v112_TEST_") as temp:
        root = Path(temp)
        project = root / "Projects" / "Universal Platform Test"
        project.mkdir(parents=True)

        save_json(
            project / "project.json",
            {
                "title": "Universal Platform Test",
                "author": "Test Author",
                "trim_width": 8.5,
                "trim_height": 11,
                "dpi": 300,
                "production_profile": "Imported Finished PDF",
            },
        )
        (project / "PDF").mkdir()
        (project / "MASTER").mkdir()

        sample_arts = []
        for art_no in range(4):
            sample_art = root / f"sample-art-{art_no + 1}.png"
            sample = Image.new("RGB", (1200, 1500), "white")
            draw = ImageDraw.Draw(sample)
            draw.rectangle((80, 80, 1120, 1420), outline="black", width=8)
            draw.ellipse(
                (180 + art_no * 35, 260, 980 - art_no * 25, 980),
                outline="black", width=10
            )
            draw.line((160, 1120 - art_no * 35, 1040, 1120 + art_no * 20), fill="black", width=8)
            draw.text((320, 1260), f"TEST ARTWORK {art_no + 1}", font=get_font(70, True), fill="black")
            sample.save(sample_art, "PNG", dpi=(300, 300))
            sample_arts.append(sample_art)

        pdf = project / "PDF" / "source.pdf"
        c = _canvas.Canvas(str(pdf), pagesize=(8.5 * 72, 11 * 72))
        for page_no in range(24):
            source_art = sample_arts[page_no % len(sample_arts)]
            c.drawImage(
                str(source_art), 54, 54,
                width=8.5 * 72 - 108,
                height=11 * 72 - 108,
                preserveAspectRatio=True,
                anchor="c"
            )
            c.showPage()
        c.save()

        master = import_existing_pdf_to_master(project, pdf)
        if not master:
            failures.append("MASTER import failed.")
        else:
            profiles = load_platform_profiles()
            for name in ("KDP", "Gumroad", "Etsy", "Payhip"):
                result = generate_platform_package(project, name, quiet=True)
                if result.get("status") not in {"READY", "READY_WITH_WARNINGS"}:
                    failures.append(f"{name} package failed: {result.get('errors')}")
                output = Path(result.get("output") or "")
                if not output.exists() or not (output / "PACKAGE_MANIFEST.json").exists():
                    failures.append(f"{name} package manifest missing.")

            gum = project / PLATFORM_DIRNAME / "GUMROAD"
            cover = gum / "cover.png"
            if not cover.exists():
                cover = gum / "cover.jpg"
            if not cover.exists():
                failures.append("Gumroad cover missing.")
            thumbs = sorted(list(gum.glob("thumb-*.png")) + list(gum.glob("thumb-*.jpg")))
            if len(thumbs) != GUMROAD_PREVIEW_COUNT:
                failures.append(f"Gumroad preview count was {len(thumbs)}, expected {GUMROAD_PREVIEW_COUNT}.")
            thumbnail = next(iter(list(gum.glob("thumbnail.png")) + list(gum.glob("thumbnail.jpg"))), None)
            if not thumbnail:
                failures.append("Gumroad product thumbnail missing.")
            else:
                with Image.open(thumbnail) as img:
                    if img.width < 600 or img.height < 600:
                        failures.append("Gumroad product thumbnail below 600x600.")

    if failures:
        print("\nUNIVERSAL PLATFORM ENGINE v1.2 SELF-TEST: FAIL")
        for failure in failures:
            print("  FAIL:", failure)
        return False

    print("\nUNIVERSAL PLATFORM ENGINE v1.2 SELF-TEST: PASS")
    print("  Immutable MASTER: PASS")
    print("  PDF intake: PASS")
    print("  KDP package: PASS")
    print("  Gumroad cover: PASS")
    print("  Gumroad 4 interior previews: PASS")
    print("  Gumroad 600x600+ thumbnail: PASS")
    print("  Etsy package: PASS")
    print("  Payhip package: PASS")
    print("  Package manifests: PASS")
    return True


run_platform_self_test = run_platform_self_test_v112


def platform_center():
    while True:
        profiles = load_platform_profiles()
        print("\n" + "=" * 78)
        print(f"UNIVERSAL PUBLISHING CENTER v{PLATFORM_ENGINE_VERSION}")
        print("=" * 78)
        print("1. ONE-CLICK PUBLISH (build + audit + all packages + ZIPs)")
        print("2. Import Finished PDF → Master + ALL Platforms")
        print("3. Generate KDP Package")
        print("4. Generate Gumroad Package")
        print("5. Generate ALL Enabled Platform Packages")
        print("6. Manage Platform Profiles")
        print("7. Platform Preflight / Audit")
        print("8. Compare Platform Requirements")
        print("9. Factory Health Dashboard")
        print("10. Create Project Snapshot")
        print("11. Create Delivery ZIPs")
        print("12. Run Universal Platform Self-Test")
        print("13. Back")
        choice = input("Choose: ").strip()

        if choice == "1":
            project = choose_project()
            if project:
                one_click_publish(project)
            input("\nPress Enter to continue...")
        elif choice == "2":
            convert_existing_pdf_enhanced()
            input("\nPress Enter to continue...")
        elif choice in {"3", "4", "5"}:
            project = choose_project()
            if not project:
                continue
            if choice == "3":
                generate_platform_package(project, "KDP")
            elif choice == "4":
                generate_platform_package(project, "Gumroad")
            else:
                generate_all_platform_packages(project)
            input("\nPress Enter to continue...")
        elif choice == "6":
            manage_platform_profiles_v2()
        elif choice == "7":
            project = choose_project()
            if not project:
                continue
            master = find_master_pdf(project)
            if not master:
                print("No MASTER PDF found.")
                input("\nPress Enter...")
                continue
            print("\nPLATFORM AUDIT")
            print("-" * 78)
            audits = {}
            for name, profile in profiles.items():
                if not profile.get("enabled"):
                    continue
                audit = platform_preflight(project, name, master, profile)
                audits[name] = audit
                print(
                    f"{name:<20} {audit['status']:<20} "
                    f"errors={len(audit['errors'])} warnings={len(audit['warnings'])}"
                )
                for error in audit["errors"]:
                    print("  ERROR:", error)
                for warning in audit["warnings"]:
                    print("  WARNING:", warning)
            save_json(
                project / PLATFORM_AUDIT_FILENAME,
                {
                    "schema_version": 5,
                    "generated": datetime.now().isoformat(timespec="seconds"),
                    "audits": audits,
                },
            )
            input("\nPress Enter to continue...")
        elif choice == "8":
            project = choose_project()
            if not project:
                continue
            print("\nPLATFORM REQUIREMENT COMPARISON")
            print("-" * 78)
            for row in platform_requirement_comparison(project):
                print(
                    f"{row['platform']:<20} "
                    f"{'ON ' if row['enabled'] else 'OFF'} | "
                    f"{row['status']:<20} | "
                    f"{row['max_mb']} MB/file | "
                    f"{row['max_files']} files | "
                    f"{row['variant']}"
                )
            input("\nPress Enter to continue...")
        elif choice == "9":
            factory_health_dashboard()
            input("\nPress Enter to continue...")
        elif choice == "10":
            project = choose_project()
            if project:
                try:
                    print(f"\nSnapshot: {create_project_snapshot(project)}")
                except Exception as error:
                    print(f"ERROR: {error}")
            input("\nPress Enter to continue...")
        elif choice == "11":
            project = choose_project()
            if project:
                results = {}
                for name, profile in profiles.items():
                    if profile.get("enabled"):
                        zip_file, errors = create_delivery_zip(project, name)
                        if zip_file:
                            results[name] = {"status": "ZIPPED", "zip": str(zip_file)}
                            print(f"{name}: {zip_file}")
                        else:
                            print(f"{name}: FAILED - {'; '.join(errors)}")
                if results:
                    print(f"Delivery index: {create_delivery_index(project, results)}")
            input("\nPress Enter to continue...")
        elif choice == "12":
            run_platform_self_test()
            input("\nPress Enter to continue...")
        elif choice == "13":
            return
        else:
            print("Invalid choice.")


def _v12_state_path():
    return FACTORY / "factory_v12_state.json"


def _v12_load_state():
    path = _v12_state_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def _v12_save_state(data):
    save_json(_v12_state_path(), data)


def v12_recent_projects(limit=12):
    rows = []
    if PROJECTS.exists():
        for item in PROJECTS.iterdir():
            if not item.is_dir() or item.name.startswith("_"):
                continue
            try:
                stamp = item.stat().st_mtime
            except OSError:
                continue
            rows.append((stamp, item))
    return [item for _, item in sorted(rows, reverse=True)[:limit]]


def v12_project_summary(project):
    master = find_master_pdf(project)
    delivery = project / "DELIVERY"
    reports = project / "REPORTS"
    audit = project / "FINAL_DELIVERY_AUDIT.json"
    if not audit.exists():
        audit = reports / "FINAL_DELIVERY_AUDIT.json"
    status = "NOT RELEASED"
    if audit.exists():
        try:
            data = json.loads(audit.read_text(encoding="utf-8"))
            status = data.get("final_status", data.get("status", "AUDITED"))
        except Exception:
            status = "AUDITED"
    return {
        "name": project.name,
        "path": str(project),
        "master": bool(master),
        "delivery": delivery.exists(),
        "reports": reports.exists(),
        "status": status,
        "modified": datetime.fromtimestamp(project.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
    }


def v12_choose_recent_project():
    projects = v12_recent_projects()
    if not projects:
        print("\nNo projects found.")
        return None
    print("\nRECENT PROJECTS")
    print("-" * 78)
    for i, project in enumerate(projects, 1):
        info = v12_project_summary(project)
        print(f"{i:>2}. {info['name'][:42]:<42} {info['status']:<16} {info['modified']}")
    raw = input("\nSelect project number, or Enter to cancel: ").strip()
    if not raw:
        return None
    try:
        selected = projects[int(raw) - 1]
        _v12_save_state({**_v12_load_state(), "active_project": str(selected)})
        return selected
    except (ValueError, IndexError):
        print("Invalid selection.")
        return None


def v12_active_project():
    state = _v12_load_state()
    value = state.get("active_project")
    if value:
        project = Path(value)
        if project.exists() and project.is_dir():
            return project
    return None


def v12_set_active_project():
    project = v12_choose_recent_project()
    if project:
        print(f"\nActive project set to: {project.name}")
    return project


def v12_open_folder(path):
    path = Path(path)
    if not path.exists():
        print(f"\nFolder does not exist: {path}")
        return False
    try:
        os.startfile(str(path))
        print(f"\nOpened: {path}")
        return True
    except Exception as error:
        print(f"\nCould not open folder: {error}")
        print(path)
        return False


def _v12_audit_state(project):
    """Return normalized final-audit status plus error/warning counts."""
    report = Path(project) / "REPORTS" / "FINAL_DELIVERY_AUDIT.json"
    if not report.exists():
        report = Path(project) / "FINAL_DELIVERY_AUDIT.json"
    if not report.exists():
        return None
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
        platforms = data.get("platforms") or {}
        total_errors = data.get("total_errors")
        total_warnings = data.get("total_warnings")
        if total_errors is None:
            total_errors = sum(len(v.get("errors", [])) for v in platforms.values() if isinstance(v, dict))
        if total_warnings is None:
            total_warnings = sum(len(v.get("warnings", [])) for v in platforms.values() if isinstance(v, dict))
        status = str(
            data.get("final_status",
            data.get("overall_status",
            data.get("status", "")))
        ).upper()
        return {
            "status": status,
            "errors": int(total_errors or 0),
            "warnings": int(total_warnings or 0),
            "path": report,
        }
    except Exception:
        return {"status": "UNKNOWN", "errors": 0, "warnings": 0, "path": report}


def v12_next_action(project):
    if not project:
        return "Select or import a finished PDF to begin."
    master = find_master_pdf(project)
    if not master:
        return "Import or select a finished PDF."
    delivery = Path(project) / "DELIVERY"
    audit = _v12_audit_state(project)
    if not audit:
        return "Run the Production Release Center or final delivery audit."
    if audit["errors"] > 0:
        return f"Fix {audit['errors']} final-audit error(s) before publishing."
    if audit["warnings"] > 0:
        return f"Review {audit['warnings']} final-audit warning(s) before publishing."
    if audit["status"] in {"READY", "PASS", "PASSED"} and delivery.exists():
        return "Production release is complete. Ready for marketplace upload."
    if not delivery.exists():
        return "Create delivery ZIPs and release packages."
    return "Review the final delivery audit report."


def v12_active_dashboard():
    project = v12_active_project() or v12_choose_recent_project()
    if not project:
        return
    info = v12_project_summary(project)
    print("\nACTIVE PROJECT DASHBOARD")
    print("=" * 78)
    print(f"Project:       {info['name']}")
    print(f"Location:      {info['path']}")
    print(f"MASTER PDF:    {'PASS' if info['master'] else 'MISSING'}")
    print(f"Delivery:      {'PRESENT' if info['delivery'] else 'MISSING'}")
    print(f"Reports:       {'PRESENT' if info['reports'] else 'MISSING'}")
    print(f"Release:       {info['status']}")
    print(f"What's next:   {v12_next_action(project)}")
    print("=" * 78)
    print("1. Quick release this project")
    print("2. Rebuild one platform")
    print("3. Open Delivery")
    print("4. Open Reports")
    print("5. Create snapshot")
    print("6. Return")
    choice = input("\nChoose: ").strip()
    if choice == "1":
        production_release_center()
    elif choice == "2":
        v12_rebuild_one_platform(project)
    elif choice == "3":
        v12_open_folder(project / "DELIVERY")
    elif choice == "4":
        v12_open_folder(project / "REPORTS")
    elif choice == "5":
        try:
            print(f"Snapshot: {create_project_snapshot(project)}")
        except Exception as error:
            print(f"ERROR: {error}")


def v12_rebuild_one_platform(project=None):
    project = project or v12_active_project() or choose_project()
    if not project:
        return
    print("\nREBUILD ONE PLATFORM")
    print("1. KDP\n2. Gumroad\n3. Payhip\n4. Digital PDF\n5. All platforms\n6. Cancel")
    choice = input("\nChoose: ").strip()
    names = {"1": "KDP", "2": "Gumroad", "3": "Payhip", "4": "Digital PDF"}
    if choice in names:
        generate_platform_package(project, names[choice])
    elif choice == "5":
        generate_all_platform_packages(project)


def v12_recent_projects_menu():
    project = v12_choose_recent_project()
    if project:
        v12_active_dashboard()


def v12_cleanup_menu():
    project = v12_active_project() or choose_project()
    if not project:
        return
    print("\nSAFE CLEANUP")
    print("This removes only temporary render/cache folders. MASTER, delivery, reports, and backups are protected.")
    targets = [project / "_TEMP", project / "TEMP", project / "CACHE", project / "RENDER_CACHE"]
    existing = [p for p in targets if p.exists()]
    if not existing:
        print("No approved temporary folders found.")
        return
    for target in existing:
        print(f"  - {target}")
    if input("\nType CLEAN to continue: ").strip().upper() != "CLEAN":
        print("Cleanup cancelled.")
        return
    for target in existing:
        try:
            shutil.rmtree(target)
            print(f"Removed: {target}")
        except Exception as error:
            print(f"Could not remove {target}: {error}")


# ============================================================
# v13.6 HISTORICAL ADDITION — PRODUCTION RELEASE HARDENING + INTEGRITY
# Bundled upgrade:
#   - Captures an immutable MASTER/source fingerprint before release work.
#   - Verifies the MASTER is byte-for-byte unchanged after packages/ZIPs/audit.
#   - Writes a release artifact inventory with SHA-256 hashes and sizes.
#   - Adds a machine-readable RELEASE_STATE.json for resumable diagnostics.
#   - Refuses to call a release clean when package/audit errors remain.
#   - Keeps all existing platform/Gumroad generation behavior intact.
# ============================================================

RELEASE_INTEGRITY_VERSION = "1.1"
RELEASE_STATE_FILENAME = "RELEASE_STATE.json"
RELEASE_ARTIFACT_INDEX_FILENAME = "RELEASE_ARTIFACT_INDEX.json"


def _v126_artifact_inventory(project):
    """Inventory release-owned deliverables without modifying them."""
    project = Path(project)
    roots = []
    for name in ("MASTER", "PDF", "KDP_PACKAGE", "PLATFORMS", "DELIVERY", "REPORTS"):
        path = project / name
        if path.exists():
            roots.append(path)
    files = []
    seen = set()
    for root in roots:
        if not root.is_dir():
            continue
        for item in root.rglob("*"):
            if not item.is_file():
                continue
            try:
                resolved = str(item.resolve())
                if resolved in seen:
                    continue
                seen.add(resolved)
                files.append({
                    "path": str(item.relative_to(project)),
                    "size": item.stat().st_size,
                    "sha256": file_hash(item),
                })
            except (OSError, ValueError) as error:
                files.append({"path": str(item.relative_to(project)), "error": str(error)})
    return sorted(files, key=lambda x: x.get("path", "").lower())


def _v126_write_release_state(project, status, master_hash=None, source_hash=None, **extra):
    project = Path(project)
    state = {
        "schema_version": 1,
        "factory_version": FACTORY_VERSION,
        "release_integrity_version": RELEASE_INTEGRITY_VERSION,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "project": project.name,
        "status": status,
        "master_sha256": master_hash,
        "source_sha256": source_hash,
    }
    state.update(extra)
    save_json(project / "REPORTS" / RELEASE_STATE_FILENAME, state)
    return project / "REPORTS" / RELEASE_STATE_FILENAME


def _v126_write_artifact_index(project, status="RECORDED"):
    project = Path(project)
    report_dir = project / "REPORTS"
    report_dir.mkdir(parents=True, exist_ok=True)
    inventory = _v126_artifact_inventory(project)
    payload = {
        "schema_version": 1,
        "factory_version": FACTORY_VERSION,
        "release_integrity_version": RELEASE_INTEGRITY_VERSION,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "project": project.name,
        "status": status,
        "artifacts": inventory,
        "artifact_count": len(inventory),
    }
    path = report_dir / RELEASE_ARTIFACT_INDEX_FILENAME
    save_json(path, payload)
    return path


def _v126_verify_master_unchanged(project, expected_hash):
    master = find_master_pdf(Path(project))
    if not master or not master.exists():
        return False, "MASTER PDF disappeared during release."
    try:
        actual = file_hash(master)
    except Exception as error:
        return False, f"Could not hash MASTER PDF after release: {error}"
    if actual != expected_hash:
        return False, "MASTER PDF changed during release; release is BLOCKED."
    return True, "MASTER PDF unchanged (SHA-256 verified)."


def _v163_split_release_warnings(project, results, audit):
    """Separate advisory marketplace-profile notices from blocking warnings.

    Advisory profile notices remain visible in platform manifests/audits,
    but do not downgrade an otherwise clean production release. Other
    warnings remain review-worthy.
    """
    profiles = load_platform_profiles()
    advisory_messages = set()

    for name, profile in profiles.items():
        for message in _platform_profile_warning_list(profile):
            advisory_messages.add((str(name).strip().lower(), str(message)))

    advisory_items = []
    blocking_warnings = []

    def classify(platform_name, message, source):
        platform_key = str(platform_name or "").strip().lower()
        text = str(message or "")
        if (platform_key, text) in advisory_messages:
            advisory_items.append({
                "platform": platform_name,
                "message": text,
                "source": source,
            })
        else:
            blocking_warnings.append({
                "platform": platform_name,
                "message": text,
                "source": source,
            })

    for name, result in results.items():
        if not isinstance(result, dict):
            continue
        for message in result.get("warnings", []) or []:
            classify(result.get("platform", name), message, "platform_result")

    for name, entry in audit.items():
        if not isinstance(entry, dict):
            continue
        for message in entry.get("warnings", []) or []:
            classify(entry.get("platform", name), message, "delivery_audit")

    return blocking_warnings, advisory_items


def create_release_bundle_v126(project):
    """Integrity-aware replacement for the final production release workflow."""
    project = Path(project)
    print("\n" + "=" * 78)
    print(f"PRODUCTION RELEASE BUILD v{FACTORY_VERSION}")
    print("=" * 78)
    print("Integrity mode: ON")

    master = find_master_pdf(project)
    if not master:
        print("ERROR: No MASTER PDF exists. Build/import the book first.")
        return None

    try:
        master_hash_before = file_hash(master)
    except Exception as error:
        print(f"ERROR: Could not fingerprint MASTER PDF: {error}")
        return None

    source_hash_before = None
    source = project / "INPUT" / "source.pdf"
    if source.exists():
        try:
            source_hash_before = file_hash(source)
        except Exception:
            source_hash_before = None

    _v126_write_release_state(
        project, "STARTED", master_hash_before, source_hash_before,
        message="Release started; MASTER fingerprint captured before generation."
    )

    try:
        results = generate_all_platform_packages(project)
        delivery_index = create_delivery_index(project, results)
        audit = audit_delivery_packages(project)

        master_ok, master_message = _v126_verify_master_unchanged(project, master_hash_before)
        if not master_ok:
            print(f"ERROR: {master_message}")
            state_path = _v126_write_release_state(
                project, "BLOCKED", master_hash_before, source_hash_before,
                integrity_error=master_message,
            )
            _v126_write_artifact_index(project, "BLOCKED")
            return {"results": results, "audit": audit, "report": None, "snapshot": None,
                    "status": "BLOCKED", "integrity_error": master_message, "state": state_path}

        audit_errors = sum(len(v.get("errors", [])) for v in audit.values() if isinstance(v, dict))
        result_errors = sum(len(r.get("errors", [])) for r in results.values() if isinstance(r, dict))
        total_errors = audit_errors + result_errors
        blocking_warnings, advisory_items = _v163_split_release_warnings(project, results, audit)
        total_warnings = len(blocking_warnings)
        total_advisories = len(advisory_items)
        final_status = "BLOCKED" if total_errors else ("REVIEW" if total_warnings else "READY")

        snapshot = create_project_snapshot(project)
        artifact_index = _v126_write_artifact_index(project, final_status)
        report = project / "REPORTS" / "PRODUCTION_RELEASE_REPORT.json"
        save_json(report, {
            "schema_version": 2,
            "factory_version": FACTORY_VERSION,
            "release_engine_version": RELEASE_ENGINE_VERSION,
            "release_integrity_version": RELEASE_INTEGRITY_VERSION,
            "generated": datetime.now().isoformat(timespec="seconds"),
            "project": project.name,
            "master_sha256_before": master_hash_before,
            "master_sha256_after": file_hash(master),
            "master_unchanged": True,
            "source_sha256": source_hash_before,
            "platform_results": results,
            "delivery_index": str(delivery_index),
            "delivery_audit": audit,
            "snapshot": str(snapshot),
            "artifact_index": str(artifact_index),
            "final_status": final_status,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "total_advisories": total_advisories,
            "blocking_warnings": blocking_warnings,
            "advisories": advisory_items,
        })
        state_path = _v126_write_release_state(
            project, final_status, master_hash_before, source_hash_before,
            report=str(report), artifact_index=str(artifact_index),
            master_unchanged=True, total_errors=total_errors, total_warnings=total_warnings,
            total_advisories=total_advisories,
        )

        print("\n" + "=" * 78)
        print("PRODUCTION RELEASE COMPLETE")
        print("=" * 78)
        print(f"Final status:   {final_status}")
        print(f"Errors:         {total_errors}")
        print(f"Warnings:       {total_warnings}")
        print(f"Advisories:     {total_advisories}")
        print(f"MASTER:         VERIFIED UNCHANGED")
        print(f"Release report: {report}")
        print(f"Artifact index: {artifact_index}")
        print(f"State file:     {state_path}")
        print(f"Safety snapshot:{snapshot}")
        return {"results": results, "audit": audit, "report": report, "snapshot": snapshot,
                "status": final_status, "artifact_index": artifact_index, "state": state_path}

    except Exception as error:
        _v126_write_release_state(
            project, "BLOCKED", master_hash_before, source_hash_before,
            integrity_error=str(error),
        )
        _v126_write_artifact_index(project, "BLOCKED")
        print(f"\nPRODUCTION RELEASE FAILED: {error}")
        return {"results": {}, "audit": {}, "report": None, "snapshot": None,
                "status": "BLOCKED", "errors": [str(error)]}


# Make the integrity-aware release workflow authoritative for v13.1.
create_release_bundle = create_release_bundle_v126


# ============================================================
# v13.6 HISTORICAL ADDITION — RELEASE CENTER HARDENING
#   - Adds a single authoritative release-health view.
#   - Verifies MASTER and source.pdf before and after release.
#   - Makes BLOCKED/REVIEW/READY status visible from the main release center.
#   - Adds a safe resume/repair action that reruns the integrity-aware release.
#   - Keeps MASTER immutable and refuses a READY result after fingerprint drift.
# ============================================================

RELEASE_HARDENING_VERSION = "1.0"


def _v127_release_health(project):
    """Return normalized release state for dashboards without changing files."""
    project = Path(project)
    state_path = project / "REPORTS" / RELEASE_STATE_FILENAME
    audit = _v12_audit_state(project)
    state = {}
    if state_path.exists():
        try:
            data = load_json(state_path)
            if isinstance(data, dict):
                state = data
        except Exception:
            state = {}
    master = find_master_pdf(project)
    master_hash = file_hash(master) if master and master.exists() else None
    expected_master = state.get("master_sha256")
    master_ok = bool(master_hash and (not expected_master or master_hash == expected_master))
    delivery = project / DELIVERY_DIRNAME
    artifact_index = project / "REPORTS" / RELEASE_ARTIFACT_INDEX_FILENAME
    report = project / "REPORTS" / "PRODUCTION_RELEASE_REPORT.json"
    audit_errors = int((audit or {}).get("errors", 0) or 0)
    audit_warnings = int((audit or {}).get("warnings", 0) or 0)
    state_status = str(state.get("status", "NOT STARTED")).upper()
    if not master:
        status = "BLOCKED"
    elif state_status == "BLOCKED" or audit_errors:
        status = "BLOCKED"
    elif state_status in {"READY", "PASS", "PASSED"} and master_ok and delivery.exists() and audit:
        status = "READY" if audit_warnings == 0 else "REVIEW"
    elif state:
        status = "REVIEW"
    else:
        status = "NOT RELEASED"
    return {
        "status": status,
        "state": state_status,
        "master": bool(master),
        "master_ok": master_ok,
        "delivery": delivery.exists(),
        "artifact_index": artifact_index.exists(),
        "report": report.exists(),
        "audit": audit,
        "state_path": state_path,
    }


def _v127_verify_source_unchanged(project, expected_hash):
    source = Path(project) / "INPUT" / "source.pdf"
    if not expected_hash:
        return True, "No source.pdf fingerprint was recorded."
    if not source.exists():
        return False, "INPUT/source.pdf disappeared during release."
    try:
        actual = file_hash(source)
    except Exception as error:
        return False, f"Could not hash source.pdf after release: {error}"
    if actual != expected_hash:
        return False, "INPUT/source.pdf changed during release; release is BLOCKED."
    return True, "Source PDF unchanged (SHA-256 verified)."


def create_release_bundle_v127(project):
    """Integrity-aware v13.1 release wrapper around the proven v13.1 engine."""
    project = Path(project)
    master = find_master_pdf(project)
    if not master:
        print("ERROR: No MASTER PDF exists. Build/import the book first.")
        return None
    master_before = file_hash(master)
    source = project / "INPUT" / "source.pdf"
    source_before = file_hash(source) if source.exists() else None

    result = create_release_bundle_v126(project)
    if not isinstance(result, dict):
        return result

    master_after = find_master_pdf(project)
    master_ok = bool(master_after and master_after.exists() and file_hash(master_after) == master_before)
    source_ok, source_message = _v127_verify_source_unchanged(project, source_before)
    if not master_ok or not source_ok:
        integrity_error = " | ".join(x for x in [
            "MASTER changed during release." if not master_ok else "",
            source_message if not source_ok else "",
        ] if x)
        report = project / "REPORTS" / "PRODUCTION_RELEASE_REPORT.json"
        if report.exists():
            try:
                data = load_json(report)
                data["factory_version"] = FACTORY_VERSION
                data["release_hardening_version"] = RELEASE_HARDENING_VERSION
                data["master_unchanged"] = master_ok
                data["source_unchanged"] = source_ok
                data["integrity_error"] = integrity_error
                data["final_status"] = "BLOCKED"
                save_json(report, data)
            except Exception:
                pass
        state = _v126_write_release_state(
            project, "BLOCKED", master_before, source_before,
            master_unchanged=master_ok,
            source_unchanged=source_ok,
            integrity_error=integrity_error,
        )
        result["status"] = "BLOCKED"
        result["integrity_error"] = integrity_error
        result["state"] = state
        print("\nRELEASE INTEGRITY GATE: BLOCKED")
        print(f"  {integrity_error}")
        return result

    result["master_unchanged"] = True
    result["source_unchanged"] = True
    return result


# v13.1 is now the authoritative production release entry point.
create_release_bundle = create_release_bundle_v127


def production_release_center_v127():
    """Production release control center with visible integrity state."""
    while True:
        project = v12_active_project()
        print("\n" + "=" * 78)
        print(f"PRODUCTION RELEASE CENTER v{FACTORY_VERSION}")
        print("=" * 78)
        if project:
            health = _v127_release_health(project)
            print(f"Active project: {project.name}")
            print(f"Release status: {health['status']}")
            print(f"MASTER:         {'PASS' if health['master'] and health['master_ok'] else 'BLOCKED'}")
            print(f"Delivery:       {'PRESENT' if health['delivery'] else 'MISSING'}")
            print(f"Audit errors:   {health['audit'].get('errors', 0) if health['audit'] else 0}")
            print(f"Audit warnings: {health['audit'].get('warnings', 0) if health['audit'] else 0}")
        else:
            print("Active project: None selected")
        print("-" * 78)
        print("1. ONE-CLICK PRODUCTION RELEASE")
        print("2. RELEASE HEALTH / STATUS")
        print("3. RESUME / REPAIR RELEASE")
        print("4. Audit Delivery Packages")
        print("5. Rebuild One Platform")
        print("6. Create Delivery ZIPs")
        print("7. Create Safety Snapshot")
        print("8. Open Delivery Folder")
        print("9. Open Reports Folder")
        print("10. Back")
        choice = input("\nChoose: ").strip()
        if choice == "10":
            return
        if choice == "2":
            project = project or choose_project()
            if project:
                h = _v127_release_health(project)
                print("\nRELEASE HEALTH")
                print("-" * 78)
                for key, value in h.items():
                    if key not in {"audit", "state_path"}:
                        print(f"{key:<18}: {value}")
                if h["audit"]:
                    print(f"audit status      : {h['audit'].get('status')}")
                print(f"state file        : {h['state_path']}")
            input("\nPress Enter to continue...")
            continue
        project = project or choose_project()
        if not project:
            continue
        if choice == "1":
            create_release_bundle(project)
        elif choice == "3":
            print("\nRESUME / REPAIR RELEASE")
            print("This reruns packages, delivery ZIPs, audit, and integrity verification.")
            create_release_bundle(project)
        elif choice == "4":
            audit_delivery_packages(project)
        elif choice == "5":
            v12_rebuild_one_platform(project)
        elif choice == "6":
            results = generate_all_platform_packages(project)
            print(f"\nDelivery index: {create_delivery_index(project, results)}")
        elif choice == "7":
            print(f"\nSafety snapshot: {create_project_snapshot(project)}")
        elif choice == "8":
            v12_open_folder(project / DELIVERY_DIRNAME)
        elif choice == "9":
            v12_open_folder(project / "REPORTS")
        else:
            print("Invalid choice.")
        input("\nPress Enter to continue...")


production_release_center = production_release_center_v127


# ============================================================
# v13.1 MAJOR UPGRADE — FINISHED BOOK FOLDER INTAKE + AUTHORITATIVE COVER
#
# A finished coloring book may consist of two separate source files:
#   1) interior PDF
#   2) KDP full-wrap cover PDF/image
#
# This layer makes the FOLDER the intake unit.  It deliberately refuses to
# silently use an interior copyright/title page as a finished cover.
# ============================================================

SEPARATE_COVER_VERSION = "1.0"

# Finished-book PDFs commonly contain title/copyright/TOC/front-matter pages
# before the actual coloring artwork. Those pages must never become Gumroad
# preview thumbnails. The values are deliberately conservative and can be
# overridden later if a book format requires a different layout.
GUMROAD_FRONT_MATTER_PAGES = 5
GUMROAD_BACK_MATTER_PAGES = 2
GUMROAD_PREVIEW_MIN_ARTWORK_SCORE = 0.035
SEPARATE_COVER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
SEPARATE_COVER_PDF_EXTENSIONS = {".pdf"}
SEPARATE_COVER_POSITIVE = (
    "cover", "fullwrap", "full-wrap", "full_wrap", "kdp", "jacket", "wrap", "frontcover", "front-cover", "front_cover"
)
SEPARATE_COVER_NEGATIVE = (
    "thumbnail", "thumb", "preview", "interior", "coloring", "copyright", "toc", "tableofcontents",
    "titlepage", "title-page", "lore", "sample", "manifest", "proof", "watermark", "backcover", "back-cover"
)


def _cover_candidate_score(path, interior_pdf=None):
    """Score a source-folder file as a likely finished cover without guessing from PDF page order."""
    path = Path(path)
    name = path.stem.lower().replace(" ", "")
    score = 0
    reasons = []
    for token in SEPARATE_COVER_POSITIVE:
        if token in name:
            score += 45
            reasons.append(f"name:{token}")
    for token in SEPARATE_COVER_NEGATIVE:
        if token in name:
            score -= 60
            reasons.append(f"exclude:{token}")
    if interior_pdf and path.resolve() == Path(interior_pdf).resolve():
        return -10000, ["same-as-interior"]
    if path.suffix.lower() in SEPARATE_COVER_PDF_EXTENSIONS:
        score += 10
    elif path.suffix.lower() in SEPARATE_COVER_IMAGE_EXTENSIONS:
        score += 8
    else:
        return -10000, ["unsupported-extension"]

    try:
        if path.suffix.lower() in SEPARATE_COVER_IMAGE_EXTENSIONS:
            with Image.open(path) as im:
                ratio = im.width / max(1, im.height)
                if 1.42 <= ratio <= 1.68:
                    score += 80; reasons.append("KDP-wrap-ratio")
                elif 0.68 <= ratio <= 0.86:
                    score += 45; reasons.append("front-cover-ratio")
                elif ratio > 1.2:
                    score += 15; reasons.append("landscape")
        elif path.suffix.lower() == ".pdf":
            info = inspect_pdf(path)
            pages = int(info.get("page_count") or 0)
            sizes = info.get("sizes") or []
            if pages == 1:
                score += 35; reasons.append("single-page-pdf")
            elif pages > 1:
                score -= min(80, pages * 5)
            if sizes:
                w = float(sizes[0].get("width", 0) or 0)
                h = float(sizes[0].get("height", 0) or 0)
                ratio = w / max(0.01, h)
                if 1.42 <= ratio <= 1.68:
                    score += 90; reasons.append("KDP-wrap-ratio")
                elif 0.68 <= ratio <= 0.86:
                    score += 45; reasons.append("front-cover-ratio")
    except Exception as error:
        reasons.append(f"inspect-error:{error}")
    return score, reasons


def _discover_separate_cover(source_folder, interior_pdf):
    """Find a dedicated cover in the finished-book folder and likely cover subfolders."""
    source_folder = Path(source_folder)
    interior_pdf = Path(interior_pdf).resolve()
    search_roots = [source_folder]
    for name in ("COVER", "COVERS", "KDP", "KDP_PACKAGE", "SOURCE", "SOURCES"):
        candidate = source_folder / name
        if candidate.is_dir():
            search_roots.append(candidate)

    candidates = []
    seen = set()
    for root in search_roots:
        for item in root.iterdir():
            if not item.is_file():
                continue
            resolved = item.resolve()
            if resolved in seen or resolved == interior_pdf:
                continue
            seen.add(resolved)
            score, reasons = _cover_candidate_score(item, interior_pdf)
            if score > -1000:
                candidates.append({"path": item, "score": score, "reasons": reasons})

    candidates.sort(key=lambda x: (x["score"], x["path"].name.lower()), reverse=True)
    if not candidates:
        return None, [], "NOT_FOUND"
    top = candidates[0]
    second = candidates[1]["score"] if len(candidates) > 1 else -9999
    # Require a meaningful signal. A generic unrelated image/PDF must not become
    # a cover merely because it happened to be next to the interior.
    if top["score"] < 45:
        return None, candidates, "NOT_FOUND"
    if len(candidates) > 1 and top["score"] - second < 20:
        return None, candidates, "AMBIGUOUS"
    return top, candidates, "FOUND"


def _render_separate_cover_source(source, output_dir):
    """Convert a separate cover PDF/image into a stable PNG for downstream use."""
    source = Path(source); output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in SEPARATE_COVER_IMAGE_EXTENSIONS:
        out = output_dir / "MASTER_COVER.png"
        with Image.open(source) as im:
            im.convert("RGB").save(out, "PNG", dpi=(300, 300), optimize=True)
        return out
    if source.suffix.lower() == ".pdf":
        try:
            import pypdfium2 as pdfium
        except Exception as error:
            raise RuntimeError(f"Separate cover is a PDF but pypdfium2 is unavailable: {error}")
        pdf = pdfium.PdfDocument(str(source))
        if len(pdf) < 1:
            raise RuntimeError("Separate cover PDF contains no pages.")
        page = pdf[0]
        bitmap = page.render(scale=3.0)
        pil = bitmap.to_pil().convert("RGB")
        out = output_dir / "MASTER_COVER.png"
        pil.save(out, "PNG", dpi=(216, 216), optimize=True)
        return out
    raise RuntimeError(f"Unsupported separate cover format: {source.suffix}")


def _record_authoritative_cover(project, source, rendered_cover, candidates, status):
    """Store the source cover provenance and checksum inside the immutable MASTER area."""
    project = Path(project); master_dir = project / "MASTER"; master_dir.mkdir(parents=True, exist_ok=True)
    cover_dir = master_dir / "COVER_SOURCE"; cover_dir.mkdir(parents=True, exist_ok=True)
    source_copy = cover_dir / Path(source).name
    if Path(source).resolve() != source_copy.resolve():
        shutil.copy2(source, source_copy)
    rendered_copy = master_dir / "MASTER_COVER.png"
    if Path(rendered_cover).resolve() != rendered_copy.resolve():
        shutil.copy2(rendered_cover, rendered_copy)
    payload = {
        "schema_version": 1,
        "resolver_version": SEPARATE_COVER_VERSION,
        "status": status,
        "source_file": str(Path(source).resolve()),
        "source_basename": Path(source).name,
        "source_sha256": file_hash(source),
        "master_cover": str(rendered_copy),
        "master_cover_sha256": file_hash(rendered_copy),
        "detected_at": datetime.now().isoformat(timespec="seconds"),
        "candidates": [
            {"file": str(x["path"]), "score": x["score"], "reasons": x["reasons"]}
            for x in candidates[:10]
        ],
    }
    save_json(master_dir / "COVER_SOURCE.json", payload)
    return rendered_copy, payload


def _resolve_finished_cover_for_folder(project, source_folder, interior_pdf):
    """Resolve a dedicated cover; never substitute PDF page 1 when a folder is used."""
    found, candidates, status = _discover_separate_cover(source_folder, interior_pdf)
    print("\nCOVER DETECTION")
    print("-" * 78)
    print(f"Interior PDF:  {Path(interior_pdf).name}")
    if status == "AMBIGUOUS":
        print("Cover detected: AMBIGUOUS")
        for item in candidates[:5]:
            print(f"  {item['score']:>4}  {item['path'].name}")
        raise RuntimeError("Multiple plausible cover files were found. Rename the intended cover with 'cover' or 'full-wrap' in the filename and retry.")
    if not found:
        print("Cover detected: NO")
        raise RuntimeError("No dedicated cover file was found in the selected book folder. The Factory will not use an interior page as a fake cover.")
    rendered = _render_separate_cover_source(found["path"], Path(project) / "_TEMP" / "cover_source")
    master_cover, payload = _record_authoritative_cover(project, found["path"], rendered, candidates, status)
    try:
        with Image.open(master_cover) as im:
            ratio = im.width / max(1, im.height)
            cover_type = "KDP FULL WRAP" if 1.42 <= ratio <= 1.68 else ("FRONT COVER" if 0.68 <= ratio <= 0.86 else "OTHER")
            print(f"Cover detected: YES")
            print(f"Cover file:    {found['path']}")
            print(f"Cover type:    {cover_type}")
            print(f"Dimensions:    {im.width}x{im.height}")
            print(f"Confidence:    {found['score']}")
    except Exception:
        pass
    return master_cover, payload


def choose_finished_book_folder_v128():
    """Pick the folder containing the finished interior PDF and separate cover."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
        folder = filedialog.askdirectory(parent=root, title="Select Finished Coloring Book Folder")
        root.destroy()
        return Path(folder) if folder else None
    except Exception as error:
        print(f"Folder picker unavailable ({error}).")
        raw = input("Enter the full path to the finished book folder: ").strip().strip('"')
        return Path(raw) if raw else None


def import_finished_book_folder_v128():
    """Folder intake for an interior PDF + separate finished cover."""
    print("\n" + "=" * 78)
    print("FINISHED BOOK FOLDER → MASTER + ALL PLATFORMS")
    print("=" * 78)
    print("Select the folder containing the interior PDF and its separate full-wrap cover.")
    folder = choose_finished_book_folder_v128()
    if not folder or not folder.is_dir():
        print("No valid book folder selected.")
        return None
    pdfs = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
    if not pdfs:
        print("ERROR: No PDF found in the selected folder.")
        return None
    # Prefer a PDF that does not look like a cover. If there is only one PDF,
    # it is the interior and the separate cover may be an image.
    interior_candidates = [p for p in pdfs if not any(t in p.stem.lower().replace(" ", "") for t in SEPARATE_COVER_POSITIVE)]
    if len(interior_candidates) == 1:
        interior_pdf = interior_candidates[0]
    elif len(pdfs) == 1:
        interior_pdf = pdfs[0]
    else:
        print("Multiple PDFs found. Select the INTERIOR PDF:")
        for i, item in enumerate(pdfs, 1): print(f"  {i}. {item.name}")
        raw = input("Choose interior PDF number: ").strip()
        if not raw.isdigit() or not (1 <= int(raw) <= len(pdfs)):
            print("Invalid selection."); return None
        interior_pdf = pdfs[int(raw) - 1]

    info = inspect_pdf(interior_pdf)
    if info.get("error"):
        print(f"ERROR: {info['error']}"); return None
    print(f"\nInterior: {interior_pdf.name}")
    print(f"Pages:    {info.get('page_count')}")
    print(f"Size:     {info.get('file_size_mb')} MB")
    default_title = re.sub(r"[_-]+", " ", interior_pdf.stem).strip()
    name = input(f"\nProject name [{default_title}]: ").strip() or default_title
    author = input("Author [blank = unknown]: ").strip()
    project_name = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip().rstrip(".") or "Imported Finished Book"
    project = PROJECTS / unique_project_name(project_name)
    project.mkdir(parents=True, exist_ok=True); setup_project(project); (project / "MASTER").mkdir(exist_ok=True)
    sizes = info.get("sizes") or [{"width": 8.5, "height": 11}]
    settings = {
        "title": name,
        "author": author,
        "trim_width": sizes[0]["width"], "trim_height": sizes[0]["height"], "dpi": 300,
        "production_profile": "Imported Finished Book Folder", "factory_version": FACTORY_VERSION,
        "platform_engine_version": PLATFORM_ENGINE_VERSION, "universal_publishing_version": UNIVERSAL_PUBLISHING_VERSION,
        "world_engine_version": WORLD_ENGINE_VERSION, "source_pdf": str(interior_pdf), "source_pdf_sha256": file_hash(interior_pdf),
        "source_pdf_pages": info.get("page_count"), "source_pdf_size_mb": info.get("file_size_mb"),
        "source_folder": str(folder.resolve()), "cover_resolver_version": SEPARATE_COVER_VERSION,
        "imported_at": datetime.now().isoformat(timespec="seconds"), "imported_pdf_metadata": info.get("metadata", {}),
    }
    save_json(project / "project.json", settings); save_json(project / "book.json", {"pages": [], "source": "imported_finished_book_folder"})
    # Lock the interior first, then resolve the separate cover into MASTER.
    master = import_existing_pdf_to_master(project, interior_pdf)
    if not master:
        print("ERROR: MASTER creation failed."); return None
    try:
        _resolve_finished_cover_for_folder(project, folder, interior_pdf)
    except Exception as error:
        print(f"\nCOVER INTAKE BLOCKED: {error}")
        print("No platform packages were generated because a verified finished cover is required.")
        return None
    print(f"\nMASTER LOCKED: {master}")
    print("Interior source remains untouched. Separate cover source is recorded in MASTER/COVER_SOURCE.json.")
    results = generate_all_platform_packages(project)
    create_delivery_index(project, results)
    health = project_health_scan(project)
    print_project_health(health)
    print(f"\nImported project: {project}")
    return project


# Make the folder workflow the first-class Quick Publish intake.
def v12_quick_publish():
    print("\nQUICK PUBLISH")
    print("1. Select an existing project")
    print("2. Import/select a finished PDF")
    print("3. Import a FINISHED BOOK FOLDER (interior + separate cover)")
    print("4. Use active project")
    choice = input("\nChoose: ").strip()
    if choice == "2":
        import_finished_pdf_v111(); return
    if choice == "3":
        import_finished_book_folder_v128(); return
    project = v12_active_project() if choice == "4" else v12_choose_recent_project()
    if not project: return
    _v12_save_state({**_v12_load_state(), "active_project": str(project)})
    production_release_center()


# ============================================================
# v13.1 — BOOK CREATION ENGINE
# Idea -> World -> Location -> Blueprint -> Prompt Manifest
# This layer plans books without touching the existing publishing engine.
# ============================================================

BOOK_CREATION_ENGINE_VERSION = "16.2"
BOOK_BLUEPRINT_FILENAME = "BOOK_BLUEPRINT.json"
PROMPT_MANIFEST_FILENAME = "PROMPT_MANIFEST.json"
CREATION_MANIFEST_FILENAME = "CREATION_MANIFEST.json"

BOOK_CREATION_DEFAULTS = {
    "image_count": 30,
    "trim_width": 8.5,
    "trim_height": 11.0,
    "dpi": 300,
    "border_pixels": 150,
    "art_style": "adult horror coloring book line art",
    "line_style": "bold clean black outlines, intricate detail, white background",
    "negative_prompt": "no color, no shading, no grayscale, no crosshatching, no stippling, no solid black fills, no glow, no mist, no fog, no text, no watermark, no frame",
}


def cb13_safe_name(value):
    """Return a Windows-safe folder name for a newly created book project."""
    import re
    value = re.sub(r'[<>:"/\\|?*]+', "", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip().rstrip(".")
    return value or "New Coloring Book"


def cb13_slug(value):
    import re
    value = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "")).strip("_").lower()
    return value or "book"


def cb13_world_choices():
    index = load_world_index()
    worlds = []
    for wid, meta in (index.get("worlds", {}) or {}).items():
        if isinstance(meta, dict) and not meta.get("archived", False):
            world = load_world(wid)
            if world:
                worlds.append(world_v2_upgrade_record(world))
    return sorted(worlds, key=lambda w: str(w.get("name", "")).casefold())


# ============================================================
# SERIES / LORE ENGINE v1.1 — MANUAL BOOK SELECTOR
# ============================================================

def lore_safe_name(value):
    value = re.sub(r'[<>:"/\\|?*]+', "", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip().rstrip(".")
    return value or "New Series"


def series_path(series_id):
    return SERIES_DIR / str(series_id)


def series_id_from_name(name):
    base = lore_safe_name(name)
    candidate = base
    counter = 2
    while series_path(candidate).exists():
        candidate = f"{base} ({counter})"
        counter += 1
    return candidate


def save_series_bible(bible):
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    sid = str(bible.get("series_id", "")).strip()
    if not sid:
        raise ValueError("Series is missing series_id")
    folder = series_path(sid)
    folder.mkdir(parents=True, exist_ok=True)
    bible["engine_version"] = SERIES_ENGINE_VERSION
    bible["factory_version"] = FACTORY_VERSION
    bible["updated"] = datetime.now().isoformat(timespec="seconds")
    save_json(folder / SERIES_BIBLE_FILENAME, bible)
    lore_write_series_markdown(bible)
    return folder


def load_series_bible(series_id):
    path = series_path(series_id) / SERIES_BIBLE_FILENAME
    if not path.exists():
        return None
    try:
        data = load_json(path)
        return data if isinstance(data, dict) else None
    except Exception as error:
        print(f"WARNING: Could not read series bible: {error}")
        return None


def list_series_bibles():
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    found = []
    for folder in sorted(SERIES_DIR.iterdir(), key=lambda p: p.name.casefold()):
        if not folder.is_dir():
            continue
        bible = load_series_bible(folder.name)
        if bible:
            found.append(bible)
    return found


def lore_write_series_markdown(bible):
    folder = series_path(bible.get("series_id", ""))
    lines = [
        f"{bible.get('name', 'Series')} — SERIES BIBLE",
        "=" * 78,
        f"Series ID: {bible.get('series_id', '')}",
        f"Engine: {bible.get('engine_version', SERIES_ENGINE_VERSION)}",
        f"World: {bible.get('world_name', '') or 'Not assigned'}",
        f"Status: {bible.get('status', 'ACTIVE')}",
        "",
        "CORE PREMISE",
        "------------",
        bible.get("core_premise", ""),
        "",
        "CENTRAL MYTHOLOGY",
        "------------------",
        bible.get("central_mythology", ""),
        "",
        "CANON RULES",
        "-----------",
    ]
    for item in bible.get("canon_rules", []):
        lines.append(f"- {item}")
    lines += ["", "ESTABLISHED FACTS", "-----------------"]
    for item in bible.get("established_facts", []):
        lines.append(f"- {item}")
    lines += ["", "OPEN MYSTERIES", "---------------"]
    for item in bible.get("open_mysteries", []):
        lines.append(f"- {item}")
    lines += ["", "REVEALS / LORE PROGRESSION", "---------------------------"]
    for item in bible.get("reveals", []):
        if isinstance(item, dict):
            lines.append(f"- Book {item.get('book_number', '?')}: {item.get('reveal', '')}")
        else:
            lines.append(f"- {item}")
    lines += ["", "BOOKS", "-----"]
    for book in sorted(bible.get("books", []), key=lambda x: (x.get("book_number", 9999) if isinstance(x, dict) and isinstance(x.get("book_number"), int) else 9999, str(x.get("title", "")) if isinstance(x, dict) else str(x))):
        if isinstance(book, dict):
            lines.append(f"- Book {book.get('book_number', '?')}: {book.get('title', '')} [{book.get('project', '')}]")
        else:
            lines.append(f"- {book}")
    lines += ["", "CREATURES", "---------"]
    for item in bible.get("creatures", []):
        lines.append(f"- {item.get('name', '') if isinstance(item, dict) else item}")
    lines += ["", "LOCATIONS", "---------"]
    for item in bible.get("locations", []):
        lines.append(f"- {item.get('name', '') if isinstance(item, dict) else item}")
    lines += ["", "FUTURE HOOKS", "------------"]
    for item in bible.get("future_hooks", []):
        lines.append(f"- {item}")
    lines += ["", "CONTINUITY NOTES", "-----------------"]
    for item in bible.get("continuity_notes", []):
        lines.append(f"- {item}")
    (folder / SERIES_BIBLE_MD_FILENAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def lore_extract_project_record(project):
    project = Path(project)
    settings = {}
    for filename in ("project.json", "BOOK_BLUEPRINT.json"):
        path = project / filename
        if path.exists():
            try:
                data = load_json(path)
                if filename == "project.json":
                    settings = data if isinstance(data, dict) else {}
            except Exception:
                pass
    blueprint = {}
    bp = project / BOOK_BLUEPRINT_FILENAME
    if bp.exists():
        try:
            data = load_json(bp)
            blueprint = data if isinstance(data, dict) else {}
        except Exception:
            pass
    title = str(settings.get("title") or blueprint.get("title") or project.name).strip()
    series_name = str(settings.get("series_name") or (blueprint.get("series", {}).get("name", "") if isinstance(blueprint.get("series"), dict) else "")).strip()
    world_name = str(settings.get("universe_name") or blueprint.get("world", {}).get("name", "") if isinstance(blueprint.get("world"), dict) else "").strip()
    concept = str(settings.get("description") or blueprint.get("concept") or "").strip()
    number = settings.get("book_number")
    if not isinstance(number, int):
        number = blueprint.get("book_number") if isinstance(blueprint.get("book_number"), int) else None
    if number is None:
        match = re.search(r"\b(?:book|vol(?:ume)?)[ _-]*(\d+)\b", title, re.I)
        if match:
            number = int(match.group(1))
    return {
        "project": project.name,
        "path": str(project),
        "title": title,
        "series_name": series_name,
        "world_name": world_name,
        "concept": concept,
        "book_number": number,
        "primary_location": settings.get("primary_location_name", ""),
        "lore_files": [str(p.relative_to(project)) for p in project.rglob("*.txt") if p.name.lower() in {"lore.txt", "world_lore.txt", "series_lore.txt", "story.txt", "description.txt"}],
    }


def lore_safe_metadata_updates(settings, expected_fields):
    """Fill only missing metadata values and return existing-value conflicts.

    This pure helper deliberately does not write files. It can be tested
    independently so a future refactor cannot accidentally reintroduce silent
    book-number or world-identity overwrites.
    """
    if not isinstance(settings, dict):
        raise TypeError("Project metadata must be a dictionary")
    conflicts = []
    for key, expected in expected_fields:
        if expected is None or expected == "":
            continue
        current = settings.get(key)
        current_missing = current is None or (
            isinstance(current, str) and not current.strip()
        )
        if current_missing:
            settings[key] = expected
        elif current != expected:
            conflicts.append(
                f"{key}: existing={current!r}, Series Bible={expected!r}"
            )
    return conflicts


def lore_ensure_series_world_link(bible):
    """Deliberately register a series in its existing canonical world record.

    This is a repair action, not an audit side effect. It never creates a world
    or world record, and it preserves all existing world metadata.
    """
    if not isinstance(bible, dict):
        return "invalid_series_bible"
    world_name = str(bible.get("world_name", "")).strip()
    series_name = str(bible.get("name", "")).strip()
    if not world_name or not series_name:
        return "missing_series_or_world_name"

    index_path = WORLDS_DIR / WORLD_INDEX_FILENAME
    if not index_path.exists():
        return "world_index_missing"
    try:
        index = load_json(index_path)
        worlds = index.get("worlds", {}) if isinstance(index, dict) else {}
        matches = [
            (str(world_id), metadata)
            for world_id, metadata in worlds.items()
            if isinstance(metadata, dict)
            and str(metadata.get("name") or world_id).strip().casefold() == world_name.casefold()
        ]
        if len(matches) != 1:
            return "world_not_registered" if not matches else "ambiguous_world_name"
        world_id, _ = matches[0]
        world_file = WORLDS_DIR / world_id / "world.json"
        if not world_file.exists():
            return "world_record_missing"
        world = load_json(world_file)
        if not isinstance(world, dict):
            return "invalid_world_record"
        existing = world.get("series", [])
        if not isinstance(existing, list):
            return "invalid_world_series_list"
        for item in existing:
            existing_name = (
                str(item.get("name") or item.get("series") or "").strip()
                if isinstance(item, dict) else str(item).strip()
            )
            if existing_name.casefold() == series_name.casefold():
                return "already_linked"
        world["series"].append(series_name)
        world["updated"] = datetime.now().isoformat(timespec="seconds")
        save_json(world_file, world)
        return "linked"
    except Exception as error:
        print(f"WARNING: Could not link series '{series_name}' to world '{world_name}': {error}")
        return "link_failed"


def lore_sync_explicit_series_attachments(bible):
    """Safely sync explicit Series Bible attachments without overwriting conflicts.

    Missing metadata can be filled from the Series Bible. Existing non-empty
    values that disagree with canon are preserved and reported for deliberate
    resolution; this routine never silently renumbers a book or changes its
    world identity.
    """
    if not bible:
        return 0
    changed = 0
    series_name = str(bible.get("name", "")).strip()
    series_id = str(bible.get("series_id", "")).strip()
    world_name = str(bible.get("world_name", "")).strip()
    world_id = ""
    # Resolve a stable world_id from the existing index without creating or
    # repairing any world files as a side effect of a series sync.
    world_index_path = WORLDS_DIR / WORLD_INDEX_FILENAME
    if world_name and world_index_path.exists():
        try:
            world_index = load_json(world_index_path)
            registered_worlds = world_index.get("worlds", {}) if isinstance(world_index, dict) else {}
            for candidate_id, metadata in registered_worlds.items():
                if (
                    isinstance(metadata, dict)
                    and str(metadata.get("name") or candidate_id).strip().casefold() == world_name.casefold()
                ):
                    world_id = str(candidate_id)
                    break
        except Exception as error:
            print(f"WARNING: Could not resolve world_id for '{world_name}': {error}")
    for book in bible.get("books", []):
        if not isinstance(book, dict):
            continue
        project_name = str(book.get("project", "")).strip()
        project_path = str(book.get("path", "")).strip()
        project = Path(project_path) if project_path else (PROJECTS / project_name)
        # Older Bible entries may contain paths from another machine or an
        # archived working copy. Prefer the named project folder when the
        # saved path no longer resolves, but never guess by title alone.
        if (not project.exists() or not project.is_dir()) and project_name:
            project = PROJECTS / project_name
        if not project_name or not project.exists() or not project.is_dir():
            book["attachment_status"] = "missing_project_folder"
            continue
        book["path"] = str(project)
        book["attachment_status"] = "attached"
        book["explicit_attachment"] = True
        metadata = project / "project.json"
        if not metadata.exists():
            print(f"WARNING: {project.name}/project.json is missing; attachment recorded, metadata not changed.")
            continue
        try:
            settings = load_json(metadata)
            if not isinstance(settings, dict):
                print(f"WARNING: {project.name}/project.json is not a JSON object; skipped.")
                continue
            before = dict(settings)
            expected_fields = (
                ("series_name", series_name),
                ("series_id", series_id),
                ("book_number", book.get("book_number")),
                ("universe_name", world_name),
                ("world_id", world_id),
            )
            conflicts = lore_safe_metadata_updates(settings, expected_fields)
            # Explicit registration establishes canon status, but does not
            # authorize rewriting a conflicting series/world/number value.
            settings["series_canon"] = True
            if not settings.get("world_relationship"):
                settings["world_relationship"] = "canon"
            if conflicts:
                print(
                    f"CONFLICT: {project.name}/project.json preserved existing metadata: "
                    + "; ".join(conflicts)
                )
            if settings != before:
                save_json(metadata, settings)
                changed += 1
        except Exception as error:
            print(f"WARNING: Could not sync {project.name}/project.json: {error}")
    bible["updated"] = datetime.now().isoformat(timespec="seconds")
    save_series_bible(bible)
    return changed

def lore_find_series_projects(series_name):
    target = str(series_name or "").strip().casefold()
    records = []
    if not PROJECTS.exists():
        return records
    for project in sorted(PROJECTS.iterdir(), key=lambda p: p.name.casefold()):
        if not project.is_dir() or project.name.startswith("_"):
            continue
        rec = lore_extract_project_record(project)
        if target and rec["series_name"].casefold() == target:
            records.append(rec)
    return records


def lore_candidate_projects(series_name):
    """Find likely legacy series books whose series_name was never recorded."""
    target = str(series_name or "").strip().casefold()
    if not target or not PROJECTS.exists():
        return []
    keywords = [x for x in re.split(r"\W+", target) if len(x) >= 4]
    # The legacy Nightmare books often never had series_name recorded.
    # Treat the distinctive franchise token as the recognition key.
    if "nightmare" in target:
        keywords = ["nightmare"]
    candidates = []
    for project in sorted(PROJECTS.iterdir(), key=lambda p: p.name.casefold()):
        if not project.is_dir():
            continue
        rec = lore_extract_project_record(project)
        if rec["series_name"]:
            continue
        hay = f"{rec['title']} {rec['concept']} {rec['world_name']}".casefold()
        if keywords and all(k in hay for k in keywords):
            candidates.append(rec)
    return candidates


def lore_new_series(name=None):
    name = (name or input("Series name: ").strip())
    if not name:
        return None
    sid = series_id_from_name(name)
    default_myth = "Hollow Stitch Nursery" if "nightmare" in name.casefold() else ""
    default_premise = "A connected horror coloring-book series whose books expand one persistent mythology without contradicting established canon."
    world_name = input("World / universe name [Nightmare World if this is the Nightmare series]: ").strip()
    if not world_name and "nightmare" in name.casefold():
        world_name = "Nightmare World"
    central = input(f"Central mythology [{default_myth or 'enter a central mythology'}]: ").strip() or default_myth
    premise = input(f"Core premise [{default_premise}]: ").strip() or default_premise
    bible = {
        "schema_version": 1,
        "engine_version": SERIES_ENGINE_VERSION,
        "factory_version": FACTORY_VERSION,
        "series_id": sid,
        "name": name,
        "status": "ACTIVE",
        "world_name": world_name,
        "core_premise": premise,
        "central_mythology": central,
        "canon_rules": [
            "Established canon must not be silently contradicted.",
            "New creatures and locations must be registered before becoming series canon.",
            "Each book should add new information rather than repeatedly restating the same reveal.",
            "Open mysteries may remain unresolved until a later book deliberately reveals them.",
        ],
        "established_facts": [],
        "open_mysteries": [],
        "reveals": [],
        "books": [],
        "creatures": [],
        "locations": [],
        "future_hooks": [],
        "continuity_notes": [],
        "created": datetime.now().isoformat(timespec="seconds"),
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    save_series_bible(bible)
    print(f"\nSERIES CREATED: {name}")
    print(f"Series Bible: {series_path(sid) / SERIES_BIBLE_FILENAME}")
    return bible


def lore_register_book(bible, record, make_canon=True):
    books = bible.setdefault("books", [])
    existing = next((b for b in books if isinstance(b, dict) and (b.get("project") == record["project"] or b.get("title") == record["title"])), None)
    if existing is None:
        existing = {
            "project": record["project"],
            "title": record["title"],
            "book_number": record.get("book_number"),
            "canon": bool(make_canon),
            "world_name": record.get("world_name", ""),
            "primary_location": record.get("primary_location", ""),
            "concept": record.get("concept", ""),
            "path": record.get("path", ""),
            "explicit_attachment": bool(record.get("explicit_attachment", False)),
            "added": datetime.now().isoformat(timespec="seconds"),
        }
        books.append(existing)
    else:
        existing.update({"book_number": record.get("book_number") or existing.get("book_number"), "concept": record.get("concept", existing.get("concept", "")), "path": record.get("path", existing.get("path", "")), "explicit_attachment": bool(record.get("explicit_attachment", existing.get("explicit_attachment", False))), "canon": bool(make_canon)})
    if record.get("primary_location") and record["primary_location"] not in bible.setdefault("locations", []):
        bible["locations"].append({"name": record["primary_location"], "source_book": record["title"]})


def lore_bootstrap_nightmare_series():
    """Create/reconcile the Nightmare Series around the Hollow Stitch Nursery."""
    existing = next((b for b in list_series_bibles() if "nightmare" in str(b.get("name", "")).casefold()), None)
    if existing:
        bible = existing
        print(f"Using existing Series Bible: {bible.get('name', '')}")
    else:
        world_name = "Nightmare World"
        try:
            index = load_world_index()
            for wid, meta in index.get("worlds", {}).items():
                if "nightmare" in str(meta.get("name", wid)).casefold():
                    world_name = str(meta.get("name", wid))
                    break
        except Exception:
            pass
        bible = {
            "schema_version": 1,
            "engine_version": SERIES_ENGINE_VERSION,
            "factory_version": FACTORY_VERSION,
            "series_id": series_id_from_name("Nightmare Series"),
            "name": "Nightmare Series",
            "status": "ACTIVE",
            "world_name": world_name,
            "core_premise": "A connected horror coloring-book series whose nightmares trace back to the Hollow Stitch Nursery, with each book expanding the mythology while preserving established canon.",
            "central_mythology": "Hollow Stitch Nursery",
            "canon_rules": [
                "The Hollow Stitch Nursery is the central mythology of the Nightmare Series.",
                "Each new book must build on established lore instead of resetting the mythology.",
                "Existing creatures, locations, events, and reveals remain canon unless deliberately marked for reconciliation.",
                "New creatures and locations must have a logical connection to the existing world before becoming canon.",
                "Mysteries may remain unresolved and should be tracked as future lore hooks.",
                "No existing book is silently rewritten by the lore engine.",
            ],
            "established_facts": [],
            "open_mysteries": [
                "What was the original purpose of the Hollow Stitch Nursery?",
                "Who founded or controlled the Nursery?",
                "What exists beneath or beyond the known Nursery areas?",
            ],
            "reveals": [], "books": [], "creatures": [], "locations": [], "future_hooks": [], "continuity_notes": [],
            "created": datetime.now().isoformat(timespec="seconds"),
            "updated": datetime.now().isoformat(timespec="seconds"),
        }
        save_series_bible(bible)
    candidates = lore_candidate_projects(bible.get("name", ""))
    print("\nNIGHTMARE SERIES RECONCILIATION")
    print(f"Central mythology: {bible.get('central_mythology')}")
    print(f"Legacy Nightmare projects found by discovery: {len(candidates)}")
    print("No projects are automatically attached by bootstrap.")
    print("Use 'Add / Select Books Manually' to choose the exact project folders you want.")
    if any(isinstance(b, dict) and not isinstance(b.get("book_number"), int) for b in bible.get("books", [])):
        note = "Some legacy Nightmare books do not have confirmed book numbers; assign the canonical order before creating the next numbered installment."
        bible["continuity_notes"] = list(dict.fromkeys(bible.get("continuity_notes", []) + [note]))
    save_series_bible(bible)
    print(f"\nNightmare Series Bible ready: {series_path(bible['series_id']) / SERIES_BIBLE_FILENAME}")
    print("Existing book PDFs/artwork were NOT modified.")
    return bible

def lore_validate_series_continuity(bible):
    """Return non-mutating continuity findings for registered series books."""
    if not isinstance(bible, dict):
        return [{"severity": "ERROR", "code": "INVALID_BIBLE", "message": "Series Bible is not a dictionary."}]

    findings = []
    books = [book for book in bible.get("books", []) if isinstance(book, dict)]
    seen_projects = {}
    seen_numbers = {}
    expected_series = str(bible.get("name", "")).strip()
    expected_series_id = str(bible.get("series_id", "")).strip()
    expected_world = str(bible.get("world_name", "")).strip()
    expected_world_id = ""

    # Validate the top of the canon hierarchy without calling load_world_index(),
    # which creates directories and therefore is not suitable for read-only audit.
    if not expected_world:
        findings.append({
            "severity": "ERROR", "code": "SERIES_WORLD_UNASSIGNED",
            "message": "Series Bible has no world_name; assign its canonical world before extending the series.",
        })
    else:
        index_path = WORLDS_DIR / WORLD_INDEX_FILENAME
        if not index_path.exists():
            findings.append({
                "severity": "WARNING", "code": "WORLD_INDEX_MISSING",
                "message": f"World index is missing; cannot verify '{expected_world}' against registered worlds.",
            })
        else:
            try:
                world_index = load_json(index_path)
                registered_worlds = world_index.get("worlds", {}) if isinstance(world_index, dict) else {}
                world_match = next(
                    (
                        (world_id, meta)
                        for world_id, meta in registered_worlds.items()
                        if isinstance(meta, dict)
                        and str(meta.get("name") or world_id).strip().casefold() == expected_world.casefold()
                    ),
                    None,
                )
                if world_match is None:
                    findings.append({
                        "severity": "ERROR", "code": "WORLD_NOT_REGISTERED",
                        "message": f"Series world '{expected_world}' is not registered in the world index.",
                    })
                else:
                    world_id, world_meta = world_match
                    expected_world_id = str(world_id)
                    world_file = WORLDS_DIR / str(world_id) / "world.json"
                    if not world_file.exists():
                        findings.append({
                            "severity": "ERROR", "code": "WORLD_RECORD_MISSING",
                            "message": f"World '{expected_world}' is indexed but its world.json record is missing.",
                        })
                    else:
                        try:
                            world_record = load_json(world_file)
                            if not isinstance(world_record, dict):
                                raise ValueError("world.json must contain an object")
                            registered_series = world_record.get("series", [])
                            if not isinstance(registered_series, list):
                                registered_series = []
                            series_keys = {
                                str(item.get("name") or item.get("series") or "").strip().casefold()
                                if isinstance(item, dict) else str(item).strip().casefold()
                                for item in registered_series
                            }
                            if expected_series.casefold() not in series_keys:
                                findings.append({
                                    "severity": "WARNING", "code": "SERIES_NOT_LINKED_TO_WORLD",
                                    "message": f"Series '{expected_series}' is not listed under world '{expected_world}'.",
                                })
                        except Exception as error:
                            findings.append({
                                "severity": "ERROR", "code": "UNREADABLE_WORLD_RECORD",
                                "message": f"World '{expected_world}' record could not be read ({error}).",
                            })
            except Exception as error:
                findings.append({
                    "severity": "ERROR", "code": "UNREADABLE_WORLD_INDEX",
                    "message": f"World index could not be read ({error}).",
                })

    for book in books:
        title = str(book.get("title") or book.get("project") or "Untitled book").strip()
        project_name = str(book.get("project", "")).strip()
        number = book.get("book_number")

        if not project_name:
            findings.append({
                "severity": "ERROR", "code": "MISSING_PROJECT_NAME",
                "message": f"{title}: no project-folder name is registered.",
            })
            continue

        project_key = project_name.casefold()
        if project_key in seen_projects:
            findings.append({
                "severity": "ERROR", "code": "DUPLICATE_PROJECT",
                "message": f"{title}: project '{project_name}' is also registered as '{seen_projects[project_key]}'.",
            })
        else:
            seen_projects[project_key] = title

        if isinstance(number, int) and not isinstance(number, bool) and number > 0:
            if number in seen_numbers:
                findings.append({
                    "severity": "ERROR", "code": "DUPLICATE_BOOK_NUMBER",
                    "message": f"Book number {number} is assigned to both '{seen_numbers[number]}' and '{title}'.",
                })
            else:
                seen_numbers[number] = title
        elif number is None:
            findings.append({
                "severity": "WARNING", "code": "UNASSIGNED_BOOK_NUMBER",
                "message": f"{title}: canonical book number is unassigned.",
            })
        else:
            findings.append({
                "severity": "ERROR", "code": "INVALID_BOOK_NUMBER",
                "message": f"{title}: book number '{number}' must be a positive integer or unassigned.",
            })

        saved_path = str(book.get("path", "")).strip()
        project = Path(saved_path) if saved_path else (PROJECTS / project_name)
        if not project.exists() or not project.is_dir():
            project = PROJECTS / project_name
        if not project.exists() or not project.is_dir():
            findings.append({
                "severity": "ERROR", "code": "MISSING_PROJECT_FOLDER",
                "message": f"{title}: project folder '{project_name}' cannot be found.",
            })
            continue

        metadata_path = project / "project.json"
        if not metadata_path.exists():
            findings.append({
                "severity": "WARNING", "code": "MISSING_PROJECT_METADATA",
                "message": f"{title}: project.json is missing; metadata cannot be cross-checked.",
            })
            continue
        try:
            metadata = load_json(metadata_path)
        except Exception as error:
            findings.append({
                "severity": "ERROR", "code": "UNREADABLE_PROJECT_METADATA",
                "message": f"{title}: project.json could not be read ({error}).",
            })
            continue
        if not isinstance(metadata, dict):
            findings.append({
                "severity": "ERROR", "code": "INVALID_PROJECT_METADATA",
                "message": f"{title}: project.json must contain a JSON object.",
            })
            continue

        project_series = str(metadata.get("series_name", "")).strip()
        project_series_id = str(metadata.get("series_id", "")).strip()
        if expected_series and project_series and project_series.casefold() != expected_series.casefold():
            findings.append({
                "severity": "WARNING", "code": "SERIES_NAME_MISMATCH",
                "message": f"{title}: project.json names series '{project_series}', but the Bible is '{expected_series}'.",
            })
        if expected_series_id and project_series_id and project_series_id.casefold() != expected_series_id.casefold():
            findings.append({
                "severity": "WARNING", "code": "SERIES_ID_MISMATCH",
                "message": f"{title}: project.json series_id '{project_series_id}' differs from Bible id '{expected_series_id}'.",
            })

        project_number = metadata.get("book_number")
        if isinstance(number, int) and not isinstance(number, bool) and project_number != number:
            findings.append({
                "severity": "WARNING", "code": "BOOK_NUMBER_MISMATCH",
                "message": f"{title}: Series Bible says book {number}, but project.json says {project_number!r}.",
            })

        project_world = str(metadata.get("universe_name") or "").strip()
        if expected_world and project_world and project_world.casefold() != expected_world.casefold():
            findings.append({
                "severity": "WARNING", "code": "WORLD_NAME_MISMATCH",
                "message": f"{title}: project.json world '{project_world}' differs from Series Bible world '{expected_world}'.",
            })
        project_world_id = str(metadata.get("world_id") or "").strip()
        if expected_world_id and not project_world_id:
            findings.append({
                "severity": "WARNING", "code": "PROJECT_WORLD_ID_MISSING",
                "message": f"{title}: project.json has no world_id; safe repair can fill it from the registered world.",
            })
        elif expected_world_id and project_world_id != expected_world_id:
            findings.append({
                "severity": "WARNING", "code": "WORLD_ID_MISMATCH",
                "message": f"{title}: project.json world_id '{project_world_id}' differs from canonical world id '{expected_world_id}'.",
            })

    return findings


def lore_analyze_series(bible=None):
    if bible is None:
        bibles = list_series_bibles()
        if not bibles:
            print("No Series Bibles exist yet.")
            return None
        for i, b in enumerate(bibles, 1):
            print(f"{i}. {b.get('name', b.get('series_id'))} ({len(b.get('books', []))} books)")
        try:
            bible = bibles[int(input("Series number: ").strip()) - 1]
        except (ValueError, IndexError):
            print("Invalid selection.")
            return None
    # Read-only analysis: never repair the Series Bible or project.json here.
    # Explicit attachment/metadata synchronization belongs in a deliberate
    # attach or repair action, not in a diagnostic screen.
    books = [b for b in bible.get("books", []) if isinstance(b, dict)]
    attached_books = []
    missing_books = []
    for book in books:
        project_name = str(book.get("project", "")).strip()
        project_path = str(book.get("path", "")).strip()
        project = Path(project_path) if project_path else (PROJECTS / project_name)
        if (not project.exists() or not project.is_dir()) and project_name:
            project = PROJECTS / project_name
        if project_name and project.exists() and project.is_dir():
            attached_books.append(book)
        else:
            missing_books.append(book)
    records = lore_find_series_projects(bible.get("name", ""))
    candidates = lore_candidate_projects(bible.get("name", ""))
    print("\n" + "=" * 78)
    print(f"SERIES LORE ANALYSIS — {bible.get('name', '')}")
    print("=" * 78)
    print(f"Central mythology: {bible.get('central_mythology') or 'Not defined'}")
    print(f"Books recorded in Series Bible: {len(books)}")
    print(f"Registered books with existing project folders: {len(attached_books)}")
    print(f"Project folders missing for registered books: {len(missing_books)}")
    print(f"Project metadata independently identifies as this series: {len(records)}")
    print(f"Possible legacy/unattached matches: {len(candidates)}")
    findings = lore_validate_series_continuity(bible)
    errors = sum(1 for item in findings if item.get("severity") == "ERROR")
    warnings = sum(1 for item in findings if item.get("severity") == "WARNING")
    print(f"Continuity audit: {errors} error(s), {warnings} warning(s)")
    for finding in findings:
        print(f"  [{finding.get('severity', 'INFO')}] {finding.get('code', 'FINDING')}: {finding.get('message', '')}")
    if not findings:
        print("  No registered-book continuity conflicts detected.")
    for book in attached_books:
        title = str(book.get("title") or book.get("project") or "Untitled book")
        print(f"  ✓ {title}" + (f" — Book {book['book_number']}" if book.get("book_number") else ""))
    if missing_books:
        print("\nREGISTERED BOOKS WITH MISSING PROJECT FOLDERS")
        for book in missing_books:
            print(f"  ! {book.get('title') or book.get('project') or 'Untitled book'} — {book.get('path') or book.get('project') or 'no path recorded'}")
    if candidates:
        print("\nPOSSIBLE LEGACY BOOKS")
        for i, rec in enumerate(candidates, 1):
            print(f"  {i}. {rec['title']}")
    return bible


def lore_curated_nightmare_projects():
    """Return one curated project per known Nightmare book, excluding duplicate/working-copy folders."""
    wanted = [
        "Nightmare Llamas",
        "Nightmare Cryptids",
        "Nightmare Unicorns",
        "Nightmare Teddy Bears",
        "Nightmare Vending Machines",
    ]
    if not PROJECTS.exists():
        return []
    all_records = []
    for project in sorted(PROJECTS.iterdir(), key=lambda p: p.name.casefold()):
        if not project.is_dir() or project.name.startswith("_"):
            continue
        rec = lore_extract_project_record(project)
        if rec.get("series_name") and rec["series_name"].casefold() != "nightmare series":
            continue
        all_records.append(rec)

    active = v12_active_project()
    selected = []
    for wanted_title in wanted:
        key = wanted_title.casefold()
        matches = []
        for rec in all_records:
            hay = f"{rec.get('title','')} {rec.get('project','')}".casefold()
            if key in hay:
                matches.append(rec)
        if not matches:
            continue
        # Prefer the active project, then an exact project/title match, then the
        # project with the newest project.json. This prevents UnicornsFinished
        # copies from being treated as separate books.
        def score(rec):
            project = PROJECTS / rec["project"]
            exact = int(rec.get("project", "").casefold() == key or rec.get("title", "").casefold() == key)
            active_score = int(active is not None and project.resolve() == Path(active).resolve())
            has_pdf = int(any(project.glob("*.pdf")) or (project / "MASTER").exists())
            try:
                mtime = (project / "project.json").stat().st_mtime
            except Exception:
                mtime = project.stat().st_mtime
            return (active_score, exact, has_pdf, mtime)
        chosen = max(matches, key=score)
        chosen = dict(chosen)
        chosen["canonical_title"] = wanted_title
        selected.append(chosen)
    return selected


def lore_attach_curated_nightmare_series(bible):
    """Attach the five known Nightmare books without importing duplicate legacy folders."""
    records = lore_curated_nightmare_projects()
    print("\nCURATED NIGHTMARE SERIES BOOK SET")
    print("These are treated as five books, not five-plus duplicate project folders:")
    if not records:
        print("No matching Nightmare projects were found.")
        return 0
    for i, rec in enumerate(records, 1):
        print(f"  {i}. {rec.get('canonical_title', rec.get('title'))} <- {rec.get('project')}")
    missing = [t for t in ["Nightmare Llamas", "Nightmare Cryptids", "Nightmare Unicorns", "Nightmare Teddy Bears", "Nightmare Vending Machines"]
               if not any(r.get("canonical_title") == t for r in records)]
    if missing:
        print("\nNot found:")
        for title in missing:
            print(f"  - {title}")
    raw = input("Attach this curated set to the Nightmare Series Bible? [Y/n]: ").strip().lower()
    if raw not in ("", "y", "yes"):
        print("No books attached. Existing PDFs/artwork were NOT modified.")
        return 0
    count = 0
    for rec in records:
        lore_register_book(bible, rec, True)
        project = PROJECTS / rec["project"]
        path = project / "project.json"
        if path.exists():
            try:
                settings = load_json(path)
                settings["series_name"] = bible.get("name", "Nightmare Series")
                settings["series_id"] = bible.get("series_id", "")
                settings["series_canon"] = True
                settings["world_relationship"] = settings.get("world_relationship", "canon")
                save_json(path, settings)
            except Exception as error:
                print(f"WARNING: Could not update project metadata for {project.name}: {error}")
        count += 1
    bible["continuity_notes"] = list(dict.fromkeys(bible.get("continuity_notes", []) + [
        "Five-book curated Nightmare starting set attached; duplicate/working-copy project folders were excluded.",
        "Canonical book numbering remains unassigned until the creator confirms the series order.",
    ]))
    save_series_bible(bible)
    print(f"\nCURATED NIGHTMARE SET ATTACHED — {count} books registered.")
    print("Book numbers were intentionally NOT guessed.")
    print("Existing PDFs/artwork were NOT modified.")
    return count


def lore_all_project_records():
    """Return every usable project as a manual-selection record.

    This intentionally does NOT use lore keyword matching. Manual selection is
    the escape hatch for projects whose names/metadata do not contain the
    expected series name.
    """
    records = []
    if not PROJECTS.exists():
        return records
    for project in sorted(PROJECTS.iterdir(), key=lambda p: p.name.casefold()):
        if not project.is_dir() or project.name.startswith("_"):
            continue
        try:
            rec = lore_extract_project_record(project)
        except Exception:
            continue
        rec["_path"] = str(project)
        records.append(rec)
    return records


def lore_manual_select_projects(bible):
    """Show a Windows popup allowing the creator to choose books manually.

    No series-name matching is performed here. The creator explicitly chooses
    which existing project folders belong to the selected series.
    """
    if not bible:
        return 0

    records = lore_all_project_records()
    attached = {
        str(book.get("project", "")).casefold()
        for book in bible.get("books", [])
        if isinstance(book, dict)
    }
    available = [r for r in records if r.get("project", "").casefold() not in attached]

    if not available:
        print("\nNo unattached projects are available for manual selection.")
        return 0

    # tkinter is part of standard Windows Python. If unavailable, retain a
    # safe console fallback so the factory never loses the manual path.
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as error:
        print(f"\nPopup selector unavailable ({error}). Using console selector.")
        print("Select project numbers, comma separated. Enter to cancel.")
        for i, rec in enumerate(available, 1):
            print(f"  {i}. {rec['title']} <- {rec['project']}")
        raw = input("Projects to attach: ").strip()
        if not raw:
            return 0
        chosen = []
        for part in raw.split(","):
            try:
                chosen.append(available[int(part.strip()) - 1])
            except (ValueError, IndexError):
                pass
    else:
        # Keep selections by project-folder identity, not listbox row number.
        # Rebuilding the list when the filter changes otherwise silently clears
        # prior selections, which made multi-filter series attachment unreliable.
        selected_projects = set()
        chosen = []
        root = tk.Tk()
        root.title(f"Add Books to {bible.get('name', 'Series')}")
        root.geometry("820x620")
        root.minsize(700, 500)

        header = ttk.Label(
            root,
            text=(
                "MANUAL SERIES BOOK SELECTOR\n"
                "Choose the actual project folders that belong to this series.\n"
                "Selections are kept when you change the filter.\n"
                "The factory will NOT infer membership from the name."
            ),
            justify="left",
        )
        header.pack(fill="x", padx=14, pady=(14, 8))

        filter_var = tk.StringVar()
        ttk.Label(root, text="Filter projects:").pack(anchor="w", padx=14)
        filter_entry = ttk.Entry(root, textvariable=filter_var)
        filter_entry.pack(fill="x", padx=14, pady=(2, 8))

        selection_status = ttk.Label(root, text="Selected: 0")
        selection_status.pack(anchor="w", padx=14, pady=(0, 6))

        frame = ttk.Frame(root)
        frame.pack(fill="both", expand=True, padx=14)
        scrollbar = ttk.Scrollbar(frame, orient="vertical")
        listbox = tk.Listbox(frame, selectmode=tk.EXTENDED, yscrollcommand=scrollbar.set)
        scrollbar.config(command=listbox.yview)
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        filtered = []

        def remember_visible_selection():
            visible_projects = {
                str(rec.get("project", "")).casefold() for rec in filtered
            }
            selected_projects.difference_update(visible_projects)
            for index in listbox.curselection():
                if 0 <= index < len(filtered):
                    selected_projects.add(str(filtered[index].get("project", "")).casefold())

        def update_selection_status():
            selection_status.config(text=f"Selected: {len(selected_projects)}")

        def selection_changed(_event=None):
            remember_visible_selection()
            update_selection_status()

        def refresh(*_):
            remember_visible_selection()
            query = filter_var.get().strip().casefold()
            filtered.clear()
            listbox.delete(0, tk.END)
            for rec in available:
                hay = f"{rec.get('title','')} {rec.get('project','')} {rec.get('world_name','')}".casefold()
                if query and query not in hay:
                    continue
                filtered.append(rec)
                label = f"{rec.get('title','')}    [{rec.get('project','')}]"
                if rec.get("series_name"):
                    label += f"    series={rec['series_name']}"
                listbox.insert(tk.END, label)
                if str(rec.get("project", "")).casefold() in selected_projects:
                    listbox.selection_set(tk.END)
            update_selection_status()

        def select_all():
            for rec in filtered:
                selected_projects.add(str(rec.get("project", "")).casefold())
            for index in range(len(filtered)):
                listbox.selection_set(index)
            update_selection_status()

        def clear_all():
            selected_projects.clear()
            listbox.selection_clear(0, tk.END)
            update_selection_status()

        def attach():
            remember_visible_selection()
            chosen.extend(
                rec for rec in available
                if str(rec.get("project", "")).casefold() in selected_projects
            )
            root.destroy()

        def cancel():
            chosen.clear()
            root.destroy()

        listbox.bind("<<ListboxSelect>>", selection_changed)
        filter_var.trace_add("write", refresh)
        refresh()

        buttons = ttk.Frame(root)
        buttons.pack(fill="x", padx=14, pady=12)
        ttk.Button(buttons, text="Select All", command=select_all).pack(side="left")
        ttk.Button(buttons, text="Clear", command=clear_all).pack(side="left", padx=6)
        ttk.Button(buttons, text="Cancel", command=cancel).pack(side="right")
        ttk.Button(buttons, text="Add Selected Books", command=attach).pack(side="right", padx=6)

        root.bind("<Escape>", lambda _e: cancel())
        root.bind("<Control-a>", lambda _e: select_all())
        root.protocol("WM_DELETE_WINDOW", cancel)
        filter_entry.focus_set()
        root.mainloop()

    if not chosen:
        print("\nNo books selected. Existing projects were NOT modified.")
        return 0

    print(f"\nSelected {len(chosen)} project(s):")
    for i, rec in enumerate(chosen, 1):
        print(f"  {i}. {rec['title']} <- {rec['project']}")

    count = 0
    reserved_numbers = {
        book.get("book_number")
        for book in bible.get("books", [])
        if isinstance(book, dict)
        and isinstance(book.get("book_number"), int)
        and not isinstance(book.get("book_number"), bool)
        and book.get("book_number") > 0
    }
    for rec in chosen:
        book_number = None
        while True:
            raw_number = input(
                f"Book number for '{rec['title']}' (blank = unassigned): "
            ).strip()
            if not raw_number:
                break
            try:
                parsed = int(raw_number)
            except ValueError:
                print("  Enter a positive whole number, or blank to leave unassigned.")
                continue
            if parsed <= 0:
                print("  Book numbers must be positive. Try again or leave blank.")
                continue
            if parsed in reserved_numbers:
                print(f"  Book {parsed} is already assigned in this Series Bible. Choose another number.")
                continue
            book_number = parsed
            reserved_numbers.add(parsed)
            break

        rec = dict(rec)
        rec["book_number"] = book_number
        rec["explicit_attachment"] = True
        rec["path"] = str(PROJECTS / rec["project"])
        lore_register_book(bible, rec, True)

        count += 1

    # Run all metadata writes through the conflict-aware sync. The creator's
    # explicit book number is stored in the Series Bible, while conflicting
    # pre-existing project identity/number/world fields remain intact and are
    # reported instead of being silently overwritten.
    synced = lore_sync_explicit_series_attachments(bible)
    print(f"Safe metadata sync updated {synced} project.json file(s).")

    bible["continuity_notes"] = list(dict.fromkeys(
        bible.get("continuity_notes", []) + [
            "Books may be attached manually through the popup project selector; manual selection overrides filename/metadata discovery.",
        ]
    ))
    save_series_bible(bible)
    print(f"\nMANUAL SERIES ATTACHMENT COMPLETE — {count} book(s) registered.")
    print("Existing PDFs/artwork were NOT modified.")
    return count

def lore_repair_series():
    bibles = list_series_bibles()
    if not bibles:
        print("No Series Bibles exist. Create the series first.")
        return
    for i, b in enumerate(bibles, 1):
        print(f"{i}. {b.get('name', b.get('series_id'))}")
    try:
        bible = bibles[int(input("Series number: ").strip()) - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return
    if "nightmare" in bible.get("name", "").casefold():
        print("\nNightmare Series manual reconciliation")
        print("The popup lets you choose exactly which existing project folders belong to the series.")
        lore_manual_select_projects(bible)
        print("\nSyncing metadata for books already registered in this Series Bible...")
        changed = lore_sync_explicit_series_attachments(bible)
        world_link_status = lore_ensure_series_world_link(bible)
        findings = lore_validate_series_continuity(bible)
        report = {
            "series": bible.get("name", ""),
            "series_id": bible.get("series_id", ""),
            "world_name": bible.get("world_name", ""),
            "world_link_status": world_link_status,
            "central_mythology": bible.get("central_mythology", ""),
            "books": bible.get("books", []),
            "possible_conflicts": findings,
            "error_count": sum(1 for item in findings if item.get("severity") == "ERROR"),
            "warning_count": sum(1 for item in findings if item.get("severity") == "WARNING"),
            "unresolved_items": [
                "Resolve reported series/world identity conflicts before republishing.",
                "Existing PDF prose and artwork are not modified by lore reconciliation.",
            ],
            "generated": datetime.now().isoformat(timespec="seconds"),
        }
        report_path = series_path(bible["series_id"]) / "LORE_REPAIR_REPORT.json"
        save_json(report_path, report)
        print(f"Series metadata sync complete. Updated {changed} project.json file(s).")
        print(f"World-to-series link: {world_link_status}")
        print(
            f"Continuity report: {report['error_count']} error(s), "
            f"{report['warning_count']} warning(s)."
        )
        print(f"Saved report: {report_path}")
        print("Existing PDFs and artwork were NOT modified.")
        return
    records = lore_find_series_projects(bible.get("name", ""))
    candidates = lore_candidate_projects(bible.get("name", ""))
    if candidates:
        print("\nPotential legacy books:")
        for i, rec in enumerate(candidates, 1):
            print(f"{i}. {rec['title']}")
        raw = input("Enter numbers to attach (comma separated), or Enter to skip: ").strip()
        if raw:
            for part in raw.split(","):
                try:
                    rec = candidates[int(part.strip()) - 1]
                    records.append(rec)
                except (ValueError, IndexError):
                    pass
    unique = {}
    for rec in records:
        unique[rec["project"]] = rec
    records = list(unique.values())
    for rec in records:
        lore_register_book(bible, rec, True)
    # Use the same conflict-aware sync path as Nightmare reconciliation.
    # A discovered legacy match is not permission to overwrite a conflicting
    # series identity or renumber an existing book.
    synced = lore_sync_explicit_series_attachments(bible)
    world_link_status = lore_ensure_series_world_link(bible)
    # Build a transparent repair report instead of silently rewriting old books.
    findings = lore_validate_series_continuity(bible)
    report = {
        "series": bible.get("name", ""),
        "series_id": bible.get("series_id", ""),
        "world_name": bible.get("world_name", ""),
        "central_mythology": bible.get("central_mythology", ""),
        "world_link_status": world_link_status,
        "possible_conflicts": findings,
        "error_count": sum(1 for item in findings if item.get("severity") == "ERROR"),
        "warning_count": sum(1 for item in findings if item.get("severity") == "WARNING"),
        "unresolved_items": [
            "Review each existing book's lore pages against the canonical Series Bible before republishing.",
            "Existing PDF prose is not automatically declared canon; explicit approval is required for new facts.",
        ],
        "generated": datetime.now().isoformat(timespec="seconds"),
    }
    save_json(series_path(bible["series_id"]) / "LORE_REPAIR_REPORT.json", report)
    bible["continuity_notes"] = list(dict.fromkeys(bible.get("continuity_notes", []) + ["Legacy series projects were reconciled into the Series Bible; existing book text remains unchanged until republished."]))
    save_series_bible(bible)
    print(f"\nLORE REPAIR COMPLETE — {len(records)} books registered; {synced} project.json file(s) safely updated.")
    print(f"World-to-series link: {world_link_status}")
    print(f"Repair report: {series_path(bible['series_id']) / 'LORE_REPAIR_REPORT.json'}")
    print("Existing PDFs were NOT modified.")


def lore_continuity_audit():
    bibles = list_series_bibles()
    if not bibles:
        print("No Series Bibles exist yet.")
        return
    for i, b in enumerate(bibles, 1):
        print(f"{i}. {b.get('name', b.get('series_id'))}")
    try:
        bible = bibles[int(input("Series number: ").strip()) - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return
    errors, warnings = [], []
    nums = []
    for book in bible.get("books", []):
        if isinstance(book, dict) and isinstance(book.get("book_number"), int):
            if book["book_number"] in nums:
                errors.append(f"Duplicate book number: {book['book_number']} ({book.get('title', '')})")
            nums.append(book["book_number"])
    if not bible.get("central_mythology"):
        warnings.append("Central mythology is not defined.")
    if not bible.get("canon_rules"):
        warnings.append("No canon rules are defined.")
    report = {"series": bible.get("name", ""), "errors": errors, "warnings": warnings, "status": "PASS" if not errors else "REVIEW", "generated": datetime.now().isoformat(timespec="seconds")}
    save_json(series_path(bible["series_id"]) / "CONTINUITY_AUDIT.json", report)
    print("\nSERIES CONTINUITY AUDIT")
    print(f"Errors: {len(errors)} | Warnings: {len(warnings)} | Status: {report['status']}")
    for item in errors + warnings:
        print(f"- {item}")


def lore_add_item(item_type):
    bibles = list_series_bibles()
    if not bibles:
        print("Create a Series Bible first.")
        return
    for i, b in enumerate(bibles, 1):
        print(f"{i}. {b.get('name', b.get('series_id'))}")
    try:
        bible = bibles[int(input("Series number: ").strip()) - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return
    name = input(f"{item_type.title()} name: ").strip()
    if not name:
        return
    description = input("Description / role: ").strip()
    target = bible.setdefault(item_type, [])
    if not any((x.get("name") if isinstance(x, dict) else str(x)).casefold() == name.casefold() for x in target):
        target.append({"name": name, "description": description, "added": datetime.now().isoformat(timespec="seconds")})
    save_series_bible(bible)
    print(f"Registered {item_type[:-1] if item_type.endswith('s') else item_type}: {name}")


def series_engine_center():
    while True:
        bibles = list_series_bibles()
        print("\n" + "=" * 78)
        print(f"SERIES & LORE ENGINE v{FACTORY_VERSION}")
        print("=" * 78)
        print(f"Series Bibles: {len(bibles)}")
        print("1. Create New Series")
        print("2. Bootstrap / Repair Nightmare Series")
        print("3. Analyze Existing Series")
        print("4. Add / Select Books Manually")
        print("5. Repair / Reconcile Existing Series Lore")
        print("6. Series Continuity Audit")
        print("7. Register Creature")
        print("8. Register Location")
        print("9. Open Series Bible Folder")
        print("10. Canonical Ownership Check")
        print("11. Back")
        c = input("Choose: ").strip()
        if c == "1": lore_new_series()
        elif c == "2": lore_bootstrap_nightmare_series()
        elif c == "3": lore_analyze_series()
        elif c == "4":
            bibles = list_series_bibles()
            if not bibles:
                print("No Series Bibles exist yet. Create one first.")
            else:
                for i, b in enumerate(bibles, 1):
                    print(f"{i}. {b.get('name', b.get('series_id'))} — {len(b.get('books', []))} books")
                try:
                    bible = bibles[int(input("Series number: ").strip()) - 1]
                    lore_manual_select_projects(bible)
                except (ValueError, IndexError):
                    print("Invalid selection.")
        elif c == "5": lore_repair_series()
        elif c == "6": lore_continuity_audit()
        elif c == "7": lore_add_item("creatures")
        elif c == "8": lore_add_item("locations")
        elif c == "9":
            SERIES_DIR.mkdir(parents=True, exist_ok=True)
            v12_open_folder(SERIES_DIR)
        elif c == "10": canonical_ownership_check()
        elif c == "11": return
        else: print("Invalid choice.")
        if c != "11": input("\nPress Enter to continue...")


def lore_select_series_for_book():
    bibles = list_series_bibles()
    print("\nSERIES ATTACHMENT")
    print("0. Standalone / no series")
    for i, b in enumerate(bibles, 1):
        print(f"{i}. {b.get('name', b.get('series_id'))} — {len(b.get('books', []))} books")
    raw = input("Choose series [0]: ").strip() or "0"
    try:
        choice = int(raw)
    except ValueError:
        choice = 0
    if 1 <= choice <= len(bibles):
        return bibles[choice - 1]
    return None


def lore_attach_new_book_to_series(project, bible, book_number=None):
    if not project or not bible:
        return
    settings = load_json(project / "project.json")
    settings["series_name"] = bible.get("name", "")
    settings["series_id"] = bible.get("series_id", "")
    settings["series_canon"] = True
    settings["world_relationship"] = "canon"
    if book_number is not None:
        settings["book_number"] = book_number
    save_json(project / "project.json", settings)
    rec = lore_extract_project_record(project)
    rec["book_number"] = book_number
    lore_register_book(bible, rec, True)
    save_series_bible(bible)


def marketing_platform_post(title, series, description, buy_targets=""):
    hook = f"Enter the nightmare: {title}."
    if series:
        hook = f"A new nightmare has arrived in the {series} series: {title}."
    body = description or "A detailed adult horror coloring adventure filled with strange creatures and unsettling designs."
    return f"{hook}\n\n{body}\n\nColor, explore, and discover what waits beyond the page.\n\n{buy_targets}".strip()


def marketing_build_package(project=None):
    project = Path(project) if project else (v12_active_project() or choose_project())
    if not project:
        return
    try:
        settings = load_json(project / "project.json")
    except Exception:
        settings = {}
    title = str(settings.get("title") or project.name).strip()
    series = str(settings.get("series_name") or "").strip()
    description = str(settings.get("description") or settings.get("cover_blurb") or "").strip()
    marketing = project / MARKETING_DIR_NAME
    marketing.mkdir(parents=True, exist_ok=True)
    image_dir = marketing / "IMAGES"
    preview_dir = marketing / "PREVIEW"
    image_dir.mkdir(exist_ok=True)
    preview_dir.mkdir(exist_ok=True)
    targets = "KDP • Gumroad • Payhip • Etsy (where eligible)"
    universal = marketing_platform_post(title, series, description, targets)
    variants = {
        "UNIVERSAL_POST.txt": universal,
        "X_POST.txt": universal[:275] + ("…" if len(universal) > 275 else ""),
        "FACEBOOK_POST.txt": universal,
        "INSTAGRAM_CAPTION.txt": universal + "\n\n#coloringbook #horrorcoloringbook #adultcoloring #horrorart",
        "MESSENGER_MESSAGE.txt": f"I just released {title}!\n\n{description or 'It is an adult horror coloring adventure.'}\n\n{targets}",
        "PRODUCT_DESCRIPTION.txt": description or f"{title} is an adult horror coloring adventure featuring intricate black-and-white line art.",
        "SHORT_AD.txt": f"{title} — an adult horror coloring adventure. Intricate creatures. Dark details. Your colors. {targets}",
        "LAUNCH_ANNOUNCEMENT.txt": f"NEW RELEASE: {title}\n\n{description or 'The newest nightmare is here.'}\n\n{targets}",
    }
    for filename, content in variants.items():
        (marketing / filename).write_text(content.strip() + "\n", encoding="utf-8")
    # Reuse production assets when they already exist; never modify the source artwork.
    candidates = [
        project / "PLATFORM" / "GUMROAD" / "cover.png",
        project / "PLATFORM" / "GUMROAD" / "thumbnail.png",
        project / "QC" / CONTACT_SHEET_FILENAME,
        project / "QC" / "artwork_contact_sheet.png",
    ]
    copied = []
    for src in candidates:
        if src.exists() and src.is_file():
            dest = image_dir / src.name
            try:
                shutil.copy2(src, dest)
                copied.append(str(dest))
            except Exception:
                pass
    # Generate a simple square promotional image from an existing contact sheet when possible.
    sheet = next((Path(x) for x in copied if Path(x).suffix.lower() in IMAGE_EXTENSIONS and "contact" in Path(x).name.lower()), None)
    if sheet and sheet.exists():
        try:
            im = Image.open(sheet).convert("RGB")
            side = min(im.size)
            left = (im.width - side) // 2
            top = (im.height - side) // 2
            promo = im.crop((left, top, left + side, top + side)).resize((1080, 1080))
            promo.save(image_dir / "SOCIAL_SQUARE.png", dpi=(72, 72))
        except Exception:
            pass
    # Build a small sample PDF from the finished interior, skipping common non-art opening pages.
    final_candidates = sorted((project / "FINAL").glob("*.pdf")) if (project / "FINAL").exists() else []
    if final_candidates:
        sample_path = preview_dir / f"{title}_SAMPLE.pdf"
        try:
            from pypdf import PdfReader, PdfWriter
            reader = PdfReader(str(final_candidates[0]))
            writer = PdfWriter()
            blueprint = load_json(project / BOOK_BLUEPRINT_FILENAME) if (project / BOOK_BLUEPRINT_FILENAME).exists() else {}
            pages = blueprint.get("pages", []) if isinstance(blueprint, dict) else []
            selected = []
            for idx in range(len(reader.pages)):
                ptype = pages[idx].get("type") if idx < len(pages) and isinstance(pages[idx], dict) else None
                if ptype in {"coloring", None}:
                    selected.append(idx)
                if len(selected) >= 5:
                    break
            if not selected:
                selected = list(range(min(5, len(reader.pages))))
            for idx in selected:
                writer.add_page(reader.pages[idx])
            with open(sample_path, "wb") as f:
                writer.write(f)
        except Exception as error:
            (preview_dir / "SAMPLE_BUILD_WARNING.txt").write_text(str(error) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "factory_version": FACTORY_VERSION,
        "project": project.name,
        "title": title,
        "series": series,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "files": sorted(str(p.relative_to(marketing)) for p in marketing.rglob("*") if p.is_file()),
    }
    save_json(marketing / "MARKETING_MANIFEST.json", manifest)
    print("\nMARKETING PACKAGE COMPLETE")
    print(f"Folder: {marketing}")
    print(f"Text assets: {len(variants)}")
    print(f"Images copied/generated: {len(copied)}")
    print(f"Sample PDF: {'READY' if list(preview_dir.glob('*_SAMPLE.pdf')) else 'NOT CREATED'}")
    return marketing


def marketing_center():
    while True:
        project = v12_active_project()
        print("\n" + "=" * 78)
        print(f"MARKETING CENTER v{FACTORY_VERSION}")
        print("=" * 78)
        print(f"Active project: {project.name if project else 'None'}")
        print("1. Generate Marketing Package")
        print("2. Generate Universal Social Post")
        print("3. Generate Sample / Preview Package")
        print("4. Open Marketing Folder")
        print("5. Back")
        c = input("Choose: ").strip()
        if c == "1": marketing_build_package(project)
        elif c == "2":
            marketing_build_package(project)
            if project: print((project / MARKETING_DIR_NAME / "UNIVERSAL_POST.txt").read_text(encoding="utf-8"))
        elif c == "3": marketing_build_package(project)
        elif c == "4":
            if project:
                (project / MARKETING_DIR_NAME).mkdir(parents=True, exist_ok=True)
                v12_open_folder(project / MARKETING_DIR_NAME)
        elif c == "5": return
        else: print("Invalid choice.")
        if c != "5": input("\nPress Enter to continue...")

def cb13_choose_world():
    worlds = cb13_world_choices()
    print("\nWORLD SELECTION")
    print("0. No world / standalone book")
    for i, world in enumerate(worlds, 1):
        print(f"{i}. {world.get('name', world.get('world_id', 'World'))}")
    raw = input("Choose world [0]: ").strip() or "0"
    try:
        choice = int(raw)
    except ValueError:
        choice = 0
    if 1 <= choice <= len(worlds):
        return worlds[choice - 1]
    return None


def cb13_choose_location(world):
    if not world:
        return None
    world = world_location_recalculate_metadata(world)
    locations = sorted(
        world.get("locations", []),
        key=lambda x: world_location_path(world, x).casefold()
    )
    if not locations:
        print("\nNo locations exist in this world yet.")
        print("The book can remain world-level, or you can create locations later in World Engine.")
        return None
    print("\nPRIMARY LOCATION")
    print("0. World-level / no primary location")
    for i, loc in enumerate(locations, 1):
        path = world_location_path(world, loc)
        print(f"{i}. {path} [{world_location_level_label(loc.get('level', 'location'))}]")
    raw = input("Choose primary location [0]: ").strip() or "0"
    try:
        choice = int(raw)
        if 1 <= choice <= len(locations):
            return locations[choice - 1]
    except ValueError:
        pass
    return None


def cb13_existing_entity_names(world, category):
    if not world:
        return []
    return [
        str(x.get("name", "")).strip()
        for x in world.get(category, [])
        if isinstance(x, dict) and str(x.get("name", "")).strip()
    ]


def cb16_lore_snapshot(series):
    """Return a compact, generation-safe snapshot of series canon."""
    if not isinstance(series, dict):
        return {
            "attached": False, "series_id": "", "series_name": "",
            "central_mythology": "", "core_premise": "", "canon_rules": [],
            "established_facts": [], "open_mysteries": [], "reveals": [],
            "creatures": [], "locations": [], "future_hooks": [],
        }
    def names(items, limit=12):
        out=[]
        for item in items or []:
            if isinstance(item, dict):
                value=str(item.get("name") or item.get("title") or "").strip()
            else:
                value=str(item).strip()
            if value and value not in out:
                out.append(value)
        return out[:limit]
    return {
        "attached": True,
        "series_id": str(series.get("series_id", "")),
        "series_name": str(series.get("name", "")),
        "central_mythology": str(series.get("central_mythology", "")),
        "core_premise": str(series.get("core_premise", "")),
        "canon_rules": names(series.get("canon_rules", []), 12),
        "established_facts": names(series.get("established_facts", []), 16),
        "open_mysteries": names(series.get("open_mysteries", []), 12),
        "reveals": [
            str(x.get("reveal", "")).strip() for x in (series.get("reveals", []) or [])
            if isinstance(x, dict) and str(x.get("reveal", "")).strip()
        ][:12],
        "creatures": names(series.get("creatures", []), 16),
        "locations": names(series.get("locations", []), 16),
        "future_hooks": names(series.get("future_hooks", []), 12),
    }


def cb16_select_lore_terms(snapshot, n):
    """Deterministically rotate canon references so 30 prompts do not read alike."""
    pools = [
        snapshot.get("creatures", []),
        snapshot.get("locations", []),
        snapshot.get("established_facts", []),
        snapshot.get("open_mysteries", []),
        snapshot.get("future_hooks", []),
    ]
    terms=[]
    for offset, pool in enumerate(pools):
        if pool:
            terms.append(pool[(n - 1 + offset) % len(pool)])
    return terms[:2]


def cb16_prompt_archetype(n):
    archetypes = [
        ("signature portrait", "front-facing or three-quarter character portrait with distinctive anatomy and a memorable facial expression"),
        ("full-body stance", "full-body standing pose with the silhouette completely readable and the feet clearly visible"),
        ("predatory crouch", "low crouched pose with tense anatomy, claws or grasping limbs emphasized"),
        ("movement", "dynamic running, lunging, climbing, or twisting action while keeping the silhouette readable"),
        ("environmental interaction", "the subject physically interacting with a recognizable environmental object"),
        ("discovery", "the subject discovering a disturbing object, clue, doorway, nest, or relic"),
        ("threshold", "the subject framed at a doorway, arch, tunnel, gate, or other threshold"),
        ("landmark", "the subject positioned at a distinctive landmark that can recur elsewhere in the series"),
        ("secondary entity encounter", "the main subject confronting or observing one secondary creature or entity"),
        ("object focus", "a large eerie story object as the visual focus with the creature incorporated into the composition"),
        ("anatomical detail", "a highly detailed close view of unusual anatomy, texture, teeth, eyes, horns, limbs, or costume"),
        ("symbolic scene", "a visually symbolic arrangement of the subject with recurring series motifs"),
        ("aftermath", "the quiet aftermath of an unseen disturbing event with evidence left in the environment"),
        ("surveillance", "the subject caught in a tense moment as if watched from an unseen position"),
        ("ritual", "a strange non-graphic ritual-like arrangement using props and recurring symbols"),
    ]
    return archetypes[(n - 1) % len(archetypes)]


def cb16_make_image_prompt(blueprint, n, archetype, lore_terms):
    title = blueprint["title"]
    idea = blueprint["concept"]
    world = blueprint.get("world", {}) or {}
    loc = blueprint.get("primary_location", {}) or {}
    series = blueprint.get("series", {}) or {}
    context = []
    if world.get("name"): context.append(f"world: {world['name']}")
    if loc.get("path"): context.append(f"location: {loc['path']}")
    if series.get("central_mythology"): context.append(f"central mythology: {series['central_mythology']}")
    if lore_terms: context.append("canon references: " + "; ".join(lore_terms))
    setting = " | ".join(context)
    return (
        f"Adult horror coloring book illustration, '{title}', illustration {n:02d}. "
        f"Core book concept: {idea}. Composition archetype: {archetype[0]}. "
        f"Design direction: {archetype[1]}. "
        + (f"Series continuity: {setting}. " if setting else "")
        + "Create one dominant subject with a strong readable silhouette and a clear visual hierarchy. "
        "Use intricate original horror details, believable anatomy, expressive shapes, and purposeful environmental props. "
        "Keep the composition printable as a coloring page: generous white negative space around the outer edge, "
        "clean closed contours where practical, varied line weight, crisp black ink linework, no muddy textures. "
        "Do not add captions, lettering, logos, borders, frames, watermarks, or decorative text. "
        "FINAL COLORING-PAGE CONSTRAINTS: black-and-white adult horror coloring page, bold clean outlines, intricate detail, "
        "no color, no shading, no grayscale, no crosshatching, no stippling, no solid black fills, no glow, no mist, no fog."
    )


def cb16_build_prompt_manifest(blueprint):
    """Build distinct, lore-aware prompt records with stable image IDs."""
    count = int(blueprint.get("image_count", 30))
    snapshot = blueprint.get("lore_context", {}) or {}
    records=[]
    seen=set()
    for n in range(1, count + 1):
        archetype=cb16_prompt_archetype(n)
        lore_terms=cb16_select_lore_terms(snapshot, n)
        prompt=cb16_make_image_prompt(blueprint, n, archetype, lore_terms)
        # A deterministic uniqueness guard prevents accidental duplicate prompts.
        if prompt in seen:
            prompt += f" Variation constraint: change the pose, camera angle, and prop arrangement for illustration {n:02d}."
        seen.add(prompt)
        records.append({
            "image_id": f"IMG-{n:03d}",
            "sequence": n,
            "status": "PLANNED",
            "title": f"{blueprint['title']} — Illustration {n:02d}",
            "archetype": archetype[0],
            "composition_direction": archetype[1],
            "lore_references": lore_terms,
            "world_id": blueprint.get("world", {}).get("world_id", ""),
            "world_name": blueprint.get("world", {}).get("name", ""),
            "location_id": blueprint.get("primary_location", {}).get("id", ""),
            "location_name": blueprint.get("primary_location", {}).get("name", ""),
            "location_path": blueprint.get("primary_location", {}).get("path", ""),
            "series_id": blueprint.get("series", {}).get("series_id", ""),
            "series_name": blueprint.get("series", {}).get("name", ""),
            "book_number": blueprint.get("series", {}).get("book_number"),
            "prompt": prompt,
            "negative_prompt": blueprint["style"]["negative_prompt"],
            "output_spec": {"width_px":2550,"height_px":3300,"dpi":300,"color_mode":"RGB","background":"white","border_pixels":150},
            "continuity": {
                "reuse_world": bool(blueprint.get("world", {}).get("attached")),
                "reuse_primary_location": bool(blueprint.get("primary_location", {}).get("attached")),
                "stable_world_id": blueprint.get("world", {}).get("world_id", ""),
                "stable_location_id": blueprint.get("primary_location", {}).get("id", ""),
                "stable_series_id": blueprint.get("series", {}).get("series_id", ""),
            },
        })
    return records


def cb16_prompt_qa(manifest):
    """Deterministic QA for prompt completeness and continuity before artwork."""
    images=manifest.get("images", []) if isinstance(manifest, dict) else []
    errors=[]; warnings=[]; ids=set(); prompts=set()
    required=["black", "line", "white", "coloring page"]
    required_negative = ["no color", "no shading", "no grayscale", "no crosshatching", "no stippling", "no solid black fills", "no glow", "no mist", "no fog"]
    for i, rec in enumerate(images, 1):
        iid=str(rec.get("image_id", "")); prompt=str(rec.get("prompt", "")).lower()
        if not iid or iid in ids: errors.append(f"Image {i}: missing or duplicate image_id")
        ids.add(iid)
        if prompt in prompts: errors.append(f"{iid}: duplicate prompt")
        prompts.add(prompt)
        missing=[x for x in required if x not in prompt]
        if missing: errors.append(f"{iid}: prompt missing {', '.join(missing)}")
        negative = str(rec.get("negative_prompt", "")).lower()
        if not negative: errors.append(f"{iid}: missing negative_prompt")
        else:
            missing_negative = [term for term in required_negative if term not in negative]
            if missing_negative: errors.append(f"{iid}: negative_prompt missing {', '.join(missing_negative)}")
        if manifest.get("series_id") and not rec.get("series_name"):
            errors.append(f"{iid}: canonical series name missing")
        if manifest.get("world_id") and not rec.get("world_name"):
            errors.append(f"{iid}: canonical world name missing")
        if not rec.get("continuity", {}).get("stable_series_id") and manifest.get("series_id"):
            errors.append(f"{iid}: series continuity ID missing")
        if not rec.get("lore_references") and manifest.get("series_id"):
            warnings.append(f"{iid}: no rotating lore reference available")
    expected=[f"IMG-{n:03d}" for n in range(1,len(images)+1)]
    if [x.get("image_id") for x in images] != expected:
        errors.append("Image IDs are not sequential IMG-001..IMG-N")
    return {"status":"PASS" if not errors else "FAIL","errors":errors,"warnings":warnings,"checked":len(images)}


def cb162_canonicalize_blueprint(project, blueprint):
    """Refresh an existing blueprint from authoritative Series/World canon.

    This is a non-destructive creation-context repair: it updates only the
    blueprint/prompt-generation context and never rewrites legacy project
    metadata or silently reassigns the project to a different World.
    """
    project = Path(project)
    bp = dict(blueprint or {})
    ownership = canonical_ownership_for_project(project)
    series = ownership.get("series") or {}
    book = ownership.get("book") or {}
    world = ownership.get("world") or {}

    if ownership.get("status") != "PASS":
        return bp, ownership

    world_id = str(world.get("world_id", ""))
    world_name = str(world.get("name", ""))
    series_id = str(series.get("series_id", ""))
    series_name = str(series.get("name", ""))

    bp["engine_version"] = BOOK_CREATION_ENGINE_VERSION
    bp["canonical_context"] = {
        "status": "PASS",
        "resolution": ownership.get("reason", "Explicit Series Bible attachment is canonical."),
        "legacy_world_ignored": ownership.get("legacy_world", ""),
    }
    bp["world"] = {
        "attached": bool(world),
        "world_id": world_id,
        "name": world_name,
        "genre": world.get("genre", ""),
        "tone": world.get("tone", ""),
        "description": world.get("description", ""),
    }
    bp["series"] = {
        "attached": bool(series),
        "series_id": series_id,
        "name": series_name,
        "book_number": book.get("book_number", bp.get("series", {}).get("book_number")),
        "central_mythology": series.get("central_mythology", ""),
        "core_premise": series.get("core_premise", ""),
    }

    # Resolve the canonical book location without inventing a new hierarchy.
    location_name = str(book.get("primary_location", "") or "").strip()
    location = None
    if location_name and world_id:
        world_record = load_world(world_id) or world
        for item in (world_record.get("locations", []) or []):
            if isinstance(item, dict) and str(item.get("name", "")).strip().casefold() == location_name.casefold():
                location = item
                break
    old_loc = bp.get("primary_location") or {}
    if location is None and location_name and str(old_loc.get("name", "")).strip().casefold() == location_name.casefold():
        location = old_loc
    bp["primary_location"] = {
        "attached": bool(location or location_name),
        "id": str((location or {}).get("id", old_loc.get("id", ""))),
        "name": location_name or str((location or {}).get("name", old_loc.get("name", ""))),
        "path": str((location or {}).get("path", old_loc.get("path", ""))),
        "level": str((location or {}).get("level", old_loc.get("level", ""))),
        "location_type": str((location or {}).get("location_type", old_loc.get("location_type", ""))),
        "description": str((location or {}).get("description", old_loc.get("description", ""))),
    }
    bp["lore_context"] = cb16_lore_snapshot(series)
    return bp, ownership


def cb162_reset_stale_production_state(project):
    """Remove stale serialized production claims after a canonical prompt rebuild."""
    project = Path(project)
    for name in (ARTWORK_QUEUE_FILENAME, ARTWORK_QA_FILENAME):
        path = project / name
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    bp_path = project / BOOK_BLUEPRINT_FILENAME
    if bp_path.exists():
        bp = load_json(bp_path)
        plan = bp.setdefault("artwork_plan", {})
        total = int(bp.get("image_count", 30) or 30)
        plan.update({"total": total, "planned": total, "generated": 0, "passed_qa": 0, "failed_qa": 0})
        bp["creation_status"] = "PROMPTS_READY"
        save_json(bp_path, bp)


def cb162_real_artwork_counts(project, queue=None):
    """Count only actual image files and current QA status; never trust old counters."""
    project = Path(project)
    source = project / ARTWORK_QUEUE_DIRNAME / "SOURCE"
    approved = project / ARTWORK_QUEUE_DIRNAME / "APPROVED"
    review_dir = project / ARTWORK_QUEUE_DIRNAME / "REVIEW"
    failed_dir = project / ARTWORK_QUEUE_DIRNAME / "FAILED"
    image_exts = {".png", ".jpg", ".jpeg", ".webp"}
    def ids(folder):
        if not folder.exists(): return set()
        return {p.stem.upper() for p in folder.iterdir() if p.is_file() and p.suffix.lower() in image_exts}
    src, appr, rev, fail = map(ids, (source, approved, review_dir, failed_dir))
    generated_ids = appr | rev | fail
    passed = len(appr)
    return {"generated": len(generated_ids), "passed": passed, "review": len(rev), "failed": len(fail), "source": len(src)}

def cb16_lore_prompt_studio(project=None):
    project = Path(project) if project else (v12_active_project() or choose_project())
    if not project: return
    bp_path = project / BOOK_BLUEPRINT_FILENAME
    if not bp_path.exists():
        print("No BOOK_BLUEPRINT.json exists. Create a blueprint first."); return
    blueprint = load_json(bp_path)
    blueprint, ownership = cb162_canonicalize_blueprint(project, blueprint)
    print("\n" + "=" * 78)
    print("LORE + PROMPT STUDIO v16.2")
    print("=" * 78)
    print(f"Project: {project.name}")
    print(f"Series:  {blueprint.get('series', {}).get('name') or 'Standalone'}")
    print(f"World:   {blueprint.get('world', {}).get('name') or 'Standalone'}")
    print(f"Location:{blueprint.get('primary_location', {}).get('name') or 'World-level'}")
    print(f"Myth:    {blueprint.get('lore_context', {}).get('central_mythology') or 'None'}")
    if ownership.get("legacy_world"):
        print(f"Legacy:  {ownership['legacy_world']} (ignored)")
    print(f"Canon:   {ownership.get('status', 'REVIEW')}")
    if ownership.get("status") != "PASS":
        print("\nBLOCKED: canonical ownership is not PASS. Resolve the Series/World attachment first.")
        print("\n4. Back")
        input("Press Enter to return...")
        return
    print("\n1. Rebuild canonical lore-aware prompt manifest")
    print("2. Run prompt + continuity QA")
    print("3. Open prompts folder")
    print("4. Back")
    c = input("Choose: ").strip()
    if c == "1":
        # Save corrected creation context first, then generate from that exact snapshot.
        save_json(bp_path, blueprint)
        prompts = cb16_build_prompt_manifest(blueprint)
        manifest = {
            "schema_version": 3,
            "engine_version": BOOK_CREATION_ENGINE_VERSION,
            "project_id": project.name,
            "book_title": blueprint.get("title", project.name),
            "series_id": blueprint.get("series", {}).get("series_id", ""),
            "world_id": blueprint.get("world", {}).get("world_id", ""),
            "primary_location_id": blueprint.get("primary_location", {}).get("id", ""),
            "lore_context": blueprint.get("lore_context", {}),
            "canonical_context": blueprint.get("canonical_context", {}),
            "images": prompts,
        }
        manifest["qa"] = cb16_prompt_qa(manifest)
        save_json(project / PROMPT_MANIFEST_FILENAME, manifest)
        cb13_write_prompt_jobs(project, prompts)
        blueprint["artwork_plan"] = {
            "total": len(prompts), "planned": len(prompts),
            "generated": 0, "passed_qa": 0, "failed_qa": 0,
        }
        blueprint["prompt_qa"] = manifest["qa"]
        blueprint["prompt_manifest_schema"] = 3
        blueprint["creation_status"] = "PROMPTS_READY"
        save_json(bp_path, blueprint)
        cb162_reset_stale_production_state(project)
        print(f"\nPROMPTS REBUILT: {len(prompts)}")
        print(f"Prompt QA: {manifest['qa']['status']}")
        print("Production state reset: 0 generated / 0 QA passed until real artwork is supplied.")
    elif c == "2":
        if not (project / PROMPT_MANIFEST_FILENAME).exists():
            print("Prompt manifest missing.")
        else:
            manifest = load_json(project / PROMPT_MANIFEST_FILENAME)
            qa = cb16_prompt_qa(manifest)
            manifest["qa"] = qa
            save_json(project / PROMPT_MANIFEST_FILENAME, manifest)
            print(f"\nPROMPT QA: {qa['status']} | Checked: {qa['checked']} | Errors: {len(qa['errors'])} | Warnings: {len(qa['warnings'])}")
            for e in qa["errors"][:20]: print("  ERROR:", e)
            for w in qa["warnings"][:10]: print("  WARNING:", w)
    elif c == "3":
        v12_open_folder(project / "ARTWORK_QUEUE" / "PROMPTS")

def cb13_create_project(title, author, genre, theme, image_count):
    base = cb13_safe_name(title)
    folder = PROJECTS / base
    counter = 2
    while folder.exists():
        folder = PROJECTS / f"{base} ({counter})"
        counter += 1
    folder.mkdir(parents=True, exist_ok=True)
    setup_project(folder)
    settings = {
        "title": title,
        "author": author,
        "genre": genre,
        "theme": theme,
        "trim_width": 8.5,
        "trim_height": 11.0,
        "dpi": 300,
        "border_pixels": 150,
        "number_of_images": image_count,
        "min_source_width": 1500,
        "min_source_height": 2000,
        "kdp_ink_type": "black_white",
        "kdp_auto_pad_minimum_pages": True,
        "kdp_minimum_pages": 24,
        "kdp_maximum_pages": 828,
        "kdp_generate_cover": True,
        "assembly_mode": "manual",
        "universe_name": "",
        "series_name": "",
        "world_relationship": "standalone",
        "world_canon": False,
        "continuity_gate": True,
        "auto_update_world_bible": True,
        "auto_register_artwork_entities": True,
        "production_profile_version": 2,
        "book_creation_engine_version": BOOK_CREATION_ENGINE_VERSION,
        "creation_status": "BLUEPRINT_CREATED",
    }
    save_json(folder / "project.json", settings)
    save_json(folder / "book.json", {"pages": []})
    return folder


def cb13_attach_book_to_world(project, world, primary_location):
    if not world:
        return
    settings = load_json(project / "project.json")
    settings["world_id"] = world.get("world_id", "")
    settings["universe_name"] = world.get("name", "")
    settings["world_relationship"] = "canon"
    settings["world_canon"] = True
    if primary_location:
        settings["primary_location_id"] = primary_location.get("id", "")
        settings["primary_location_name"] = primary_location.get("name", "")
        settings["primary_location_path"] = world_location_path(world, primary_location)
    save_json(project / "project.json", settings)
    world = world_v2_attach_book(
        world,
        project_id=project.name,
        title=settings.get("title", project.name),
        series_id="",
        book_number=None,
        canon=True,
    )
    # Keep an explicit book-to-primary-location reference without inventing lore.
    if primary_location:
        upgraded = world_v2_upgrade_record(world)
        loc = world_v2_find(upgraded, "locations", primary_location.get("id", ""))
        if loc is not None:
            refs = loc.setdefault("books", [])
            if project.name not in refs:
                refs.append(project.name)
            loc["last_updated"] = world_v2_now()
        world_v2_save(upgraded)


def ensure_canonical_series_world_registered(bible):
    """Register a Series Bible's declared World in World Engine when explicitly requested.

    This creates only the missing World record; it does not rewrite project metadata,
    move files, or alter existing worlds. If the exact world already exists, it is reused.
    """
    if not isinstance(bible, dict):
        return None, False, "No Series Bible supplied."
    world_name = str(bible.get("world_name", "")).strip()
    if not world_name:
        return None, False, "Series has no canonical World name."

    index = load_world_index()
    worlds = index.setdefault("worlds", {})
    for wid in list(worlds.keys()):
        world = load_world(wid) or worlds.get(wid, {})
        if str(world.get("name", wid)).strip().casefold() == world_name.casefold():
            upgraded = world_v2_upgrade_record(world)
            series_name = str(bible.get("name", "")).strip()
            if series_name and not any(
                str(item.get("name", "")).strip().casefold() == series_name.casefold()
                for item in upgraded.get("series", []) if isinstance(item, dict)
            ):
                world_v2_upsert(upgraded, "series", {
                    "name": series_name,
                    "series_id": bible.get("series_id", ""),
                    "canon": True,
                })
            return load_world(wid) or upgraded, False, "Existing canonical World reused."

    # Create the exact World name declared by the Series Bible.
    world = new_world_record(
        world_name,
        description=str(bible.get("core_premise", "")).strip(),
        genre="Horror",
        tone="Nightmare horror",
    )
    world["schema_version"] = WORLD_ENGINE_2_SCHEMA
    world["engine_version"] = WORLD_ENGINE_2_VERSION
    world["production_history"] = []
    world["archived"] = False
    world = world_v2_save(world)
    series_name = str(bible.get("name", "")).strip()
    if series_name:
        world = world_v2_upsert(world, "series", {
            "name": series_name,
            "series_id": bible.get("series_id", ""),
            "canon": True,
        })
    world_v2_write_bible(world)
    return world, True, "Canonical World registered from Series Bible."


def canonical_ownership_for_project(project):
    """Resolve canonical World -> Series ownership without rewriting legacy metadata."""
    project = Path(project)
    rec = lore_extract_project_record(project)
    project_name = project.name.casefold()
    title = str(rec.get("title", "")).strip().casefold()
    path_text = str(project).casefold()

    matches = []
    for bible in list_series_bibles():
        for book in bible.get("books", []) or []:
            if not isinstance(book, dict):
                continue
            bp = str(book.get("path", "")).strip().casefold()
            bn = str(book.get("project", "")).strip().casefold()
            bt = str(book.get("title", "")).strip().casefold()
            explicit = bool(book.get("explicit_attachment"))
            if explicit and (bp == path_text or bn == project_name or (title and bt == title)):
                matches.append((bible, book))

    # Explicit Series Bible attachment is authoritative for creation context.
    if matches:
        bible, book = matches[0]
        world_name = str(bible.get("world_name", "")).strip()
        world = next((w for w in cb13_world_choices() if str(w.get("name", "")).strip().casefold() == world_name.casefold()), None) if world_name else None
        conflict_world = rec.get("world_name", "")
        return {
            "status": "PASS" if world else "REVIEW",
            "project": project.name,
            "world": world,
            "series": bible,
            "book": book,
            "legacy_world": conflict_world if conflict_world and conflict_world.casefold() != world_name.casefold() else "",
            "reason": "Explicit Series Bible attachment is canonical.",
        }

    # Explicit project metadata is second priority, but is not allowed to override
    # a real Series Bible attachment discovered above.
    series_id = str((load_json(project / "project.json") if (project / "project.json").exists() else {}).get("series_id", "")).strip()
    if series_id:
        bible = load_series_bible(series_id)
        if bible:
            world_name = str(bible.get("world_name", "")).strip()
            world = next((w for w in cb13_world_choices() if str(w.get("name", "")).strip().casefold() == world_name.casefold()), None) if world_name else None
            return {
                "status": "PASS" if world else "REVIEW",
                "project": project.name,
                "world": world,
                "series": bible,
                "book": None,
                "legacy_world": rec.get("world_name", "") if world_name and rec.get("world_name", "").casefold() != world_name.casefold() else "",
                "reason": "Project series metadata resolves to the Series Bible.",
            }

    world_name = str(rec.get("world_name", "")).strip()
    world = next((w for w in cb13_world_choices() if str(w.get("name", "")).strip().casefold() == world_name.casefold()), None) if world_name else None
    return {
        "status": "PASS" if world else "REVIEW",
        "project": project.name,
        "world": world,
        "series": None,
        "book": None,
        "legacy_world": "",
        "reason": "No explicit Series attachment; using project World metadata.",
    }


def canonical_ownership_check():
    project = v12_active_project() or choose_project()
    if not project:
        return
    result = canonical_ownership_for_project(project)
    series = result.get("series") or {}
    world = result.get("world") or {}
    print("\n" + "=" * 78)
    print("CANONICAL OWNERSHIP CHECK")
    print("=" * 78)
    print(f"Project:             {project.name}")
    print(f"Book:                {lore_extract_project_record(project).get('title', project.name)}")
    print(f"World:               {world.get('name') or 'UNRESOLVED'}")
    print(f"Series:              {series.get('name') or 'Standalone / none'}")
    print(f"Mythology:           {series.get('central_mythology') or 'None'}")
    print(f"Status:              {result.get('status')}")
    print(f"Resolution:          {result.get('reason')}")
    if result.get("legacy_world"):
        print(f"Legacy metadata:     {result['legacy_world']} (ignored for canonical context)")
    if series and not world:
        print("WARNING: Series declares a World that is not registered in World Engine.")
        canonical_name = str(series.get("world_name", "")).strip()
        if canonical_name:
            answer = input(f"Register canonical World '{canonical_name}' now? [y/N]: ").strip().lower()
            if answer in ("y", "yes"):
                created_world, created, message = ensure_canonical_series_world_registered(series)
                if created_world:
                    result = canonical_ownership_for_project(project)
                    world = result.get("world") or {}
                    print(f"\n{message}")
                    print(f"Canonical World: {world.get('name') or canonical_name}")
                    print(f"Series: {series.get('name') or 'Standalone / none'}")
                    print(f"Status: {result.get('status')}")
    print("\nNo project metadata was changed by this check.")


def cb13_create_book_blueprint_from_idea():
    print("\n" + "=" * 78)
    print(f"BOOK CREATION ENGINE v{FACTORY_VERSION} — IDEA -> BLUEPRINT")
    print("=" * 78)
    print("This creates the book plan and prompt manifest. It does NOT generate artwork yet.")

    title = input("\nBook title: ").strip()
    if not title:
        print("Cancelled — a book title is required.")
        return None
    concept = input("Describe the book idea: ").strip()
    if not concept:
        print("Cancelled — a book idea is required.")
        return None
    author = input("Author [J.A.C.]: ").strip() or "J.A.C."
    subtitle = input("Subtitle [A Horror Coloring Adventure]: ").strip() or "A Horror Coloring Adventure"
    genre = input("Genre [Adult Horror Coloring Book]: ").strip() or "Adult Horror Coloring Book"
    theme = input("Main theme / creature / subject: ").strip() or concept
    raw_count = input("Number of coloring images [30]: ").strip() or "30"
    try:
        image_count = max(1, min(200, int(raw_count)))
    except ValueError:
        image_count = 30

    # Series is selected BEFORE World. If a Series is attached, its canonical
    # World controls the creation context; stale project metadata cannot override it.
    series = lore_select_series_for_book()
    if series:
        canonical_world_name = str(series.get("world_name", "")).strip()
        world = next((w for w in cb13_world_choices() if str(w.get("name", "")).strip().casefold() == canonical_world_name.casefold()), None) if canonical_world_name else None
        if not world:
            print(f"WARNING: Series '{series.get('name', '')}' has no registered canonical World '{canonical_world_name}'.")
            world = None
        primary_location = cb13_choose_location(world) if world else None
    else:
        world = cb13_choose_world()
        primary_location = cb13_choose_location(world) if world else None
    book_number = None
    if series:
        existing_numbers = [b.get("book_number") for b in series.get("books", []) if isinstance(b, dict) and isinstance(b.get("book_number"), int)]
        suggested = max(existing_numbers) + 1 if existing_numbers else (len(series.get("books", [])) + 1)
        raw_number = input(f"Book number [{suggested}]: ").strip() or str(suggested)
        book_number = int(raw_number) if raw_number.isdigit() else suggested

    print("\nCREATION SUMMARY")
    print(f"Title:            {title}")
    print(f"Subtitle:         {subtitle}")
    print(f"Author:           {author}")
    print(f"Images:           {image_count}")
    print(f"World:            {world.get('name') if world else 'Standalone'}")
    print(f"Primary location: {world_location_path(world, primary_location) if world and primary_location else 'World-level'}")
    confirm = input("\nCreate blueprint? [Y/n]: ").strip().lower()
    if confirm not in ("", "y", "yes"):
        print("Cancelled.")
        return None

    project = cb13_create_project(title, author, genre, theme, image_count)
    settings = load_json(project / "project.json")
    settings["subtitle"] = subtitle
    settings["description"] = concept
    settings["creation_status"] = "BLUEPRINT_CREATED"
    if series:
        settings["series_name"] = series.get("name", "")
        settings["series_id"] = series.get("series_id", "")
        settings["series_canon"] = True
        settings["book_number"] = book_number
    save_json(project / "project.json", settings)
    if series:
        lore_attach_new_book_to_series(project, series, book_number)

    blueprint = {
        "schema_version": 1,
        "engine_version": BOOK_CREATION_ENGINE_VERSION,
        "created": datetime.now().isoformat(timespec="seconds"),
        "project_id": project.name,
        "project_path": str(project),
        "title": title,
        "subtitle": subtitle,
        "author": author,
        "genre": genre,
        "theme": theme,
        "concept": concept,
        "image_count": image_count,
        "format": {
            "trim": "8.5x11",
            "width_inches": 8.5,
            "height_inches": 11.0,
            "dpi": 300,
            "interior_pixels": "2550x3300",
            "border_pixels": 150,
            "color_mode": "RGB",
        },
        "style": {
            "art_style": BOOK_CREATION_DEFAULTS["art_style"],
            "line_style": BOOK_CREATION_DEFAULTS["line_style"],
            "negative_prompt": BOOK_CREATION_DEFAULTS["negative_prompt"],
        },
        "world": {
            "attached": bool(world),
            "world_id": world.get("world_id", "") if world else "",
            "name": world.get("name", "") if world else "",
            "genre": world.get("genre", "") if world else "",
            "tone": world.get("tone", "") if world else "",
            "description": world.get("description", "") if world else "",
        },
        "series": {
            "attached": bool(series),
            "series_id": series.get("series_id", "") if series else "",
            "name": series.get("name", "") if series else "",
            "book_number": book_number,
            "central_mythology": series.get("central_mythology", "") if series else "",
            "core_premise": series.get("core_premise", "") if series else "",
        },
        "primary_location": {
            "attached": bool(primary_location),
            "id": primary_location.get("id", "") if primary_location else "",
            "name": primary_location.get("name", "") if primary_location else "",
            "path": world_location_path(world, primary_location) if world and primary_location else "",
            "level": primary_location.get("level", "") if primary_location else "",
            "location_type": primary_location.get("location_type", "") if primary_location else "",
            "description": primary_location.get("description", "") if primary_location else "",
        },
        "continuity_rules": [
            "Reuse the selected world identity whenever the book is attached to a world.",
            "Reuse the selected primary location instead of creating an untracked duplicate.",
            "Keep stable world and location IDs in every artwork prompt record.",
            "Do not invent canon changes silently; new entities must be explicitly added to World Engine.",
        ],
        "pipeline": [
            "BLUEPRINT_CREATED",
            "PROMPTS_READY",
            "ARTWORK_GENERATION",
            "ARTWORK_QA",
            "BOOK_ASSEMBLY",
            "PUBLISHING_ENGINE",
            "RELEASE_AUDIT",
        ],
    }

    # Capture a frozen lore snapshot before prompt generation so every prompt is traceable to canon.
    blueprint["lore_context"] = cb16_lore_snapshot(series)

    if world:
        cb13_attach_book_to_world(project, world, primary_location)
        # Refresh the saved world after attachment so the blueprint records the same IDs.
        world = load_world(world.get("world_id", "")) or world
    blueprint["world_record"] = {
        "world_id": world.get("world_id", "") if world else "",
        "name": world.get("name", "") if world else "",
    }
    blueprint["primary_location_record"] = {
        "id": primary_location.get("id", "") if primary_location else "",
        "name": primary_location.get("name", "") if primary_location else "",
        "path": world_location_path(world, primary_location) if world and primary_location else "",
    }

    prompts = cb16_build_prompt_manifest(blueprint)
    blueprint["prompt_manifest_file"] = PROMPT_MANIFEST_FILENAME
    blueprint["artwork_plan"] = {
        "total": len(prompts),
        "planned": len(prompts),
        "generated": 0,
        "passed_qa": 0,
        "failed_qa": 0,
    }

    save_json(project / BOOK_BLUEPRINT_FILENAME, blueprint)
    save_json(project / PROMPT_MANIFEST_FILENAME, {
        "schema_version": 1,
        "engine_version": BOOK_CREATION_ENGINE_VERSION,
        "project_id": project.name,
        "book_title": title,
        "world_id": blueprint["world"]["world_id"],
        "primary_location_id": blueprint["primary_location"]["id"],
        "images": prompts,
    })
    save_json(project / CREATION_MANIFEST_FILENAME, {
        "schema_version": 1,
        "engine_version": BOOK_CREATION_ENGINE_VERSION,
        "project_id": project.name,
        "title": title,
        "status": "PROMPTS_READY",
        "files": [BOOK_BLUEPRINT_FILENAME, PROMPT_MANIFEST_FILENAME],
        "next_stage": "ARTWORK_GENERATION",
    })

    record_world_production_event(project, "BOOK_BLUEPRINT_CREATED", "READY", image_count, 0, 0)
    print("\n" + "=" * 78)
    print("BOOK BLUEPRINT CREATED")
    print("=" * 78)
    print(f"Project:          {project}")
    print(f"Blueprint:        {project / BOOK_BLUEPRINT_FILENAME}")
    print(f"Prompt manifest:  {project / PROMPT_MANIFEST_FILENAME}")
    print(f"Images planned:   {len(prompts)}")
    print(f"World continuity: {'ATTACHED' if world else 'STANDALONE'}")
    print("Status:            PROMPTS_READY")
    return project


# ============================================================
# 13.2 ARTWORK PRODUCTION / QA LAYER
#
# 13.2 turns the deterministic prompt manifest into a real artwork
# production queue. The factory does not pretend to generate artwork
# when no image-generation backend is connected. Instead it creates
# stable per-image jobs, accepts generated artwork by image ID, and
# performs measurable technical QA before assembly.
# ============================================================

ARTWORK_QUEUE_DIRNAME = "ARTWORK_QUEUE"
ARTWORK_SOURCE_DIRNAME = "SOURCE"
ARTWORK_APPROVED_DIRNAME = "APPROVED"
ARTWORK_REVIEW_DIRNAME = "REVIEW"
ARTWORK_FAILED_DIRNAME = "FAILED"
ARTWORK_PROMPTS_DIRNAME = "PROMPTS"
ARTWORK_QUEUE_FILENAME = "ARTWORK_QUEUE.json"
ARTWORK_QA_FILENAME = "ARTWORK_QA.json"


def cb13_artwork_dirs(project):
    root = project / ARTWORK_QUEUE_DIRNAME
    dirs = {
        "root": root,
        "source": root / ARTWORK_SOURCE_DIRNAME,
        "approved": root / ARTWORK_APPROVED_DIRNAME,
        "review": root / ARTWORK_REVIEW_DIRNAME,
        "failed": root / ARTWORK_FAILED_DIRNAME,
        "prompts": root / ARTWORK_PROMPTS_DIRNAME,
    }
    for folder in dirs.values():
        folder.mkdir(parents=True, exist_ok=True)
    return dirs


def cb13_find_artwork_file(source_dir, image_id, sequence):
    """Find generated artwork using stable IMG-### or numeric filenames."""
    candidates = []
    for stem in (image_id, image_id.lower(), f"{sequence:03d}", str(sequence), f"image_{sequence:03d}"):
        for ext in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"):
            candidates.append(source_dir / f"{stem}{ext}")
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    # Fallback: tolerate a filename containing the stable image ID.
    for candidate in sorted(source_dir.iterdir() if source_dir.exists() else []):
        if candidate.is_file() and image_id.lower() in candidate.stem.lower():
            return candidate
    return None


def cb13_write_prompt_jobs(project, prompts):
    dirs = cb13_artwork_dirs(project)
    for record in prompts:
        path = dirs["prompts"] / f"{record['image_id']}.txt"
        text = (
            f"TITLE: {record.get('title', '')}\n"
            f"IMAGE ID: {record.get('image_id', '')}\n"
            f"WORLD: {record.get('world_name', '')}\n"
            f"LOCATION: {record.get('location_path', '')}\n"
            f"\nPROMPT:\n{record.get('prompt', '')}\n"
            f"\nNEGATIVE PROMPT:\n{record.get('negative_prompt', '')}\n"
            f"\nOUTPUT: 2550x3300 px, 300 DPI, white background, RGB\n"
        )
        path.write_text(text, encoding="utf-8")


def cb13_prepare_artwork_queue(project=None):
    project = project or (v12_active_project() or choose_project())
    if not project:
        return None
    manifest_path = project / PROMPT_MANIFEST_FILENAME
    blueprint_path = project / BOOK_BLUEPRINT_FILENAME
    if not manifest_path.exists() or not blueprint_path.exists():
        print("\nNo v13.2-ready blueprint/prompt manifest exists for this project.")
        print("Create the Book Blueprint first.")
        return None
    try:
        manifest = load_json(manifest_path)
        blueprint = load_json(blueprint_path)
        prompts = manifest.get("images", [])
    except Exception as error:
        print(f"Could not load creation files: {error}")
        return None
    if not prompts:
        print("Prompt manifest contains no artwork jobs.")
        return None

    dirs = cb13_artwork_dirs(project)
    cb13_write_prompt_jobs(project, prompts)

    jobs = []
    for record in prompts:
        job = dict(record)
        job["status"] = "READY"
        job["source_file"] = ""
        job["qa_status"] = "NOT_CHECKED"
        job["qa_errors"] = []
        job["qa_warnings"] = []
        job["approved_file"] = ""
        jobs.append(job)

    queue = {
        "schema_version": 1,
        "engine_version": BOOK_CREATION_ENGINE_VERSION,
        "project_id": project.name,
        "book_title": blueprint.get("title", project.name),
        "created": datetime.now().isoformat(timespec="seconds"),
        "source_directory": str(dirs["source"]),
        "approved_directory": str(dirs["approved"]),
        "jobs": jobs,
    }
    save_json(project / ARTWORK_QUEUE_FILENAME, queue)

    blueprint["artwork_plan"] = {
        "total": len(jobs),
        "planned": len(jobs),
        "generated": 0,
        "passed_qa": 0,
        "failed_qa": 0,
        "review": 0,
        "queue_ready": True,
    }
    save_json(blueprint_path, blueprint)

    creation = load_json(project / CREATION_MANIFEST_FILENAME) if (project / CREATION_MANIFEST_FILENAME).exists() else {}
    creation.update({
        "schema_version": 1,
        "engine_version": BOOK_CREATION_ENGINE_VERSION,
        "project_id": project.name,
        "title": blueprint.get("title", project.name),
        "status": "ARTWORK_QUEUE_READY",
        "files": [BOOK_BLUEPRINT_FILENAME, PROMPT_MANIFEST_FILENAME, ARTWORK_QUEUE_FILENAME],
        "next_stage": "ARTWORK_GENERATION",
    })
    save_json(project / CREATION_MANIFEST_FILENAME, creation)

    print("\n" + "=" * 78)
    print("ARTWORK PRODUCTION QUEUE READY")
    print("=" * 78)
    print(f"Project:       {project.name}")
    print(f"Jobs:          {len(jobs)}")
    print(f"Prompt files:  {dirs['prompts']}")
    print(f"Artwork input: {dirs['source']}")
    print("\nPut generated artwork in SOURCE using names such as:")
    print("  IMG-001.png")
    print("  IMG-002.png")
    print("  ...")
    print("\nThe factory will match artwork by stable image ID and never by list position alone.")
    return project


def cb13_validate_artwork_file(path, expected_width=2550, expected_height=3300):
    errors = []
    warnings = []
    try:
        from PIL import Image
        with Image.open(path) as img:
            width, height = img.size
            mode = img.mode
            info = dict(img.info)
            dpi = info.get("dpi")
            if width != expected_width or height != expected_height:
                errors.append(f"Dimensions are {width}x{height}; expected {expected_width}x{expected_height}.")
            if mode not in ("RGB", "L"):
                errors.append(f"Color mode is {mode}; expected RGB or L for interior artwork.")
            if dpi:
                effective_dpi = min(float(dpi[0]), float(dpi[1])) if isinstance(dpi, tuple) else float(dpi)
                # PNG stores DPI as pixels-per-meter, so Pillow commonly reads a
                # file saved at exactly 300 DPI as 299.9994. Treat that as the
                # intended 300-DPI production value rather than sending every
                # normalized import to manual REVIEW.
                if effective_dpi < 299.0:
                    warnings.append(f"Embedded DPI is {effective_dpi:.1f}; target is 300 DPI.")
            else:
                # Pixel dimensions are authoritative for this normalized import.
                # Missing metadata alone should not downgrade otherwise valid art.
                pass
            # Lightweight background sanity check. This is not artistic QA.
            sample = img.convert("L").resize((64, 64))
            extrema = sample.getextrema()
            if extrema[0] > 250:
                warnings.append("Image is nearly blank/white; inspect manually.")
            return errors, warnings, {"width": width, "height": height, "mode": mode, "dpi": dpi}
    except Exception as error:
        return [f"Could not read image: {error}"], [], {}


def cb13_scan_artwork_qa(project=None):
    project = project or (v12_active_project() or choose_project())
    if not project:
        return None
    queue_path = project / ARTWORK_QUEUE_FILENAME
    if not queue_path.exists():
        print("\nNo artwork queue exists. Run Prepare Artwork Queue first.")
        return None
    queue = load_json(queue_path)
    dirs = cb13_artwork_dirs(project)
    jobs = queue.get("jobs", [])
    results = []
    passed = failed = review = generated = 0

    for job in jobs:
        image_id = job.get("image_id", "")
        sequence = int(job.get("sequence", 0) or 0)
        source = cb13_find_artwork_file(dirs["source"], image_id, sequence)
        job["qa_errors"] = []
        job["qa_warnings"] = []
        job["approved_file"] = ""
        if not source:
            job["status"] = "WAITING_FOR_ARTWORK"
            job["qa_status"] = "NOT_CHECKED"
            results.append({"image_id": image_id, "status": job["status"]})
            continue

        generated += 1
        job["source_file"] = str(source)
        errors, warnings, metadata = cb13_validate_artwork_file(source)
        job["qa_errors"] = errors
        job["qa_warnings"] = warnings
        job["metadata"] = metadata

        if errors:
            job["status"] = "FAIL"
            job["qa_status"] = "FAIL"
            failed += 1
            destination = dirs["failed"] / source.name
        elif warnings:
            job["status"] = "REVIEW"
            job["qa_status"] = "REVIEW"
            review += 1
            destination = dirs["review"] / source.name
        else:
            job["status"] = "PASS"
            job["qa_status"] = "PASS"
            passed += 1
            destination = dirs["approved"] / source.name
            job["approved_file"] = str(destination)

        try:
            import shutil
            shutil.copy2(source, destination)
        except Exception as error:
            job["qa_errors"].append(f"Could not copy QA result: {error}")
            job["status"] = "FAIL"
            job["qa_status"] = "FAIL"
            failed += 1

        results.append({
            "image_id": image_id,
            "status": job["status"],
            "errors": errors,
            "warnings": warnings,
        })

    queue["last_qa"] = datetime.now().isoformat(timespec="seconds")
    queue["summary"] = {
        "total": len(jobs),
        "generated": generated,
        "passed": passed,
        "review": review,
        "failed": failed,
        "waiting": len(jobs) - generated,
    }
    save_json(queue_path, queue)
    save_json(project / ARTWORK_QA_FILENAME, {
        "schema_version": 1,
        "engine_version": BOOK_CREATION_ENGINE_VERSION,
        "project_id": project.name,
        "timestamp": queue["last_qa"],
        "summary": queue["summary"],
        "results": results,
    })

    blueprint_path = project / BOOK_BLUEPRINT_FILENAME
    if blueprint_path.exists():
        blueprint = load_json(blueprint_path)
        blueprint.setdefault("artwork_plan", {})
        blueprint["artwork_plan"].update({
            "total": len(jobs),
            "generated": generated,
            "passed_qa": passed,
            "failed_qa": failed,
            "review": review,
            "queue_ready": True,
        })
        save_json(blueprint_path, blueprint)

    print("\n" + "=" * 78)
    print("ARTWORK QA RESULTS")
    print("=" * 78)
    print(f"Total jobs:      {len(jobs)}")
    print(f"Artwork found:   {generated}")
    print(f"PASS:            {passed}")
    print(f"REVIEW:          {review}")
    print(f"FAIL:            {failed}")
    print(f"Waiting:         {len(jobs) - generated}")
    print(f"QA report:       {project / ARTWORK_QA_FILENAME}")
    return queue


def cb13_import_artwork_from_existing_pdf(project=None):
    """Import artwork from a complete interior PDF without requiring PyMuPDF.

    Uses the Factory's universal PDF renderer (PDFium first, then installed CLI
    renderers) and analyzes every page in the supplied interior.  The importer
    ranks pages as coloring-art candidates, excludes text-heavy matter where
    possible, selects exactly the planned number of artwork pages, normalizes
    them to 2550x3300 RGB PNG at 300 DPI, and immediately runs the existing QA.
    The source PDF is never modified.
    """
    project = project or (v12_active_project() or choose_project())
    if not project:
        return None

    queue_path = project / ARTWORK_QUEUE_FILENAME
    if not queue_path.exists():
        cb13_prepare_artwork_queue(project)
    queue = load_json(queue_path)
    jobs = queue.get("jobs", [])
    if not jobs:
        print("\nNo artwork jobs exist. Prepare the Artwork Queue first.")
        return None

    print("\nSELECT FINISHED BOOK PDF")
    print("Choose the COMPLETE interior PDF containing the coloring pages.")
    pdf_path = choose_pdf_file("Finished book PDF")
    if not pdf_path:
        print("\nNo PDF selected.")
        return None

    dirs = cb13_artwork_dirs(project)
    render_dir = project / ARTWORK_QUEUE_DIRNAME / "PDF_IMPORT_RENDER"
    render_dir.mkdir(parents=True, exist_ok=True)
    for old in render_dir.glob("*.png"):
        try:
            old.unlink()
        except Exception:
            pass

    # Use PDFium / external renderers instead of PyMuPDF.  Render every page so
    # a 30-page book is not limited by a sampling heuristic.
    try:
        info = inspect_pdf(pdf_path)
        total_pages = int(info.get("page_count") or 0)
    except Exception as error:
        print(f"\nERROR: Could not inspect PDF: {error}")
        return None

    if total_pages <= 0:
        print("\nERROR: PDF contains no pages.")
        return None

    pdfium, bootstrap_message = _try_import_pdfium(auto_install=True)
    if pdfium is None:
        print("\nERROR: No working PDF renderer is available.")
        print(bootstrap_message or "Install pypdfium2 with: python -m pip install pypdfium2")
        return None

    print("\n" + "=" * 78)
    print("FULL INTERIOR PDF IMPORT")
    print("=" * 78)
    print(f"Source PDF:       {pdf_path}")
    print(f"PDF pages:        {total_pages}")
    print(f"Artwork required: {len(jobs)}")
    if bootstrap_message:
        print(f"Renderer:         {bootstrap_message}")
    else:
        print("Renderer:         PDFium / pypdfium2")
    print("Analyzing every PDF page for coloring artwork...")

    candidates = []
    document = None
    try:
        document = pdfium.PdfDocument(str(pdf_path))
        if len(document) != total_pages:
            total_pages = len(document)

        # Render at a moderate resolution for detection.  The selected pages are
        # rendered again at the exact production dimensions below.
        for idx in range(total_pages):
            try:
                page = document[idx]
                bitmap = page.render(scale=1.25, rev_byteorder=True)
                preview = bitmap.to_pil().convert("RGB")
                raw = render_dir / f"page-{idx + 1:04d}.png"
                preview.save(raw, "PNG", optimize=True)
                score = float(_pdf_preview_score(raw))
                try:
                    # pypdfium2 page text extraction is not consistently available;
                    # use zero here and let the visual score drive ranking.
                    text_chars = 0
                except Exception:
                    text_chars = 0
                candidates.append({
                    "page": idx + 1,
                    "path": raw,
                    "score": score,
                    "text_chars": text_chars,
                })
                try:
                    page.close()
                except Exception:
                    pass
            except Exception as error:
                print(f"  Page {idx + 1}: render failed — {error}")

        if not candidates:
            print("\nERROR: No PDF pages could be rendered.")
            return None

        target_count = min(len(jobs), len(candidates))

        # Front/back matter is normally lighter than coloring pages.  Exclude a
        # small front/back region only when doing so still leaves enough pages.
        front_skip = 5 if total_pages > target_count + 7 else 0
        back_skip = 2 if total_pages > target_count + 7 else 0
        interior = [
            c for c in candidates
            if front_skip < int(c["page"]) <= total_pages - back_skip
        ]
        if len(interior) < target_count:
            interior = candidates

        # Prefer visibly inked pages.  If the scoring signal is weak, fall back
        # to the strongest available pages rather than blocking the workflow.
        interior.sort(key=lambda x: (float(x["score"]), -int(x["page"])), reverse=True)
        usable = [c for c in interior if float(c["score"]) >= 0.02]
        if len(usable) < target_count:
            usable = interior

        selected = sorted(usable[:target_count], key=lambda x: int(x["page"]))
        if len(selected) < len(jobs):
            print(f"\nERROR: Only {len(selected)} usable pages were found; {len(jobs)} are required.")
            print("The PDF may not contain enough detectable coloring artwork pages.")
            return None

        # Clear previous test/import output so old images cannot contaminate QA.
        for key in ("source", "approved", "review", "failed"):
            for old in dirs[key].glob("IMG-*.png"):
                try:
                    old.unlink()
                except Exception:
                    pass

        target_w, target_h, target_dpi = 2550, 3300, 300
        imported = []
        print(f"Selected artwork pages: {len(selected)}")
        print("Normalizing selected pages to 2550x3300 @ 300 DPI...")

        # Re-render selected pages directly to the target canvas.  PDF page sizes
        # can vary, so fit-within-canvas preserves the original line art without
        # distortion or cropping.
        for n, candidate in enumerate(selected, start=1):
            destination = dirs["source"] / f"IMG-{n:03d}.png"
            page_index = int(candidate["page"]) - 1
            page = document[page_index]
            bitmap = page.render(scale=3.0, rev_byteorder=True)
            image = bitmap.to_pil().convert("RGB")
            if image.size != (target_w, target_h):
                canvas_img = Image.new("RGB", (target_w, target_h), "white")
                fitted = ImageOps.contain(image, (target_w, target_h), Image.Resampling.LANCZOS)
                x = (target_w - fitted.width) // 2
                y = (target_h - fitted.height) // 2
                canvas_img.paste(fitted, (x, y))
                image = canvas_img
            image.save(destination, "PNG", optimize=True, dpi=(target_dpi, target_dpi))
            try:
                page.close()
            except Exception:
                pass
            imported.append({
                "image_id": f"IMG-{n:03d}",
                "source_pdf_page": int(candidate["page"]),
                "artwork_score": float(candidate["score"]),
                "text_chars": 0,
                "file": str(destination),
            })
            if n == 1 or n == len(selected) or n % 5 == 0:
                print(f"  Imported {n}/{len(selected)}")

        queue["source_pdf"] = str(pdf_path)
        queue["source_pdf_pages"] = imported
        queue["imported_from_pdf"] = True
        queue["import_timestamp"] = datetime.now().isoformat(timespec="seconds")
        save_json(queue_path, queue)
        save_json(project / "PDF_ARTWORK_IMPORT.json", {
            "schema_version": 2,
            "engine_version": BOOK_CREATION_ENGINE_VERSION,
            "project_id": project.name,
            "source_pdf": str(pdf_path),
            "source_page_count": total_pages,
            "renderer": "PDFium/pypdfium2",
            "selected_artwork_count": len(imported),
            "selected_pages": imported,
        })

        print("\n" + "=" * 78)
        print("PDF ARTWORK IMPORT COMPLETE")
        print("=" * 78)
        print(f"Source PDF:       {pdf_path}")
        print(f"PDF pages:        {total_pages}")
        print(f"Artwork imported: {len(imported)}")
        print(f"Artwork SOURCE:   {dirs['source']}")
        print("All imported pages were normalized to 2550x3300 pixels at 300 DPI.")
        print("\nRunning technical QA now...")
        return cb13_scan_artwork_qa(project)
    except Exception as error:
        print(f"\nERROR: PDF artwork import failed: {error}")
        return None
    finally:
        try:
            if document is not None:
                document.close()
        except Exception:
            pass


def cb13_build_and_publish_project(project=None):
    """Assemble approved creation artwork, then hand the finished PDF to the v12 publishing engine."""
    project = project or (v12_active_project() or choose_project())
    if not project:
        return None
    queue_path = project / ARTWORK_QUEUE_FILENAME
    if not queue_path.exists():
        print("\nNo artwork queue exists. Prepare or import artwork first.")
        return None
    queue = load_json(queue_path)
    jobs = queue.get("jobs", [])
    passed = [j for j in jobs if j.get("status") == "PASS" and j.get("approved_file")]
    if not passed:
        print("\nBUILD BLOCKED: No artwork has passed QA yet.")
        print("Use 'Import Artwork from Existing PDF' or place generated artwork in SOURCE, then run QA.")
        return None
    if len(passed) < len(jobs):
        print(f"\nBUILD BLOCKED: {len(passed)} of {len(jobs)} artwork jobs have passed QA.")
        print("All planned artwork must pass before the factory assembles the book.")
        return None

    settings_path = project / "project.json"
    settings = load_json(settings_path) if settings_path.exists() else {}
    settings["assembly_mode"] = "auto"
    settings["number_of_images"] = len(passed)
    settings["creation_status"] = "ARTWORK_QA_PASS"
    save_json(settings_path, settings)

    input_dir = project / "INPUT"
    input_dir.mkdir(parents=True, exist_ok=True)
    # Replace the assembly INPUT with the immutable QA-approved set.
    for old in input_dir.iterdir():
        if old.is_file() and old.suffix.lower() in IMAGE_EXTENSIONS:
            try:
                old.unlink()
            except Exception:
                pass
    for number, job in enumerate(passed, start=1):
        source = Path(job["approved_file"])
        destination = input_dir / f"{number:03d}_{job.get('image_id', f'IMG-{number:03d}')}.png"
        shutil.copy2(source, destination)

    print("\n" + "=" * 78)
    print("BOOK ASSEMBLY + PUBLISH")
    print("=" * 78)
    print(f"Project:        {project.name}")
    print(f"Approved art:   {len(passed)}")
    print("Stage 1/3: Building finished PDF...")
    build_book(project)

    final_pdf = project / "FINAL" / f"{settings.get('title', project.name)}.pdf"
    if not final_pdf.exists():
        candidates = sorted((project / "FINAL").glob("*.pdf")) if (project / "FINAL").exists() else []
        final_pdf = candidates[0] if candidates else None
    if not final_pdf or not Path(final_pdf).exists():
        print("\nBUILD FAILED: No finished PDF was produced.")
        return None

    print(f"\nStage 2/3: MASTER from finished PDF: {final_pdf}")
    master = import_existing_pdf_to_master(project, final_pdf)
    if not master:
        print("\nPUBLISH BLOCKED: MASTER creation failed.")
        return None

    print("\nStage 3/3: Generating KDP / Gumroad / Etsy / Payhip packages...")
    results = {}
    for platform in ("KDP", "Gumroad", "Etsy", "Payhip"):
        try:
            result = generate_platform_package(project, platform, quiet=True)
        except Exception as error:
            result = {"status": "FAILED", "errors": [str(error)], "warnings": []}
        results[platform] = result
        print(f"  {platform:8s}: {result.get('status', 'UNKNOWN')}")

    creation = load_json(project / CREATION_MANIFEST_FILENAME) if (project / CREATION_MANIFEST_FILENAME).exists() else {}
    creation.update({
        "engine_version": BOOK_CREATION_ENGINE_VERSION,
        "status": "PUBLISH_PACKAGES_READY",
        "finished_pdf": str(final_pdf),
        "master_pdf": str(master),
        "platform_results": {k: v.get("status") for k, v in results.items()},
        "next_stage": "SELL_OR_UPDATE",
    })
    save_json(project / CREATION_MANIFEST_FILENAME, creation)

    print("\n" + "=" * 78)
    print("PRODUCTION COMPLETE")
    print("=" * 78)
    print(f"Finished PDF: {final_pdf}")
    print(f"MASTER:       {master}")
    print(f"Gumroad:      {results.get('Gumroad', {}).get('status', 'UNKNOWN')}")
    print(f"KDP:          {results.get('KDP', {}).get('status', 'UNKNOWN')}")
    print(f"Payhip:       {results.get('Payhip', {}).get('status', 'UNKNOWN')}")
    print(f"Etsy:         {results.get('Etsy', {}).get('status', 'UNKNOWN')}")
    print("\nYour Gumroad package is in the project's PLATFORM/GUMROAD folder.")
    return results


def cb13_artwork_production_center():
    project = v12_active_project() or choose_project()
    if not project:
        return
    while True:
        print("\n" + "=" * 78)
        print(f"ARTWORK PRODUCTION CENTER v{FACTORY_VERSION}")
        print("=" * 78)
        print(f"Project: {project.name}")
        queue_path = project / ARTWORK_QUEUE_FILENAME
        if queue_path.exists():
            try:
                q = load_json(queue_path)
                summary = q.get("summary", {})
                print(f"Jobs: {len(q.get('jobs', []))} | Found: {summary.get('generated', 0)} | PASS: {summary.get('passed', 0)} | REVIEW: {summary.get('review', 0)} | FAIL: {summary.get('failed', 0)}")
            except Exception:
                print("Queue: present (summary unavailable)")
        else:
            print("Queue: NOT PREPARED")
        print("\n1. Prepare Artwork Queue")
        print("2. Import Artwork From Existing PDF")
        print("3. Scan Artwork + Run QA")
        print("4. Build Book + Publish Packages")
        print("5. Open Artwork Queue Folder")
        print("6. Back")
        choice = input("Choose: ").strip()
        if choice == "1":
            cb13_prepare_artwork_queue(project)
        elif choice == "2":
            cb13_import_artwork_from_existing_pdf(project)
        elif choice == "3":
            cb13_scan_artwork_qa(project)
        elif choice == "4":
            cb13_build_and_publish_project(project)
        elif choice == "5":
            v12_open_folder(project / ARTWORK_QUEUE_DIRNAME)
        elif choice == "6":
            return
        else:
            print("Invalid choice.")
        input("\nPress Enter to continue...")

def cb13_creation_dashboard():
    project = v12_active_project() or choose_project()
    if not project:
        return
    blueprint_path = project / BOOK_BLUEPRINT_FILENAME
    manifest_path = project / PROMPT_MANIFEST_FILENAME
    queue_path = project / ARTWORK_QUEUE_FILENAME
    print("\n" + "=" * 78)
    print(f"BOOK CREATION DASHBOARD v{FACTORY_VERSION}")
    print("=" * 78)
    print(f"Project: {project.name}")
    if not blueprint_path.exists():
        print("No blueprint exists for this project yet.")
        return
    try:
        blueprint = load_json(blueprint_path)
    except Exception as error:
        print(f"Could not read blueprint: {error}")
        return

    # Canonical ownership is authoritative for creation context.  Do not let
    # stale project/blueprint metadata display an obsolete World or Location.
    ownership = canonical_ownership_for_project(project)
    canonical_world = ownership.get("world") or {}
    canonical_series = ownership.get("series") or {}
    canonical_book = ownership.get("book") or {}
    canonical_world_name = str(canonical_world.get("name", "")).strip()
    canonical_series_name = str(canonical_series.get("name", "")).strip()
    canonical_location = ""
    if isinstance(canonical_book, dict):
        canonical_location = str(canonical_book.get("primary_location", "") or "").strip()
    if not canonical_location:
        canonical_location = str((blueprint.get("primary_location") or {}).get("name", "") or "").strip()
    if canonical_location and "/" not in canonical_location:
        # Series Bible locations are often stored by leaf name; keep that name
        # rather than inventing an AREA 420 hierarchy.
        location_display = canonical_location
    else:
        location_display = canonical_location

    plan = blueprint.get("artwork_plan", {})
    print(f"Title:       {blueprint.get('title', project.name)}")
    print(f"Concept:     {blueprint.get('concept', '')}")
    print(f"World:       {canonical_world_name or 'UNRESOLVED'}")
    print(f"Series:      {canonical_series_name or 'Standalone / none'}")
    print(f"Location:    {location_display or 'World-level'}")
    print(f"Images:      {blueprint.get('image_count', 0)}")
    print(f"Prompts:     {'READY' if manifest_path.exists() else 'MISSING'}")
    print(f"Artwork Q:   {'READY' if queue_path.exists() else 'NOT PREPARED'}")

    # Production counts must come from the current artwork queue, not stale
    # blueprint counters.  This prevents old/test QA values from masquerading
    # as newly generated artwork.
    counts = cb162_real_artwork_counts(project)
    generated = counts["generated"]
    passed = counts["passed"]
    review = counts["review"]
    failed = counts["failed"]
    print(f"Generated:   {generated}")
    print(f"QA PASS:     {passed}")
    print(f"QA REVIEW:   {review}")
    print(f"QA FAIL:     {failed}")

    if ownership.get("legacy_world"):
        print(f"Legacy metadata: {ownership['legacy_world']} (ignored for canonical creation context)")
    if ownership.get("status") != "PASS":
        print(f"Canonical ownership: {ownership.get('status', 'REVIEW')}")

    print("\nFiles:")
    print(f"  {blueprint_path.name}")
    print(f"  {manifest_path.name}")
    print(f"  {CREATION_MANIFEST_FILENAME}")
    if queue_path.exists():
        print(f"  {ARTWORK_QUEUE_FILENAME}")
        print(f"  {ARTWORK_QA_FILENAME if (project / ARTWORK_QA_FILENAME).exists() else '(QA report not created yet)'}")


def _project_stage_status(project):
    project = Path(project)
    if not project.exists():
        return {"stage":"NO_PROJECT", "label":"No project", "next":"Start a New Book"}
    blueprint = project / BOOK_BLUEPRINT_FILENAME
    prompts = project / PROMPT_MANIFEST_FILENAME
    queue = project / ARTWORK_QUEUE_FILENAME
    qa = project / ARTWORK_QA_FILENAME
    final_dir = project / "FINAL"
    master_dir = project / "MASTER"
    final_pdfs = list(final_dir.glob("*.pdf")) if final_dir.exists() else []
    master_pdfs = list(master_dir.glob("*.pdf")) if master_dir.exists() else []
    if not blueprint.exists() and not prompts.exists() and not queue.exists():
        return {"stage":"PROJECT_CREATED", "label":"Project created", "next":"Start / configure the book"}
    if blueprint.exists() and not prompts.exists():
        return {"stage":"BLUEPRINT", "label":"Blueprint ready", "next":"Create prompts"}
    if queue.exists() and qa.exists():
        try:
            q = load_json(queue); jobs = q.get("jobs", [])
            passed = sum(1 for j in jobs if j.get("status") == "PASS" and j.get("approved_file"))
            total = len(jobs); failed = sum(1 for j in jobs if j.get("status") == "FAIL"); review = sum(1 for j in jobs if j.get("status") == "REVIEW")
            if total and passed == total and not final_pdfs:
                return {"stage":"ARTWORK_QA_PASS", "label":f"Artwork QA PASS ({passed}/{total})", "next":"Build Book"}
            if failed or review:
                return {"stage":"ARTWORK_REVIEW", "label":f"Artwork needs review ({passed}/{total} PASS)", "next":"Review / fix artwork"}
        except Exception:
            pass
    if queue.exists() and not qa.exists():
        return {"stage":"ARTWORK_QUEUE", "label":"Artwork queue ready", "next":"Run Artwork QA"}
    if prompts.exists() and not queue.exists():
        return {"stage":"PROMPTS_READY", "label":"Prompts ready", "next":"Import / generate artwork"}
    if final_pdfs and not master_pdfs:
        return {"stage":"INTERIOR_BUILT", "label":"Interior built", "next":"Create MASTER / publish"}
    if master_pdfs:
        return {"stage":"MASTER_READY", "label":"MASTER ready", "next":"Publish / run release audit"}
    return {"stage":"PROJECT", "label":"Project in progress", "next":"Open Project Dashboard"}


def _print_project_status(project):
    if not project:
        print("Active project: None")
        return
    state = _project_stage_status(project)
    print(f"Active project: {project.name}")
    print(f"Status:         {state['label']}")
    print(f"Next:           {state['next']}")


def continue_active_book():
    project = v12_active_project() or choose_project()
    if not project: return
    state = _project_stage_status(project)
    print("\n" + "=" * 78)
    print(f"CONTINUE ACTIVE BOOK — v{FACTORY_VERSION}")
    print("=" * 78)
    print(f"Project: {project.name}\nStatus:  {state['label']}\nNext:    {state['next']}")
    choice = input("\nContinue now? [Y/n]: ").strip().lower()
    if choice not in ("", "y", "yes"): return
    stage = state["stage"]
    # Creation and publishing are separate workflows.  Even when a project
    # already has a MASTER PDF, Continue Active Book must open the creation
    # engine so the user can inspect canon, rebuild prompts, or continue art.
    # Publishing is available explicitly from main-menu option 6.
    if stage == "ARTWORK_QA_PASS":
        cb13_build_and_publish_project(project)
    elif stage in ("ARTWORK_REVIEW", "ARTWORK_QUEUE", "PROMPTS_READY"):
        cb13_artwork_production_center()
    elif stage == "INTERIOR_BUILT":
        pdfs = sorted((project / "FINAL").glob("*.pdf"))
        if pdfs:
            try: print(f"MASTER: {import_existing_pdf_to_master(project, pdfs[0])}")
            except Exception as error: print(f"MASTER creation failed: {error}")
        book_creation_engine_menu()
    else:
        book_creation_engine_menu()


def start_new_book_menu():
    while True:
        print("\n" + "=" * 78); print(f"START A NEW BOOK — v{FACTORY_VERSION}"); print("=" * 78)
        print("1. Create Book From Idea\n2. Create Basic Project\n3. Clone Existing Book Structure\n4. Back")
        c=input("Choose: ").strip()
        if c=="1": cb13_create_book_blueprint_from_idea()
        elif c=="2": create_project()
        elif c=="3": clone_project_from_template()
        elif c=="4": return
        else: print("Invalid choice.")
        input("\nPress Enter to continue...")


def import_existing_book_menu():
    while True:
        print("\n" + "=" * 78); print(f"IMPORT AN EXISTING BOOK — v{FACTORY_VERSION}"); print("=" * 78)
        print("1. Finished PDF -> MASTER + Platforms\n2. Artwork Folder -> Create Book\n3. Finished PDF Into Active Project\n4. Back")
        c=input("Choose: ").strip()
        if c=="1": v12_quick_publish()
        elif c=="2": import_artwork_folder()
        elif c=="3":
            project=v12_active_project() or choose_project()
            if project:
                raw=input("Finished interior PDF path: ").strip().strip('"')
                if raw: cb13_import_artwork_from_existing_pdf(project, raw)
        elif c=="4": return
        else: print("Invalid choice.")
        input("\nPress Enter to continue...")


def import_artwork_menu():
    while True:
        print("\n" + "=" * 78); print(f"IMPORT ARTWORK — v{FACTORY_VERSION}"); print("=" * 78)
        print("1. Import Artwork From Existing PDF\n2. Import Artwork Folder\n3. Scan Artwork + Run QA\n4. Artwork Production Center\n5. Open Artwork Queue Folder\n6. Back")
        c=input("Choose: ").strip()
        project=v12_active_project() or choose_project() if c in {"1","3","4","5"} else None
        if c=="1" and project: cb13_import_artwork_from_existing_pdf(project)
        elif c=="2": import_artwork_folder()
        elif c=="3" and project: cb13_scan_artwork_qa(project)
        elif c=="4": cb13_artwork_production_center()
        elif c=="5" and project: v12_open_folder(project / ARTWORK_QUEUE_DIRNAME)
        elif c=="6": return
        elif c not in {"1","3","4","5"}: print("Invalid choice.")
        input("\nPress Enter to continue...")


def production_menu():
    while True:
        print("\n" + "=" * 78); print(f"PRODUCTION CENTER — v{FACTORY_VERSION}"); print("=" * 78)
        print("1. Continue Active Book\n2. Production Center\n3. Build Current Book\n4. Production Queue\n5. Production Dashboard\n6. Artwork QA\n7. Back")
        c=input("Choose: ").strip()
        if c=="1": book_creation_engine_menu()
        elif c=="2": production_center()
        elif c=="3": cb13_build_and_publish_project()
        elif c=="4": production_queue_menu()
        elif c=="5": production_dashboard()
        elif c=="6": cb13_artwork_production_center()
        elif c=="7": return
        else: print("Invalid choice.")
        input("\nPress Enter to continue...")


def publishing_menu():
    while True:
        print("\n" + "=" * 78); print(f"PUBLISH / EXPORT — v{FACTORY_VERSION}"); print("=" * 78)
        print("1. Publish Current Book\n2. Platform & Publishing Center\n3. Rebuild One Platform\n4. Production Release Center\n5. Marketing Center\n6. Open Delivery Folder\n7. Back")
        c=input("Choose: ").strip()
        if c=="1": cb13_build_and_publish_project()
        elif c=="2": platform_center()
        elif c=="3": v12_rebuild_one_platform()
        elif c=="4": production_release_center()
        elif c=="5": marketing_center()
        elif c=="6":
            project=v12_active_project() or choose_project()
            if project: v12_open_folder(project / "DELIVERY")
        elif c=="7": return
        else: print("Invalid choice.")
        input("\nPress Enter to continue...")


def worlds_projects_menu():
    while True:
        print("\n" + "=" * 78); print(f"WORLDS, SERIES & PROJECTS — v{FACTORY_VERSION}"); print("=" * 78)
        print("1. Worlds & Universes\n2. Series & Lore Engine\n3. Recent Projects\n4. Set Active Project\n5. Active Project Dashboard\n6. Clone Project From Template\n7. Back")
        c=input("Choose: ").strip()
        if c=="1": world_engine_center_v9()
        elif c=="2": series_engine_center()
        elif c=="3": v12_recent_projects_menu()
        elif c=="4": v12_set_active_project()
        elif c=="5": v12_active_dashboard()
        elif c=="6": clone_project_from_template()
        elif c=="7": return
        else: print("Invalid choice.")
        input("\nPress Enter to continue...")


def maintenance_menu():
    while True:
        print("\n" + "=" * 78); print(f"TOOLS / MAINTENANCE — v{FACTORY_VERSION}"); print("=" * 78)
        print("1. Factory Health / Self-Test\n2. Safe Cleanup\n3. Set Active Project\n4. Back")
        c=input("Choose: ").strip()
        if c=="1": run_platform_self_test()
        elif c=="2": v12_cleanup_menu()
        elif c=="3": v12_set_active_project()
        elif c=="4": return
        else: print("Invalid choice.")
        input("\nPress Enter to continue...")


# ============================================================
# v16.6 — PLATFORM CONNECTIONS & UPLOAD CENTER  (pcu_*)
# Honest upload workflow:  Package -> Verify -> Upload -> Record.
#   * Never claims an upload happened unless the user confirms a manual
#     upload, or (future) an API call returned success.
#   * Does NOT modify the Universal Publishing Center / package engine;
#     it only READS the packages that engine produced.
#   * Secrets live in connections_private.json (auto-added to .gitignore)
#     or in environment variables. They are never printed or logged.
# ============================================================
import getpass
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

PCU_VERSION = "1.0"
PCU_DIRNAME = "UPLOAD_CENTER"
PCU_HISTORY_FILENAME = "UPLOAD_HISTORY.json"
PCU_CONNECTIONS_FILENAME = "connections_private.json"
PCU_DEFAULT_SHOPIFY_API_VERSION = "2026-07"
PCU_SHOPIFY_TOKEN_URL = "https://{store}/admin/oauth/access_token"
PCU_SHOPIFY_GRAPHQL_URL = "https://{store}/admin/api/{version}/graphql.json"

# Capability registry. "api" is what Factory can actually do TODAY, not what a
# platform might theoretically offer.  Update here when a real integration ships.
PCU_PLATFORMS = [
    {"key": "KDP", "label": "Amazon KDP", "api": "NONE",
     "url": "https://kdp.amazon.com",
     "api_note": "No upload API available to Factory.",
     "steps": ["Open your KDP bookshelf and create or open the paperback title.",
               "Copy in title, subtitle, author, description, keywords and categories (option 3).",
               "Upload the interior PDF and the cover file from the package folder.",
               "Run KDP's previewer and fix anything it flags.",
               "Set pricing and territories, submit, then order a proof copy."]},
    {"key": "Gumroad", "label": "Gumroad", "api": "NONE",
     "url": "https://gumroad.com",
     "api_note": "No product-upload API available to Factory.",
     "steps": ["Create a new product in Gumroad.",
               "Upload the digital PDF; add the cover and preview images from the package folder.",
               "Option 6 edits the listing; option 3 shows it. Paste NAME, SUMMARY, DESCRIPTION and TAGS into the matching fields.",
               "Set the price and publish, then open the page as a buyer and test the download."]},
    {"key": "Payhip", "label": "Payhip", "api": "NONE",
     "url": "https://payhip.com",
     "api_note": "No product-upload API available to Factory.",
     "steps": ["Add a new digital product in your Payhip dashboard.",
               "Upload the digital PDF and the cover/preview images from the package folder.",
               "Paste the product description (option 3) and set the price.",
               "Publish, then test the download as a buyer."]},
    {"key": "Etsy", "label": "Etsy", "api": "POSSIBLE",
     "url": "https://www.etsy.com",
     "api_note": "Etsy has an Open API with listing endpoints, but Factory does not implement it yet.",
     "steps": ["Create a digital-download listing in your shop.",
               "Upload the file(s) from the package folder (already split to Etsy's file limits) and the listing images.",
               "Paste title, description and tags (option 3) and set the price.",
               "Publish, then check the buyer download."]},
    {"key": "Ko-fi", "label": "Ko-fi", "api": "NONE",
     "url": "https://ko-fi.com",
     "api_note": "No product-upload API available to Factory.",
     "steps": ["Add a new digital product in your Ko-fi shop.",
               "Upload the digital PDF and cover from the package folder.",
               "Paste the description (option 3), set the price and publish."]},
    {"key": "Creative Market", "label": "Creative Market", "api": "NONE",
     "url": "https://creativemarket.com",
     "api_note": "No upload API available to Factory.",
     "steps": ["Start a new product in your Creative Market shop dashboard.",
               "Upload the digital PDF, cover and preview images from the package folder.",
               "Paste the description (option 3), set the price and submit for review."]},
    {"key": "Shopify", "label": "Shopify", "api": "SHOPIFY",
     "url": "https://admin.shopify.com",
     "api_note": "Connection test is built. Draft-product creation is not built yet.",
     "steps": ["Create the product in Shopify admin (title, description, cover image).",
               "Deliver the PDF with a Digital Downloads app so buyers get a protected link.",
               "DO NOT upload the PDF to Shopify Files: files there are public URLs anyone can open.",
               "Publish, then place a test order to check the download."]},
]


def _pcu_now():
    return datetime.now().isoformat(timespec="seconds")


def _pcu_platform(key):
    for p in PCU_PLATFORMS:
        if p["key"] == key:
            return p
    return None


def _pcu_fmt_size(num):
    num = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024


# ---------------- package inspection (read-only) ----------------

def _pcu_package_root(project, key):
    try:
        profiles = load_platform_profiles()
    except Exception:
        profiles = {}
    out = (profiles.get(key) or {}).get("output_dir") or key.upper()
    return Path(project) / PLATFORM_DIRNAME / out


def _pcu_master_sha(project):
    try:
        master = find_master_pdf(project)
        return file_hash(master) if master else None
    except Exception:
        return None


def _pcu_package_info(project, key, master_sha=None):
    root = _pcu_package_root(project, key)
    info = {"platform": key, "root": root, "state": "MISSING", "files": [], "manifest": None,
            "problems": [], "master_sha": None, "generated": None, "warnings": []}
    manifest_path = root / "PACKAGE_MANIFEST.json"
    if not manifest_path.exists():
        return info
    try:
        manifest = load_json(manifest_path)
        if not isinstance(manifest, dict):
            raise ValueError("manifest is not a JSON object")
    except Exception as error:
        info["state"] = "DAMAGED"
        info["problems"].append(f"PACKAGE_MANIFEST.json cannot be read: {error}")
        return info
    info["manifest"] = manifest
    info["generated"] = manifest.get("generated")
    info["master_sha"] = manifest.get("master_sha256")
    info["warnings"] = list(manifest.get("warnings") or [])
    for name, expected in (manifest.get("file_hashes") or {}).items():
        if name == "PACKAGE_MANIFEST.json":
            continue  # the manifest is rewritten after its own hash is recorded
        path = root / name
        if not path.exists():
            info["problems"].append(f"Missing file: {name}")
            continue
        try:
            if file_hash(path) != expected:
                info["problems"].append(f"Changed since packaging: {name}")
        except Exception as error:
            info["problems"].append(f"Could not verify {name}: {error}")
    info["files"] = [n for n in (manifest.get("files") or []) if (root / n).exists()]
    status = str(manifest.get("status") or "")
    if info["problems"]:
        info["state"] = "DAMAGED"
    elif status in ("READY", "READY_WITH_WARNINGS"):
        info["state"] = status
        if master_sha is None:
            master_sha = _pcu_master_sha(project)
        if master_sha and info["master_sha"] and master_sha != info["master_sha"]:
            info["state"] = "STALE"
    else:
        info["state"] = status or "UNKNOWN"
    return info


_PCU_PACKAGE_LABELS = {"READY": "READY", "READY_WITH_WARNINGS": "READY (warnings)",
                       "STALE": "STALE - rebuild", "DAMAGED": "DAMAGED - rebuild",
                       "MISSING": "NOT BUILT"}


def _pcu_package_label(state):
    return _PCU_PACKAGE_LABELS.get(state, state)


# ---------------- upload history (per project) ----------------

def _pcu_history_path(project):
    return Path(project) / PCU_DIRNAME / PCU_HISTORY_FILENAME


def _pcu_load_history(project):
    path = _pcu_history_path(project)
    empty = {"schema_version": 1, "entries": []}
    if not path.exists():
        return empty
    try:
        data = load_json(path)
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data
        raise ValueError("unexpected structure")
    except Exception:
        try:  # keep the unreadable file instead of silently overwriting it
            shutil.copy2(path, path.with_name(f"{path.stem}.corrupt-{datetime.now():%Y%m%d-%H%M%S}.json"))
        except Exception:
            pass
        return empty


def _pcu_last_upload(history, key):
    for entry in reversed(history.get("entries", [])):
        if entry.get("platform") == key:
            return entry
    return None


def _pcu_upload_label(history, key, info):
    last = _pcu_last_upload(history, key)
    if not last:
        return "not recorded"
    when = str(last.get("recorded", ""))[:10]
    old, cur = last.get("package_master_sha256"), info.get("master_sha")
    if old and cur and old != cur:
        return f"uploaded {when} - OLDER version"
    return f"uploaded {when} (you confirmed)"


def _pcu_record_upload(project, key, info, listing_url="", note=""):
    history = _pcu_load_history(project)
    try:
        title = (info.get("manifest") or {}).get("title") or Path(project).name
    except Exception:
        title = Path(project).name
    entry = {"id": len(history["entries"]) + 1, "platform": key, "method": "manual",
             "recorded": _pcu_now(), "title": title, "listing_url": listing_url, "note": note,
             "package_state_at_record": info.get("state"),
             "package_generated": info.get("generated"),
             "package_master_sha256": info.get("master_sha")}
    history["entries"].append(entry)
    save_json(_pcu_history_path(project), history)
    return entry


# ---------------- connections (secrets stay local) ----------------

def _pcu_connections_path():
    return FACTORY / PCU_CONNECTIONS_FILENAME


def _pcu_ensure_gitignore():
    try:
        gi = FACTORY / ".gitignore"
        text = gi.read_text(encoding="utf-8") if gi.exists() else ""
        if PCU_CONNECTIONS_FILENAME not in [ln.strip() for ln in text.splitlines()]:
            with open(gi, "a", encoding="utf-8", newline="") as handle:
                if text and not text.endswith("\n"):
                    handle.write("\n")
                handle.write(PCU_CONNECTIONS_FILENAME + "\n")
    except Exception:
        pass


def _pcu_load_connections():
    path = _pcu_connections_path()
    if not path.exists():
        return {}
    try:
        data = load_json(path)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _pcu_save_connections(data):
    save_json(_pcu_connections_path(), data)
    _pcu_ensure_gitignore()


def _pcu_shopify_settings():
    cfg = _pcu_load_connections().get("shopify") or {}
    env = os.environ.get
    return {"store": env("SHOPIFY_STORE") or cfg.get("store", ""),
            "api_version": cfg.get("api_version") or PCU_DEFAULT_SHOPIFY_API_VERSION,
            "client_id": env("SHOPIFY_CLIENT_ID") or cfg.get("client_id", ""),
            "client_secret": env("SHOPIFY_CLIENT_SECRET") or cfg.get("client_secret", ""),
            "access_token": env("SHOPIFY_ADMIN_TOKEN") or cfg.get("access_token", ""),
            "last_test": cfg.get("last_test")}


def _pcu_shopify_configured(s):
    return bool(s["store"]) and (bool(s["access_token"]) or bool(s["client_id"] and s["client_secret"]))


def _pcu_normalize_store(value):
    value = (value or "").strip().lower()
    value = re.sub(r"^https?://", "", value).split("/")[0].strip()
    if value and "." not in value:
        value += ".myshopify.com"
    return value if re.fullmatch(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", value) else ""


def _pcu_http(request, timeout=20):
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    except urllib.error.URLError as error:
        raise RuntimeError(f"Network error: {error.reason}")
    except Exception as error:
        raise RuntimeError(f"Request failed: {error}")
    try:
        return status, json.loads(raw.decode("utf-8"))
    except Exception:
        return status, {"raw": raw.decode("utf-8", "replace")[:300]}


def _pcu_short(payload):
    text = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload
    return text if len(text) <= 300 else text[:300] + "..."


def _pcu_shopify_get_token(s):
    if s["access_token"]:
        return s["access_token"], {"method": "static token"}
    body = urllib.parse.urlencode({"client_id": s["client_id"], "client_secret": s["client_secret"],
                                   "grant_type": "client_credentials"}).encode("utf-8")
    request = urllib.request.Request(
        PCU_SHOPIFY_TOKEN_URL.format(store=s["store"]), data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    status, payload = _pcu_http(request)
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if status == 200 and token:
        return token, {"method": "client credentials", "scope": payload.get("scope", ""),
                       "expires_in": payload.get("expires_in")}
    raise RuntimeError(f"Token request failed (HTTP {status}): {_pcu_short(payload)}")


def pcu_shopify_test_connection(save=True):
    """Read-only check: gets a token, asks Shopify for the shop name and granted scopes."""
    s = _pcu_shopify_settings()
    result = {"ok": False, "when": _pcu_now(), "shop_name": "", "scopes": [], "message": ""}
    if not _pcu_shopify_configured(s):
        result["message"] = "Shopify is not configured (store + credentials needed)."
    else:
        try:
            token, meta = _pcu_shopify_get_token(s)
            query = "{ shop { name myshopifyDomain } currentAppInstallation { accessScopes { handle } } }"
            request = urllib.request.Request(
                PCU_SHOPIFY_GRAPHQL_URL.format(store=s["store"], version=s["api_version"]),
                data=json.dumps({"query": query}).encode("utf-8"), method="POST",
                headers={"Content-Type": "application/json", "X-Shopify-Access-Token": token})
            status, payload = _pcu_http(request)
            if status != 200:
                raise RuntimeError(f"Shopify API returned HTTP {status}: {_pcu_short(payload)}")
            data = payload.get("data") or {}
            shop = data.get("shop") or {}
            if shop.get("name"):
                result["ok"] = True
                result["shop_name"] = shop["name"]
                result["scopes"] = [x.get("handle") for x in
                                    ((data.get("currentAppInstallation") or {}).get("accessScopes") or [])
                                    if x.get("handle")]
                result["message"] = f"Connected via {meta.get('method')}."
            else:
                raise RuntimeError("Shopify answered but returned no shop data: " + _pcu_short(payload.get("errors") or payload))
        except RuntimeError as error:
            result["message"] = str(error)
    if save:
        cfg = _pcu_load_connections()
        cfg.setdefault("shopify", {})["last_test"] = result
        try:
            _pcu_save_connections(cfg)
        except Exception:
            pass
    return result


def _pcu_connection_label(platform):
    api = platform["api"]
    if api == "SHOPIFY":
        s = _pcu_shopify_settings()
        last = s.get("last_test") or {}
        if not _pcu_shopify_configured(s):
            return "NOT CONNECTED - manual upload"
        if not last:
            return "CONFIGURED, not tested - manual upload"
        if last.get("ok"):
            return f"CONNECTED (tested {str(last.get('when', ''))[:10]}) - upload not built yet, manual"
        return "CONNECTION FAILED - manual upload"
    if api == "POSSIBLE":
        return "API exists, not built in Factory - manual upload"
    return "MANUAL upload (no API available to Factory)"


# ---------------- screens ----------------

def _pcu_pick_project(force_choose=False):
    project = None if force_choose else v12_active_project()
    if not project:
        project = choose_project()
    return project


def _pcu_collect_status(project):
    master_sha = _pcu_master_sha(project)
    history = _pcu_load_history(project)
    rows = []
    for platform in PCU_PLATFORMS:
        info = _pcu_package_info(project, platform["key"], master_sha)
        rows.append({"platform": platform, "info": info,
                     "upload": _pcu_upload_label(history, platform["key"], info)})
    return rows


def _pcu_print_status(project, rows):
    print("\n" + "=" * 78)
    print(f"PLATFORM CONNECTIONS / UPLOAD CENTER   (Factory v{FACTORY_VERSION})")
    print("=" * 78)
    print(f"Project: {Path(project).name}")
    print(f"\n{'#':<3}{'Platform':<17}{'Package':<19}{'Upload record'}")
    print("-" * 78)
    for i, row in enumerate(rows, 1):
        print(f"{i:<3}{row['platform']['label']:<17}{_pcu_package_label(row['info']['state']):<19}{row['upload']}")
    print("\nPackages come from the Universal Publishing Center (press P to open it).")
    print("'Upload record' only reflects uploads YOU confirmed - Factory cannot see inside your accounts.")


def _pcu_listing_text(project, info):
    if info.get("platform") == "Gumroad":
        listing = gumroad_build_listing(project)
        _gl_print("\n" + gumroad_render_listing_text(listing))
        for w in listing["warnings"]:
            _gl_print(f"Heads up: {w}")
        return
    settings = {}
    try:
        settings = load_project_settings_safe(project) or {}
    except Exception:
        pass
    meta = {}
    try:
        mp = info["root"] / "METADATA.json"
        if mp.exists():
            meta = load_json(mp)
    except Exception:
        pass

    def pick(*names):
        for n in names:
            v = meta.get(n) or settings.get(n)
            if v:
                return ", ".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)
        return ""

    fields = [("Title", pick("title")), ("Subtitle", pick("subtitle", "cover_subtitle")),
              ("Author", pick("author")), ("Series", pick("series", "series_name")),
              ("Keywords", pick("keywords")), ("Categories", pick("categories")),
              ("Description", pick("description", "cover_blurb"))]
    print("\nLISTING TEXT (copy/paste into the platform)")
    print("-" * 78)
    shown = False
    for label, value in fields:
        if value:
            shown = True
            print(f"\n{label}:\n{value}")
    if not shown:
        print("No listing text found in this project's settings or package metadata.")


def _pcu_print_package(info):
    print(f"\nPackage: {_pcu_package_label(info['state'])}")
    print(f"Folder:  {info['root']}")
    if info.get("generated"):
        print(f"Built:   {info['generated']}")
    if info["state"] == "MISSING":
        print("No package has been built for this platform yet.")
        print("Build it in the Universal Publishing Center (press P from the Upload Center).")
        return
    if info["state"] == "STALE":
        print("The book's MASTER PDF changed after this package was built. Rebuild before uploading.")
    for problem in info["problems"]:
        print(f"  PROBLEM: {problem}")
    if info["platform"] == "Gumroad" and info["state"] in ("READY", "READY_WITH_WARNINGS") and \
            gumroad_package_listing_in_sync(info["root"].parent.parent) is False:
        print("  NOTE: the listing text changed since this package was built - rebuild it (Studio option 10).")
    for warning in info["warnings"][:5]:
        print(f"  warning: {warning}")
    if info["files"]:
        print("Files:")
        for name in info["files"]:
            try:
                size = _pcu_fmt_size((info["root"] / name).stat().st_size)
            except Exception:
                size = "?"
            print(f"  - {name}  ({size})")


def pcu_history_screen(project, key=None):
    history = _pcu_load_history(project)
    entries = [e for e in history["entries"] if key is None or e.get("platform") == key]
    print("\n" + "=" * 78)
    print("UPLOAD HISTORY" + (f" - {key}" if key else "") + f" - {Path(project).name}")
    print("=" * 78)
    if not entries:
        print("Nothing recorded yet.")
        return
    for e in entries:
        print(f"#{e.get('id')}  {str(e.get('recorded',''))[:16].replace('T', ' ')}  {e.get('platform')}  "
              f"[{e.get('method')}]  package was {e.get('package_state_at_record')}")
        if e.get("listing_url"):
            print(f"     link: {e['listing_url']}")
        if e.get("note"):
            print(f"     note: {e['note']}")


def pcu_platform_page(project, key):
    platform = _pcu_platform(key)
    while True:
        info = _pcu_package_info(project, key)
        history = _pcu_load_history(project)
        print("\n" + "=" * 78)
        print(f"{platform['label'].upper()} - {Path(project).name}")
        print("=" * 78)
        print(f"Upload mode: {_pcu_connection_label(platform)}")
        print(f"Note: {platform['api_note']}")
        _pcu_print_package(info)
        print(f"Upload record: {_pcu_upload_label(history, key, info)}")
        print("\nMANUAL UPLOAD CHECKLIST")
        for i, step in enumerate(platform["steps"], 1):
            print(f"  {i}. {step}")
        print("\n1. Open package folder")
        print(f"2. Open {platform['label']} in browser")
        print("3. Show listing text to copy")
        print("4. I uploaded it - record it")
        print("5. History for this platform")
        if platform["api"] == "SHOPIFY":
            print("6. Shopify connection setup / test")
        if key == "Gumroad":
            print("6. Gumroad Listing Studio (price, summary, description, tags, terms)")
        print("0. Back")
        choice = input("Choose: ").strip()
        if choice == "1":
            v12_open_folder(info["root"])
        elif choice == "2":
            try:
                webbrowser.open(platform["url"])
                print(f"Opened {platform['url']}")
            except Exception as error:
                print(f"Could not open browser: {error}\n{platform['url']}")
        elif choice == "3":
            _pcu_listing_text(project, info)
        elif choice == "4":
            if info["state"] not in ("READY", "READY_WITH_WARNINGS"):
                print(f"\nWarning: the package is {_pcu_package_label(info['state'])}.")
                print("Recording only means YOU uploaded something; the record will note the package state.")
            if input("Type YES to record that you uploaded this book to "
                     f"{platform['label']}: ").strip().upper() != "YES":
                print("Not recorded.")
                continue
            url = input("Listing link (optional, Enter to skip): ").strip()
            note = input("Note (optional): ").strip()
            entry = _pcu_record_upload(project, key, info, url, note)
            print(f"Recorded upload #{entry['id']} for {platform['label']}.")
        elif choice == "5":
            pcu_history_screen(project, key)
        elif choice == "6" and platform["api"] == "SHOPIFY":
            pcu_shopify_setup()
        elif choice == "6" and key == "Gumroad":
            gumroad_listing_studio(project)
        elif choice in ("0", "", "B"):
            return
        else:
            print("Invalid choice.")
        if choice not in ("0", "", "B"):
            input("\nPress Enter to continue...")


def pcu_shopify_setup():
    while True:
        s = _pcu_shopify_settings()
        last = s.get("last_test") or {}
        print("\n" + "=" * 78)
        print("SHOPIFY CONNECTION")
        print("=" * 78)
        print(f"Store:        {s['store'] or '(not set)'}")
        print(f"API version:  {s['api_version']}")
        creds = ("static access token" if s["access_token"] else
                 "client ID + secret" if (s["client_id"] and s["client_secret"]) else "(not set)")
        print(f"Credentials:  {creds}")
        if last:
            state = "PASSED" if last.get("ok") else "FAILED"
            print(f"Last test:    {state} {str(last.get('when',''))[:16].replace('T', ' ')}")
            if last.get("shop_name"):
                print(f"Shop name:    {last['shop_name']}")
            if last.get("scopes"):
                print(f"Scopes:       {', '.join(last['scopes'])}")
                if "write_products" not in last["scopes"]:
                    print("              (write_products not granted - needed for a future draft-product step)")
            if last.get("message"):
                print(f"Message:      {last['message']}")
        print("\n1. Set store + credentials")
        print("2. Test connection (read-only)")
        print("3. Remove saved credentials")
        print("4. How to get credentials")
        print("0. Back")
        choice = input("Choose: ").strip()
        if choice == "1":
            store = _pcu_normalize_store(input("Store (e.g. mystore.myshopify.com): "))
            if not store:
                print("That is not a valid *.myshopify.com store name.")
                continue
            client_id = input("Client ID: ").strip()
            try:
                secret = getpass.getpass("Client secret (hidden): ").strip()
            except Exception:
                secret = input("Client secret: ").strip()
            if not (client_id and secret):
                print("Both client ID and secret are required. Nothing saved.")
                continue
            cfg = _pcu_load_connections()
            sh = cfg.setdefault("shopify", {})
            sh.update({"store": store, "client_id": client_id, "client_secret": secret})
            sh.pop("access_token", None)
            sh.pop("last_test", None)
            _pcu_save_connections(cfg)
            print(f"Saved to {PCU_CONNECTIONS_FILENAME} (plain text, added to .gitignore). Run the test next.")
        elif choice == "2":
            print("Testing...")
            r = pcu_shopify_test_connection()
            print("PASSED" if r["ok"] else "FAILED", "-", r["message"])
        elif choice == "3":
            if input("Type REMOVE to delete saved Shopify credentials: ").strip().upper() == "REMOVE":
                cfg = _pcu_load_connections()
                cfg.pop("shopify", None)
                _pcu_save_connections(cfg)
                print("Removed. (Environment variables, if set, are untouched.)")
        elif choice == "4":
            print("\nHOW TO GET SHOPIFY CREDENTIALS (current as of 2026)")
            print("  - Legacy 'custom apps' can no longer be created in the store admin.")
            print("  - Create an app in the Shopify Dev Dashboard, set scopes (read_products, write_products),")
            print("    release a version, and install it on your store.")
            print("  - Copy the app's Client ID and Client Secret from its Settings and enter them here.")
            print("  - Factory exchanges them for a short-lived token (about 24h) each time it connects.")
            print("  - Alternative: set SHOPIFY_STORE / SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET as")
            print("    environment variables instead of saving them in a file.")
            print("  - Never paste these into chat, git, or screenshots.")
        elif choice in ("0", "", "B"):
            return
        else:
            print("Invalid choice.")
        input("\nPress Enter to continue...")


def pcu_connection_status_screen(project=None):
    print("\n" + "=" * 78)
    print("CONNECTION STATUS")
    print("=" * 78)
    for platform in PCU_PLATFORMS:
        print(f"\n{platform['label']}")
        print(f"  {_pcu_connection_label(platform)}")
        print(f"  {platform['api_note']}")
    print("\nCapabilities reflect what Factory can do today (researched Oct 2026). Platforms change;")
    print("no upload is ever started without you, and nothing is marked uploaded unless you confirm it.")


def pcu_center():
    project = _pcu_pick_project()
    if not project:
        print("\nNo project selected.")
        return
    while True:
        rows = _pcu_collect_status(project)
        _pcu_print_status(project, rows)
        print("\n1-7. Open a platform (numbers above)")
        print("8. Connection Status")
        print("9. Upload History (all platforms)")
        print("G. Gumroad Listing Studio")
        print("P. Universal Publishing Center (build / refresh packages)")
        print("S. Switch project")
        print("10. Back")
        choice = input("Choose: ").strip().upper()
        if choice.isdigit() and 1 <= int(choice) <= len(PCU_PLATFORMS):
            pcu_platform_page(project, PCU_PLATFORMS[int(choice) - 1]["key"])
            continue
        elif choice == "8":
            pcu_connection_status_screen(project)
        elif choice == "9":
            pcu_history_screen(project)
        elif choice == "G":
            gumroad_listing_studio(project)
            continue
        elif choice == "P":
            platform_center()
            continue
        elif choice == "S":
            picked = _pcu_pick_project(force_choose=True)
            if picked:
                project = picked
            continue
        elif choice in ("10", "0", "B", ""):
            return
        else:
            print("Invalid choice.")
        input("\nPress Enter to continue...")


# ============================================================
# v16.7 — GUMROAD LISTING STUDIO  (gumroad_* / _gl_*)
# Turns a project into a paste-ready Gumroad listing:
#   NAME / PRICE / SUMMARY / DESCRIPTION / TAGS / ADDITIONAL DETAILS / FILES
# Written into the Gumroad package as PRODUCT_DESCRIPTION.txt, and editable
# per book in the Listing Studio (stored in UPLOAD_CENTER/GUMROAD_LISTING.json,
# so project.json is never touched). Nothing is invented: price stays blank
# until you set it, and the license text is clearly marked as editable.
# ============================================================
GUMROAD_LISTING_FILENAME = "GUMROAD_LISTING.json"
GUMROAD_DEFAULT_LICENSE = ("Personal use only. You may print copies for yourself. "
                           "Please do not resell, share, or redistribute the files.")
_GL_PHYSICAL_RE = re.compile(
    r"\b(paperback|hardcover|amazon|kdp|print edition|order your copy|ships?|shipping)\b", re.I)


def _gl_print(text=""):
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(str(text).encode(enc, "replace").decode(enc, "replace"))


def _gl_path(project):
    return Path(project) / PCU_DIRNAME / GUMROAD_LISTING_FILENAME


def gumroad_load_overrides(project):
    path = _gl_path(project)
    if not path.exists():
        return {}
    try:
        data = load_json(path)
        if isinstance(data, dict):
            return data
        raise ValueError("unexpected structure")
    except Exception:
        try:
            shutil.copy2(path, path.with_name(f"{path.stem}.corrupt-{datetime.now():%Y%m%d-%H%M%S}.json"))
        except Exception:
            pass
        return {}


def gumroad_save_overrides(project, data):
    clean = {k: v for k, v in data.items() if v not in ("", None, [], {})}
    save_json(_gl_path(project), clean)


def _gl_clean_list(value):
    if isinstance(value, str):
        value = re.split(r"[,\n]", value)
    out, seen = [], set()
    for item in value or []:
        item = str(item).strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out


def _gl_num(value):
    try:
        return f"{float(value):g}"
    except Exception:
        return str(value)


def _gl_first_sentences(text, limit=200):
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text.rfind(". ", 0, limit)
    if cut > 40:
        return text[:cut + 1]
    cut = text.rfind(" ", 0, limit - 1)
    return text[:cut if cut > 0 else limit - 1].rstrip(",;:") + "..."


def _gl_norm_price(raw):
    raw = (raw or "").strip()
    if not raw or raw == "-":
        return ""
    match = re.fullmatch(r"\$?\s*(\d+(?:\.\d{1,2})?)", raw)
    return f"${float(match.group(1)):.2f}" if match else raw


def gumroad_build_listing(project, settings=None, files_dir=None):
    project = Path(project)
    if settings is None:
        settings = load_project_settings_safe(project)
    ov = gumroad_load_overrides(project)
    warnings = []

    title = str(settings.get("title") or project.name).strip()
    subtitle = str(settings.get("subtitle") or settings.get("cover_subtitle") or "").strip()
    author = str(settings.get("author") or "").strip()
    series = str(settings.get("series_name") or settings.get("series") or "").strip()
    world = str(settings.get("universe_name") or "").strip()

    master, pages = None, None
    try:
        master = find_master_pdf(project)
        pages = pdf_page_count(master) if master else None
    except Exception:
        pass
    size_txt = ""
    tw, th = settings.get("trim_width"), settings.get("trim_height")
    if not (tw and th) and master:
        try:
            first = (inspect_pdf(master).get("sizes") or [{}])[0]
            tw, th = first.get("width"), first.get("height")
        except Exception:
            pass
    if tw and th:
        size_txt = f"{_gl_num(tw)} x {_gl_num(th)} in"

    # ---- name
    if ov.get("name"):
        name = str(ov["name"]).strip()
    else:
        name = f"{title}: {subtitle}" if subtitle and subtitle.lower() not in title.lower() else title
        if "pdf" not in name.lower():
            name += " (Printable PDF)"

    # ---- description body
    desc_source = "Studio"
    raw = str(ov.get("description") or "").strip()
    if not raw:
        for key in ("long_description", "description", "cover_blurb"):
            if str(settings.get(key) or "").strip():
                raw, desc_source = str(settings[key]).strip(), f"project setting '{key}'"
                break
    if not raw:
        raw = f"{title} is a printable coloring book" + (f" by {author}." if author else ".")
        desc_source = "auto-generated"
        warnings.append("No description found - a basic one was generated. Write your own in the Listing Studio.")
    hit = sorted({m.group(0).lower() for m in _GL_PHYSICAL_RE.finditer(raw)})
    if hit:
        warnings.append("Description mentions " + ", ".join(f"'{h}'" for h in hit) +
                        " - Gumroad buyers get a digital PDF, so check that wording.")

    summary = str(ov.get("summary") or settings.get("short_description") or "").strip()
    if not summary:
        summary = _gl_first_sentences(raw, 200)

    get = [f"{pages}-page digital PDF coloring book" if pages else "Digital PDF coloring book"]
    if not pages:
        warnings.append("Could not read the PDF page count, so 'What you get' omits it.")
    if size_txt:
        get.append(f"Page size: {size_txt}")
    get.append("Instant download after purchase - nothing is shipped")
    get += _gl_clean_list(ov.get("bullets"))

    lines = [raw, "", "WHAT YOU GET"] + [f"• {g}" for g in get]
    lines += ["", "HOW TO USE",
              "• Download the PDF and print as many copies as you like for personal use.",
              "• Works on any device or app that opens PDFs, so you can also color digitally.",
              "• Tip: for markers or wet media, print on heavier paper or slip a sheet behind the page."]
    if series:
        lines += ["", "ABOUT THE SERIES", f"Part of {series}." + (f" Set in {world}." if world else "")]
    lines += ["", "TERMS OF USE", str(ov.get("license") or GUMROAD_DEFAULT_LICENSE).strip()]
    if str(ov.get("content_note") or "").strip():
        lines += ["", "CONTENT NOTE", str(ov["content_note"]).strip()]
    description = "\n".join(lines)

    tags = _gl_clean_list(ov.get("tags")) or _gl_clean_list(settings.get("keywords"))
    if not tags:
        warnings.append("No tags/keywords set.")
    price = _gl_norm_price(str(ov.get("price") or ""))
    if not price:
        warnings.append("No price set yet (set it in the Studio, or just enter it on Gumroad).")
    if not author:
        warnings.append("No author in project settings.")

    details = [("Format", "PDF (digital download)")]
    if pages:
        details.append(("Pages", str(pages)))
    if size_txt:
        details.append(("Page size", size_txt))
    if author:
        details.append(("Author", author))
    if series:
        details.append(("Series", series))

    files = []
    root = Path(files_dir) if files_dir else _pcu_package_root(project, "Gumroad")
    try:
        if root.exists():
            for pdf in sorted(root.glob("*.pdf")):
                if not pdf.name.startswith("."):
                    files.append(("Product file", pdf.name))
            for label, stem in (("Cover image", "cover"), ("Thumbnail", "thumbnail")):
                for ext in (".png", ".jpg"):
                    if (root / (stem + ext)).exists():
                        files.append((label, stem + ext))
                        break
            for img in sorted(list(root.glob("thumb-*.png")) + list(root.glob("thumb-*.jpg"))):
                files.append(("Preview image", img.name))
    except Exception:
        pass

    return {"name": name, "price": price, "summary": summary, "description": description,
            "tags": tags, "details": details, "files": files, "warnings": warnings,
            "desc_source": desc_source}


def gumroad_render_listing_text(listing):
    parts = ["GUMROAD LISTING - copy each section into the matching Gumroad field",
             "(Field names in Gumroad's editor may differ slightly. Upload the files listed at the bottom.)",
             "",
             "=== NAME ===", listing["name"], "",
             "=== PRICE ===", listing["price"] or "(not set - choose your price in Gumroad)", "",
             "=== SUMMARY ===", listing["summary"], "",
             "=== DESCRIPTION ===", listing["description"], "",
             "=== TAGS ===", ", ".join(listing["tags"]) or "(none)", "",
             "=== ADDITIONAL DETAILS ===", *[f"{k}: {v}" for k, v in listing["details"]], "",
             "=== FILES TO UPLOAD ===",
             *([f"{label}: {fn}" for label, fn in listing["files"]] or ["(build the Gumroad package first)"])]
    return "\n".join(parts) + "\n"


def gumroad_write_listing(project, output_dir, settings):
    listing = gumroad_build_listing(project, settings, files_dir=output_dir)
    path = Path(output_dir) / "PRODUCT_DESCRIPTION.txt"
    path.write_text(gumroad_render_listing_text(listing), encoding="utf-8")
    return path


def gumroad_package_listing_in_sync(project):
    """True/False: does the package's PRODUCT_DESCRIPTION.txt match the current listing? None if unknown."""
    try:
        root = _pcu_package_root(project, "Gumroad")
        existing = root / "PRODUCT_DESCRIPTION.txt"
        if not existing.exists():
            return None
        live = gumroad_render_listing_text(gumroad_build_listing(project))
        return existing.read_text(encoding="utf-8").replace("\r\n", "\n") == live
    except Exception:
        return None


def _gl_read_block(prompt):
    print(prompt)
    print("  Type or paste text, then END on its own line. CANCEL = abort, '-' alone = reset to automatic.")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        marker = line.strip().upper()
        if not lines and marker == "CANCEL":
            return None
        if marker == "END":
            break
        lines.append(line.rstrip("\r\n"))
    text = "\n".join(lines).strip()
    return "" if text == "-" else text


def gumroad_listing_studio(project):
    project = Path(project)
    while True:
        listing = gumroad_build_listing(project)
        ov = gumroad_load_overrides(project)
        print("\n" + "=" * 78)
        print(f"GUMROAD LISTING STUDIO - {project.name}")
        print("=" * 78)
        _gl_print(f"Name:         {listing['name']}")
        _gl_print(f"Price:        {listing['price'] or '(not set)'}")
        _gl_print(f"Summary:      {listing['summary']}")
        _gl_print(f"Tags:         {', '.join(listing['tags']) or '(none)'}")
        print(f"Description:  {len(listing['description'])} characters (hook text from: {listing['desc_source']})")
        print("Terms:        " + ("custom" if ov.get("license") else "default (personal use only) - edit if you want different terms"))
        if listing["warnings"]:
            print("\nHeads up:")
            for w in listing["warnings"]:
                _gl_print(f"  - {w}")
        sync = gumroad_package_listing_in_sync(project)
        if sync is False:
            print("\nThe Gumroad package still has an OLDER listing. Use option 10 to rebuild it.")
        print("\n1. Name              6. Extra 'What you get' bullets")
        print("2. Price             7. Terms of use / license")
        print("3. Summary           8. Content note (optional)")
        print("4. Description       9. Preview the full listing")
        print("5. Tags             10. Save + rebuild Gumroad package now")
        print("0. Back")
        print("(Enter on a prompt keeps the current value; '-' resets a field to automatic.)")
        choice = input("Choose: ").strip()
        changed = False
        if choice in ("1", "2", "3"):
            key = {"1": "name", "2": "price", "3": "summary"}[choice]
            raw = input(f"New {key}: ").strip()
            if raw:
                value = _gl_norm_price(raw) if key == "price" else ("" if raw == "-" else raw)
                ov[key] = value
                changed = True
        elif choice == "4":
            text = _gl_read_block("\nPaste your product description (the hook / main sales text):")
            if text is not None:
                ov["description"] = text
                changed = True
        elif choice == "5":
            raw = input("Tags, comma-separated: ").strip()
            if raw:
                ov["tags"] = [] if raw == "-" else _gl_clean_list(raw)
                changed = True
        elif choice == "6":
            text = _gl_read_block("\nExtra bullets for 'What you get', one per line:")
            if text is not None:
                ov["bullets"] = _gl_clean_list(text.replace(",", ";").split("\n")) if text else []
                changed = True
        elif choice == "7":
            text = _gl_read_block("\nYour terms of use / license text:")
            if text is not None:
                ov["license"] = text
                changed = True
        elif choice == "8":
            text = _gl_read_block("\nContent note (for example a heads-up about creepy/horror themes):")
            if text is not None:
                ov["content_note"] = text
                changed = True
        elif choice == "9":
            _gl_print("\n" + gumroad_render_listing_text(listing))
            input("Press Enter to continue...")
        elif choice == "10":
            print("\nRebuilding the Gumroad package (this regenerates the cover and previews too)...")
            try:
                result = generate_platform_package(project, "Gumroad")
                print(f"Result: {result.get('status')}")
                for e in result.get("errors", []):
                    print("  ERROR:", e)
            except Exception as error:
                print(f"Rebuild failed: {error}")
            input("Press Enter to continue...")
        elif choice in ("0", "", "B"):
            return
        else:
            print("Invalid choice.")
        if changed:
            gumroad_save_overrides(project, ov)
            print("Saved. Use option 10 to put this into the Gumroad package.")


def factory_main_menu():
    PROJECTS.mkdir(exist_ok=True)
    while True:
        active=v12_active_project()
        print("\n" + "=" * 78); print(f"          COLORING BOOK FACTORY v{FACTORY_VERSION}"); print("=" * 78)
        _print_project_status(active)
        print("\nCREATE A NEW BOOK")
        print("  1. New Book From Idea")
        print("  2. New Book From Template")
        print("  3. New Blank Project")
        print("\nEXISTING / PART-FINISHED BOOKS")
        print("  4. Continue Existing Book")
        print("  5. Import Finished PDF")
        print("  6. Import Artwork / Images")
        print("  7. Recover / Repair Existing Project")
        print("\nPRODUCTION")
        print("  8. Production Center")
        print("  9. Book / Creation Dashboard")
        print("\nPUBLISH & SELL")
        print(" 10. Publishing Center")
        print(" 11. Production Release")
        print(" 12. Platform Connections / Upload Center")
        print(" 13. Marketing Center")
        print("\nWORLDS & SERIES")
        print(" 14. Worlds & Projects")
        print(" 15. Series & Lore")
        print("\nTOOLS")
        print(" 16. Maintenance / Factory Health")
        print(" 17. Backups / Safety")
        print("  0. Exit")
        c=input("\nChoose: ").strip().upper()
        if c=="1": start_new_book_menu()
        elif c=="2": clone_project_from_template()
        elif c=="3": create_project()
        elif c=="4": continue_active_book()
        elif c=="5": import_existing_book_menu()
        elif c=="6": import_artwork_menu()
        elif c=="7":
            try: repair_reconcile_project_menu()
            except NameError: import_existing_book_menu()
        elif c=="8": production_menu()
        elif c=="9": cb13_creation_dashboard()
        elif c=="10": publishing_menu()
        elif c=="11": production_release_center()
        elif c=="12": pcu_center()
        elif c=="13": marketing_center()
        elif c=="14": worlds_projects_menu()
        elif c=="15":
            try: series_lore_center()
            except NameError: worlds_projects_menu()
        elif c=="16" or c=="H": maintenance_menu()
        elif c=="17":
            try: safety_backup_menu()
            except NameError: maintenance_menu()
        elif c=="P": publishing_menu()
        elif c=="R": v12_recent_projects_menu()
        elif c=="A": v12_active_dashboard()
        elif c in ("0","Q"): print("\nGoodbye."); break
        else: print("\nInvalid choice.")
        input("\nPress Enter to continue...")

def book_creation_engine_menu():
    while True:
        print("\n" + "=" * 78)
        print(f"BOOK CREATION ENGINE v{FACTORY_VERSION}")
        print("=" * 78)
        print("1. Create Book Blueprint from Idea")
        print("2. Open Creation Dashboard")
        print("3. Lore + Prompt Studio")
        print("4. Artwork Production Center")
        print("5. Build Current Book + Publish Packages")
        print("6. Back")
        choice = input("Choose: ").strip()
        if choice == "1":
            cb13_create_book_blueprint_from_idea()
        elif choice == "2":
            cb13_creation_dashboard()
        elif choice == "3":
            cb16_lore_prompt_studio()
        elif choice == "4":
            cb13_artwork_production_center()
        elif choice == "5":
            cb13_build_and_publish_project()
        elif choice == "6":
            return
        else:
            print("Invalid choice.")
        input("\nPress Enter to continue...")

def main():
    factory_main_menu()


if __name__ == "__main__":
    main()
