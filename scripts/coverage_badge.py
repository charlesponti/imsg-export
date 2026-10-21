#!/usr/bin/env python3
"""Render a static coverage badge from coverage.py's JSON report.

    uv run coverage json
    python3 scripts/coverage_badge.py coverage.json .github/badges/coverage.svg

The badge is committed so the README renders it without a third-party service.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

COLORS = [(95, "#4c1"), (90, "#97ca00"), (80, "#a4a61d"), (70, "#dfb317"), (0, "#e05d44")]
TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" \
aria-label="coverage: {percent:.0f}%">
  <title>coverage: {percent:.0f}%</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="{width}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="62" height="20" fill="#555"/>
    <rect x="62" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{width}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" \
font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text aria-hidden="true" x="31" y="15" fill="#010101" fill-opacity=".3">coverage</text>
    <text x="31" y="14">coverage</text>
    <text aria-hidden="true" x="{text_x}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{text_x}" y="14">{label}</text>
  </g>
</svg>
"""


def colour_for(percent: float) -> str:
    return next(colour for threshold, colour in COLORS if percent >= threshold)


def main() -> int:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "coverage.json")
    destination = Path(sys.argv[2] if len(sys.argv) > 2 else ".github/badges/coverage.svg")

    percent = float(json.loads(source.read_text())["totals"]["percent_covered"])
    label = f"{percent:.0f}%"
    value_width = max(len(label) * 7 + 10, 40)
    width = 62 + value_width

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        TEMPLATE.format(
            width=width,
            value_width=value_width,
            percent=percent,
            color=colour_for(percent),
            label=label,
            text_x=62 + value_width / 2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {destination} ({label})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
