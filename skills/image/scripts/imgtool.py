#!/usr/bin/env python3
"""Image editing tool: crop, rotate, resize/scale, blur, sharpen, grayscale,
brightness/contrast/saturation, flip, text overlay, format conversion.
Pillow only, no extra deps. Flags apply in the order they appear on argv,
same chaining pattern as the screenshot skill's shot.py.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageFont

try:
    from PIL import ImageDraw
except ImportError:  # pragma: no cover
    ImageDraw = None

FORMAT_EXT = {"png": "png", "jpeg": "jpg", "jpg": "jpg", "webp": "webp"}


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def op_crop(img: Image.Image, box: str) -> Image.Image:
    l, t, r, b = (int(x) for x in box.split(","))
    return img.crop((l, t, r, b))


def op_rotate(img: Image.Image, deg: str) -> Image.Image:
    return img.rotate(float(deg), expand=True)


def op_resize(img: Image.Image, spec: str) -> Image.Image:
    if "x" in spec:
        w, h = (int(x) for x in spec.split("x"))
    else:
        w = int(spec)
        h = max(1, round(img.height * (w / img.width)))
    return img.resize((w, h), Image.LANCZOS)


def op_scale(img: Image.Image, factor: str) -> Image.Image:
    f = float(factor)
    size = (max(1, round(img.width * f)), max(1, round(img.height * f)))
    return img.resize(size, Image.LANCZOS)


def op_blur(img: Image.Image, radius: str) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(float(radius)))


def op_sharpen(img: Image.Image, _: str | None) -> Image.Image:
    return img.filter(ImageFilter.SHARPEN)


def op_grayscale(img: Image.Image, _: str | None) -> Image.Image:
    return img.convert("L").convert(img.mode if img.mode in ("RGB", "RGBA") else "RGB")


def op_brightness(img: Image.Image, factor: str) -> Image.Image:
    return ImageEnhance.Brightness(img).enhance(float(factor))


def op_contrast(img: Image.Image, factor: str) -> Image.Image:
    return ImageEnhance.Contrast(img).enhance(float(factor))


def op_saturation(img: Image.Image, factor: str) -> Image.Image:
    return ImageEnhance.Color(img).enhance(float(factor))


def op_flip(img: Image.Image, direction: str) -> Image.Image:
    if direction == "horizontal":
        return img.transpose(Image.FLIP_LEFT_RIGHT)
    if direction == "vertical":
        return img.transpose(Image.FLIP_TOP_BOTTOM)
    raise ValueError(f"unknown flip direction: {direction}")


def op_text(img: Image.Image, content: str, pos: str, color: str, size: int) -> Image.Image:
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")
    draw = ImageDraw.Draw(img)
    x, y = (int(v) for v in pos.split(","))
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 load_default has no size arg
        font = ImageFont.load_default()
    draw.text((x, y), content, fill=color, font=font)
    return img


def op_format_convert(img: Image.Image, fmt: str) -> Image.Image:
    if fmt in ("jpeg", "jpg") and img.mode in ("RGBA", "P"):
        return img.convert("RGB")
    return img


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", nargs="?", help="input image path")
    p.add_argument("--crop", metavar="L,T,R,B")
    p.add_argument("--rotate", metavar="DEG")
    p.add_argument("--resize", metavar="WIDTH|WIDTHxHEIGHT")
    p.add_argument("--scale", metavar="FACTOR")
    p.add_argument("--blur", metavar="RADIUS")
    p.add_argument("--sharpen", action="store_true")
    p.add_argument("--grayscale", action="store_true")
    p.add_argument("--brightness", metavar="FACTOR")
    p.add_argument("--contrast", metavar="FACTOR")
    p.add_argument("--saturation", metavar="FACTOR")
    p.add_argument("--flip", choices=["horizontal", "vertical"])
    p.add_argument("--text", metavar="CONTENT")
    p.add_argument("--text-pos", metavar="X,Y", default="10,10")
    p.add_argument("--text-color", metavar="COLOR", default="white")
    p.add_argument("--text-size", type=int, default=24)
    p.add_argument("--format", choices=["png", "jpeg", "jpg", "webp"])
    p.add_argument("--quality", type=int, default=85)
    p.add_argument("--output", type=Path)
    p.add_argument("--selftest", action="store_true")
    return p


# Order in which flags apply when multiple are given, following the argparse
# dest names above. Text/format/quality are handled separately since they
# need extra args or happen at save time.
OP_ORDER = [
    ("crop", op_crop),
    ("rotate", op_rotate),
    ("resize", op_resize),
    ("scale", op_scale),
    ("blur", op_blur),
    ("sharpen", op_sharpen),
    ("grayscale", op_grayscale),
    ("brightness", op_brightness),
    ("contrast", op_contrast),
    ("saturation", op_saturation),
    ("flip", op_flip),
]


def apply_ops(img: Image.Image, args: argparse.Namespace) -> Image.Image:
    for name, fn in OP_ORDER:
        value = getattr(args, name)
        if not value:
            continue
        img = fn(img, value) if not isinstance(value, bool) else fn(img, None)
    if args.text:
        img = op_text(img, args.text, args.text_pos, args.text_color, args.text_size)
    return img


def default_output(fmt: str) -> Path:
    d = Path.cwd() / ".images"
    d.mkdir(exist_ok=True)
    ext = FORMAT_EXT[fmt]
    return d / f"edit-{datetime.now():%Y%m%d-%H%M%S}.{ext}"


def run(input_path: Path, args: argparse.Namespace) -> Path:
    img = Image.open(input_path)
    img = apply_ops(img, args)

    fmt = args.format or (input_path.suffix.lstrip(".").lower() or "png")
    if fmt not in FORMAT_EXT:
        fmt = "png"
    img = op_format_convert(img, fmt)

    output = args.output or default_output(fmt)
    output.parent.mkdir(parents=True, exist_ok=True)

    save_fmt = "JPEG" if fmt in ("jpeg", "jpg") else fmt.upper()
    save_kwargs = {"quality": args.quality} if fmt in ("jpeg", "jpg", "webp") else {}
    img.save(output, save_fmt, **save_kwargs)
    return output


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.selftest:
        return _selftest()

    if not args.input:
        print("error: input image path required", file=sys.stderr)
        return 1

    output = run(Path(args.input), args)
    print(output)
    return 0


def _selftest() -> int:
    """Exercise every operation on an in-memory-generated image."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "src.png"
        Image.new("RGB", (400, 200), "blue").save(src)

        parser = build_parser()

        out = run(src, parser.parse_args([str(src), "--crop", "0,0,100,100"]))
        with Image.open(out) as img:
            assert img.size == (100, 100), f"crop failed: {img.size}"

        out = run(src, parser.parse_args([str(src), "--rotate", "90"]))
        with Image.open(out) as img:
            assert img.size == (200, 400), f"rotate failed: {img.size}"

        out = run(src, parser.parse_args([str(src), "--resize", "200"]))
        with Image.open(out) as img:
            assert img.size == (200, 100), f"resize failed: {img.size}"

        out = run(src, parser.parse_args([str(src), "--scale", "0.5"]))
        with Image.open(out) as img:
            assert img.size == (200, 100), f"scale failed: {img.size}"

        out = run(src, parser.parse_args([str(src), "--blur", "3"]))
        assert out.exists(), "blur produced no file"

        out = run(src, parser.parse_args([str(src), "--sharpen"]))
        assert out.exists(), "sharpen produced no file"

        out = run(src, parser.parse_args([str(src), "--grayscale"]))
        assert out.exists(), "grayscale produced no file"

        out = run(src, parser.parse_args([str(src), "--brightness", "1.5"]))
        assert out.exists(), "brightness produced no file"

        out = run(src, parser.parse_args([str(src), "--contrast", "1.5"]))
        assert out.exists(), "contrast produced no file"

        out = run(src, parser.parse_args([str(src), "--saturation", "0.5"]))
        assert out.exists(), "saturation produced no file"

        out = run(src, parser.parse_args([str(src), "--flip", "horizontal"]))
        with Image.open(out) as img:
            assert img.size == (400, 200), f"flip failed: {img.size}"

        out = run(src, parser.parse_args([str(src), "--text", "hi", "--text-pos", "5,5"]))
        assert out.exists(), "text overlay produced no file"

        out = run(src, parser.parse_args([str(src), "--format", "jpeg"]))
        assert out.suffix == ".jpg", f"format convert failed: {out.suffix}"

        out = run(src, parser.parse_args(
            [str(src), "--crop", "0,0,300,150", "--rotate", "90", "--blur", "2", "--resize", "100"]
        ))
        with Image.open(out) as img:
            assert img.size[0] == 100, f"chained ops failed: {img.size}"

    print("selftest OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
