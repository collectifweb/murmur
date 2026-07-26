#!/usr/bin/env python3
"""Assemble src/aparte/assets/aparte.icns from aparte-app.svg.

A maintainer tool, not a build step: the .icns is committed, so a contributor never
runs this. It exists because there is no Mac here — `iconutil` and `sips` are macOS
tools, and the .icns container is simple enough to write directly: a magic word, the
total length, then one length-prefixed PNG per size.

    python3 scripts/build-icns.py

Needs `inkscape` on PATH to rasterise. Deterministic: same SVG in, same bytes out.
"""

from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "src" / "aparte" / "assets"
SOURCE = ASSETS / "aparte-app.svg"
TARGET = ASSETS / "aparte.icns"

# The OSTypes macOS reads, and the pixel size each one carries. Both the @1x and the
# @2x slots are filled: macOS picks by slot, not by measuring, so a missing @2x makes
# Retina fall back to an upscaled smaller image.
SLOTS = [
    ("icp4", 16),
    ("icp5", 32),
    ("icp6", 64),
    ("ic07", 128),
    ("ic08", 256),
    ("ic09", 512),
    ("ic10", 1024),  # 512@2x
    ("ic11", 32),    # 16@2x
    ("ic12", 64),    # 32@2x
    ("ic13", 256),   # 128@2x
    ("ic14", 512),   # 256@2x
]


def render(size: int, destination: Path) -> None:
    subprocess.run(
        [
            "inkscape",
            "--export-type=png",
            f"--export-filename={destination}",
            f"--export-width={size}",
            f"--export-height={size}",
            str(SOURCE),
        ],
        check=True,
        capture_output=True,
    )


def main() -> int:
    if not SOURCE.exists():
        print(f"missing {SOURCE}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        rendered: dict[int, bytes] = {}
        for size in sorted({size for _, size in SLOTS}):
            png = Path(tmp) / f"{size}.png"
            render(size, png)
            rendered[size] = png.read_bytes()

    chunks = [
        struct.pack(">4sI", ostype.encode("ascii"), len(rendered[size]) + 8) + rendered[size]
        for ostype, size in SLOTS
    ]
    body = b"".join(chunks)
    TARGET.write_bytes(struct.pack(">4sI", b"icns", len(body) + 8) + body)
    print(f"wrote {TARGET} ({TARGET.stat().st_size} bytes, {len(SLOTS)} slots)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
