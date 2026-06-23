import struct
import zlib
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


def read_png(path):
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")

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
    if bit_depth != 8 or compression != 0 or filter_method != 0 or interlace != 0:
        raise ValueError("Unsupported PNG format")
    if color_type == 2:
        channels = 3
    elif color_type == 6:
        channels = 4
    else:
        raise ValueError(f"Unsupported PNG color type: {color_type}")

    raw = zlib.decompress(b"".join(payload for ctype, payload in chunks if ctype == b"IDAT"))
    stride = width * channels
    rows = []
    offset = 0
    previous = bytearray(stride)

    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        row = bytearray(raw[offset : offset + stride])
        offset += stride

        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            up = previous[i]
            up_left = previous[i - channels] if i >= channels else 0
            if filter_type == 1:
                row[i] = (row[i] + left) & 255
            elif filter_type == 2:
                row[i] = (row[i] + up) & 255
            elif filter_type == 3:
                row[i] = (row[i] + ((left + up) // 2)) & 255
            elif filter_type == 4:
                row[i] = (row[i] + paeth(left, up, up_left)) & 255
            elif filter_type != 0:
                raise ValueError(f"Unsupported PNG filter: {filter_type}")

        if channels == 3:
            rgba = bytearray()
            for x in range(width):
                i = x * 3
                rgba.extend((row[i], row[i + 1], row[i + 2], 255))
            rows.append(rgba)
        else:
            rows.append(row)
        previous = row

    return width, height, rows


def png_chunk(ctype, payload):
    return (
        struct.pack(">I", len(payload))
        + ctype
        + payload
        + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF)
    )


def write_png(path, width, height, rows):
    raw = bytearray()
    for row in rows:
        raw.append(0)
        raw.extend(row)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    data = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + png_chunk(b"IEND", b"")
    )
    Path(path).write_bytes(data)


def get_pixel(rows, width, x, y):
    x = max(0, min(width - 1, x))
    y = max(0, min(len(rows) - 1, y))
    i = x * 4
    return rows[y][i : i + 4]


def set_pixel(rows, x, y, color):
    i = x * 4
    rows[y][i : i + 4] = bytes(color)


def blend(a, b, amount):
    return [round(a[i] * (1 - amount) + b[i] * amount) for i in range(4)]


def smoothstep(edge0, edge1, x):
    if edge0 == edge1:
        return 1
    x = max(0, min(1, (x - edge0) / (edge1 - edge0)))
    return x * x * (3 - 2 * x)


def clone_patch(rows, width, height, target, source, feather=18, darken=0.0):
    tx, ty, tw, th = target
    sx, sy, sw, sh = source
    original = [bytearray(row) for row in rows]

    for y in range(th):
        for x in range(tw):
            px = tx + x
            py = ty + y
            if not (0 <= px < width and 0 <= py < height):
                continue

            u = x / max(1, tw - 1)
            v = y / max(1, th - 1)
            src_x = sx + round(u * (sw - 1))
            src_y = sy + round(v * (sh - 1))
            color = list(get_pixel(original, width, src_x, src_y))
            if darken:
                color[:3] = [max(0, round(c * (1 - darken))) for c in color[:3]]

            edge = min(x, y, tw - 1 - x, th - 1 - y)
            amount = smoothstep(0, feather, edge)
            current = list(get_pixel(rows, width, px, py))
            set_pixel(rows, px, py, blend(current, color, amount))


def blur_region(rows, width, height, region, radius=7):
    rx, ry, rw, rh = region
    original = [bytearray(row) for row in rows]
    for y in range(rh):
        for x in range(rw):
            px = rx + x
            py = ry + y
            if not (0 <= px < width and 0 <= py < height):
                continue
            total = [0, 0, 0, 0]
            count = 0
            for oy in range(-radius, radius + 1, 3):
                for ox in range(-radius, radius + 1, 3):
                    sample = get_pixel(original, width, px + ox, py + oy)
                    for i in range(4):
                        total[i] += sample[i]
                    count += 1
            set_pixel(rows, px, py, [round(v / count) for v in total])


def point_in_polygon(x, y, points):
    inside = False
    j = len(points) - 1
    for i, point in enumerate(points):
        xi, yi = point
        xj, yj = points[j]
        intersects = (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / max(0.0001, yj - yi) + xi
        if intersects:
            inside = not inside
        j = i
    return inside


def distance_to_segment(px, py, ax, ay, bx, by):
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    x = ax + t * dx
    y = ay + t * dy
    return math.hypot(px - x, py - y)


def polygon_edge_distance(x, y, points):
    return min(
        distance_to_segment(x, y, points[i][0], points[i][1], points[(i + 1) % len(points)][0], points[(i + 1) % len(points)][1])
        for i in range(len(points))
    )


def grille_texture(rows, width, x, y, sample_offset=(0, 220), darken=0.18):
    sx = x + sample_offset[0]
    sy = y + sample_offset[1]
    sampled = list(get_pixel(rows, width, sx, sy))
    brightness = sum(sampled[:3]) / 3
    if brightness > 95:
        base = [22, 27, 29]
    else:
        base = [round(sampled[i] * (1 - darken)) for i in range(3)]

    honeycomb = ((x * 0.78 + y * 0.42) % 78) < 9 or ((x * 0.62 - y * 0.34) % 86) < 8
    shadow = ((x + y * 0.22) % 148) < 42
    highlight = ((x - y * 0.12) % 116) < 7

    if honeycomb:
        base = [max(4, round(c * 0.38)) for c in base]
    elif shadow:
        base = [max(5, round(c * 0.68)) for c in base]
    elif highlight:
        base = [min(95, round(c * 1.34 + 14)) for c in base]

    return [base[0], base[1], base[2], 255]


def fill_plate_with_grille(rows, width, height, points, sample_offset=(0, 220), feather=18, darken=0.18):
    min_x = max(0, math.floor(min(x for x, _ in points) - feather))
    max_x = min(width - 1, math.ceil(max(x for x, _ in points) + feather))
    min_y = max(0, math.floor(min(y for _, y in points) - feather))
    max_y = min(height - 1, math.ceil(max(y for _, y in points) + feather))
    original = [bytearray(row) for row in rows]

    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            if not point_in_polygon(x, y, points):
                continue
            distance = polygon_edge_distance(x, y, points)
            amount = smoothstep(0, feather, distance)
            texture = grille_texture(original, width, x, y, sample_offset=sample_offset, darken=darken)
            current = list(get_pixel(rows, width, x, y))
            set_pixel(rows, x, y, blend(current, texture, amount))


def edit_hatch():
    width, height, rows = read_png("/private/tmp/fleet-hatch.png")
    # Rebuild the grille where the front plate sat, using the car's own dark grille texture.
    fill_plate_with_grille(
        rows,
        width,
        height,
        [(250, 925), (960, 955), (890, 1335), (250, 1305)],
        sample_offset=(0, 300),
        feather=24,
        darken=0.26,
    )
    write_png(ROOT / "assets" / "fleet-hatch-no-plate.png", width, height, rows)


def edit_sedan():
    width, height, rows = read_png("/private/tmp/fleet-sedan.png")
    # Remove both visible German plates by continuing the surrounding black grille.
    fill_plate_with_grille(
        rows,
        width,
        height,
        [(3370, 1165), (4290, 1185), (4285, 1400), (3400, 1390)],
        sample_offset=(-120, 280),
        feather=22,
        darken=0.2,
    )
    fill_plate_with_grille(
        rows,
        width,
        height,
        [(3160, 1405), (4080, 1395), (4100, 1710), (3175, 1725)],
        sample_offset=(0, 265),
        feather=26,
        darken=0.24,
    )
    write_png(ROOT / "assets" / "fleet-sedan-no-plate.png", width, height, rows)


if __name__ == "__main__":
    edit_hatch()
    edit_sedan()
