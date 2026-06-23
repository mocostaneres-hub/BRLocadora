import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "br-locadora-logo.png"
TRANSPARENT = ROOT / "assets" / "br-locadora-logo-transparent.png"
FAVICON = ROOT / "favicon.ico"
FAVICON_PNG = ROOT / "assets" / "favicon-512.png"


def read_png(path):
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not a PNG")

    pos = 8
    chunks = []
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        chunks.append((ctype, payload))
        pos += 12 + length

    ihdr = next(payload for ctype, payload in chunks if ctype == b"IHDR")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
        ">IIBBBBB", ihdr
    )
    if (bit_depth, color_type, compression, filter_method, interlace) != (8, 2, 0, 0, 0):
        raise ValueError("Expected an 8-bit RGB PNG")

    compressed = b"".join(payload for ctype, payload in chunks if ctype == b"IDAT")
    raw = zlib.decompress(compressed)
    stride = width * 3
    rows = []
    offset = 0
    previous = bytearray(stride)

    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        row = bytearray(raw[offset : offset + stride])
        offset += stride

        for i in range(stride):
            left = row[i - 3] if i >= 3 else 0
            up = previous[i]
            up_left = previous[i - 3] if i >= 3 else 0

            if filter_type == 1:
                row[i] = (row[i] + left) & 255
            elif filter_type == 2:
                row[i] = (row[i] + up) & 255
            elif filter_type == 3:
                row[i] = (row[i] + ((left + up) // 2)) & 255
            elif filter_type == 4:
                predictor = paeth(left, up, up_left)
                row[i] = (row[i] + predictor) & 255
            elif filter_type != 0:
                raise ValueError(f"Unsupported PNG filter: {filter_type}")

        rows.append(row)
        previous = row

    return width, height, rows


def paeth(left, up, up_left):
    p = left + up - up_left
    pa = abs(p - left)
    pb = abs(p - up)
    pc = abs(p - up_left)
    if pa <= pb and pa <= pc:
        return left
    if pb <= pc:
        return up
    return up_left


def png_chunk(ctype, payload):
    return (
        struct.pack(">I", len(payload))
        + ctype
        + payload
        + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF)
    )


def write_rgba_png(path, width, height, rows):
    raw = bytearray()
    for row in rows:
        raw.append(0)
        raw.extend(row)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + png_chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def distance(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def transparent_logo(width, height, rows):
    corners = [
        rows[0][0:3],
        rows[0][(width - 1) * 3 : width * 3],
        rows[height - 1][0:3],
        rows[height - 1][(width - 1) * 3 : width * 3],
    ]
    background = tuple(round(sum(c[i] for c in corners) / 4) for i in range(3))

    visited = [[False] * width for _ in range(height)]
    stack = []
    for x in range(width):
        stack.append((x, 0))
        stack.append((x, height - 1))
    for y in range(height):
        stack.append((0, y))
        stack.append((width - 1, y))

    edge_background = set()
    while stack:
        x, y = stack.pop()
        if visited[y][x]:
            continue
        idx = x * 3
        color = tuple(rows[y][idx : idx + 3])
        if distance(color, background) > 44:
            continue
        visited[y][x] = True
        edge_background.add((x, y))
        if x > 0:
            stack.append((x - 1, y))
        if x + 1 < width:
            stack.append((x + 1, y))
        if y > 0:
            stack.append((x, y - 1))
        if y + 1 < height:
            stack.append((x, y + 1))

    output = []
    for y, row in enumerate(rows):
        rgba = bytearray()
        for x in range(width):
            idx = x * 3
            r, g, b = row[idx : idx + 3]
            alpha = 0 if (x, y) in edge_background else 255
            rgba.extend((r, g, b, alpha))
        output.append(rgba)
    return output


def resize_nearest(rows, width, height, size):
    resized = []
    for y in range(size):
        source_y = min(height - 1, round(y * (height - 1) / max(1, size - 1)))
        row = bytearray()
        for x in range(size):
            source_x = min(width - 1, round(x * (width - 1) / max(1, size - 1)))
            idx = source_x * 4
            row.extend(rows[source_y][idx : idx + 4])
        resized.append(row)
    return resized


def make_ico(path, width, height, rows):
    images = []
    for size in (16, 32, 48, 64, 128, 256):
        resized = resize_nearest(rows, width, height, size)
        raw = bytearray()
        for row in resized:
            raw.append(0)
            raw.extend(row)
        ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
        png = (
            b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", ihdr)
            + png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + png_chunk(b"IEND", b"")
        )
        images.append((size, png))

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + len(images) * 16
    entries = bytearray()
    payloads = bytearray()

    for size, png in images:
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                0 if size == 256 else size,
                0 if size == 256 else size,
                0,
                0,
                1,
                32,
                len(png),
                offset,
            )
        )
        payloads.extend(png)
        offset += len(png)

    path.write_bytes(header + entries + payloads)


def main():
    width, height, rows = read_png(SOURCE)
    rgba_rows = transparent_logo(width, height, rows)
    write_rgba_png(TRANSPARENT, width, height, rgba_rows)
    write_rgba_png(FAVICON_PNG, 512, 512, resize_nearest(rgba_rows, width, height, 512))
    make_ico(FAVICON, width, height, rgba_rows)


if __name__ == "__main__":
    main()
