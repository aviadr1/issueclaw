"""The report must account for handoffs, not silently lose their visuals."""

import json

import pytest

from issueclaw.design_media import discover_routes, select_states, validate_report


def test_routes_use_exact_static_entry_and_changed_dev_routes():
    routes = discover_routes(
        "https://preview.example.test/pr-42/",
        "Open https://preview.example.test/pr-42/mobile-demo/index.html; source is `apps/app/public/mobile-demo/index.html`.",
        [
            "apps/app/public/mobile-demo/index.html",
            "apps/app/src/routes/_app/dev.showcase.tsx",
        ],
    )
    assert set(routes) == {
        "https://preview.example.test/pr-42/mobile-demo/index.html",
        "https://preview.example.test/pr-42/dev/showcase",
    }


def test_state_selection_preserves_description_only_inventory_without_capturing_it():
    states = [
        {"label": "01 Default", "described_only": False},
        {"label": "02 Checkout DESC", "described_only": True},
        {"label": "03 Empty shelf", "described_only": False},
        {"label": "04 Join failed", "described_only": False},
    ]
    assert [s["label"] for s in select_states(states, 3)] == [
        "01 Default",
        "03 Empty shelf",
        "04 Join failed",
    ]


def test_report_cannot_omit_captured_pr_or_embed_unpublished_media(tmp_path):
    manifest = {
        "prs": [{"url": "https://github.com/acme/app/pull/42"}],
        "captures": [
            {
                "id": "42-feed",
                "pr_url": "https://github.com/acme/app/pull/42",
                "file": "feed.png",
                "sha256": "abc",
            }
        ],
    }
    plan = {
        "sources": [{"pr_url": manifest["prs"][0]["url"], "media_ids": ["42-feed"]}]
    }
    with pytest.raises(ValueError, match="hosted"):
        validate_report(manifest, plan, "![Feed](file.png)")
    manifest["captures"][0]["hosted_url"] = "https://media.example.test/feed.png"
    with pytest.raises(ValueError, match="embedded"):
        validate_report(manifest, plan, "A report without images")
    with pytest.raises(ValueError, match="accounted"):
        validate_report(manifest, {"sources": []}, "A report without coverage")
    validate_report(manifest, plan, "![Feed](https://media.example.test/feed.png)")
    with pytest.raises(ValueError, match="embedded"):
        validate_report(manifest, plan, "[Feed](https://media.example.test/feed.png)")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))


def test_exclusion_needs_visible_reason_and_unknown_media_is_rejected():
    url = "https://github.com/acme/app/pull/42"
    manifest = {"prs": [{"url": url}], "captures": []}
    plan = {
        "sources": [
            {"pr_url": url, "exclusion_reason": "Preview requires authentication"}
        ]
    }
    with pytest.raises(ValueError, match="visible"):
        validate_report(manifest, plan, "Everything is covered")
    validate_report(manifest, plan, f"[{url}]({url}): Preview requires authentication")
    with pytest.raises(ValueError, match="unknown"):
        validate_report(
            manifest, {"sources": [{"pr_url": url, "media_ids": ["fake"]}]}, ""
        )
