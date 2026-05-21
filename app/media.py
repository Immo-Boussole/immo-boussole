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
) -> Optional[Path]:
    """
    Downloads a single image from a URL and saves it to dest_path.
    Returns the resolved Path on success, None on failure.
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

    # Hamming distance for 64-bit hashes
    def hamming_distance(h1, h2):
        return sum(bin(int(c1, 16) ^ int(c2, 16)).count('1') for c1, c2 in zip(h1, h2))

    dist_d = hamming_distance(d1, d2)
    dist_a = hamming_distance(a1, a2)

    sim_d = (64 - dist_d) / 64 * 100
    sim_a = (64 - dist_a) / 64 * 100

    return (sim_d + sim_a) / 2.0

