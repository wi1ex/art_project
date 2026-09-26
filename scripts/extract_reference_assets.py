"""Temporary illustration crops from the supplied Figma screenshot.

Run: python scripts/extract_reference_assets.py "path/to/Final ver.png"
Requires Pillow. Replace these crops with original Figma exports before release.
Coordinates use a 416px-wide reference preview; no UI text is used as HTML.
"""
import sys
from pathlib import Path
from PIL import Image

source = Image.open(sys.argv[1]).convert('RGB')
out = Path(__file__).resolve().parents[1] / 'public' / 'images'
out.mkdir(parents=True, exist_ok=True)
scale = source.width / 416
crops = {
    'hero': (209, 25, 416, 219),
    'service-electrical': (13, 335, 119, 427),
    'service-smart': (126, 335, 232, 427),
    'service-solar': (239, 335, 344, 427),
    'service-heat': (351, 335, 416, 427),
    'comparison': (24, 537, 392, 739),
    'developers': (291, 1088, 391, 1165),
    'designers': (291, 1173, 391, 1251),
    'builders': (291, 1259, 391, 1337),
    'architects': (291, 1344, 391, 1423),
}
for name, box in crops.items():
    image = source.crop(tuple(round(v * scale) for v in box))
    image.thumbnail((1200, 1100))
    image.save(out / f'{name}.webp', 'WEBP', quality=84, method=6)
