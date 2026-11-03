"""Reproducible crop/background removal of the attributed CC BY-NC-SA reference."""

from collections import deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "art-sources" / "shijiemao-maid.webp"
destination = ROOT / "frontend" / "public" / "art" / "portrait.webp"
image = Image.open(source).convert("RGBA").crop((40, 0, 470, 665))
pixels = image.load()
width, height = image.size
seen = set()
queue = deque(
    [(x, y) for x in range(width) for y in (0, height - 1)]
    + [(x, y) for y in range(height) for x in (0, width - 1)]
)
while queue:
    x, y = queue.popleft()
    if (x, y) in seen or not (0 <= x < width and 0 <= y < height):
        continue
    seen.add((x, y))
    r, g, b, a = pixels[x, y]
    if min(r, g, b) >= 232 and max(r, g, b) - min(r, g, b) < 24:
        pixels[x, y] = (r, g, b, 0)
        queue.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
destination.parent.mkdir(parents=True, exist_ok=True)
image.save(destination, format="WEBP", quality=94, method=6)
print(f"Prepared portrait: {image.width}x{image.height}")

