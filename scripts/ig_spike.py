"""
scripts/ig_spike.py — Instagram Reel feasibility spike

ISOLATED EXPERIMENT — do NOT import from src/ or integrate into the pipeline.
This script tests whether yt-dlp can reliably extract metadata/audio from
public Instagram Reel URLs without login.

Usage:
    python scripts/ig_spike.py

Results are printed to stdout and written to scripts/ig_spike_report.txt.

Methodology:
  - Uses yt-dlp in "info extraction only" mode (no download) to probe each URL.
  - If info extraction succeeds, also attempts a short subtitle/description pull
    (nearest equivalent to a transcript for video content with no captions API).
  - Measures wall-clock time for each attempt.
  - Captures the exact error string on failure.
  - Records any HTTP status codes that indicate login walls or bot detection.
"""

import json
import os
import sys
import time
import textwrap
from datetime import datetime

# yt-dlp import — must be installed in the same env (pip install yt-dlp)
try:
    import yt_dlp
except ImportError:
    print("ERROR: yt-dlp is not installed. Run: pip install yt-dlp")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Target URLs provided by the team
# ---------------------------------------------------------------------------
REEL_URLS = [
    "https://www.instagram.com/reels/Dam0leboT-G/",
    "https://www.instagram.com/reels/DaZDCOQNh7L/",
    "https://www.instagram.com/reels/DalDi3xITwW/",
]

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "ig_spike_report.txt")


# ---------------------------------------------------------------------------
# Spike logic
# ---------------------------------------------------------------------------

def probe_reel(url: str) -> dict:
    """
    Attempt to extract info from a single Instagram Reel URL using yt-dlp.
    Returns a result dict; never raises.
    """
    result = {
        "url": url,
        "success": False,
        "elapsed_seconds": None,
        "error": None,
        "error_type": None,
        "title": None,
        "description": None,
        "duration_seconds": None,
        "has_subtitles": False,
        "http_status_hint": None,
    }

    ydl_opts = {
        # Info extraction only — no file download
        "skip_download": True,
        "quiet": True,
        "no_warnings": False,
        # Don't write any files
        "noplaylist": True,
        # Reasonable timeout
        "socket_timeout": 20,
        # Don't use cookies (testing unauthenticated access)
        "cookiefile": None,
        # Capture subtitles/auto-subtitles metadata if present
        "writesubtitles": False,
        "writeautomaticsub": False,
        # User-agent: default yt-dlp (not spoofing a logged-in browser)
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        },
    }

    t0 = time.perf_counter()
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        elapsed = time.perf_counter() - t0
        result["elapsed_seconds"] = round(elapsed, 2)
        result["success"] = True
        result["title"] = info.get("title")
        result["description"] = (info.get("description") or "")[:300]  # truncate
        result["duration_seconds"] = info.get("duration")

        subs = info.get("subtitles", {})
        auto_subs = info.get("automatic_captions", {})
        result["has_subtitles"] = bool(subs or auto_subs)

    except yt_dlp.utils.DownloadError as exc:
        elapsed = time.perf_counter() - t0
        result["elapsed_seconds"] = round(elapsed, 2)
        err_str = str(exc)
        result["error"] = err_str
        result["error_type"] = "DownloadError"

        # Classify the error for the feasibility verdict
        lower = err_str.lower()
        if "login" in lower or "log in" in lower or "authentication" in lower:
            result["http_status_hint"] = "LOGIN_WALL"
        elif "429" in err_str or "rate" in lower:
            result["http_status_hint"] = "RATE_LIMITED"
        elif "404" in err_str or "not found" in lower:
            result["http_status_hint"] = "NOT_FOUND"
        elif "403" in err_str or "forbidden" in lower:
            result["http_status_hint"] = "FORBIDDEN_BOT_DETECT"
        elif "private" in lower:
            result["http_status_hint"] = "PRIVATE_CONTENT"
        else:
            result["http_status_hint"] = "UNKNOWN"

    except Exception as exc:  # noqa: BLE001
        elapsed = time.perf_counter() - t0
        result["elapsed_seconds"] = round(elapsed, 2)
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["http_status_hint"] = "UNEXPECTED_ERROR"

    return result


def format_result(r: dict, idx: int) -> str:
    lines = [
        f"{'='*60}",
        f"Reel {idx}  {r['url']}",
        f"{'='*60}",
    ]
    if r["success"]:
        lines += [
            f"  STATUS        : [PASS] SUCCESS",
            f"  Time taken    : {r['elapsed_seconds']}s",
            f"  Title         : {r['title']}",
            f"  Duration      : {r['duration_seconds']}s",
            f"  Has subtitles : {r['has_subtitles']}",
            f"  Description   : {textwrap.shorten(r['description'] or '', 120)}",
        ]
    else:
        lines += [
            f"  STATUS        : [FAIL] FAILED",
            f"  Time taken    : {r['elapsed_seconds']}s",
            f"  Error type    : {r['error_type']}",
            f"  HTTP hint     : {r['http_status_hint']}",
            f"  Full error    :",
        ]
        for chunk in textwrap.wrap(r["error"] or "", width=70):
            lines.append(f"    {chunk}")
    return "\n".join(lines)


def feasibility_verdict(results: list[dict]) -> str:
    successes = sum(1 for r in results if r["success"])
    failures = len(results) - successes
    login_walls = sum(
        1 for r in results if r.get("http_status_hint") in ("LOGIN_WALL", "FORBIDDEN_BOT_DETECT")
    )

    lines = [
        "",
        "=" * 60,
        "FEASIBILITY VERDICT",
        "=" * 60,
        f"  Succeeded : {successes} / {len(results)}",
        f"  Failed    : {failures} / {len(results)}",
        f"  Login/bot walls detected : {login_walls}",
        "",
    ]

    if successes >= 2:
        lines += [
            "  RECOMMENDATION: POTENTIALLY VIABLE — at least 2/3 URLs",
            "  succeeded. However, verify whether success is stable",
            "  across repeated runs and different IP addresses before",
            "  integrating into the MVP critical path.",
        ]
    else:
        lines += [
            "  RECOMMENDATION: DO NOT INTEGRATE INTO MVP.",
            "",
            "  Fewer than 2/3 test URLs succeeded. Instagram actively",
            "  blocks unauthenticated programmatic access. Key risks:",
            "",
            "  1. LOGIN WALL — Instagram requires authentication for",
            "     most Reel content when accessed by bots/scrapers.",
            "  2. BOT DETECTION — Even with a browser User-Agent,",
            "     yt-dlp requests are fingerprinted and blocked.",
            "  3. FRAGILITY — Any approach that works today can break",
            "     silently with the next Instagram deploy, with no",
            "     advance warning and no fallback.",
            "  4. DEMO RISK — A live demo failure on Instagram is",
            "     unrecoverable. Per scope_document.md this input type",
            "     should be demoted to 'shown as a bonus if it happens",
            "     to work' — NOT the demo lead.",
            "",
            "  PIVOT: Lead the demo with YouTube + article + plain text.",
            "  Mention Instagram as a roadmap item with honest framing:",
            "  'We tested it — it works when the platform cooperates,",
            "  but we chose not to stake the live demo on a scraping",
            "  dependency.'",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"\nVerity - Instagram Reel Feasibility Spike")
    print(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"yt-dlp version: {yt_dlp.version.__version__}")
    print(f"Testing {len(REEL_URLS)} URLs...\n")

    results = []
    for i, url in enumerate(REEL_URLS, start=1):
        print(f"[{i}/{len(REEL_URLS)}] Probing {url} ...")
        r = probe_reel(url)
        results.append(r)
        print(format_result(r, i))
        print()

    verdict = feasibility_verdict(results)
    print(verdict)

    # Write full report
    report_lines = [
        f"Verity — Instagram Reel Feasibility Spike Report",
        f"Generated: {datetime.now().isoformat()}",
        f"yt-dlp version: {yt_dlp.version.__version__}",
        "",
    ]
    for i, r in enumerate(results, start=1):
        report_lines.append(format_result(r, i))
        report_lines.append("")

    report_lines.append(verdict)
    report_lines.append("")
    report_lines.append("Raw JSON results:")
    report_lines.append(json.dumps(results, indent=2))

    report_text = "\n".join(report_lines)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"\nFull report written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
