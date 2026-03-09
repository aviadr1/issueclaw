"""Tests for image downloading and URL rewriting in markdown content."""

import re
from pathlib import Path

from issueclaw.image_sync import rewrite_image_urls, IMAGE_URL_PATTERN


def test_rewrite_image_urls_replaces_linear_uploads():
    """INVARIANT: Linear upload URLs are rewritten to local relative paths."""
    content = 'Some text\n![image.png](https://uploads.linear.app/org-id/asset-id/file-id)\nMore text'
    result, urls = rewrite_image_urls(content, "linear/teams/AI/issues")
    assert "uploads.linear.app" not in result
    assert "linear/teams/AI/issues" not in result  # path should be relative
    assert len(urls) == 1
    assert urls[0][0] == "https://uploads.linear.app/org-id/asset-id/file-id"
    # The local path should be in _assets/ subdirectory
    assert "_assets/" in urls[0][1]


def test_rewrite_image_urls_preserves_non_linear_images():
    """INVARIANT: Non-Linear image URLs are left unchanged."""
    content = '![photo](https://example.com/photo.jpg)\n![linear](https://uploads.linear.app/a/b/c)'
    result, urls = rewrite_image_urls(content, "linear/teams/AI/issues")
    assert "https://example.com/photo.jpg" in result
    assert len(urls) == 1  # only the linear URL
    assert urls[0][0] == "https://uploads.linear.app/a/b/c"


def test_rewrite_image_urls_handles_no_images():
    """INVARIANT: Content without images is returned unchanged."""
    content = "Just plain text\nNo images here"
    result, urls = rewrite_image_urls(content, "linear/teams/AI/issues")
    assert result == content
    assert urls == []


def test_rewrite_image_urls_generates_unique_filenames():
    """INVARIANT: Multiple images get unique filenames."""
    content = (
        '![a](https://uploads.linear.app/org/a1/f1)\n'
        '![b](https://uploads.linear.app/org/a2/f2)\n'
    )
    result, urls = rewrite_image_urls(content, "linear/teams/AI/issues")
    assert len(urls) == 2
    # Filenames should be different
    assert urls[0][1] != urls[1][1]


def test_rewrite_preserves_alt_text():
    """INVARIANT: Alt text in image markdown is preserved."""
    content = '![My Screenshot](https://uploads.linear.app/org/a/f)'
    result, urls = rewrite_image_urls(content, "linear/teams/AI/issues")
    assert "![My Screenshot](" in result


def test_image_url_pattern_matches_linear_uploads():
    """INVARIANT: Pattern matches Linear upload URLs in markdown image syntax."""
    text = '![image.png](https://uploads.linear.app/6872ccce-2412/8461c137-62fc/1b784746-94f1)'
    matches = IMAGE_URL_PATTERN.findall(text)
    assert len(matches) == 1


def test_rewrite_uses_file_id_for_path():
    """INVARIANT: Local filename is derived from the URL's file-id component."""
    content = '![screen.png](https://uploads.linear.app/org-uuid/asset-uuid/abc123def456)'
    result, urls = rewrite_image_urls(content, "linear/teams/AI/issues")
    # The local path should contain the file-id for uniqueness
    assert "abc123def456" in urls[0][1]
