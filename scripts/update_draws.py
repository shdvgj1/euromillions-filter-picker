from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


RESULTS_PAGE_URL = "https://irish.national-lottery.com/euromillions/results"
MAX_RECENT_DRAWS = 5
ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT_DIR / "data" / "draws.json"


def fetch_upstream_text(url: str) -> str:
    req = request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "euromillions-filter-picker/1.0",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=10) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="ignore")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore").strip()
        detail = body[:120] if body else exc.reason
        raise RuntimeError(f"Upstream returned status {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def extract_number_groups(html: str, block_pattern: str | None = None) -> dict[str, list[int]]:
    block_html = html
    if block_pattern:
        block_match = re.search(block_pattern, html, re.S)
        if not block_match:
            raise RuntimeError("Could not locate the number list in the results page")
        block_html = block_match.group("ul")

    numbers: list[int] = []
    stars: list[int] = []
    for match in re.finditer(r'<li class="(?P<class>[^"]+)">(?P<value>\d+)</li>', block_html):
        value = int(match.group("value"))
        classes = match.group("class")
        if "lucky-star" in classes:
            stars.append(value)
        elif "ball" in classes:
            numbers.append(value)

    if len(numbers) < 5 or len(stars) < 2:
        raise RuntimeError("Parsed result page but did not find five numbers and two stars")
    return {"numbers": numbers[:5], "stars": stars[:2]}


def build_draw(*, href: str, numbers: list[int], stars: list[int]) -> dict[str, Any]:
    date_match = re.search(r"results-(\d{2})-(\d{2})-(\d{4})", href)
    if not date_match:
        raise RuntimeError(f"Could not parse draw date from href: {href}")
    day, month, year = date_match.groups()
    iso_date = f"{year}-{month}-{day}"
    return {
        "id": iso_date,
        "date": iso_date,
        "numbers": numbers,
        "stars": stars,
    }


def parse_results_page(html: str) -> list[dict[str, Any]]:
    latest_numbers = extract_number_groups(
        html,
        r'<div class="h4">Result:</div>\s*<ul class="balls">(?P<ul>.*?)</ul>',
    )
    latest_href_match = re.search(
        r'<a href="(?P<href>/euromillions/results-\d{2}-\d{2}-\d{4})" class="button alt angled-blue">View Prize Breakdown</a>',
        html,
        re.S,
    )
    if not latest_href_match:
        raise RuntimeError("Could not parse the latest draw block")

    previous_section = html.split("<h3>Previous Results</h3>", 1)
    if len(previous_section) != 2:
        raise RuntimeError("Could not find the previous results section")

    latest_draw = build_draw(
        href=latest_href_match.group("href"),
        numbers=latest_numbers["numbers"],
        stars=latest_numbers["stars"],
    )

    previous_pattern = re.compile(
        r'<div class="box previousResults resultStyle euromillions">.*?<ul class="balls">(?P<ul>.*?)</ul>.*?<a href="(?P<href>/euromillions/results-\d{2}-\d{2}-\d{4})" class="hoverBox">',
        re.S,
    )
    previous_draws: list[dict[str, Any]] = []
    for match in previous_pattern.finditer(previous_section[1]):
        number_groups = extract_number_groups(match.group("ul"))
        previous_draws.append(
            build_draw(
                href=match.group("href"),
                numbers=number_groups["numbers"],
                stars=number_groups["stars"],
            )
        )
        if len(previous_draws) >= MAX_RECENT_DRAWS - 1:
            break

    draws = [latest_draw, *previous_draws]
    unique_draws: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for draw in draws:
        draw_id = str(draw["id"])
        if draw_id in seen_ids:
            continue
        seen_ids.add(draw_id)
        unique_draws.append(draw)

    if len(unique_draws) < MAX_RECENT_DRAWS:
        raise RuntimeError("Could not parse five recent draws from the results page")
    return unique_draws[:MAX_RECENT_DRAWS]


def write_output(draws: list[dict[str, Any]]) -> None:
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sourceLabel": "GitHub 静态数据",
        "sourceUrl": RESULTS_PAGE_URL,
        "draws": draws,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    html = fetch_upstream_text(RESULTS_PAGE_URL)
    draws = parse_results_page(html)
    write_output(draws)
    print(f"Wrote {len(draws)} draws to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
