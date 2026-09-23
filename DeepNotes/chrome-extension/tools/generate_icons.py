"""Rebuild original extension PNG artwork using only Python's standard library."""
from pathlib import Path
import struct
import zlib


def rounded(x, y, left, top, right, bottom, radius):
    if not (left <= x <= right and top <= y <= bottom):
        return False
    cx = min(max(x, left + radius), right - radius)
    cy = min(max(y, top + radius), bottom - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2


def pixel(x, y):
    if not rounded(x, y, 2, 2, 126, 126, 29):
        return (0, 0, 0, 0)
    color = (98 + int(y * .09), 66 + int(y * .07), 220, 255)
    if rounded(x, y, 32, 25, 96, 107, 12):
        color = (216, 205, 255, 255)
    if rounded(x, y, 25, 20, 89, 101, 12):
        color = (255, 252, 247, 255)
    if rounded(x, y, 38, 39, 76, 45, 3) or rounded(x, y, 38, 53, 68, 59, 3):
        color = (127, 104, 204, 255)
    if (x - 72) ** 2 + (y - 79) ** 2 < 8 ** 2:
        color = (106, 70, 215, 255)
    if rounded(x, y, 38, 72, 55, 78, 3):
        color = (188, 174, 224, 255)
    return color


def png(size):
    scale = 4
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            samples = [pixel((x + (sx + .5) / scale) * 128 / size,
                             (y + (sy + .5) / scale) * 128 / size)
                       for sy in range(scale) for sx in range(scale)]
            row.extend(round(sum(p[channel] for p in samples) / len(samples)) for channel in range(4))
        rows.append(row)
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', size, size, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b''.join(rows), 9)) + chunk(b'IEND', b'')


if __name__ == '__main__':
    output = Path(__file__).resolve().parents[1] / 'icons'
    output.mkdir(exist_ok=True)
    for size in (16, 32, 48, 128):
        (output / f'icon{size}.png').write_bytes(png(size))
    print('Generated four extension icons.')
