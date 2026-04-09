"""Download Linear upload images and rewrite markdown URLs to local paths."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

# Matches markdown image syntax with uploads.linear.app URLs
IMAGE_URL_PATTERN = re.compile(r"!\[([^\]]*)\]\((https://uploads\.linear\.app/[^)]+)\)")


def rewrite_image_urls(
    content: str, entity_dir: str
) -> tuple[str, list[tuple[str, str]]]:
    """Rewrite Linear upload image URLs in markdown to local relative paths.

    Args:
        content: Markdown content that may contain image references.
        entity_dir: The directory path of the entity file (e.g. "linear/teams/AI/issues").

    Returns:
        Tuple of (rewritten_content, list of (remote_url, local_repo_path) pairs).
        The local_repo_path is relative to the repo root.
    """
    downloads: list[tuple[str, str]] = []

    def _replace(match: re.Match) -> str:
        alt_text = match.group(1)
        url = match.group(2)

        # Extract file-id from URL for a stable filename
        # URL format: https://uploads.linear.app/{org-id}/{asset-id}/{file-id}
        parts = url.rstrip("/").split("/")
        file_id = parts[-1] if parts else "image"

        # Determine extension from alt text or default to .png
        ext = PurePosixPath(alt_text).suffix if "." in alt_text else ".png"
        local_filename = f"{file_id}{ext}"

        # Store in _assets/ directory next to the entity files
        local_repo_path = f"{entity_dir}/_assets/{local_filename}"

        # Markdown reference is relative from the .md file's directory
        relative_ref = f"_assets/{local_filename}"

        downloads.append((url, local_repo_path))
        return f"![{alt_text}]({relative_ref})"

    rewritten = IMAGE_URL_PATTERN.sub(_replace, content)
    return rewritten, downloads
