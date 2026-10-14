#!/usr/bin/env python3
"""Generate only Yokohama launcher icons from assets/icon/go_logo_yokohama.png.

Usage: python scripts/generate_yokohama_app_icons.py [--check]
No network, silent fallbacks, or edits to other city flavors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from io import BytesIO
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "assets/icon/go_logo_yokohama.png"
IOS_DIR = REPO / "ios/Runner/Assets.xcassets/AppIconYokohama.appiconset"
ANDROID = REPO / "android/app/src/yokohama/res"
ANDROID_SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}


def _master() -> Image.Image:
    with Image.open(SOURCE) as im:
        if im.format != "PNG" or im.mode != "RGBA" or im.size != (480, 370):
            raise ValueError("Yokohama source logo must be a 480x370 RGBA PNG")
        pixels = im.copy()
    bounds = pixels.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("Yokohama source logo has no opaque pixels")
    cropped = pixels.crop(bounds)
    scale = min(916 / cropped.width, 916 / cropped.height)
    scaled = cropped.resize(
        (round(cropped.width * scale), round(cropped.height * scale)),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (1024, 1024), (255, 255, 255, 255))
    canvas.alpha_composite(
        scaled, ((1024 - scaled.width) // 2, (1024 - scaled.height) // 2),
    )
    return canvas.convert("RGB")


def _ios_sizes() -> dict[str, int]:
    raw = json.loads((IOS_DIR / "Contents.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("images"), list):
        raise ValueError("invalid Yokohama iOS icon Contents.json")
    sizes = {}
    for image in raw["images"]:
        filename, size, scale = image["filename"], image["size"], image["scale"]
        if (not isinstance(filename, str) or not filename.startswith("Icon-App-")
                or not filename.endswith(".png")):
            raise ValueError("unexpected Yokohama iOS icon filename")
        dimensions = size.split("x")
        if (len(dimensions) != 2 or dimensions[0] != dimensions[1]
                or scale not in {"1x", "2x", "3x"}):
            raise ValueError("unsupported Yokohama iOS icon size")
        points = float(dimensions[0])
        pixel_size = points * int(scale[0])
        if not pixel_size.is_integer() or not 1 <= pixel_size <= 1024:
            raise ValueError("non-integral Yokohama icon pixel size")
        if filename in sizes and sizes[filename] != int(pixel_size):
            raise ValueError("conflicting dimensions for Yokohama icon filename")
        sizes[filename] = int(pixel_size)
    if sizes.get("Icon-App-1024x1024@1x.png") != 1024 or len(sizes) != 15:
        raise ValueError("unexpected Yokohama iOS icon inventory")
    return sizes


def _png_bytes(master: Image.Image, side: int) -> bytes:
    image = master if side == 1024 else master.resize(
        (side, side), Image.Resampling.LANCZOS,
    )
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify icons match the source logo; do not modify files")
    args = parser.parse_args()
    master = _master()
    expected = {IOS_DIR / filename: side for filename, side in _ios_sizes().items()}
    expected.update({
        ANDROID / f"mipmap-{density}" / "ic_launcher.png": side
        for density, side in ANDROID_SIZES.items()
    })
    rendered = {side: _png_bytes(master, side) for side in set(expected.values())}
    for path, side in sorted(expected.items()):
        data = rendered[side]
        if args.check:
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError(
                    f"missing or stale Yokohama launcher icon: {path.relative_to(REPO)}"
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        print(f"{path.relative_to(REPO)} {side}x{side} sha256={hashlib.sha256(data).hexdigest()[:12]}")
    print(f"Yokohama icons: {len(expected)} {'verified' if args.check else 'generated'}")


if __name__ == "__main__":
    main()
