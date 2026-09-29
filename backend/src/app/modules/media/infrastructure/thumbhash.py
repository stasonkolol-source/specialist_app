"""ThumbHash: плейсхолдер фото в ~25 байт (ARCHITECTURE §10.3).

Порт `rgbaToThumbHash` из эталонной реализации Evan Wallace (github.com/evanw/thumbhash,
MIT). Mini App декодирует хэш пакетом `thumbhash` из npm. Округление — как Math.round,
порядок сложений — тот же, что в JS; побайтно хэши всё же могут разойтись на единицу в
отдельных коэффициентах: `cos` из libm и из V8 различаются в последнем бите. На картинке
это не видно (тест сверяет с векторами JS-версии с таким допуском).
"""

import math
from collections.abc import Sequence

MAX_SIDE = 100
"""Больше 100×100 кодировать медленно и бессмысленно: хэш хранит только низкие частоты."""


def _round(value: float) -> int:
    """Math.round из JS: половина — вверх (round() в Python — к чётному)."""
    return math.floor(value + 0.5)


def _encode_channel(
    channel: Sequence[float], w: int, h: int, nx: int, ny: int
) -> tuple[float, list[float], float]:
    """DCT канала: постоянная часть и нормированные переменные коэффициенты."""
    dc, scale = 0.0, 0.0
    ac: list[float] = []
    for cy in range(ny):
        cx = 0
        while cx * ny < nx * (ny - cy):
            fx = [math.cos(math.pi / w * cx * (x + 0.5)) for x in range(w)]
            f = 0.0
            for y in range(h):
                fy = math.cos(math.pi / h * cy * (y + 0.5))
                row = y * w
                for x in range(w):
                    f += channel[x + row] * fx[x] * fy
            f /= w * h
            if cx or cy:
                ac.append(f)
                scale = max(scale, abs(f))
            else:
                dc = f
            cx += 1
    if scale:
        ac = [0.5 + 0.5 / scale * f for f in ac]
    return dc, ac, scale


def rgba_to_thumbhash(w: int, h: int, rgba: bytes) -> bytes:
    """ThumbHash картинки `w`×`h` (не больше 100×100) из байтов RGBA."""
    if w > MAX_SIDE or h > MAX_SIDE:
        raise ValueError(f"{w}x{h} doesn't fit in {MAX_SIDE}x{MAX_SIDE}")
    if len(rgba) != w * h * 4:
        raise ValueError("rgba must hold w * h * 4 bytes")

    # средний цвет с учётом прозрачности
    avg_r = avg_g = avg_b = avg_a = 0.0
    for j in range(0, w * h * 4, 4):
        alpha = rgba[j + 3] / 255
        avg_r += alpha / 255 * rgba[j]
        avg_g += alpha / 255 * rgba[j + 1]
        avg_b += alpha / 255 * rgba[j + 2]
        avg_a += alpha
    if avg_a:
        avg_r /= avg_a
        avg_g /= avg_a
        avg_b /= avg_a

    has_alpha = avg_a < w * h
    l_limit = 5 if has_alpha else 7  # с прозрачностью — меньше бит на яркость
    lx = max(1, _round(l_limit * w / max(w, h)))
    ly = max(1, _round(l_limit * h / max(w, h)))

    # RGBA → LPQA поверх среднего цвета
    lum: list[float] = []
    yb: list[float] = []
    rg: list[float] = []
    alphas: list[float] = []
    for j in range(0, w * h * 4, 4):
        alpha = rgba[j + 3] / 255
        r = avg_r * (1 - alpha) + alpha / 255 * rgba[j]
        g = avg_g * (1 - alpha) + alpha / 255 * rgba[j + 1]
        b = avg_b * (1 - alpha) + alpha / 255 * rgba[j + 2]
        lum.append((r + g + b) / 3)
        yb.append((r + g) / 2 - b)
        rg.append(r - g)
        alphas.append(alpha)

    l_dc, l_ac, l_scale = _encode_channel(lum, w, h, max(3, lx), max(3, ly))
    p_dc, p_ac, p_scale = _encode_channel(yb, w, h, 3, 3)
    q_dc, q_ac, q_scale = _encode_channel(rg, w, h, 3, 3)
    a_dc, a_ac, a_scale = _encode_channel(alphas, w, h, 5, 5) if has_alpha else (0.0, [], 0.0)

    is_landscape = w > h
    header24 = (
        _round(63 * l_dc)
        | (_round(31.5 + 31.5 * p_dc) << 6)
        | (_round(31.5 + 31.5 * q_dc) << 12)
        | (_round(31 * l_scale) << 18)
        | (int(has_alpha) << 23)
    )
    header16 = (
        (ly if is_landscape else lx)
        | (_round(63 * p_scale) << 3)
        | (_round(63 * q_scale) << 9)
        | (int(is_landscape) << 15)
    )
    out = [header24 & 255, (header24 >> 8) & 255, header24 >> 16, header16 & 255, header16 >> 8]
    if has_alpha:
        out.append(_round(15 * a_dc) | (_round(15 * a_scale) << 4))
    start = len(out)
    index = 0
    for coefficients in (l_ac, p_ac, q_ac, a_ac) if has_alpha else (l_ac, p_ac, q_ac):
        for f in coefficients:
            position = start + (index >> 1)
            if position == len(out):
                out.append(0)
            out[position] |= _round(15 * f) << ((index & 1) << 2)
            index += 1
    return bytes(out)
