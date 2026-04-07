from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


RESULTS_PAGE_URL = "https://irish.national-lottery.com/euromillions/results"
MAX_RECENT_DRAWS = 5
ROOT_DIR = Path(__file__).resolve().parents[1]
DRAWS_OUTPUT_PATH = ROOT_DIR / "data" / "draws.json"
HISTORY_DRAWS_OUTPUT_PATH = ROOT_DIR / "data" / "history-draws.json"
TENS_PATTERNS_OUTPUT_PATH = ROOT_DIR / "data" / "tens-patterns.json"
ONES_PATTERNS_OUTPUT_PATH = ROOT_DIR / "data" / "ones-patterns.json"
SEED_HISTORY_CSV_CANDIDATES = [
    ROOT_DIR / "euromillions.csv",
    Path.home() / "Downloads" / "euromillions.csv",
]


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


def main_number_to_decade(value: int) -> int:
    if value == 50:
        return 5
    return (value - 1) // 10


def draw_to_tens_pattern(draw: dict[str, Any]) -> list[int]:
    return sorted(main_number_to_decade(int(number)) for number in draw["numbers"])


def draw_to_units_pattern(draw: dict[str, Any]) -> list[int]:
    return [int(number) % 10 for number in draw["numbers"]]


def normalize_draw_item(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    date = str(raw.get("date") or raw.get("id") or "").strip()
    numbers = raw.get("numbers")
    stars = raw.get("stars")
    if not date or not isinstance(numbers, list) or not isinstance(stars, list):
        return None
    if len(numbers) != 5 or len(stars) != 2:
        return None

    clean_numbers = sorted(int(value) for value in numbers)
    clean_stars = sorted(int(value) for value in stars)
    if len(set(clean_numbers)) != 5 or len(set(clean_stars)) != 2:
        return None
    if any(value < 1 or value > 50 for value in clean_numbers):
        return None
    if any(value < 1 or value > 12 for value in clean_stars):
        return None

    return {
        "id": date,
        "date": date,
        "numbers": clean_numbers,
        "stars": clean_stars,
    }


def load_seed_history_from_csv(csv_path: Path) -> list[dict[str, Any]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    seed_items: list[dict[str, Any]] = []
    for row in rows:
        raw_date = str(row.get("date (dd-mm-yyyy)") or "").strip()
        if not raw_date:
            continue
        parsed_date = datetime.strptime(raw_date, "%d-%m-%Y").date().isoformat()
        draw = normalize_draw_item(
            {
                "date": parsed_date,
                "numbers": [row.get(f"num_{index}") for index in range(1, 6)],
                "stars": [row.get(f"star_{index}") for index in range(1, 3)],
            }
        )
        if draw:
            seed_items.append(draw)

    seed_items.sort(key=lambda item: item["date"], reverse=True)
    return seed_items


def load_existing_draw_items(output_path: Path) -> list[dict[str, Any]]:
    if output_path.exists():
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        items = payload.get("draws")
        if isinstance(items, list):
            normalized = [normalize_draw_item(item) for item in items]
            return [item for item in normalized if item]

    for candidate in SEED_HISTORY_CSV_CANDIDATES:
        if candidate.exists():
            return load_seed_history_from_csv(candidate)
    return []


def load_existing_pattern_items(output_path: Path) -> list[dict[str, Any]]:
    if not output_path.exists():
        return []
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        date = str(item.get("date") or "").strip()
        pattern = item.get("pattern")
        if not date or not isinstance(pattern, list) or len(pattern) != 5:
            continue
        normalized.append({"date": date, "pattern": [int(v) for v in pattern]})
    return normalized


def merge_pattern_items(
    draws: list[dict[str, Any]],
    *,
    output_path: Path,
    pattern_builder,
) -> list[dict[str, Any]]:
    existing_items = load_existing_pattern_items(output_path)
    merged: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    for draw in draws:
        date = str(draw["date"])
        merged.append({"date": date, "pattern": pattern_builder(draw)})
        seen_dates.add(date)

    for item in existing_items:
        date = str(item["date"])
        if date in seen_dates:
            continue
        merged.append(item)
        seen_dates.add(date)

    return merged


def merge_history_draws(draws: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_items = load_existing_draw_items(HISTORY_DRAWS_OUTPUT_PATH)
    merged: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    for draw in draws:
        normalized = normalize_draw_item(draw)
        if not normalized:
            continue
        date = str(normalized["date"])
        merged.append(normalized)
        seen_dates.add(date)

    for item in existing_items:
        date = str(item["date"])
        if date in seen_dates:
            continue
        merged.append(item)
        seen_dates.add(date)

    return merged


def merge_tens_patterns(draws: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return merge_pattern_items(
        draws,
        output_path=TENS_PATTERNS_OUTPUT_PATH,
        pattern_builder=draw_to_tens_pattern,
    )


def merge_ones_patterns(draws: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return merge_pattern_items(
        draws,
        output_path=ONES_PATTERNS_OUTPUT_PATH,
        pattern_builder=draw_to_units_pattern,
    )


def write_draws_output(draws: list[dict[str, Any]], generated_at: str) -> None:
    payload = {
        "generatedAt": generated_at,
        "sourceLabel": "GitHub 静态数据",
        "sourceUrl": RESULTS_PAGE_URL,
        "draws": draws,
    }
    DRAWS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DRAWS_OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_history_draws_output(items: list[dict[str, Any]], generated_at: str) -> None:
    payload = {
        "generatedAt": generated_at,
        "sourceLabel": "历史开奖（主号+星号）",
        "sourceUrl": RESULTS_PAGE_URL,
        "draws": items,
    }
    HISTORY_DRAWS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_DRAWS_OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_tens_patterns_output(items: list[dict[str, Any]], generated_at: str) -> None:
    payload = {
        "generatedAt": generated_at,
        "sourceLabel": "历史十位数组",
        "sourceUrl": RESULTS_PAGE_URL,
        "items": items,
    }
    TENS_PATTERNS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TENS_PATTERNS_OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_ones_patterns_output(items: list[dict[str, Any]], generated_at: str) -> None:
    payload = {
        "generatedAt": generated_at,
        "sourceLabel": "历史个位数组",
        "sourceUrl": RESULTS_PAGE_URL,
        "items": items,
    }
    ONES_PATTERNS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ONES_PATTERNS_OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    html = fetch_upstream_text(RESULTS_PAGE_URL)
    draws = parse_results_page(html)
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    history_draws = merge_history_draws(draws)
    tens_patterns = merge_tens_patterns(draws)
    ones_patterns = merge_ones_patterns(draws)
    write_draws_output(draws, generated_at)
    write_history_draws_output(history_draws, generated_at)
    write_tens_patterns_output(tens_patterns, generated_at)
    write_ones_patterns_output(ones_patterns, generated_at)
    print(f"Wrote {len(draws)} draws to {DRAWS_OUTPUT_PATH}")
    print(f"Wrote {len(history_draws)} historical draws to {HISTORY_DRAWS_OUTPUT_PATH}")
    print(f"Wrote {len(tens_patterns)} tens patterns to {TENS_PATTERNS_OUTPUT_PATH}")
    print(f"Wrote {len(ones_patterns)} ones patterns to {ONES_PATTERNS_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
