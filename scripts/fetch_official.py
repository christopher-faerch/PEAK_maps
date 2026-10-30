"""Fetch a resort's own piste map and render it to OUT_DIR/SLUG/official.webp, ready for write_manifest.py.

Usage:
    python -I scripts/fetch_official.py areas.json OUT_DIR SLUG [SLUG ...] [--force]

Only areas whose areas.json 'official_map' has 'show_image': true are rendered – the owner's decision to show the
picture in PEAK (docs/manifest.md, "official_map"). The source is the file the resort publishes itself: 'image_url'
(JPEG or PNG) or 'pdf_url' (page 'page', default 1). The rendering changes nothing but the resolution: the long edge is
at most MAX_EDGE pixels, and a smaller picture is kept as it is. The source is kept next to the result
(official-source.<ext>) and is only downloaded again with --force or when the URL changed.

Tools: pdftoppm (poppler-utils) for PDFs, cwebp (webp) for the WebP and ImageMagick for a CMYK JPEG – the same as the
publish workflow installs.
Prints one JSON line per area; a failure is reported and the next area is done.
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # -I keeps the script's folder off sys.path
from write_manifest import webp_size  # noqa: E402

UA = "PEAK_maps/0.1 (+https://github.com/christopher-faerch/PEAK_maps)"
MAX_EDGE = 6000
QUALITY = "82"


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


def image_size(path):
    """Width, height and colour components (3 = RGB, 4 = CMYK) of a PNG or JPEG, from its header."""
    with open(path, "rb") as f:
        head = f.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"), 3
        if head[:2] != b"\xff\xd8":
            raise ValueError("not a PNG or JPEG")
        f.seek(2)
        while True:
            marker = f.read(2)
            if len(marker) < 2 or marker[0] != 0xFF:
                raise ValueError("no JPEG frame header")
            if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                f.read(3)
                h, w = int.from_bytes(f.read(2), "big"), int.from_bytes(f.read(2), "big")
                return w, h, f.read(1)[0]
            f.seek(int.from_bytes(f.read(2), "big") - 2, 1)


def to_rgb_png(source, png):
    """A CMYK JPEG (a print file) is beyond cwebp – ImageMagick turns it into an sRGB PNG first."""
    magick = ["magick"] if shutil.which("magick") else ["convert"]
    subprocess.run([*magick, source, "-colorspace", "sRGB", png], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def render(cfg, out, force):
    official = cfg["official_map"]
    url = official.get("image_url") or official.get("pdf_url")
    if not url:
        raise ValueError("official_map has neither image_url nor pdf_url")
    os.makedirs(out, exist_ok=True)
    is_pdf = not official.get("image_url")
    ext = "pdf" if is_pdf else os.path.splitext(url.split("?")[0])[1].lstrip(".").lower() or "img"
    source = os.path.join(out, f"official-source.{ext}")
    stamp = os.path.join(out, "official-source.url")
    same = os.path.exists(source) and os.path.exists(stamp) and open(stamp, encoding="utf-8").read().strip() == url
    if force or not same:
        download(url, source)
        with open(stamp, "w", encoding="utf-8", newline="\n") as f:
            f.write(url + "\n")
    target = os.path.join(out, "official.webp")
    if is_pdf:
        page = str(int(official.get("page", 1)))
        png = os.path.join(out, "official-page")
        subprocess.run(["pdftoppm", "-f", page, "-l", page, "-singlefile", "-scale-to", str(MAX_EDGE), "-png", source, png],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        subprocess.run(["cwebp", "-quiet", "-q", QUALITY, "-m", "6", png + ".png", "-o", target], check=True, stderr=subprocess.PIPE)
        os.remove(png + ".png")
    else:
        w, h, components = image_size(source)
        resize = ["-resize", str(MAX_EDGE), "0"] if w >= h and w > MAX_EDGE else ["-resize", "0", str(MAX_EDGE)] if h > MAX_EDGE else []
        picture = source
        if components == 4:
            picture = os.path.join(out, "official-rgb.png")
            to_rgb_png(source, picture)
        subprocess.run(["cwebp", "-quiet", "-q", QUALITY, "-m", "6", *resize, picture, "-o", target], check=True, stderr=subprocess.PIPE)
        if picture != source:
            os.remove(picture)
    w, h = webp_size(target)
    return {"slug": cfg["slug"], "source": url, "width": w, "height": h, "bytes": os.path.getsize(target)}


def main():
    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--force"]
    areas_file, out_root = args[0:2]
    areas = {a["slug"]: a for a in json.load(open(areas_file, encoding="utf-8"))["areas"]}
    failed = 0
    for slug in args[2:]:
        cfg = areas.get(slug)
        if not cfg or not (cfg.get("official_map") or {}).get("show_image"):
            print(json.dumps({"slug": slug, "skipped": "show_image is not true"}), flush=True)
            continue
        try:
            print(json.dumps(render(cfg, os.path.join(out_root, slug), force), ensure_ascii=False), flush=True)
        except (subprocess.CalledProcessError, OSError, ValueError) as ex:
            failed += 1
            detail = getattr(ex, "stderr", b"") or b""
            print(json.dumps({"slug": slug, "error": (str(ex) + " " + detail.decode("utf-8", "replace"))[-300:]}), flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
