"""Independent check of the fixed flight example's saved final page (never agent input)."""

import base64
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def verify(folder: Path) -> dict:
    page = json.loads((folder / "final-page.json").read_text())
    elements = [e for e in page["elements"] if e.get("visible") and not e.get("covered")]
    controls = "\n".join(str(e.get("text") or e.get("label") or "") for e in elements)
    text = "\n".join(page.get("page_text") or [])
    url = page["page"]["url"]
    encoded = parse_qs(urlparse(url).query).get("tfs", [""])[0]
    decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    checks = {
        "round_trip": "Round trip" in controls,
        "airports": "Where from? New York JFK" in controls and "Where to? San Francisco SFO" in controls,
        "dates": b"2026-11-12" in decoded and b"2026-11-16" in decoded,
        "one_adult": "1 passenger" in controls and "1 adult" in text,
        "economy": "Economy (include Basic)" in controls,
        "nonstop_selected": "Nonstop, Stops, Selected" in controls,
        "popup_closed": "Close dialog" not in controls,
        "fare_visible": "round trip" in controls and "US dollars" in controls and "Delta" in controls,
    }
    result = {"passed": all(checks.values()), "checks": checks, "url": url}
    (folder / "independent-grade.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    import sys

    result = verify(Path(sys.argv[1]))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
