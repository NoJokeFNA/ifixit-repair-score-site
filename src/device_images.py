"""Public iFixit image metadata and a same-origin thumbnail cache."""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)
CDN = "guide-images.cdn.ifixit.com"


def image_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.netloc == CDN and parsed.path.startswith("/igi/") else None


def device_image(value, source):
    if not isinstance(value, dict) or not image_url(value.get("thumbnail")):
        return None
    return {
        "image_id": value.get("id"),
        "thumbnail": image_url(value.get("thumbnail")),
        "detail": image_url(value.get("200x150")) or image_url(value["thumbnail"]),
        "large": image_url(value.get("large")),
        "original": image_url(value.get("original")),
        "source": source,
    }


def build_image_manifest(devices, previous, output_directory, *, session_factory=requests.Session):
    output_directory = Path(output_directory)
    target = output_directory / "assets/devices"
    target.mkdir(parents=True, exist_ok=True)
    mapping = {}
    unique = {}
    for device in devices:
        image = device.get("image")
        if not isinstance(image, dict) or not image_url(image.get("thumbnail")):
            continue
        image = dict(image)
        old = previous.get(device["title"], {}) if isinstance(previous, dict) else {}
        old_path = old.get("local", "")
        if (
            image.get("image_id") is not None
            and image.get("image_id") == old.get("image_id")
            and image.get("thumbnail") == old.get("thumbnail")
            and old_path.startswith("assets/devices/")
        ):
            candidate = (output_directory / old_path).resolve()
            if candidate.is_relative_to(target.resolve()) and candidate.is_file():
                image["local"] = old_path
        mapping[device["title"]] = image
        if image.get("image_id") is not None:
            unique.setdefault(str(image["image_id"]), image)

    def download(item):
        identifier, image = item
        if image.get("local") or not identifier.isdecimal():
            return identifier, image.get("local")
        try:
            with session_factory() as session:
                response = session.get(image.get("detail") or image["thumbnail"], timeout=30)
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
                suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(content_type)
                if not suffix or not response.content or len(response.content) > 2_000_000:
                    raise ValueError("Invalid iFixit thumbnail response")
                path = target / (identifier + suffix)
                temporary = path.with_suffix(path.suffix + ".tmp")
                temporary.write_bytes(response.content)
                os.replace(temporary, path)
                return identifier, path.relative_to(output_directory).as_posix()
        except (requests.RequestException, OSError, ValueError) as error:
            logger.warning("Thumbnail unavailable for image %s: %s", identifier, error)
            return identifier, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = dict(pool.map(download, unique.items()))
    for image in mapping.values():
        image["local"] = paths.get(str(image.get("image_id")))
    return mapping
