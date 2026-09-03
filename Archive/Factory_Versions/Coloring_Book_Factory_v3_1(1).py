from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import json
import textwrap
import shutil
import sys
import os
from datetime import datetime
from hashlib import sha256

# ============================================================
# COLORING BOOK FACTORY v3.0
# PAGE BUILDER + PDF BUILDER + PREFLIGHT
# ============================================================

FACTORY = Path(__file__).resolve().parent
PROJECTS = FACTORY / "Projects"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

FACTORY_VERSION = "3.1"
BUILD_STATE_FILE = "build_state.json"
SUPPORTED_TRIM_SIZES = {
    "8.5x11": (8.5, 11.0),
    "8x10": (8.0, 10.0),
    "7.5x9.25": (7.5, 9.25),
    "6x9": (6.0, 9.0),
}


# ============================================================
# JSON
# ============================================================

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


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

def get_images(project):

    folder = project / "INPUT"

    images = [
        p
        for p in folder.iterdir()
        if p.is_file()
        and p.suffix.lower()
        in IMAGE_EXTENSIONS
    ]

    return sorted(
        images,
        key=lambda p: p.name.lower()
    )


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
        f.write("COLORING BOOK FACTORY v3.0\n")
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
    processed_map = {}

    # ----------------------------------------
    # PROCESS SOURCE IMAGES WITH REAL CHANGE DETECTION
    # ----------------------------------------
    for number, source in enumerate(images, start=1):
        image_id = f"{number:03d}"
        image_map[image_id] = source

        current_hash = file_hash(source)
        cached = old_images.get(source.name, {})
        output = processed / f"{image_id}.png"

        reusable = (
            cached.get("hash") == current_hash
            and cached.get("process_signature") == process_signature
            and output.exists()
        )

        if reusable:
            print(f"  CACHE HIT: {source.name}")
        else:
            print(f"  PROCESSING: {source.name}")
            page = create_coloring_page(source, settings)
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
                page = create_coloring_page(source, settings)

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
# COMPLETE BOOK BUILD
# ============================================================

def build_book(project):
    setup_project(project)
    try:
        settings = load_json(project / "project.json")
        book = load_json(project / "book.json")
        if update_project_defaults(settings):
            save_json(project / "project.json", settings)
    except Exception as error:
        print(f"\nERROR: Could not load project configuration: {error}")
        return
    images = get_images(project)
    current_inventory = source_inventory(images)
    state = load_build_state(project)
    current_fingerprint_payload = {
        "factory_version": FACTORY_VERSION,
        "settings": settings_full_fingerprint(settings),
        "manifest": manifest_fingerprint(book),
        "images": {name: data.get("hash") for name, data in sorted(current_inventory.items())},
    }
    current_fingerprint = sha256(
        json.dumps(current_fingerprint_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    print()
    print("=" * 60)
    print("COLORING BOOK FACTORY v3.1")
    print("=" * 60)
    print()
    print(f"Book: {settings.get('title')}")
    print(f"Images found: {len(images)}")
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
    all_errors = qc_errors + page_errors + pdf_errors
    all_warnings = qc_warnings + page_warnings + pdf_warnings
    report = write_final_report(project, settings, built_pages, pdf_file, final_pdf, all_errors, all_warnings)

    if not all_errors:
        state = load_build_state(project)
        state["version"] = FACTORY_VERSION
        state["images"] = {}
        for name, data in current_inventory.items():
            state["images"][name] = dict(data)
            state["images"][name]["process_signature"] = settings_fingerprint(settings)
            if name in {image.name for image in images}:
                try:
                    index = [image.name for image in images].index(name) + 1
                    state["images"][name]["processed_id"] = f"{index:03d}.png"
                except ValueError:
                    pass
        state["build_fingerprint"] = current_fingerprint
        state["last_build"] = datetime.now().isoformat(timespec="seconds")
        save_build_state(project, state)

        package = project / "KDP_PACKAGE"
        package.mkdir(exist_ok=True)
        shutil.copy2(final_pdf, package / final_pdf.name)
        shutil.copy2(report, package / "BUILD_REPORT.txt")

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
    print()

    results = []
    for project in projects:
        print(f"\n>>> BUILDING: {project.name}")
        try:
            settings = load_json(project / "project.json")
            images = get_images(project)
            if not images:
                results.append((project.name, "FAILED - no images"))
                continue
            # Reuse the normal build pipeline while keeping bulk mode non-interactive.
            build_book(project)
            report = project / "REPORTS" / "final_report.txt"
            status = "FAILED"
            if report.exists() and "STATUS: BUILD SUCCESSFUL" in report.read_text(encoding="utf-8"):
                status = "READY"
            elif report.exists():
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

        "min_source_height": 2000
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
            "        COLORING BOOK FACTORY v3.0"
        )
        print("=" * 60)

        print()
        print("1. Build a book")
        print("2. Create a new project")
        print("3. Build ALL books")
        print("4. Exit")

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
            bulk_build()
            input("\nPress Enter to return to menu...")

        elif choice == "4":
            print("\nGoodbye.")
            break

        else:

            print(
                "\nInvalid choice."
            )


if __name__ == "__main__":

    main()