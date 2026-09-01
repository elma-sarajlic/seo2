from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_PATH = ROOT / "seo" / "draft-payload.json"


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required value: {name}")
    return value


def route_url(base_url: str, route: str) -> str:
    if "?route=" in base_url:
        return base_url + route
    return base_url.rstrip("/") + route


def send_notification(webhook_url: str, payload: dict) -> None:
    if not webhook_url:
        return
    title = str(payload.get("title") or "New Assembly Maker draft")
    if "ntfy.sh/" in webhook_url:
        message = f"New Assembly Maker article ready for an image and review:\n{title}"
        requests.post(
            webhook_url,
            data=message.encode("utf-8"),
            headers={"Title": "Assembly Maker draft ready", "Tags": "memo,art"},
            timeout=20,
        ).raise_for_status()
        return
    requests.post(
        webhook_url,
        json={
            "event": "assemblymaker_draft_ready",
            "title": title,
            "draft_id": payload.get("id"),
        },
        timeout=20,
    ).raise_for_status()


def main() -> int:
    api_url = required_env("ASSEMBLY_REVIEW_API_URL")
    review_token = required_env("REVIEW_API_TOKEN")
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    response = requests.post(
        route_url(api_url, "/drafts"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Review-Token": review_token,
        },
        json=payload,
        timeout=30,
    )
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"Draft API returned HTTP {response.status_code}: {response.text[:500]}")
    result = response.json()
    print(json.dumps({"status": "draft-submitted", "id": result.get("id"), "title": result.get("title")}, ensure_ascii=False))
    topic_id = os.getenv("QUEUED_TOPIC_ID", "").strip()
    if topic_id:
        completed = requests.delete(
            route_url(api_url, f"/topics/{topic_id}"),
            headers={"Accept": "application/json", "X-Review-Token": review_token},
            timeout=20,
        )
        if not 200 <= completed.status_code < 300:
            print(f"Could not clear completed topic {topic_id}: HTTP {completed.status_code}", file=sys.stderr)
    webhook_url = os.getenv("NOTIFICATION_WEBHOOK_URL", "").strip()
    try:
        send_notification(webhook_url, payload)
    except Exception as error:
        print(f"Notification failed without blocking the draft: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Draft submission failed: {error}", file=sys.stderr)
        raise
