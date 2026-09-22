from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def make_image(path: Path, title: str, color: tuple[int, int, int], offset: int, blur: float = 0) -> None:
    image = Image.new("RGB", (1200, 800), color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((80 + offset, 90, 1120, 710), outline="white", width=12)
    draw.ellipse((390 + offset, 170, 790 + offset, 570), fill=(188, 132, 97), outline=(255, 230, 190), width=10)
    draw.ellipse((490 + offset, 310, 535 + offset, 335), fill="black")
    draw.ellipse((650 + offset, 310, 695 + offset, 335), fill="black")
    draw.arc((500 + offset, 330, 685 + offset, 470), start=10, end=170, fill="white", width=8)
    draw.text((95, 35), title, fill="white", stroke_width=2, stroke_fill="black")
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    exif = Image.Exif()
    exif[271] = "FUJIFILM" if "Fuji" in title else "NIKON CORPORATION"
    exif[272] = "X-T4" if "Fuji" in title else "NIKON D3500"
    exif[36867] = (datetime(2026, 9, 1, 18, 30, 0) + timedelta(seconds=offset / 8)).strftime("%Y:%m:%d %H:%M:%S")
    exif[34855] = 800 if "Fuji" in title else 1600
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=91, exif=exif)


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "sample_event"
    samples = [
        (root / "Fuji" / "DSCF0001.jpg", "Fuji procession 1", (42, 65, 92), 0, 0),
        (root / "Fuji" / "DSCF0002.jpg", "Fuji procession 2", (44, 68, 95), 8, 0.8),
        (root / "Fuji" / "DSCF0003.jpg", "Fuji procession 3", (39, 60, 87), 16, 2.5),
        (root / "Nikon" / "DSC_0001.jpg", "Nikon interior 1", (97, 62, 35), 0, 0),
        (root / "Nikon" / "DSC_0002.jpg", "Nikon interior 2", (92, 58, 32), 8, 1.2),
        (root / "Nikon" / "DSC_0003.jpg", "Nikon interior 3", (40, 28, 20), 16, 4.0),
    ]
    for args in samples:
        make_image(*args)
    print(f"Created {len(samples)} sample photos in {root}")


if __name__ == "__main__":
    main()
