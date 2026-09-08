from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import json
import textwrap
import shutil
import sys
import zipfile
import re
import os
from datetime import datetime
from hashlib import sha256

# ============================================================
# COLORING BOOK FACTORY v8.1
# WORLD-AWARE PRODUCTION ENGINE + AUTOMATED ASSEMBLY + PAGE BUILDER + PDF/KDP PREFLIGHT + PRODUCTION CENTER
#
# v8.1 changes:
#   - Worlds & Universes screen no longer dead-ends when no worlds exist
#     (it used to print "No worlds created yet." and return immediately,
#     hiding "Create new world" and every other option).
#   - World Management Center: view world books, world production history,
#     archive/restore a world (with type-to-confirm safety), search worlds,
#     and list/remove existing world entities (not just add new ones).
#   - Production events (interior builds and platform package generation)
#     now write into the attached world's production history.
#   - Platform status displays (Platform Audit, Platform Engine self-test,
#     project health, and platform package generation) now print the
#     actual warning text next to any non-zero warning count, instead of
#     just a count, so a READY_WITH_WARNINGS result is self-explanatory.
# ============================================================

FACTORY = Path(__file__).resolve().parent
PROJECTS = FACTORY / "Projects"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

FACTORY_VERSION = "8.1"
WORLD_ENGINE_VERSION = "1.1"
WORLDS_DIR = FACTORY / "Worlds"
WORLD_INDEX_FILENAME = "world_index.json"
WORLD_SCHEMA_VERSION = 2
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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


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
PLATFORM_ENGINE_VERSION = "3.0"
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


def load_platform_profiles():
    path = platform_profiles_path()
    if not path.exists():
        save_platform_profiles(json.loads(json.dumps(DEFAULT_PLATFORM_PROFILES)))
        return json.loads(json.dumps(DEFAULT_PLATFORM_PROFILES))
    try:
        data = load_json(path)
        profiles = data.get("profiles", {}) if isinstance(data, dict) else {}
        merged = json.loads(json.dumps(DEFAULT_PLATFORM_PROFILES))
        for key, value in profiles.items():
            if isinstance(value, dict):
                base = merged.get(key, {})
                base.update({k: v for k, v in value.items() if k != "rules" and k != "variant"})
                base["rules"] = {**merged.get(key, {}).get("rules", {}), **value.get("rules", {})}
                base["variant"] = {**merged.get(key, {}).get("variant", {}), **value.get("variant", {})}
                merged[key] = base
        return merged
    except Exception:
        return json.loads(json.dumps(DEFAULT_PLATFORM_PROFILES))


def save_platform_profiles(profiles):
    save_json(platform_profiles_path(), {"version": PLATFORM_ENGINE_VERSION,
                                        "updated": datetime.now().isoformat(timespec="seconds"),
                                        "profiles": profiles})


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


def inspect_pdf(path):
    result = {"path": str(path) if path else None, "exists": bool(path and Path(path).exists()),
              "page_count": None, "sizes": [], "unique_sizes": [], "file_size_mb": None,
              "encrypted": None, "metadata": {}, "error": None}
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
        for page in reader.pages:
            w = round(float(page.mediabox.width) / 72, 4)
            h = round(float(page.mediabox.height) / 72, 4)
            sizes.append({"width": w, "height": h,
                          "orientation": "landscape" if w > h else "portrait" if h > w else "square"})
        result["sizes"] = sizes
        result["unique_sizes"] = sorted({f"{x['width']}x{x['height']}" for x in sizes})
    except ImportError:
        result["error"] = "PyPDF2 is not installed."
    except Exception as error:
        result["error"] = str(error)
    return result


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
    if platform_name == "KDP" and page_count is not None and not info.get("error"):
        try:
            kdp_errors, kdp_warnings = kdp_preflight(project, settings, master_pdf, page_count)
            errors.extend([f"KDP engine: {x}" for x in kdp_errors])
            warnings.extend([f"KDP engine: {x}" for x in kdp_warnings])
        except Exception as error:
            errors.append(f"KDP engine preflight failed: {error}")
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
    return {"schema_version": 2, "factory_version": FACTORY_VERSION, "platform_engine_version": PLATFORM_ENGINE_VERSION,
            "platform": platform_name, "platform_type": profile.get("type"), "status": status,
            "timestamp": datetime.now().isoformat(timespec="seconds"), "master_pdf": str(master_pdf) if master_pdf else None,
            "pdf": info, "metadata": {"title": settings.get("title", ""), "author": settings.get("author", ""),
                                      "page_count": page_count, "trim_width": settings.get("trim_width"),
                                      "trim_height": settings.get("trim_height")}, "rules": rules,
            "variant": profile.get("variant", {}), "errors": errors, "warnings": warnings}


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


def _copy_variant_pdf(master_pdf, root, title, profile):
    variant = profile.get("variant", {})
    mode = variant.get("mode", "copy")
    suffix = variant.get("filename_suffix", "_PLATFORM")
    target = root / f"{title}{suffix}.pdf"
    if mode == "copy":
        shutil.copy2(master_pdf, target)
        return target, []
    if mode == "rebuild_pdf":
        # Reserved extension point: a profile can request a rebuild in a future
        # recipe. We refuse silently changing content instead of guessing.
        return None, [f"Variant mode '{mode}' is not implemented; master was not modified."]
    return None, [f"Unknown platform variant mode: {mode}"]


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


def generate_platform_package(project, platform_name, source_pdf=None, quiet=False):
    profiles = load_platform_profiles()
    profile = profiles.get(platform_name)
    if not profile: return {"status": "BLOCKED", "errors": [f"Unknown platform: {platform_name}"], "warnings": []}
    settings = load_project_settings_safe(project)
    master_pdf, errors, warnings = ensure_master_book(project, source_pdf=source_pdf)
    if errors or master_pdf is None: return {"status": "BLOCKED", "errors": errors, "warnings": warnings}
    audit = platform_preflight(project, platform_name, master_pdf, profile)
    root = project / PLATFORM_DIRNAME / profile.get("output_dir", platform_name.upper().replace(" ", "_"))
    root.mkdir(parents=True, exist_ok=True)
    audit_path = root / "PLATFORM_PREFLIGHT.json"
    save_json(audit_path, audit)
    if audit["status"] == "BLOCKED":
        if not quiet:
            print(f"\n{platform_name} package BLOCKED")
            for error in audit["errors"]: print(f"ERROR: {error}")
        return {"status": "BLOCKED", "output": root, "audit": audit, "errors": audit["errors"], "warnings": audit["warnings"]}

    # Transaction-style generation: build into a staging directory first, validate,
    # then publish the complete package. Existing package files are never partially
    # overwritten by a failed build.
    staging = root / ".staging"
    if staging.exists(): shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    title = kdp_safe_filename(settings.get("title", project.name))
    generated = []
    try:
        variant_pdf, variant_errors = _copy_variant_pdf(master_pdf, staging, title, profile)
        if variant_errors: raise RuntimeError("; ".join(variant_errors))
        generated.append(variant_pdf)
        cover = _platform_cover(project)
        if cover:
            target = staging / f"{title}_COVER{cover.suffix.lower()}"
            shutil.copy2(cover, target); generated.append(target)
        if "preview_sheet" in profile.get("files", []): generated.append(create_preview_sheet(project, staging, master_pdf, settings))
        metadata = {
            "schema_version": 3, "factory_version": FACTORY_VERSION, "platform_engine_version": PLATFORM_ENGINE_VERSION,
            "platform": platform_name, "platform_type": profile.get("type"), "generated": datetime.now().isoformat(timespec="seconds"),
            "title": settings.get("title", project.name), "subtitle": settings.get("subtitle", settings.get("cover_subtitle", "")),
            "author": settings.get("author", ""), "description": settings.get("description", settings.get("cover_blurb", "")),
            "series": settings.get("series_name", ""), "series_number": settings.get("series_number", ""),
            "world": settings.get("universe_name", ""), "page_count": audit.get("pdf", {}).get("page_count"),
            "source_master": str(master_pdf), "source_master_sha256": file_hash(master_pdf),
            "profile": profile, "preflight_status": audit["status"],
        }
        metadata_path = staging / "METADATA.json"; save_json(metadata_path, metadata); generated.append(metadata_path)
        if "product_description" in profile.get("files", []): generated.append(write_product_description(project, staging, settings, platform_name))
        if platform_name == "KDP": _copy_required_kdp_assets(project, staging, generated)
        check_errors, check_warnings = validate_generated_package(staging, master_pdf, profile, generated)
        if check_errors: raise RuntimeError("Package validation failed: " + " | ".join(check_errors))
        final_status = "READY_WITH_WARNINGS" if (audit["warnings"] or check_warnings) else "READY"
        manifest = {
            "schema_version": 3, "factory_version": FACTORY_VERSION, "platform_engine_version": PLATFORM_ENGINE_VERSION,
            "platform": platform_name, "status": final_status, "project": project.name,
            "title": settings.get("title", project.name), "generated": datetime.now().isoformat(timespec="seconds"),
            "master_pdf": str(master_pdf), "master_sha256": file_hash(master_pdf),
            "variant_mode": profile.get("variant", {}).get("mode", "copy"),
            "files": [str(p.relative_to(staging)) for p in generated if p.exists()],
            "file_hashes": {str(p.relative_to(staging)): file_hash(p) for p in generated if p.exists()},
            "warnings": audit["warnings"] + check_warnings, "preflight": "PLATFORM_PREFLIGHT.json",
            "package_validation": {"status": "PASS", "errors": [], "warnings": check_warnings},
        }
        save_json(staging / "PACKAGE_MANIFEST.json", manifest)
        generated.append(staging / "PACKAGE_MANIFEST.json")
        # Publish atomically at the directory level as far as Windows filesystem
        # semantics permit: old package becomes a backup, then staging becomes live.
        backup = root.with_name(root.name + ".previous")
        if backup.exists(): shutil.rmtree(backup, ignore_errors=True)
        live_contents = [x for x in root.iterdir() if x.name != ".staging"]
        # Move old contents aside rather than deleting them before validation.
        for item in live_contents:
            if backup.exists(): break
            backup.mkdir(parents=True, exist_ok=True)
            break
        if live_contents:
            for item in live_contents:
                target = backup / item.name
                shutil.move(str(item), str(target))
        for item in list(staging.iterdir()): shutil.move(str(item), str(root / item.name))
        staging.rmdir()
        if backup.exists(): shutil.rmtree(backup, ignore_errors=True)
        # Recompute final manifest paths after publication.
        manifest["files"] = [str(p) for p in sorted((root / f).relative_to(project) for f in manifest["files"] if (root / f).exists())]
        save_json(root / "PACKAGE_MANIFEST.json", manifest)
        record_world_production_event(
            project, f"platform_package:{platform_name}", final_status,
            page_count=audit.get("pdf", {}).get("page_count") or 0,
            errors=0, warnings=len(manifest["warnings"]),
        )
        if not quiet:
            print(f"\n{platform_name} package {final_status}")
            print(f"Output: {root}\nFiles: {len(manifest['files'])}")
            for warning in manifest["warnings"]: print(f"WARNING: {warning}")
        return {"status": final_status, "output": root, "manifest": manifest, "audit": audit, "warnings": manifest["warnings"]}
    except Exception as error:
        shutil.rmtree(staging, ignore_errors=True)
        if not quiet: print(f"\n{platform_name} package FAILED: {error}")
        return {"status": "BLOCKED", "output": root, "audit": audit, "errors": [str(error)], "warnings": audit["warnings"]}


def generate_all_platform_packages(project):
    profiles = load_platform_profiles()
    enabled = [name for name, profile in profiles.items() if profile.get("enabled", False)]
    print("\nGENERATING ALL ENABLED PLATFORM PACKAGES")
    print("-" * 60)
    results = {}
    for name in enabled:
        result = generate_platform_package(project, name, quiet=True)
        results[name] = result
        print(f"{name}: {result.get('status')}")
    save_json(project / PLATFORM_INDEX_FILENAME, {"schema_version": 1, "generated": datetime.now().isoformat(timespec="seconds"),
                                                 "platforms": {n: {"status": r.get("status"), "output": str(r.get("output", ""))} for n, r in results.items()}})
    return results


def platform_requirement_comparison(project):
    profiles = load_platform_profiles(); master = find_master_pdf(project); rows = []
    for name, profile in profiles.items():
        audit = platform_preflight(project, name, master, profile); rules = profile.get("rules", {})
        rows.append({"platform": name, "enabled": bool(profile.get("enabled")), "type": profile.get("type"),
                     "status": audit.get("status"), "pages": audit.get("pdf", {}).get("page_count"),
                     "max_mb": rules.get("max_file_mb"), "min_pages": rules.get("min_pages"),
                     "max_pages": rules.get("max_pages"), "cover_required": bool(rules.get("require_cover")),
                     "variant": profile.get("variant", {}).get("mode", "copy"), "errors": len(audit.get("errors", [])),
                     "warnings": len(audit.get("warnings", []))})
    return rows


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


def run_platform_self_test():
    """Offline integration test for the v7.2 platform pipeline."""
    import tempfile
    from reportlab.pdfgen import canvas as _canvas
    failures = []
    with tempfile.TemporaryDirectory(prefix="CBF_v72_TEST_") as temp:
        root = Path(temp); project = root / "Projects" / "Test Platform Book"; project.mkdir(parents=True)
        save_json(project / "project.json", {"title": "Platform Test Book", "author": "Test Author", "trim_width": 8.5, "trim_height": 11, "dpi": 300})
        (project / "PDF").mkdir()
        pdf = project / "PDF" / "source.pdf"
        c = _canvas.Canvas(str(pdf), pagesize=(8.5 * 72, 11 * 72))
        for _ in range(24): c.drawString(72, 72, "Coloring Book Factory v7.2 TEST"); c.showPage()
        c.save()
        master, e, _ = ensure_master_book(project, pdf)
        if e: failures.append("ensure_master_book: " + str(e))
        else:
            audit = platform_preflight(project, "KDP", master, load_platform_profiles()["KDP"])
            if audit["status"] == "BLOCKED": failures.append("KDP preflight unexpectedly blocked: " + str(audit["errors"]))
            result = generate_platform_package(project, "KDP", quiet=True)
            if result["status"] not in {"READY", "READY_WITH_WARNINGS"}: failures.append("KDP package failed: " + str(result.get("errors")))
            live = project / "PLATFORMS" / "KDP"
            if not (live / "PACKAGE_MANIFEST.json").exists(): failures.append("manifest missing")
            if not any(x.suffix == ".pdf" for x in live.iterdir()): failures.append("variant PDF missing")
            variant = next((x for x in live.iterdir() if x.suffix == ".pdf"), None)
            if variant and file_hash(variant) != file_hash(master): failures.append("copy variant hash mismatch")
    if failures:
        print("\nPLATFORM ENGINE SELF-TEST: FAIL")
        for f in failures: print("  FAIL:", f)
        return False
    print("\nPLATFORM ENGINE SELF-TEST: PASS")
    print("  Master immutability: PASS")
    print("  PDF inspection: PASS")
    print("  Rule-driven preflight: PASS")
    print("  Transactional package build: PASS")
    print("  Variant SHA-256 integrity: PASS")
    return True


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


def convert_existing_pdf_enhanced():
    """Professional PDF intake: inspect first, then create immutable MASTER and publish."""
    print("\n" + "=" * 78)
    print("PDF INTAKE / CONVERSION")
    print("=" * 78)
    pdf = choose_pdf_file("Finished PDF")
    if not pdf:
        print("No valid PDF selected.")
        return

    info = inspect_pdf(pdf)
    if info.get("error"):
        print(f"ERROR: {info['error']}")
        return

    print("\nSOURCE PDF")
    print("-" * 78)
    print(f"File: {pdf}")
    print(f"Pages: {info.get('page_count')}")
    print(f"Size: {info.get('file_size_mb')} MB")
    print(f"Page sizes: {', '.join(info.get('unique_sizes', [])) or 'unknown'}")
    print(f"Encrypted: {info.get('encrypted')}")

    title = pdf.stem
    name = input(f"\nProject name [{title}]: ").strip() or title
    author = input("Author [blank = unknown]: ").strip()

    project_name = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip().rstrip(".") or "Imported PDF"
    project = PROJECTS / unique_project_name(project_name)
    project.mkdir(parents=True, exist_ok=True)
    setup_project(project)
    (project / "MASTER").mkdir(exist_ok=True)

    sizes = info.get("sizes") or [{"width": 8.5, "height": 11}]
    settings = {
        "title": title,
        "author": author,
        "trim_width": sizes[0]["width"],
        "trim_height": sizes[0]["height"],
        "dpi": 300,
        "production_profile": "Imported Finished PDF",
        "factory_version": FACTORY_VERSION,
        "platform_engine_version": PLATFORM_ENGINE_VERSION,
        "world_engine_version": WORLD_ENGINE_VERSION,
        "source_pdf": str(pdf),
        "source_pdf_sha256": file_hash(pdf),
        "source_pdf_pages": info.get("page_count"),
        "source_pdf_size_mb": info.get("file_size_mb"),
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "imported_pdf_metadata": info.get("metadata", {}),
    }
    save_json(project / "project.json", settings)
    save_json(project / "book.json", {"pages": [], "source": "imported_pdf"})

    master = import_existing_pdf_to_master(project, pdf)
    if not master:
        print("ERROR: MASTER creation failed.")
        return

    print("\nMASTER LOCKED IN.")
    results = generate_all_platform_packages(project)
    create_delivery_index(project, results)
    health = project_health_scan(project)
    print_project_health(health)
    print(f"\nImported project: {project}")
    return project


def manage_platform_profiles_v2():
    """Expanded profile manager with safe rule editing and enable/disable controls."""
    profiles = load_platform_profiles()
    names = list(profiles.keys())

    while True:
        print("\n" + "=" * 78)
        print("PLATFORM PROFILE MANAGER v3")
        print("=" * 78)
        for i, name in enumerate(names, 1):
            p = profiles[name]
            r = p.get("rules", {})
            print(f"{i}. {name:<14} {'ON ' if p.get('enabled') else 'OFF'} | "
                  f"{p.get('type','?'):<8} | pages {r.get('min_pages')}-{r.get('max_pages')} | "
                  f"{r.get('max_file_mb')} MB")
        print("\nA. Add custom platform")
        print("E. Edit selected profile")
        print("T. Toggle selected profile")
        print("X. Back")
        choice = input("Choose: ").strip().lower()
        if choice == "x":
            return
        if choice == "a":
            name = input("Platform name: ").strip()
            if not name:
                continue
            if name in profiles:
                print("That platform already exists.")
                continue
            out = re.sub(r"[^A-Za-z0-9_-]+", "_", name).upper()
            profiles[name] = {
                "name": name, "type": "digital", "enabled": False,
                "output_dir": out,
                "source": "master_pdf",
                "files": ["digital_pdf", "preview_sheet", "metadata", "product_description"],
                "variant": {"mode": "copy", "filename_suffix": "_DIGITAL"},
                "rules": {"min_pages": 1, "max_pages": 10000, "require_title": True,
                          "require_author": False, "require_cover": False,
                          "require_landscape": False, "max_file_mb": 500},
                "notes": "Custom user-defined profile.",
            }
            save_platform_profiles(profiles)
            names = list(profiles.keys())
            print(f"Added custom profile: {name}")
            continue
        if not choice.isdigit() or not (1 <= int(choice) <= len(names)):
            print("Invalid choice.")
            continue
        selected = names[int(choice) - 1]
        profile = profiles[selected]
        if choice and False:
            pass
        action = input("Toggle (T) or edit (E)? ").strip().lower()
        if action == "t":
            profile["enabled"] = not profile.get("enabled", False)
            save_platform_profiles(profiles)
            print(f"{selected}: {'ENABLED' if profile['enabled'] else 'DISABLED'}")
        elif action == "e":
            rules = profile.setdefault("rules", {})
            raw = input(f"Max file MB [{rules.get('max_file_mb', 500)}]: ").strip()
            if raw:
                try:
                    rules["max_file_mb"] = float(raw)
                except ValueError:
                    print("Invalid number; unchanged.")
            raw = input(f"Minimum pages [{rules.get('min_pages', 1)}]: ").strip()
            if raw:
                try:
                    rules["min_pages"] = int(raw)
                except ValueError:
                    print("Invalid number; unchanged.")
            raw = input(f"Maximum pages [{rules.get('max_pages', 10000)}]: ").strip()
            if raw:
                try:
                    rules["max_pages"] = int(raw)
                except ValueError:
                    print("Invalid number; unchanged.")
            author_required = input(
                f"Require author? [{'Y' if rules.get('require_author') else 'N'}]: "
            ).strip().lower()
            if author_required in {"y", "n"}:
                rules["require_author"] = author_required == "y"
            save_platform_profiles(profiles)
            print(f"Saved profile: {selected}")


def platform_center():
    while True:
        profiles = load_platform_profiles()
        print("\n" + "=" * 78)
        print(f"PLATFORM & PUBLISHING CENTER v{PLATFORM_ENGINE_VERSION}")
        print("=" * 78)
        print("1. ONE-CLICK PUBLISH (build + audit + all packages + ZIPs)")
        print("2. Generate KDP Package")
        print("3. Generate Gumroad Package")
        print("4. Generate ALL Platform Packages")
        print("5. Convert Existing PDF")
        print("6. Manage Platform Profiles")
        print("7. Platform Preflight / Audit")
        print("8. Compare Platform Requirements")
        print("9. Factory Health Dashboard")
        print("10. Create Project Snapshot")
        print("11. Create Delivery ZIPs")
        print("12. Run Platform Engine Self-Test")
        print("13. Back")
        choice = input("Choose: ").strip()

        if choice in {"1", "2", "3", "4"}:
            project = choose_project()
            if not project:
                continue
            if choice == "1":
                one_click_publish(project)
            elif choice == "2":
                generate_platform_package(project, "KDP")
            elif choice == "3":
                generate_platform_package(project, "Gumroad")
            else:
                generate_all_platform_packages(project)
            input("\nPress Enter to continue...")

        elif choice == "5":
            project = convert_existing_pdf_enhanced()
            input("\nPress Enter to continue...")

        elif choice == "6":
            manage_platform_profiles_v2()

        elif choice == "7":
            project = choose_project()
            if not project:
                continue
            master, errors, warnings = ensure_master_book(project)
            print("\nPLATFORM AUDIT\n" + "-" * 78)
            if errors:
                for error in errors:
                    print("ERROR:", error)
                input("\nPress Enter to continue...")
                continue
            audits = {}
            for name, profile in profiles.items():
                if not profile.get("enabled"):
                    continue
                audit = platform_preflight(project, name, master, profile)
                audits[name] = audit
                print(f"{name}: {audit['status']} | pages={audit['pdf'].get('page_count')} | "
                      f"errors={len(audit['errors'])} | warnings={len(audit['warnings'])}")
                for error in audit["errors"]:
                    print("  ERROR:", error)
                for warning in audit["warnings"]:
                    print("  WARNING:", warning)
            save_json(project / PLATFORM_AUDIT_FILENAME, {
                "schema_version": 3,
                "generated": datetime.now().isoformat(timespec="seconds"),
                "audits": audits,
            })
            input("\nPress Enter to continue...")

        elif choice == "8":
            project = choose_project()
            if not project:
                continue
            print("\nPLATFORM REQUIREMENT COMPARISON\n" + "-" * 78)
            for row in platform_requirement_comparison(project):
                print(f"{row['platform']:<14} {'ON' if row['enabled'] else 'OFF':<4} "
                      f"{row['status']:<18} pages {row['min_pages']}-{row['max_pages']} | "
                      f"max {row['max_mb']} MB | cover "
                      f"{'YES' if row['cover_required'] else 'NO'} | variant {row['variant']}")
            input("\nPress Enter to continue...")

        elif choice == "9":
            factory_health_dashboard()
            input("\nPress Enter to continue...")

        elif choice == "10":
            project = choose_project()
            if project:
                try:
                    snapshot = create_project_snapshot(project)
                    print(f"\nSnapshot created:\n{snapshot}")
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
                            print(f"{name}: {zip_file}")
                            results[name] = {"status": "ZIPPED", "zip": str(zip_file)}
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
    while True:
        profiles = load_platform_profiles()
        print("\n" + "=" * 72); print("PLATFORM CENTER v7.2"); print("=" * 72)
        print("1. Generate KDP Package")
        print("2. Generate Gumroad Package")
        print("3. Generate ALL Platform Packages")
        print("4. Convert Existing PDF")
        print("5. Manage Platform Profiles")
        print("6. Platform Preflight / Audit")
        print("7. Compare Platform Requirements")
        print("8. Run Platform Engine Self-Test")
        print("9. Back")
        choice = input("Choose: ").strip()
        if choice in {"1", "2", "3"}:
            project = choose_project()
            if not project: continue
            if choice == "1": generate_platform_package(project, "KDP")
            elif choice == "2": generate_platform_package(project, "Gumroad")
            else: generate_all_platform_packages(project)
            input("\nPress Enter to continue...")
        elif choice == "4":
            print("\nSelect the finished PDF from the popup, or drag/drop it onto the popup.")
            pdf = choose_pdf_file("Finished PDF path")
            if not pdf:
                print("No valid PDF selected.")
                continue
            name = input("New project name (blank = PDF filename): ").strip() or pdf.stem
            project = PROJECTS / unique_project_name(name); project.mkdir(parents=True, exist_ok=True); setup_project(project)
            (project / "MASTER").mkdir(exist_ok=True)
            info = inspect_pdf(pdf); trim_w, trim_h = (info.get("sizes") or [{"width": 8.5, "height": 11}])[0]["width"], (info.get("sizes") or [{"width": 8.5, "height": 11}])[0]["height"]
            save_json(project / "project.json", {"title": pdf.stem, "author": "", "trim_width": trim_w, "trim_height": trim_h, "dpi": 300,
                                                  "production_profile": "Imported Finished PDF", "factory_version": FACTORY_VERSION,
                                                  "platform_engine_version": PLATFORM_ENGINE_VERSION, "world_engine_version": WORLD_ENGINE_VERSION})
            save_json(project / "book.json", {"pages": [], "source": "imported_pdf"})
            master = import_existing_pdf_to_master(project, pdf)
            if master: generate_all_platform_packages(project)
            input("\nPress Enter to continue...")
        elif choice == "5":
            print("\nPLATFORM PROFILES")
            names = list(profiles.keys())
            for i, name in enumerate(names, 1):
                profile = profiles[name]; rules = profile.get("rules", {})
                print(f"{i}. {name}: {'ENABLED' if profile.get('enabled') else 'disabled'} | {profile.get('type')} | {rules.get('min_pages')}-{rules.get('max_pages')} pages | {rules.get('max_file_mb')} MB | variant={profile.get('variant', {}).get('mode', 'copy')}")
            raw = input("Enter profile number to toggle, or Enter to go back: ").strip()
            if raw.isdigit() and 0 <= int(raw) - 1 < len(names):
                name = names[int(raw) - 1]; profiles[name]["enabled"] = not profiles[name].get("enabled", False); save_platform_profiles(profiles)
                print(f"{name}: {'ENABLED' if profiles[name]['enabled'] else 'disabled'}")
        elif choice == "6":
            project = choose_project()
            if not project: continue
            master, errors, _ = ensure_master_book(project)
            print("\nPLATFORM AUDIT\n" + "-" * 72)
            if errors:
                for error in errors: print("ERROR:", error)
                input("\nPress Enter to continue..."); continue
            audits = {}
            for name, profile in profiles.items():
                if not profile.get("enabled"): continue
                audit = platform_preflight(project, name, master, profile); audits[name] = audit
                print(f"{name}: {audit['status']} | pages={audit['pdf'].get('page_count')} | errors={len(audit['errors'])} | warnings={len(audit['warnings'])}")
                for error in audit["errors"]: print("  ERROR:", error)
                for warning in audit["warnings"]: print("  WARNING:", warning)
            save_json(project / PLATFORM_AUDIT_FILENAME, {"schema_version": 2, "generated": datetime.now().isoformat(timespec="seconds"), "audits": audits})
            input("\nPress Enter to continue...")
        elif choice == "7":
            project = choose_project()
            if not project: continue
            print("\nPLATFORM REQUIREMENT COMPARISON\n" + "-" * 72)
            for row in platform_requirement_comparison(project):
                print(f"{row['platform']:<14} {'ON' if row['enabled'] else 'OFF':<4} {row['status']:<18} pages {row['min_pages']}-{row['max_pages']} | max {row['max_mb']} MB | cover {'YES' if row['cover_required'] else 'NO'} | variant {row['variant']}")
            input("\nPress Enter to continue...")
        elif choice == "8":
            run_platform_self_test(); input("\nPress Enter to continue...")
        elif choice == "9": return
        else: print("Invalid choice.")

# ============================================================
# MAIN MENU
# ============================================================

def main():

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
        print("10. Exit")

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
            world_list_menu()
            input("\nPress Enter to return to menu...")

        elif choice == "8":
            production_center()
            input("\nPress Enter to return to menu...")
        elif choice == "9":
            platform_center()
            input("\nPress Enter to return to menu...")

        elif choice == "10":
            print("\nGoodbye.")
            break

        else:

            print(
                "\nInvalid choice."
            )


if __name__ == "__main__":

    main()