from __future__ import annotations

import argparse
import json
import re
import socketserver
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error, request


BASE_DIR = Path(__file__).resolve().parent
RESULTS_PAGE_URL = "https://irish.national-lottery.com/euromillions/results"
MAX_RECENT_DRAWS = 5
FALLBACK_DRAWS = [
    {
        "id": "2026-03-27",
        "date": "2026-03-27",
        "numbers": [4, 10, 43, 44, 48],
        "stars": [2, 4],
    },
    {
        "id": "2026-03-24",
        "date": "2026-03-24",
        "numbers": [12, 16, 17, 18, 27],
        "stars": [1, 3],
    },
    {
        "id": "2026-03-20",
        "date": "2026-03-20",
        "numbers": [5, 12, 16, 37, 46],
        "stars": [8, 10],
    },
    {
        "id": "2026-03-17",
        "date": "2026-03-17",
        "numbers": [5, 17, 28, 33, 41],
        "stars": [3, 9],
    },
    {
        "id": "2026-03-13",
        "date": "2026-03-13",
        "numbers": [13, 17, 26, 41, 48],
        "stars": [4, 10],
    },
]


class EuroMillionsHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()

        if self.path.startswith("/api/latest-draws"):
            return self.handle_latest_draws()

        if self.path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return

        return super().do_GET()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def handle_latest_draws(self) -> None:
        try:
            payload = self.fetch_latest_draws_from_results_page()
            return self.send_json(payload, data_source="server-results-page")
        except Exception as exc:  # noqa: BLE001
            self.send_json(
                {
                    "error": "results_page_unavailable",
                    "message": "Unable to fetch the latest published EuroMillions draws.",
                    "details": str(exc),
                    "fallback": FALLBACK_DRAWS,
                },
                status=HTTPStatus.BAD_GATEWAY,
                data_source="server-error",
            )

    def fetch_latest_draws_from_results_page(self) -> list[dict[str, Any]]:
        html = self.fetch_upstream_text(RESULTS_PAGE_URL)
        draws = self.parse_results_page(html)
        if len(draws) < MAX_RECENT_DRAWS:
            raise RuntimeError("Could not parse five recent draws from the results page")
        return draws[:MAX_RECENT_DRAWS]

    def fetch_upstream_text(self, url: str) -> str:
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
                status = getattr(response, "status", None) or response.getcode()
                if status != HTTPStatus.OK:
                    raise RuntimeError(f"Upstream returned status {status}")
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="ignore")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore").strip()
            detail = body[:120] if body else exc.reason
            raise RuntimeError(f"Upstream returned status {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Network error: {exc.reason}") from exc

    def parse_results_page(self, html: str) -> list[dict[str, Any]]:
        latest_numbers = self.extract_number_groups(
            html,
            r'<div class="h4">Result:</div>\s*<ul class="balls">(?P<ul>.*?)</ul>',
        )
        latest_href_match = re.search(
            r'<a href="(?P<href>/euromillions/results-\d{2}-\d{2}-\d{4})" class="button alt angled-blue">View Prize Breakdown</a>',
            html,
            re.S,
        )
        if not latest_numbers or not latest_href_match:
            raise RuntimeError("Could not parse the latest draw block")

        previous_section = html.split('<h3>Previous Results</h3>', 1)
        if len(previous_section) != 2:
            raise RuntimeError("Could not find the previous results section")

        latest_draw = self.build_draw(
            href=latest_href_match.group("href"),
            numbers=latest_numbers["numbers"],
            stars=latest_numbers["stars"],
        )
        previous_draws: list[dict[str, Any]] = []
        previous_pattern = re.compile(
            r'<div class="box previousResults resultStyle euromillions">.*?<ul class="balls">(?P<ul>.*?)</ul>.*?<a href="(?P<href>/euromillions/results-\d{2}-\d{2}-\d{4})" class="hoverBox">',
            re.S,
        )
        for match in previous_pattern.finditer(previous_section[1]):
            numbers = self.extract_number_groups(match.group("ul"))
            previous_draws.append(
                self.build_draw(
                    href=match.group("href"),
                    numbers=numbers["numbers"],
                    stars=numbers["stars"],
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

        return unique_draws

    def extract_number_groups(
        self,
        html: str,
        block_pattern: str | None = None,
    ) -> dict[str, list[int]]:
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

    def build_draw(self, *, href: str, numbers: list[int], stars: list[int]) -> dict[str, Any]:
        date_match = re.search(r'results-(\d{2})-(\d{2})-(\d{4})', href)
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

    def send_json(
        self,
        payload: Any,
        *,
        status: HTTPStatus = HTTPStatus.OK,
        data_source: str,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Data-Source", data_source)
        self.end_headers()
        self.wfile.write(body)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve the EuroMillions filter picker locally or on a server."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    socketserver.TCPServer.allow_reuse_address = True
    with ThreadingHTTPServer((args.host, args.port), EuroMillionsHandler) as server:
        print(f"Serving EuroMillions filter picker at http://{args.host}:{args.port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


if __name__ == "__main__":
    main()
