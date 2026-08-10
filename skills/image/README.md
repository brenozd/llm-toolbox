# image

Light image editing with Python + Pillow — crop, rotate, resize/scale, blur,
sharpen, grayscale, brightness/contrast/saturation, flip, text/watermark
overlay, and format conversion. Built for prepping images for blog posts,
wikis, and docs.

## Trigger

`/image`, or phrases like "crop/resize/rotate this image", "blur this
screenshot", "convert to webp", "add a watermark", "grayscale this picture".

## Usage

```bash
python3 scripts/imgtool.py INPUT [ops...] [--output PATH]
```

Flags apply in the order given on the command line, so you can chain multiple
operations in one call (e.g. crop, then rotate, then resize).

## Flags

| Flag | Effect |
|---|---|
| `--crop L,T,R,B` | Crop to the box `(left, top, right, bottom)` in pixels. |
| `--rotate DEG` | Rotate by degrees (counter-clockwise), canvas expands to fit. |
| `--resize WIDTH` or `WIDTHxHEIGHT` | Resize. Width-only keeps aspect ratio. |
| `--scale FACTOR` | Resize by a multiplier, e.g. `0.5` for half size. |
| `--blur RADIUS` | Gaussian blur. |
| `--sharpen` | Sharpen filter. |
| `--grayscale` | Convert to grayscale. |
| `--brightness FACTOR` | `1.0` = unchanged, `<1` darker, `>1` brighter. |
| `--contrast FACTOR` | `1.0` = unchanged. |
| `--saturation FACTOR` | `1.0` = unchanged, `0` = grayscale. |
| `--flip horizontal\|vertical` | Mirror the image. |
| `--text CONTENT` | Draw text (e.g. a watermark or caption) onto the image. |
| `--text-pos X,Y` | Text position in pixels (default `10,10`). |
| `--text-color COLOR` | Text color, name or hex (default `white`). |
| `--text-size N` | Font size (default `24`). |
| `--format png\|jpeg\|webp` | Output format (default: input's own extension). |
| `--quality N` | JPEG/WebP quality, 1-100 (default `85`). |
| `--output PATH` | Explicit output path (default `.images/edit-<timestamp>.<ext>`). |
| `--selftest` | Run the self-check on a generated in-memory image and exit. |

## Examples

```bash
# Crop, rotate, and resize in one pass
python3 scripts/imgtool.py shot.png --crop 0,0,800,600 --rotate 90 --resize 640

# Blur a sensitive region before sharing a screenshot
python3 scripts/imgtool.py shot.png --blur 8

# Watermark and convert to webp
python3 scripts/imgtool.py photo.jpg --text "draft" --text-pos 20,20 --format webp

# Grayscale + punchier contrast for a blog illustration
python3 scripts/imgtool.py photo.png --grayscale --contrast 1.3

# Sanity-check the tool without a real image
python3 scripts/imgtool.py --selftest
```

## Requirements

- Python 3 + Pillow (same dependency as the `screenshot` skill)
