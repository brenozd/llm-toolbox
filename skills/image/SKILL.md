---
name: image
description: |
  Light image editing via Python + Pillow: crop, rotate, resize/scale, blur, sharpen,
  grayscale, brightness/contrast/saturation, flip, text/watermark overlay, and format
  conversion (PNG/JPEG/WebP). Operations chain in a single command, applied in flag
  order, ideal for prepping images for blog posts, wikis, and docs.
  Use when: "crop this image", "resize image", "rotate photo", "blur image", "convert
  to jpeg/webp", "add watermark to image", "grayscale this picture", "edit screenshot
  for blog post", "/image".
allowed-tools:
  - Bash
  - Read
---

# image

Light, scriptable image editing for prepping images for posts, wikis, and blogs.

## Trigger

User says: "crop/rotate/resize/scale/blur/sharpen this image", "convert to jpeg/webp",
"add watermark/text to image", "grayscale this picture", or `/image`.

## Workflow

1. Identify the input image path (often a screenshot from the `screenshot` skill,
   or a path the user gives).
2. Run the script from the repo root or the user's project cwd, so `.images/`
   lands in a sensible place:

   ```bash
   python3 <path-to-this-skill>/scripts/imgtool.py INPUT [ops...] [--output PATH]
   ```

   Operations chain in one call, applied in the order the flags are given:

   ```bash
   # Crop then rotate then resize, one output
   python3 scripts/imgtool.py shot.png --crop 0,0,800,600 --rotate 90 --resize 640

   # Blur a region-sensitive screenshot before sharing
   python3 scripts/imgtool.py shot.png --blur 8

   # Add a watermark and export as webp
   python3 scripts/imgtool.py photo.jpg --text "draft" --text-pos 20,20 --format webp

   # Grayscale + higher contrast for a blog illustration
   python3 scripts/imgtool.py photo.png --grayscale --contrast 1.3
   ```

3. The script prints the saved output path on stdout. `Read` it to view the
   result inline and confirm it looks right before handing it back.

## Flags

See `README.md` for the full flag reference.

## Notes

- Pillow only, no extra dependencies — reuses the same library the `screenshot`
  skill uses for resize/format.
- Defaults to `.images/edit-<timestamp>.<ext>` in the current working directory;
  pass `--output PATH` for an explicit location.
- Output format defaults to the input's extension; override with `--format`.
- Run `python3 scripts/imgtool.py --selftest` to sanity-check every operation
  without needing a real image on disk.
