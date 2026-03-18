"""
Module de gestion des médias : téléchargement asynchrone des photos
et organisation du stockage local par listing.
"""
import os
import json
import asyncio
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
) -> bool:
    """
    Downloads a single image from a URL and saves it to dest_path.
    Returns True on success, False on failure.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.leboncoin.fr/",
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
            dest_path = dest_path.with_suffix(ext)

        dest_path.write_bytes(response.content)
        return True

    except Exception as e:
        print(f"[Media] Échec téléchargement {url}: {e}")
        return False


async def download_listing_photos(
    listing_id: int,
    photo_urls: list[str],
    max_photos: int = 10,
) -> list[str]:
    """
    Downloads photos for a listing in parallel.

    Args:
        listing_id: The ID of the listing (used for directory organization)
        photo_urls: List of original photo URLs to download
        max_photos: Maximum number of photos to download

    Returns:
        List of local relative paths for successfully downloaded photos
        (e.g., ["static/media/42/photo_0.jpg", "static/media/42/photo_1.jpg"])
    """
    if not photo_urls:
        return []

    media_dir = get_listing_media_dir(listing_id)
    urls_to_download = photo_urls[:max_photos]
    local_paths = []

    print(f"[Media] Téléchargement de {len(urls_to_download)} photos pour listing #{listing_id}...")

    async with httpx.AsyncClient() as client:
        tasks = []
        dest_paths = []
        for i, url in enumerate(urls_to_download):
            dest_path = media_dir / f"photo_{i}"
            dest_paths.append(dest_path)
            tasks.append(download_single_image(client, url, dest_path))

        results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, (success, dest_path) in enumerate(zip(results, dest_paths)):
        if success is True:
            # Find the actual file (with extension added)
            for ext in [".jpg", ".webp", ".png"]:
                actual = dest_path.with_suffix(ext)
                if actual.exists():
                    # Return web-accessible path
                    local_paths.append(str(actual).replace("\\", "/"))
                    break
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
