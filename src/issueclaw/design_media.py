"""Collect handoff screens before report writing; validate media before publishing.

Only caller-configured preview hosts are browsed. Credentials stay in gh/AWS;
the browser gets no authenticated session and only clicks handoff screen rows.
"""

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from issueclaw.report_evidence import compact_discussions, gh_json


def discover_routes(base, text, files):
    """Prefer concrete handoff entrypoints over the deployment's app homepage."""
    base = base.rstrip("/") + "/"
    text = text.replace(base, "/")
    paths = set(re.findall(r"(?<![\w./])/(?:dev/[\w-]+|[\w/-]+/index\.html)", text))
    for filename in files:
        if "/public/" in filename and filename.endswith("/index.html"):
            paths.add("/" + filename.split("/public/", 1)[1])
        match = re.search(r"/routes/(?:[^/]+/)*dev\.([\w-]+)\.tsx$", filename)
        if match:
            paths.add("/dev/" + match[1])
    return sorted({base + path.lstrip("/") for path in paths}) or [base]


def select_states(states, limit):
    eligible = [s for s in states if not s["described_only"]]
    if len(eligible) <= limit:
        return eligible
    # Spread candidate captures across the whole handoff, not just its first group.
    return [
        eligible[round(i * (len(eligible) - 1) / (limit - 1))] for i in range(limit)
    ]


def validate_report(manifest, plan, markdown):
    """Every discovered PR needs embedded inspected media or a visible exclusion."""
    captures = {c["id"]: c for c in manifest["captures"]}
    sources = {s["pr_url"]: s for s in plan["sources"]}
    if len(sources) != len(plan["sources"]):
        raise ValueError("Duplicate source coverage")
    selected_images = 0
    for pr in manifest["prs"]:
        source = sources.get(pr["url"])
        if not source:
            raise ValueError(f"PR not accounted for: {pr['url']}")
        ids = source.get("media_ids", [])
        source_images = []
        if not ids:
            reason = source.get("exclusion_reason", "").strip()
            if not reason or reason not in markdown or pr["url"] not in markdown:
                raise ValueError(f"Exclusion must be visible: {pr['url']}")
        for media_id in ids:
            if media_id not in captures:
                raise ValueError(f"unknown media: {media_id}")
            media = captures[media_id]
            if media["pr_url"] != pr["url"]:
                raise ValueError(f"Media belongs to a different PR: {media_id}")
            url = media.get("hosted_url", "")
            if not url.startswith("https://"):
                raise ValueError(f"Media must be hosted: {media_id}")
            pattern = (
                (r"!?\[[^\]]*\]" if media.get("kind") == "video" else r"!\[[^\]]*\]")
                + r"\("
                + re.escape(url)
                + r"\)"
            )
            if not re.search(pattern, markdown):
                raise ValueError(f"Selected media must be embedded: {media_id}")
            if media.get("kind") != "video":
                selected_images += 1
                source_images.append(media)
        if ids:
            distinct = {
                m.get("sha256") or m.get("state_url") or m["id"] for m in source_images
            }
            available = {
                m.get("sha256") or m.get("state_url") or m["id"]
                for m in captures.values()
                if m["pr_url"] == pr["url"] and m.get("kind") != "video"
            }
            if len(distinct) < min(3, len(available)):
                reason = source.get("visual_limitation", "").strip()
                if not reason or reason not in markdown or pr["url"] not in markdown:
                    raise ValueError(
                        f"Three distinct images or a visible limitation required: {pr['url']}"
                    )
            for media in source_images:
                state_url = media.get("state_url")
                if state_url and not re.search(
                    r"(?<!!)\[[^\]]+\]\(" + re.escape(state_url) + r"\)", markdown
                ):
                    raise ValueError(
                        f"Selected state needs a prototype link: {media['id']}"
                    )
    if manifest["captures"] and not selected_images:
        raise ValueError("A visual report cannot exclude every captured image")


def commits(repo, number):
    """GraphQL pagination avoids gh pr view's 100 and REST's 250 commit caps."""
    owner, name = repo.split("/")
    query = """query($owner:String!,$name:String!,$number:Int!,$cursor:String){
      repository(owner:$owner,name:$name){pullRequest(number:$number){
        commits(first:100,after:$cursor){nodes{commit{oid committedDate messageHeadline}}
          pageInfo{hasNextPage endCursor}}}}}"""
    result, cursor = [], None
    while True:
        args = [
            "api",
            "graphql",
            "-f",
            "query=" + query,
            "-f",
            "owner=" + owner,
            "-f",
            "name=" + name,
            "-F",
            "number=" + str(number),
        ]
        if cursor:
            args += ["-f", "cursor=" + cursor]
        data = gh_json(*args)
        if data.get("errors"):
            raise ValueError("Incomplete commit query")
        page = data["data"]["repository"]["pullRequest"]["commits"]
        result.extend(n["commit"] for n in page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return result
        cursor = page["pageInfo"]["endCursor"]


def inventory(config):
    result = []
    for repo in config["repositories"]:
        for author in config["design_authors"]:
            pages = gh_json(
                "api",
                "--method",
                "GET",
                "search/issues",
                "-f",
                f"q=repo:{repo} is:pr is:open author:{author}",
                "-F",
                "per_page=100",
                "--paginate",
                "--slurp",
            )
            if any(p["incomplete_results"] or p["total_count"] > 1000 for p in pages):
                raise ValueError(f"Incomplete designer PR inventory for {repo}")
            for item in [i for p in pages for i in p["items"]]:
                number = item["number"]
                pr = gh_json("api", f"repos/{repo}/pulls/{number}")
                discussion = compact_discussions(repo, number)
                texts = [pr.get("body") or ""] + [
                    c["body"] for c in discussion["comments"]
                ]
                text = "\n".join(texts)
                bases = set()
                for url in re.findall(r"https://[^\s<>`\"]+", text):
                    parsed = urlsplit(url.rstrip(".,)"))
                    match = re.match(r"(/pr-\d+)(?:/|$)", parsed.path)
                    if (
                        parsed.hostname in config["preview_hosts"]
                        and match
                        and match[1] == f"/pr-{number}"
                    ):
                        bases.add(f"https://{parsed.netloc}{match[1]}/")
                if not bases:
                    continue
                file_pages = gh_json(
                    "api",
                    "--paginate",
                    "--slurp",
                    f"repos/{repo}/pulls/{number}/files?per_page=100",
                )
                files = [
                    f["filename"]
                    for page in file_pages
                    for f in page
                    if f["status"] != "removed"
                ]
                if pr["changed_files"] > 3000:
                    raise ValueError(f"Changed files truncated: {repo}#{number}")
                routes = sorted(
                    {u for base in bases for u in discover_routes(base, text, files)}
                )
                overrides = config.get("routes", {}).get(f"{repo}#{number}")
                if overrides:
                    routes = sorted(
                        set(
                            routes
                            + [
                                base.rstrip("/") + p
                                for base in bases
                                for p in overrides
                            ]
                        )
                    )
                result.append(
                    {
                        "repository": repo,
                        "number": number,
                        "url": pr["html_url"],
                        "title": pr["title"],
                        "head_sha": pr["head"]["sha"],
                        "body": pr.get("body"),
                        "discussion": discussion,
                        "commits": commits(repo, number),
                        "routes": routes,
                        "deployment_comments": [
                            c
                            for c in discussion["comments"]
                            if "preview-deployment" in c["body"]
                        ],
                    }
                )
    return list({p["url"]: p for p in result}.values())


SCREEN_ROWS = """() => [...document.querySelectorAll('button')].map((b,index)=>({
  index,label:b.innerText.trim(),described_only:!!b.querySelector('.desc,.tag.desc') || /\\bDESC\\b/.test(b.innerText)
})).filter(b=>/^\\d{2}\\s/.test(b.label))"""


async def capture(config, out, browser):
    manifest = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "prs": inventory(config),
        "previews": [],
        "captures": [],
    }

    def save():
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    save()
    if sum(len(pr["routes"]) for pr in manifest["prs"]) > config.get(
        "max_previews", 40
    ):
        raise ValueError(
            "Preview inventory exceeds configured budget; narrow scope explicitly"
        )
    for pr in manifest["prs"]:
        for route_index, url in enumerate(pr["routes"]):
            if urlsplit(url).hostname not in config["preview_hosts"]:
                raise ValueError("Preview escaped configured hosts")
            evidence = {
                "pr_url": pr["url"],
                "url": url,
                "status": "unavailable",
                "screens": [],
            }
            manifest["previews"].append(evidence)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1100},
                record_video_dir=str(out / "recordings")
                if config.get("record_walkthroughs", False)
                else None,
                record_video_size={"width": 1280, "height": 734},
            )
            page = await context.new_page()
            try:
                response = await page.goto(
                    url, wait_until="domcontentloaded", timeout=30000
                )
                if response is None or response.status >= 400:
                    raise ValueError(
                        f"Preview HTTP {response.status if response else 'unknown'}"
                    )
                if urlsplit(page.url).hostname not in config["preview_hosts"]:
                    raise ValueError("Preview redirected outside configured hosts")
                await page.wait_for_function(
                    """() => [...document.querySelectorAll('button')].some(b=>/^\\d{2}\\s/.test(b.innerText.trim()))""",
                    timeout=12000,
                )
                states = await page.evaluate(SCREEN_ROWS)
                evidence["screens"] = states
                for state in select_states(states, config.get("states_per_preview", 6)):
                    # Click the screen list: changing location.hash alone leaves some React previews stale.
                    rows = await page.evaluate(SCREEN_ROWS)
                    selected = next(s for s in rows if s["label"] == state["label"])
                    await page.locator("button").nth(selected["index"]).click()
                    await page.wait_for_timeout(900)
                    await page.evaluate("document.fonts.ready")
                    if not urlsplit(page.url).fragment:
                        raise ValueError("Screen selection produced no state deep link")
                    label = state["label"]
                    media_id = f"{pr['repository'].split('/')[-1]}-{pr['number']}-{route_index}-{state['index']}"
                    path = out / f"{media_id}.png"
                    device = page.locator(".device-wrap")
                    frame = page.locator(".concept-frame iframe:visible")
                    target = (
                        device
                        if await device.count() and await device.is_visible()
                        else frame.first
                        if await frame.count()
                        else None
                    )
                    if target is None:
                        await page.screenshot(path=str(path), animations="disabled")
                    else:
                        box = await target.bounding_box()
                        if box:
                            await page.screenshot(
                                path=str(path), clip=box, animations="disabled"
                            )
                        else:
                            raise ValueError(
                                "Selected screen has no visible capture surface"
                            )
                    manifest["captures"].append(
                        {
                            "id": media_id,
                            "pr_url": pr["url"],
                            "head_sha": pr["head_sha"],
                            "state_url": page.url,
                            "state": label,
                            "kind": "prototype",
                            "captured_at": datetime.now(timezone.utc).isoformat(),
                            "file": path.name,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "notes": (await page.locator("body").inner_text())[-6000:],
                        }
                    )
                    save()
                evidence["status"] = "captured"
            except Exception as exc:
                evidence["error"] = str(exc)[:1500]
            finally:
                video = page.video
                video_path = Path(await video.path()) if video else None
                await context.close()
                if video_path and evidence["status"] == "captured":
                    manifest["captures"].append(
                        {
                            "id": f"{pr['repository'].split('/')[-1]}-{pr['number']}-{route_index}-walkthrough",
                            "pr_url": pr["url"],
                            "head_sha": pr["head_sha"],
                            "state_url": url,
                            "state": "Handoff screen-selection walkthrough (fixture states, not a user journey test)",
                            "kind": "video",
                            "captured_at": datetime.now(timezone.utc).isoformat(),
                            "file": video_path.relative_to(out).as_posix(),
                            "sha256": hashlib.sha256(
                                video_path.read_bytes()
                            ).hexdigest(),
                        }
                    )
                elif video_path:
                    video_path.unlink(missing_ok=True)
                save()
    if not manifest["prs"] or not manifest["captures"]:
        raise ValueError(
            "No prototype visuals collected; inspect manifest before reporting no activity"
        )
    return manifest


def host_media(manifest_path, bucket, prefix, public_base):
    """Immutable objects are verified before they can be selected for publication."""
    import httpx

    manifest = json.loads(manifest_path.read_text())
    if not public_base.startswith("https://"):
        raise ValueError("Media hosting requires HTTPS")
    for media in manifest["captures"]:
        path = manifest_path.parent / media["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != media["sha256"]:
            raise ValueError("Capture changed after manifest creation")
        video = media.get("kind") == "video"
        key = f"{prefix.strip('/')}/{digest}.{'webm' if video else 'png'}"
        subprocess.run(
            [
                "aws",
                "s3",
                "cp",
                str(path),
                f"s3://{bucket}/{key}",
                "--content-type",
                "video/webm" if video else "image/png",
                "--only-show-errors",
            ],
            check=True,
            timeout=90,
        )
        url = public_base.rstrip("/") + "/" + key
        response = httpx.get(url, timeout=30)
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != digest:
            raise ValueError("Hosted image differs from inspected capture")
        media["hosted_url"] = url
        manifest_path.write_text(json.dumps(manifest, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    collect = subs.add_parser("collect")
    collect.add_argument("--config", type=Path, required=True)
    collect.add_argument("--out-dir", type=Path, required=True)
    collect.add_argument("--browser-executable")
    host = subs.add_parser("host")
    host.add_argument("--manifest", type=Path, required=True)
    host.add_argument("--bucket", required=True)
    host.add_argument("--prefix", required=True)
    host.add_argument("--public-base", required=True)
    check = subs.add_parser("validate")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--selection", type=Path, required=True)
    check.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate":
        validate_report(
            json.loads(args.manifest.read_text()),
            json.loads(args.selection.read_text()),
            args.report.read_text(),
        )
    elif args.command == "host":
        host_media(args.manifest, args.bucket, args.prefix, args.public_base)
    else:
        from playwright.async_api import async_playwright

        config = json.loads(args.config.read_text())
        if not 2 <= config.get("states_per_preview", 6) <= 20:
            raise ValueError("states_per_preview must be between 2 and 20")
        args.out_dir.mkdir(parents=True, exist_ok=True)

        async def run():
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    executable_path=args.browser_executable
                )
                try:
                    await capture(config, args.out_dir, browser)
                finally:
                    await browser.close()

        asyncio.run(run())


if __name__ == "__main__":
    main()
