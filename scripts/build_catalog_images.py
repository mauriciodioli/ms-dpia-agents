"""Rebuild the small local artwork library. Requires Pillow; no network access."""
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1] / 'src/static/images'
SOURCES = {'technology':'laptop', 'sport':'football', 'audio':'headphones',
           'footwear':'sneakers', 'furniture':'sofa', 'wearables':'watch'}


def main():
    (ROOT / 'catalog').mkdir(exist_ok=True)
    for target, source in SOURCES.items():
        with Image.open(ROOT / f'{source}.webp') as original:
            image = ImageOps.pad(original.convert('RGB'), (480, 360),
                                 method=Image.Resampling.LANCZOS, color='#f4f0f8')
            image.save(ROOT / 'catalog' / f'{target}.webp', 'WEBP', quality=82, method=6)


if __name__ == '__main__':
    main()
