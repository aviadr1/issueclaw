"""Publish a file to a public-by-URL S3 bucket and prove the public URL serves its bytes.

The caller has already assumed an upload role (the workflow's OIDC step); this uses
the AWS CLI with those ambient credentials and never handles a key itself.
"""

import hashlib
import subprocess
from pathlib import Path

CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".html": "text/html; charset=utf-8",
}


def content_type(path: Path) -> str:
    try:
        return CONTENT_TYPES[path.suffix.lower()]
    except KeyError:
        raise ValueError(f"Not a publishable media type: {path.name}") from None


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put(path, bucket, key, public_base, kind=None, run=subprocess.run, get=None):
    """Upload `path` to s3://bucket/key and return its verified public URL."""
    if not public_base.startswith("https://"):
        raise ValueError("Media hosting requires HTTPS")
    if get is None:
        import httpx

        get = httpx.get
    expected = digest(path.read_bytes())
    run(
        [
            "aws",
            "s3",
            "cp",
            str(path),
            f"s3://{bucket}/{key}",
            "--content-type",
            kind or content_type(path),
            "--only-show-errors",
        ],
        check=True,
        timeout=300,
    )
    url = public_base.rstrip("/") + "/" + key
    response = get(url, timeout=60)
    response.raise_for_status()
    if digest(response.content) != expected:
        raise ValueError(f"Hosted file differs from {path.name}")
    return url
