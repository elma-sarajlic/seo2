from __future__ import annotations

import json
import os
import urllib.request
import base64
from pathlib import Path


def route_url(base_url: str, route: str) -> str:
    if "?route=" in base_url:
        return base_url + route
    return base_url.rstrip("/") + route


def get_json(base_url: str, route: str, token: str):
    request = urllib.request.Request(
        route_url(base_url, route),
        headers={"Accept": "application/json", "X-Review-Token": token},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def output(name: str, value: str) -> None:
    path = Path(os.environ["GITHUB_OUTPUT"])
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def main() -> int:
    event = os.getenv("WORKFLOW_EVENT", "schedule")
    requested = os.getenv("WORKFLOW_KEYWORD", "").strip()
    base_url = os.environ["ASSEMBLY_REVIEW_API_URL"].strip()
    token = os.environ["REVIEW_API_TOKEN"].strip()
    settings = get_json(base_url, "/automation-settings", token)
    output(
        "article_prompt_b64",
        base64.b64encode(str(settings.get("article_prompt_template") or "").encode("utf-8")).decode("ascii"),
    )
    output(
        "categories_b64",
        base64.b64encode(json.dumps(settings.get("content_categories") or []).encode("utf-8")).decode("ascii"),
    )
    if event == "workflow_dispatch":
        output("should_generate", "true")
        output("keyword", requested)
        output("topic_id", "")
        return 0

    status = get_json(base_url, "/automation-status", token)
    should_generate = status.get("due") is True
    keyword = ""
    topic_id = ""
    if should_generate:
        topics = get_json(base_url, "/topics", token)
        queued = next((item for item in topics if item.get("status") == "queued"), None)
        if queued:
            keyword = str(queued.get("topic") or "").strip()
            topic_id = str(queued.get("id") or "").strip()
    output("should_generate", "true" if should_generate else "false")
    output("keyword", keyword)
    output("topic_id", topic_id)
    print(json.dumps({"due": should_generate, "keyword": keyword, "topic_id": topic_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
