"""
Module de gestion des médias : téléchargement asynchrone des photos
et organisation du stockage local par listing.
"""
import os
import json
import asyncio
import uuid
import re
import mimetypes
import unicodedata
from pathlib import Path
from datetime import datetime
from typing import Optional

import httpx
from fastapi import UploadFile

MEDIA_BASE_DIR = Path("static/media")


def get_listing_media_dir(listing_id: int) -> Path:
    """Returns the directory path for a listing's media files."""
    media_dir = MEDIA_BASE_DIR / str(listing_id)
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir


async def download_single_image(
    client: httpx.AsyncClient,
    url: str,
    dest_path: Path,
) -> Optional[Path]:
    """
    Downloads a single image from a URL and saves it to dest_path.
    Returns the resolved Path on success, None on failure.
    """
    try:
        referer = "https://www.leboncoin.fr/"
        url_lower = url.lower()
        if any(d in url_lower for d in ["seloger", "poliris", "aviv", "slstatic"]):
            referer = "https://www.seloger.com/"
        elif "lefigaro" in url_lower:
            referer = "https://immobilier.lefigaro.fr/"
        elif "bienici" in url_lower:
            referer = "https://www.bienici.com/"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": referer,
        }
        response = await client.get(url, headers=headers, timeout=30.0, follow_redirects=True)
        response.raise_for_status()

        # Determine extension from content-type or URL
        content_type = response.headers.get("content-type", "image/jpeg")
        if "webp" in content_type:
            ext = ".webp"
        elif "png" in content_type:
            ext = ".png"
        else:
            ext = ".jpg"

        # Add extension if not already present
        if not dest_path.suffix:
            actual_path = dest_path.with_suffix(ext)
        else:
            actual_path = dest_path

        # Clean up existing files with different extensions under the same basename
        for alternative_ext in [".jpg", ".jpeg", ".webp", ".png"]:
            if alternative_ext != ext:
                sibling_path = dest_path.with_suffix(alternative_ext)
                try:
                    if sibling_path.exists():
                        sibling_path.unlink()
                except Exception as cleanup_err:
                    print(f"[Media] Échec suppression fichier obsolète {sibling_path}: {cleanup_err}")

        actual_path.write_bytes(response.content)
        return actual_path

    except Exception as e:
        print(f"[Media] Échec téléchargement {url}: {e}")
        return None


async def download_listing_photos(
    listing_id: int,
    photo_urls: list[str],
    max_photos: int = 30,
) -> list[str]:
    """
    Downloads photos for a listing in parallel.

    Args:
        listing_id: The ID of the listing (used for directory organization)
        photo_urls: List of original photo URLs to download
        max_photos: Maximum number of photos to download

    Returns:
        List of local relative paths for successfully downloaded photos
        (e.g., ["static/media/42/photo_0.webp", "static/media/42/photo_1.webp"])
    """
    if not photo_urls:
        return []

    media_dir = get_listing_media_dir(listing_id)
    urls_to_download = photo_urls[:max_photos]
    local_paths = []

    print(f"[Media] Téléchargement de {len(urls_to_download)} photos pour listing #{listing_id}...")

    async with httpx.AsyncClient() as client:
        tasks = []
        for i, url in enumerate(urls_to_download):
            dest_path = media_dir / f"photo_{i}"
            tasks.append(download_single_image(client, url, dest_path))

        results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        if isinstance(result, Path):
            # Return web-accessible path
            local_paths.append(str(result).replace("\\", "/"))
        else:
            print(f"[Media] Photo {i} échouée pour listing #{listing_id}")

    print(f"[Media] {len(local_paths)}/{len(urls_to_download)} photos téléchargées pour listing #{listing_id}")
    return local_paths


def get_local_photos(listing_id: int) -> list[str]:
    """
    Returns a list of all locally stored photo paths for a given listing.
    """
    media_dir = MEDIA_BASE_DIR / str(listing_id)
    if not media_dir.exists():
        return []

    photos = []
    for ext in ["*.jpg", "*.jpeg", "*.webp", "*.png"]:
        photos.extend(sorted(media_dir.glob(ext)))

    # Return as web-accessible paths
    return [str(p).replace("\\", "/") for p in sorted(set(photos), key=lambda x: x.name)]


def photos_to_json(paths: list[str]) -> str:
    """Serializes a list of paths to a JSON string for DB storage."""
    return json.dumps(paths)


def json_to_photos(json_str: Optional[str]) -> list[str]:
    """Deserializes a JSON string from DB to a list of paths."""
    if not json_str:
        return []
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return []


async def save_uploaded_photos(listing_id: int, files: list[UploadFile]) -> list[str]:
    """
    Saves uploaded files to the listing's media directory.
    Returns a list of local relative paths for successfully saved photos.
    """
    if not files:
        return []

    media_dir = get_listing_media_dir(listing_id)
    local_paths = []

    # Get maximum existing index to prevent overwriting 'photo_0.jpg' etc.
    existing_photos = get_local_photos(listing_id)
    start_index = len(existing_photos)

    for i, file in enumerate(files):
        # We assume the file is an image. We can guess the extension.
        ext = Path(file.filename).suffix.lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            ext = ".jpg"  # fallback

        dest_path = media_dir / f"photo_upload_{start_index + i}{ext}"
        try:
            content = await file.read()
            dest_path.write_bytes(content)
            local_paths.append(str(dest_path).replace("\\", "/"))
        except Exception as e:
            print(f"[Media] Failed to save uploaded photo {file.filename}: {e}")

    return local_paths


def compute_image_dhash(image_path: str, hash_size: int = 8) -> Optional[str]:
    """
    Computes a difference hash (dHash) for an image.
    dHash is very robust to scaling, aspect ratio changes, brightness/contrast changes.
    """
    try:
        from PIL import Image
        if not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
            return None
        with Image.open(image_path) as img:
            try:
                resample_filter = Image.Resampling.BILINEAR
            except AttributeError:
                resample_filter = Image.BILINEAR
                
            img = img.convert("L").resize((hash_size + 1, hash_size), resample_filter)
            
            # Compare adjacent horizontal pixels
            difference = []
            for y in range(hash_size):
                for x in range(hash_size):
                    pixel_left = img.getpixel((x, y))
                    pixel_right = img.getpixel((x + 1, y))
                    difference.append(pixel_left > pixel_right)
            
            # Convert to hex string
            decimal_value = 0
            hex_string = []
            for index, value in enumerate(difference):
                if value:
                    decimal_value += 2 ** (index % 8)
                if (index % 8) == 7:
                    hex_string.append(hex(decimal_value)[2:].zfill(2))
                    decimal_value = 0
            return "".join(hex_string)
    except Exception as e:
        print(f"[Media] Error computing dhash for {image_path}: {e}")
        return None


def compute_image_ahash(image_path: str, hash_size: int = 8) -> Optional[str]:
    """
    Computes an average hash (aHash) for an image.
    """
    try:
        from PIL import Image
        if not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
            return None
        with Image.open(image_path) as img:
            try:
                resample_filter = Image.Resampling.BILINEAR
            except AttributeError:
                resample_filter = Image.BILINEAR
                
            img = img.convert("L").resize((hash_size, hash_size), resample_filter)
            
            # Calculate average
            pixels = list(img.getdata())
            avg = sum(pixels) / len(pixels)
            
            # Build bits
            bits = [pixel > avg for pixel in pixels]
            
            # Convert to hex string
            decimal_value = 0
            hex_string = []
            for index, value in enumerate(bits):
                if value:
                    decimal_value += 2 ** (index % 8)
                if (index % 8) == 7:
                    hex_string.append(hex(decimal_value)[2:].zfill(2))
                    decimal_value = 0
            return "".join(hex_string)
    except Exception as e:
        print(f"[Media] Error computing ahash for {image_path}: {e}")
        return None


def calculate_images_similarity(path1: str, path2: str) -> float:
    """
    Calculates similarity percentage between two images using dHash and aHash.
    Returns a score between 0.0 and 100.0.
    """
    if not os.path.exists(path1) or not os.path.exists(path2):
        return 0.0

    # If exact same size, they are 100% identical
    if os.path.getsize(path1) == os.path.getsize(path2):
        return 100.0

    d1 = compute_image_dhash(path1)
    d2 = compute_image_dhash(path2)
    a1 = compute_image_ahash(path1)
    a2 = compute_image_ahash(path2)

    if not d1 or not d2 or not a1 or not a2:
        return 0.0

    # Hamming distance for 64-bit hashes using fast integer XOR and bit_count
    # ~16x faster than iterating character-by-character over hex strings
    def hamming_distance(h1, h2):
        return (int(h1, 16) ^ int(h2, 16)).bit_count()

    dist_d = hamming_distance(d1, d2)
    dist_a = hamming_distance(a1, a2)

    sim_d = (64 - dist_d) / 64 * 100
    sim_a = (64 - dist_a) / 64 * 100

    return (sim_d + sim_a) / 2.0


ALLOWED_ATTACHMENT_EXTENSIONS = {
    # Documents
    ".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt",
    # Images
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg", ".tiff",
    # Spreadsheets
    ".xls", ".xlsx", ".ods", ".csv",
    # Archives / other
    ".zip", ".rar", ".7z"
}


def get_listing_attachments_dir(listing_id: int) -> Path:
    """Returns the directory path for a listing's attachments."""
    att_dir = MEDIA_BASE_DIR / str(listing_id) / "attachments"
    att_dir.mkdir(parents=True, exist_ok=True)
    return att_dir


def sanitize_filename(name: str) -> str:
    """Sanitizes filename keeping only ascii alphanumeric characters, dashes, underscores and dots."""
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_name = nfkd.encode('ASCII', 'ignore').decode('ASCII')
    clean = re.sub(r'[^a-zA-Z0-9\.\-_]', '_', ascii_name)
    clean = re.sub(r'_+', '_', clean)
    return clean.strip('._')


async def save_listing_attachment_file(
    listing_id: int,
    file: UploadFile
) -> tuple[str, str, str, int, str]:
    """
    Saves an uploaded attachment file for a listing.
    Returns a tuple: (saved_filename, original_filename, relative_web_path, file_size, mime_type).
    """
    orig_name = file.filename or "document"
    orig_name = os.path.basename(orig_name)
    ext = Path(orig_name).suffix.lower()
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        ext = ext if ext else ".pdf"

    safe_base = sanitize_filename(Path(orig_name).stem)
    unique_suffix = uuid.uuid4().hex[:8]
    saved_filename = f"{safe_base}_{unique_suffix}{ext}"

    att_dir = get_listing_attachments_dir(listing_id)
    dest_path = att_dir / saved_filename

    content = await file.read()
    dest_path.write_bytes(content)
    file_size = len(content)

    mime_type = file.content_type
    if not mime_type or mime_type == "application/octet-stream":
        mime_type, _ = mimetypes.guess_type(saved_filename)
    if not mime_type:
        mime_type = "application/octet-stream"

    web_path = f"static/media/{listing_id}/attachments/{saved_filename}"
    return saved_filename, orig_name, web_path, file_size, mime_type


def delete_attachment_file(file_path: str) -> bool:
    """
    Safely deletes an attachment file from the disk given its relative web path.
    """
    try:
        if not file_path:
            return False
        normalized = file_path.strip().lstrip("/\\").replace("\\", "/")
        if not normalized.startswith("static/media/"):
            return False
        full_path = Path(normalized)
        if full_path.exists() and full_path.is_file():
            full_path.unlink()
            return True
    except Exception as e:
        print(f"[Media] Error deleting attachment file {file_path}: {e}")
    return False


async def save_floorplans_as_attachments(
    listing_id: int,
    floorplan_urls: list[str],
    db,
    client: Optional[httpx.AsyncClient] = None,
) -> list:
    """
    Downloads floorplan images and creates ListingAttachment records with file_type='plan'.
    Avoids duplicate attachments if a floorplan with the same URL/title was already imported.
    """
    from app.models import ListingAttachment

    if not floorplan_urls:
        return []

    created = []
    att_dir = get_listing_attachments_dir(listing_id)
    
    # Check existing attachments to prevent duplicates
    existing_att_titles = {
        att.title for att in db.query(ListingAttachment).filter(
            ListingAttachment.listing_id == listing_id,
            ListingAttachment.file_type == "plan"
        ).all()
    }

    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        close_client = True

    try:
        for i, url in enumerate(floorplan_urls):
            title = f"Plan {i + 1}"
            if title in existing_att_titles:
                continue

            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://www.seloger.com/",
                }
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    continue

                content_type = resp.headers.get("content-type", "image/jpeg")
                if "webp" in content_type:
                    ext = ".webp"
                elif "png" in content_type:
                    ext = ".png"
                else:
                    ext = ".jpg"

                unique_suffix = uuid.uuid4().hex[:8]
                saved_filename = f"plan_{i+1}_{unique_suffix}{ext}"
                dest_path = att_dir / saved_filename
                dest_path.write_bytes(resp.content)

                web_path = f"static/media/{listing_id}/attachments/{saved_filename}"
                file_size = len(resp.content)
                mime_type = content_type.split(";")[0].strip()

                att = ListingAttachment(
                    listing_id=listing_id,
                    filename=saved_filename,
                    original_filename=f"plan_{i+1}{ext}",
                    file_path=web_path,
                    file_type="plan",
                    title=title,
                    description="Plan du bien extrait automatiquement",
                    file_size=file_size,
                    mime_type=mime_type,
                    created_by="scraper"
                )
                db.add(att)
                created.append(att)
                existing_att_titles.add(title)
            except Exception as e:
                print(f"[Media] Failed downloading floorplan {url} for listing {listing_id}: {e}")

        if created:
            db.commit()
            for att in created:
                db.refresh(att)
    finally:
        if close_client:
            await client.aclose()

    return created


def format_bytes_human(num_bytes: int) -> str:
    """Formats bytes into human readable string (KB, MB, GB)."""
    if num_bytes < 1024:
        return f"{num_bytes} o"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} Ko"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} Mo"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} Go"


def get_dir_size_and_count(dir_path: Path) -> tuple[int, int]:
    """Calculates total size in bytes and file count for a directory."""
    total_size = 0
    file_count = 0
    if not dir_path.exists():
        return 0, 0
    for root, _, files in os.walk(dir_path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                if os.path.isfile(fp) and not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
                    file_count += 1
            except (OSError, PermissionError):
                pass
    return total_size, file_count


def get_storage_metrics(db) -> dict:
    """
    Computes storage analytics for static/media directory and database references.
    Identifies total size, orphaned listing folders, rejected listings with local media,
    and orphaned attachments.
    """
    from app.models import Listing, ListingStatus, ListingAttachment

    media_base = MEDIA_BASE_DIR
    if not media_base.exists():
        media_base.mkdir(parents=True, exist_ok=True)

    total_media_size, total_media_files = get_dir_size_and_count(media_base)

    # Fetch DB IDs
    existing_listing_ids = set(r[0] for r in db.query(Listing.id).all())
    rejected_listing_ids = set(
        r[0]
        for r in db.query(Listing.id)
        .filter(Listing.status.in_([ListingStatus.REJECTED, "rejetee"]))
        .all()
    )

    valid_attachments = set()
    for (fpath,) in db.query(ListingAttachment.file_path).filter(ListingAttachment.file_path != None).all():
        if fpath:
            norm = fpath.strip().lstrip("/\\").replace("\\", "/")
            valid_attachments.add(norm)

    orphaned_dirs = []
    orphaned_dirs_size = 0
    orphaned_dirs_files = 0

    rejected_with_media = []
    rejected_media_size = 0
    rejected_media_files = 0

    orphaned_attachments = []
    orphaned_attachments_size = 0

    zero_byte_files_count = 0

    # Inspect media directories
    for child in media_base.iterdir():
        if not child.is_dir():
            continue
        # Skip special app assets directory
        if child.name in ("app", "tmp"):
            continue

        if child.name.isdigit():
            lid = int(child.name)
            dir_size, file_count = get_dir_size_and_count(child)

            if lid not in existing_listing_ids:
                orphaned_dirs.append(lid)
                orphaned_dirs_size += dir_size
                orphaned_dirs_files += file_count
            elif lid in rejected_listing_ids:
                rejected_with_media.append(lid)
                rejected_media_size += dir_size
                rejected_media_files += file_count
            else:
                # Listing is active/new/disappeared — check attachments directory
                att_dir = child / "attachments"
                if att_dir.exists() and att_dir.is_dir():
                    for att_file in att_dir.iterdir():
                        if att_file.is_file():
                            web_rel = f"static/media/{lid}/attachments/{att_file.name}"
                            if web_rel not in valid_attachments:
                                orphaned_attachments.append(str(att_file))
                                try:
                                    orphaned_attachments_size += att_file.stat().st_size
                                except OSError:
                                    pass

                # Check for 0-byte photos
                for f in child.iterdir():
                    if f.is_file():
                        try:
                            if f.stat().st_size == 0:
                                zero_byte_files_count += 1
                        except OSError:
                            pass

    reclaimable_size = orphaned_dirs_size + rejected_media_size + orphaned_attachments_size
    reclaimable_files = orphaned_dirs_files + rejected_media_files + len(orphaned_attachments) + zero_byte_files_count

    return {
        "total_media_size_bytes": total_media_size,
        "total_media_size_human": format_bytes_human(total_media_size),
        "total_media_files": total_media_files,
        "orphaned_dirs_count": len(orphaned_dirs),
        "orphaned_dirs_size_bytes": orphaned_dirs_size,
        "orphaned_dirs_size_human": format_bytes_human(orphaned_dirs_size),
        "rejected_listings_count": len(rejected_with_media),
        "rejected_media_size_bytes": rejected_media_size,
        "rejected_media_size_human": format_bytes_human(rejected_media_size),
        "orphaned_attachments_count": len(orphaned_attachments),
        "orphaned_attachments_size_bytes": orphaned_attachments_size,
        "orphaned_attachments_size_human": format_bytes_human(orphaned_attachments_size),
        "zero_byte_files_count": zero_byte_files_count,
        "reclaimable_size_bytes": reclaimable_size,
        "reclaimable_size_human": format_bytes_human(reclaimable_size),
        "reclaimable_files_count": reclaimable_files,
    }


def purge_orphaned_and_rejected_media(db, purge_orphaned: bool = True, purge_rejected: bool = False) -> dict:
    """
    Purges orphaned listing media directories and/or local photos and attachments
    of rejected listings to reclaim disk space while preserving descriptive metadata.
    """
    import shutil
    from app.models import Listing, ListingStatus, ListingAttachment

    media_base = MEDIA_BASE_DIR
    if not media_base.exists():
        return {
            "freed_bytes": 0,
            "freed_human": "0 o",
            "deleted_files_count": 0,
            "purged_orphaned_dirs": 0,
            "purged_rejected_listings": 0,
            "purged_orphaned_attachments": 0,
        }

    freed_bytes = 0
    deleted_files_count = 0
    purged_orphaned_dirs = 0
    purged_rejected_listings = 0
    purged_orphaned_attachments = 0

    existing_listing_ids = set(r[0] for r in db.query(Listing.id).all())
    rejected_listings = db.query(Listing).filter(Listing.status.in_([ListingStatus.REJECTED, "rejetee"])).all()
    rejected_listing_map = {l.id: l for l in rejected_listings}

    valid_attachments = set()
    for (fpath,) in db.query(ListingAttachment.file_path).filter(ListingAttachment.file_path != None).all():
        if fpath:
            norm = fpath.strip().lstrip("/\\").replace("\\", "/")
            valid_attachments.add(norm)

    for child in list(media_base.iterdir()):
        if not child.is_dir() or child.name in ("app", "tmp"):
            continue

        if child.name.isdigit():
            lid = int(child.name)

            # Case 1: Orphaned directory (listing was deleted from DB)
            if lid not in existing_listing_ids:
                if purge_orphaned:
                    dir_size, file_count = get_dir_size_and_count(child)
                    try:
                        shutil.rmtree(child, ignore_errors=True)
                        freed_bytes += dir_size
                        deleted_files_count += file_count
                        purged_orphaned_dirs += 1
                        print(f"[Storage Maintenance] Purged orphaned media directory #{lid} ({format_bytes_human(dir_size)})")
                    except Exception as e:
                        print(f"[Storage Maintenance] Failed to remove orphaned directory {child}: {e}")

            # Case 2: Rejected listing with local media
            elif lid in rejected_listing_map and purge_rejected:
                dir_size, file_count = get_dir_size_and_count(child)
                try:
                    shutil.rmtree(child, ignore_errors=True)
                    freed_bytes += dir_size
                    deleted_files_count += file_count
                    purged_rejected_listings += 1

                    # Update listing in DB to clear local photo array
                    listing = rejected_listing_map[lid]
                    listing.photos_local = "[]"

                    # Delete attachment records for this rejected listing
                    db.query(ListingAttachment).filter(ListingAttachment.listing_id == lid).delete()
                    print(f"[Storage Maintenance] Purged local media for rejected listing #{lid} ({format_bytes_human(dir_size)})")
                except Exception as e:
                    print(f"[Storage Maintenance] Failed to purge rejected listing media #{lid}: {e}")

            # Case 3: Existing non-rejected listing -> clean orphaned attachments and 0-byte files
            elif purge_orphaned:
                att_dir = child / "attachments"
                if att_dir.exists() and att_dir.is_dir():
                    for att_file in list(att_dir.iterdir()):
                        if att_file.is_file():
                            web_rel = f"static/media/{lid}/attachments/{att_file.name}"
                            if web_rel not in valid_attachments:
                                try:
                                    fsize = att_file.stat().st_size
                                    att_file.unlink()
                                    freed_bytes += fsize
                                    deleted_files_count += 1
                                    purged_orphaned_attachments += 1
                                except Exception as e:
                                    print(f"[Storage Maintenance] Failed to delete orphaned attachment {att_file}: {e}")

                for f in list(child.iterdir()):
                    if f.is_file():
                        try:
                            if f.stat().st_size == 0:
                                f.unlink()
                                deleted_files_count += 1
                        except Exception:
                            pass

    db.commit()

    return {
        "freed_bytes": freed_bytes,
        "freed_human": format_bytes_human(freed_bytes),
        "deleted_files_count": deleted_files_count,
        "purged_orphaned_dirs": purged_orphaned_dirs,
        "purged_rejected_listings": purged_rejected_listings,
        "purged_orphaned_attachments": purged_orphaned_attachments,
    }



