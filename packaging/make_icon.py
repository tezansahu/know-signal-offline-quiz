"""Draw the Know Signal app icon (four rising answer-colour bars on ink) as a multi-size .ico."""

import sys

from PIL import Image, ImageDraw

BG = (10, 11, 16, 255)
BARS = [(255, 71, 87), (47, 123, 255), (255, 122, 26), (18, 194, 176)]


def draw(size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(15 * s), fill=BG)
    heights = [16, 25, 34, 44]
    for i, (h, c) in enumerate(zip(heights, BARS)):
        x = (10 + i * 12) * s
        d.rounded_rectangle([x, (54 - h) * s, x + 9 * s, 54 * s], radius=int(3 * s), fill=c)
    return img


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "knowsignal.ico"
    draw(256).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", out)
