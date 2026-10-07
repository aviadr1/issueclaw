"""Real Chromium exercises screen selection and output; only GitHub is replaced."""

import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from issueclaw import design_media

pytestmark = pytest.mark.browser


@pytest.mark.asyncio
async def test_handoff_clicks_render_distinct_states_and_description_is_not_a_capture(
    tmp_path, monkeypatch
):
    playwright = pytest.importorskip("playwright.async_api")
    html = b"""<body><button onclick="select('feed','green')">01 Feed</button>
    <button onclick="select('product','blue')">02 Product</button>
    <button>03 Checkout <span class="tag desc">DESC</span></button>
    <div class="device-wrap" style="width:300px;height:400px;background:red">initial</div>
    <script>function select(id,color){history.replaceState(null,'','#/'+id);
    const d=document.querySelector('.device-wrap');d.textContent=id;d.style.background=color}</script></body>"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<h1>Legacy handoff</h1><button>Feed</button>"
                if self.path == "/legacy"
                else html
            )

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    monkeypatch.setattr(
        design_media,
        "inventory",
        lambda config: [
            {
                "url": "https://github.com/acme/app/pull/42",
                "number": 42,
                "repository": "acme/app",
                "head_sha": "head",
                "routes": [url, url + "legacy"],
            }
        ],
    )
    try:
        async with playwright.async_playwright() as pw:
            browser = await pw.chromium.launch(
                executable_path=os.getenv("DESIGN_BROWSER_EXECUTABLE")
            )
            try:
                manifest = await design_media.capture(
                    {
                        "preview_hosts": ["127.0.0.1"],
                        "states_per_preview": 3,
                        "record_walkthroughs": True,
                    },
                    tmp_path,
                    browser,
                )
            finally:
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert manifest["previews"][0]["status"] == "captured"
    assert manifest["previews"][1]["status"] == "unsupported"
    assert "page loaded" in manifest["previews"][1]["error"].lower()
    assert len(manifest["previews"][0]["screens"]) == 3
    images = [c for c in manifest["captures"] if c["kind"] != "video"]
    assert [c["state_url"].split("#/")[-1] for c in images] == [
        "feed",
        "product",
    ]
    assert len({c["sha256"] for c in images}) == 2
    videos = [c for c in manifest["captures"] if c["kind"] == "video"]
    assert len(videos) == 1
    assert (tmp_path / videos[0]["file"]).stat().st_size > 0
    for media in images:
        data = (tmp_path / media["file"]).read_bytes()
        assert data.startswith(b"\x89PNG")
        assert hashlib.sha256(data).hexdigest() == media["sha256"]
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest
