"""Offline model of the Android OpenPhotoEdit export pipeline.

This is a numpy port of ``BitmapEditor.applyParams`` from the OpenPhotoEdit
Android app (``com.killt.openphotoedit``; source under
``apps/openphotoedit/openphotoedit_android`` in the OS-Omni-V2 app tree).
Export always goes through that CPU path (``saveCurrentImage`` ->
``BitmapEditor.applyParams`` -> ``Bitmap.compress(JPEG, 94)``), never through
the GPU preview renderer, so the exported pixels can be reproduced offline.

It is used to derive and check the calibration-stripe medians that the four
v1 Android OpenPhoto task evaluators expect.  Only the operations the task
recipes use are ported (Edit: exposure/brightness/contrast/saturation/
temperature/structure; Portrait: smooth/whiten/rosy/lip colour; Landscape:
structure/sky/foliage/warm sun/cool tone/HDR; the HSL mixer; the colour
filters with their Amount).  Requesting any other operation raises, so a
recipe cannot silently be modelled as a no-op.

Arithmetic is float32 like the Kotlin source.  Slider values are the values
the editor stores; the slider label shows ``value.toInt()``, so a label of
``+6`` means a stored value in ``[6, 7)`` and ``-4`` one in ``(-5, -4]``.

Run ``python -m tools.openphoto_android_edit_model`` to print the modelled
stripe medians for every task profile.
"""

from __future__ import annotations

import io
import itertools
import statistics
from typing import Any, Iterable, Mapping

import numpy as np
from PIL import Image

F = np.float32

#: Export encoder settings: ``Bitmap.compress(JPEG, 94)``; Skia encodes 4:2:0.
EXPORT_JPEG_QUALITY = 94
EXPORT_JPEG_SUBSAMPLING = 2

#: Slider keys (``EditCatalog``) the model implements.
SUPPORTED_KEYS = frozenset(
    {
        "exposure", "brightness", "contrast", "saturation", "temperature",
        "clarity", "smoothSkin", "whiten", "rosy", "lipColor",
        "sky", "green", "warmSun", "coolTone", "hdr",
        "filterId", "filterStrength",
    }
    | {f"hsl{band}{kind}" for band in ("Red", "Orange", "Yellow", "Green", "Cyan", "Blue", "Purple", "Magenta")
       for kind in ("", "Hue", "Luminance")}
)

FILTER_IDS = {"Original": 0, "Clean": 1, "Film": 2, "Cream": 3, "Portrait": 4, "Sunset": 5, "Night": 6}

_HSL_BANDS = ("Red", "Orange", "Yellow", "Green", "Cyan", "Blue", "Purple", "Magenta")


# --------------------------------------------------------------- helpers
def _smooth_step(edge0: float, edge1: float, value: np.ndarray) -> np.ndarray:
    x = np.clip((value - F(edge0)) / F(edge1 - edge0), F(0), F(1)).astype(F)
    return (x * x * (F(3) - F(2) * x)).astype(F)


def _mix(start: np.ndarray, end: np.ndarray, amount: Any) -> np.ndarray:
    return (start + (end - start) * np.clip(F(amount) if np.isscalar(amount) else amount, F(0), F(1))).astype(F)


def _gaussian(x: np.ndarray, y: np.ndarray, cx: float, cy: float, sx: float, sy: float) -> np.ndarray:
    dx = (x - F(cx)) / F(sx)
    dy = (y - F(cy)) / F(sy)
    return np.exp(-(dx * dx + dy * dy).astype(np.float64)).astype(F)


def _skin_mask(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    warm = ((r > g) & (g > b)).astype(F)
    spread = F(1) - np.minimum(F(1), (np.abs(r - g) + np.abs(g - b)) / F(240))
    bright = np.minimum(F(1), np.maximum(F(0), (r + g + b - F(180)) / F(420)))
    return np.clip(warm * spread * bright * F(1.35), F(0), F(1)).astype(F)


def _box_blur(rgb: np.ndarray, radius: int) -> np.ndarray:
    """``BitmapEditor.boxBlur``: separable box, edge clamp, integer division per pass."""

    window = radius * 2 + 1
    src = rgb.astype(np.int64)
    height, width, _ = src.shape
    padded = np.pad(src, ((0, 0), (radius, radius + 1), (0, 0)), mode="edge")
    csum = np.cumsum(padded, axis=1)
    csum = np.concatenate([np.zeros((height, 1, 3), dtype=np.int64), csum], axis=1)
    horizontal = (csum[:, window:window + width] - csum[:, 0:width]) // window
    padded = np.pad(horizontal, ((radius, radius + 1), (0, 0), (0, 0)), mode="edge")
    csum = np.cumsum(padded, axis=0)
    csum = np.concatenate([np.zeros((1, width, 3), dtype=np.int64), csum], axis=0)
    vertical = (csum[window:window + height] - csum[0:height]) // window
    return vertical.astype(F)


def _rgb_to_hsv(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rf = np.clip(r / F(255), F(0), F(1)).astype(F)
    gf = np.clip(g / F(255), F(0), F(1)).astype(F)
    bf = np.clip(b / F(255), F(0), F(1)).astype(F)
    mx = np.maximum(rf, np.maximum(gf, bf))
    mn = np.minimum(rf, np.minimum(gf, bf))
    delta = mx - mn
    safe = np.where(delta <= F(0.00001), F(1), delta)
    hue_r = np.mod((gf - bf) / safe / F(6), F(1))
    hue_g = ((bf - rf) / safe + F(2)) / F(6)
    hue_b = ((rf - gf) / safe + F(4)) / F(6)
    hue = np.where(delta <= F(0.00001), F(0), np.where(mx == rf, hue_r, np.where(mx == gf, hue_g, hue_b)))
    sat = np.where(mx <= F(0.00001), F(0), delta / np.where(mx <= F(0.00001), F(1), mx))
    return hue.astype(F), sat.astype(F), mx.astype(F)


def _hsv_to_rgb(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    hue = np.mod(h, F(1)) * F(6)
    sector = np.floor(hue).astype(np.int64)
    f = (hue - sector).astype(F)
    p = v * (F(1) - s)
    q = v * (F(1) - f * s)
    t = v * (F(1) - (F(1) - f) * s)
    sector = sector % 6
    r = np.choose(sector, [v, q, p, p, t, v])
    g = np.choose(sector, [t, v, v, q, p, p])
    b = np.choose(sector, [p, p, t, v, v, q])
    return (r * F(255)).astype(F), (g * F(255)).astype(F), (b * F(255)).astype(F)


def _band_masks(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> list[np.ndarray]:
    ss = _smooth_step
    red = ss(10, 76, r - np.maximum(g, b)) * (F(1) - ss(24, 94, g - b))
    orange = (ss(12, 76, r - b) * ss(-18, 56, g - b) * (F(1) - ss(36, 124, np.abs(r - g)))
              * (F(1) - ss(-6, 58, g - r)))
    yellow = ss(20, 92, np.minimum(r, g) - b) * (F(1) - ss(22, 96, np.abs(r - g)))
    green = ss(10, 78, g - np.maximum(r, b))
    cyan = ss(12, 82, np.minimum(g, b) - r) * (F(1) - ss(22, 96, np.abs(g - b)))
    blue = ss(10, 78, b - np.maximum(r, g))
    purple = ss(10, 82, np.minimum(r, b) - g) * (F(1) - ss(30, 118, np.abs(r - b)))
    magenta = ss(12, 82, np.minimum(r, b) - g) * ss(-36, 64, r - b)
    return [np.clip(m, F(0), F(1)).astype(F) for m in (red, orange, yellow, green, cyan, blue, purple, magenta)]


def _selective_colors(r, g, b, hue_adj, sat_adj, lum_adj):
    """``applySelectiveColors``: masks come from the colour entering the mixer."""

    masks = _band_masks(r, g, b)
    out = [r.copy(), g.copy(), b.copy()]
    for index, mask in enumerate(masks):
        hue_amount, sat_amount, lum_amount = F(hue_adj[index]), F(sat_adj[index]), F(lum_adj[index])
        if abs(hue_amount) + abs(sat_amount) + abs(lum_amount) <= 0.001:
            continue
        active = mask > F(0.001)
        if not np.any(active):
            continue
        influence = np.clip(mask, F(0), F(1))
        h, s, v = _rgb_to_hsv(out[0], out[1], out[2])
        h = np.mod(h + hue_amount * influence * F(0.12), F(1)).astype(F)
        scale = F(1) + sat_amount * influence * (F(1.10) if sat_amount >= 0 else F(0.88))
        s = np.clip(s * scale, F(0), F(1)).astype(F)
        v = np.clip(v + max(float(sat_amount), 0.0) * influence * F(0.06) + lum_amount * influence * F(0.32),
                    F(0), F(1)).astype(F)
        nr, ng, nb = _hsv_to_rgb(h, s, v)
        out = [np.where(active, nr, out[0]), np.where(active, ng, out[1]), np.where(active, nb, out[2])]
    return out


def _apply_filter(filter_id: int, r, g, b):
    if filter_id == 1:
        return r * F(1.02) + F(3), g * F(1.03) + F(2), b * F(0.99)
    if filter_id == 2:
        return r * F(1.06) + F(10), g * F(0.98) + F(4), b * F(0.88) + F(8)
    if filter_id == 3:
        return r * F(1.04) + F(8), g * F(1.05) + F(10), b * F(1.07) + F(12)
    if filter_id == 4:
        return r * F(1.05) + F(10), g * F(1.00) + F(6), b * F(0.98) + F(4)
    if filter_id == 5:
        return r * F(1.12) + F(16), g * F(1.02) + F(8), b * F(0.86)
    if filter_id == 6:
        return r * F(0.90), g * F(0.96) + F(2), b * F(1.12) + F(12)
    return r, g, b


# ------------------------------------------------------------ lip region
def _lip_color_likelihood(r, g, b):
    ss = _smooth_step
    mx = np.maximum(np.maximum(r, np.maximum(g, b)), F(1))
    mn = np.minimum(r, np.minimum(g, b))
    sat = (mx - mn) / mx
    luma = r * F(0.299) + g * F(0.587) + b * F(0.114)
    skin = _skin_mask(r, g, b)
    defined = (ss(7, 44, r - g) * ss(10, 68, r - b) * ss(-24, -4, b - g) * ss(0.10, 0.34, sat)
               * ss(42, 92, luma) * (F(1) - ss(220, 252, luma)) * ss(34, 80, mx) * (F(1) - skin * F(0.36)))
    red_bias = np.maximum(ss(4, 32, r - g), ss(2, 34, r - (g + b) * F(0.5)))
    natural = (red_bias * ss(-6, 42, r - b) * ss(-24, -4, b - g)
               * ss(0.055, 0.24, sat) * (F(1) - ss(0.72, 0.95, sat))
               * ss(42, 84, luma) * (F(1) - ss(206, 246, luma))
               * (F(0.25) + (F(1) - ss(142, 206, luma)) * ss(34, 72, luma) * F(0.75))
               * ss(36, 78, mx) * (F(1) - skin * F(0.80)))
    return np.clip(np.maximum(np.clip(defined, 0, 1), np.clip(natural, 0, 1)), F(0), F(1)).astype(F)


def _gauss1d(value, center, spread):
    return np.exp(-(((value - F(center)) / F(spread)) ** 2).astype(np.float64)).astype(F)


def _detect_lip_region(rgb: np.ndarray) -> tuple[float, float, float, float, float]:
    """``LipRegionDetector.detect`` on the decoded source pixels."""

    height, width, _ = rgb.shape
    fallback = (0.50, 0.50, 0.13, 0.045, 0.0)
    step = max(1, min(width, height) // 360)
    y_start = min(max(int(height * F(0.34)), 0), height - 1)
    y_end = min(max(int(height * F(0.70)), y_start), height - 1)
    x_start = min(max(int(width * F(0.18)), 0), width - 1)
    x_end = min(max(int(width * F(0.82)), x_start), width - 1)
    ys = np.arange(y_start, y_end + 1, step)
    xs = np.arange(x_start, x_end + 1, step)
    yf = (ys.astype(F) / F(max(1, height - 1)))[:, None]
    xf = (xs.astype(F) / F(max(1, width - 1)))[None, :]
    sub = rgb[np.ix_(ys, xs)].astype(F)
    r, g, b = sub[..., 0], sub[..., 1], sub[..., 2]
    ss = _smooth_step
    mouth_band = (_gauss1d(xf, 0.50, 0.30) * _gauss1d(yf, 0.535, 0.17)).clip(0, 1)
    mouth_band = mouth_band * ss(0.455, 0.505, yf) * (F(1) - ss(0.635, 0.72, yf))
    center_bias = F(1) - ss(0.20, 0.34, np.abs(xf - F(0.5)))
    weight = ss(0.18, 0.70, _lip_color_likelihood(r, g, b)) * mouth_band * (F(0.72) + center_bias * F(0.28))
    if float(weight.sum()) < 0.001:
        return fallback
    rows, cols = 36, 48
    by = np.clip((((yf - F(0.34)) / F(0.36)) * rows).astype(np.int64), 0, rows - 1)
    bx = np.clip((((xf - F(0.18)) / F(0.64)) * cols).astype(np.int64), 0, cols - 1)
    buckets = np.zeros((rows, cols), dtype=np.float64)
    np.add.at(buckets, (np.broadcast_to(by, weight.shape), np.broadcast_to(bx, weight.shape)), weight)
    peak_y, peak_x = np.unravel_index(int(np.argmax(buckets)), buckets.shape)
    peak_xf = 0.18 + (peak_x + 0.5) / cols * 0.64
    peak_yf = 0.34 + (peak_y + 0.5) / rows * 0.36
    focus = weight * _gauss1d(xf, peak_xf, 0.160) * _gauss1d(yf, peak_yf, 0.080)
    focus = np.where(focus > F(0.0001), focus, F(0)).astype(np.float64)
    total = float(focus.sum())
    if total < 0.001:
        return fallback
    xx = np.broadcast_to(xf, focus.shape).astype(np.float64)
    yy = np.broadcast_to(yf, focus.shape).astype(np.float64)
    cx = min(max(float((focus * xx).sum() / total), 0.24), 0.76)
    cy = min(max(float((focus * yy).sum() / total), 0.40), 0.66)
    var_x = max(0.0, float((focus * xx * xx).sum() / total) - cx * cx)
    var_y = max(0.0, float((focus * yy * yy).sum() / total) - cy * cy)
    rx = min(max(var_x ** 0.5 * 1.85, 0.050), 0.115)
    ry = min(max(var_y ** 0.5 * 1.65, 0.014), 0.036)
    density = total / max(1.0, float((x_end - x_start) * (y_end - y_start)))
    confidence = float(_smooth_step(0.00015, 0.006, np.array(density, dtype=F)))
    return cx, cy, rx, ry, confidence


def _lip_mask(xf, yf, r, g, b, region) -> np.ndarray:
    cx, cy, rx, ry, confidence = region
    gate = _smooth_step(0.18, 0.70, _lip_color_likelihood(r, g, b))
    if confidence <= 0.001:
        upper = _gaussian(xf, yf, 0.5, 0.480, 0.115, 0.036)
        lower = _gaussian(xf, yf, 0.5, 0.515, 0.135, 0.044)
        band = _smooth_step(0.38, 0.45, yf) * (F(1) - _smooth_step(0.62, 0.72, yf))
        return np.clip(np.maximum(upper, lower) * band * (F(0.05) + gate * F(0.95)), F(0), F(1)).astype(F)
    shape = np.clip(_gauss1d(xf, cx, rx) * _gauss1d(yf, cy, ry), F(0), F(1))
    tight = _smooth_step(0.18, 0.74, shape)
    core = _smooth_step(0.58, 0.92, shape)
    return np.clip((core * gate * F(0.18) + tight * gate * F(1.05)) * F(confidence), F(0), F(1)).astype(F)


# -------------------------------------------------------------- pipeline
def apply_params(source: np.ndarray, params: Mapping[str, float], *, origin: tuple[int, int] = (0, 0),
                 full_size: tuple[int, int] | None = None,
                 lip_region: tuple[float, float, float, float, float] | None = None) -> np.ndarray:
    """Return the float32 RGB result of ``applyParams`` before 8-bit clamping.

    ``source`` may be a crop of the full photo: ``origin`` is the crop's
    top-left pixel and ``full_size`` the full ``(width, height)``, so the
    position-dependent masks see full-frame coordinates.  Local blurs are then
    exact for pixels at least 9 px inside the crop.  ``lip_region`` must be the
    full-frame ``LipRegionDetector.detect`` result when cropping with Lip Color.
    """

    unknown = {key for key, value in params.items() if key not in SUPPORTED_KEYS and float(value) != 0.0}
    if unknown:
        raise NotImplementedError(f"edit model does not implement: {sorted(unknown)}")
    p = {key: F(params.get(key, 0.0)) for key in SUPPORTED_KEYS}
    base = np.asarray(source, dtype=np.uint8)[..., :3]
    height, width, _ = base.shape
    full_width, full_height = full_size or (width, height)
    if full_size is not None and p["lipColor"] > 0 and lip_region is None:
        raise ValueError("a cropped Lip Color evaluation needs the full-frame lip_region")
    rgb = base.astype(F)
    r, g, b = rgb[..., 0].copy(), rgb[..., 1].copy(), rgb[..., 2].copy()
    yf = ((np.arange(height) + origin[1]).astype(F) / F(max(1, full_height - 1)))[:, None]
    xf = ((np.arange(width) + origin[0]).astype(F) / F(max(1, full_width - 1)))[None, :]

    smooth = p["smoothSkin"] / F(100)
    if smooth > 0:
        blurred = _box_blur(base, 9)
        face = np.clip(_gaussian(xf, yf, 0.5, 0.48, 0.31, 0.43), F(0), F(1))
        raw_skin = _skin_mask(r, g, b) * face
        sr, sg, sb = blurred[..., 0], blurred[..., 1], blurred[..., 2]
        distance = np.abs(r - sr) * F(0.299) + np.abs(g - sg) * F(0.587) + np.abs(b - sb) * F(0.114)
        amount = np.clip(smooth * raw_skin * (F(1) - _smooth_step(28, 118, distance)) * F(1.85), F(0), F(1))
        amount = np.where(raw_skin > 0, amount, F(0))
        r, g, b = _mix(r, sr, amount), _mix(g, sg, amount), _mix(b, sb, amount)

    clarity = min(max(float(p["clarity"]) / 100.0, 0.0), 1.0)
    if clarity > 0:
        blurred = _box_blur(base, 8)
        base_luma = r * F(0.299) + g * F(0.587) + b * F(0.114)
        blur_luma = blurred[..., 0] * F(0.299) + blurred[..., 1] * F(0.587) + blurred[..., 2] * F(0.114)
        local = base_luma - blur_luma
        midtone = F(1) - _smooth_step(0, 116, np.abs(base_luma - F(128)))
        gain = F(clarity) * (F(0.18) + midtone * F(0.46))
        r, g, b = r + local * gain, g + local * gain, b + local * gain

    brightness = p["brightness"] * F(1.6)
    exposure = F(2.0 ** (float(p["exposure"]) / 100.0))
    r, g, b = (r + brightness) * exposure, (g + brightness) * exposure, (b + brightness) * exposure
    contrast = F(1) + p["contrast"] / F(115)
    r, g, b = (r - F(128)) * contrast + F(128), (g - F(128)) * contrast + F(128), (b - F(128)) * contrast + F(128)
    luma = r * F(0.299) + g * F(0.587) + b * F(0.114)
    saturation = F(1) + p["saturation"] / F(100)
    r, g, b = luma + (r - luma) * saturation, luma + (g - luma) * saturation, luma + (b - luma) * saturation

    temperature = p["temperature"] / F(100)
    warm, cool, green_boost = p["warmSun"] / F(100), p["coolTone"] / F(100), p["green"] / F(100)
    r = r + temperature * F(22) + warm * F(24) - cool * F(8)
    green_mask = np.minimum(F(1), np.maximum(F(0), (g - np.maximum(r, b)) / F(80)))
    g = g + warm * F(8) + green_boost * green_mask * F(26)
    b = b - (temperature * F(18) + warm * F(18))
    b = b + cool * F(24)

    whiten, rosy = p["whiten"] / F(100), p["rosy"] / F(100)
    skin = _skin_mask(r, g, b)
    r = r + whiten * skin * F(24) + rosy * skin * F(22)
    g = g + whiten * skin * F(18)
    b = b + whiten * skin * F(12) - rosy * skin * F(4)

    lip_color = p["lipColor"] / F(100)
    if lip_color > 0:
        region = lip_region if lip_region is not None else _detect_lip_region(base)
        mask = _lip_mask(xf, yf, base[..., 0].astype(F), base[..., 1].astype(F), base[..., 2].astype(F), region)
        mask = mask * lip_color
        on = mask > F(0.001)
        r = np.where(on, _mix(r, np.maximum(r, F(220)), mask * F(0.72)), r)
        g = np.where(on, _mix(g, g * F(0.50) + F(24), mask * F(0.68)), g)
        b = np.where(on, _mix(b, b * F(0.42) + F(28), mask * F(0.68)), b)

    sky_boost = p["sky"] / F(100)
    sky_color = np.minimum(F(1), np.maximum(F(0), (b - r + g - r) / F(190)))
    sky = np.where(yf < F(0.48), sky_color * sky_boost, F(0))
    r, g, b = r - sky * F(8), g + sky * F(8), b + sky * F(30)

    hdr_lift = p["hdr"] / F(100) * (F(128) - luma) / F(128)
    r, g, b = r + hdr_lift * F(18), g + hdr_lift * F(18), b + hdr_lift * F(18)

    hue_adj = [float(p[f"hsl{band}Hue"]) / 100.0 for band in _HSL_BANDS]
    sat_adj = [float(p[f"hsl{band}"]) / 100.0 for band in _HSL_BANDS]
    lum_adj = [float(p[f"hsl{band}Luminance"]) / 100.0 for band in _HSL_BANDS]
    if any(abs(v) > 0.001 for v in hue_adj + sat_adj + lum_adj):
        r, g, b = _selective_colors(r, g, b, hue_adj, sat_adj, lum_adj)

    amount = F(p["filterStrength"] / F(100))
    fr, fg, fb = _apply_filter(int(p["filterId"]), r, g, b)
    r, g, b = _mix(r, fr, amount), _mix(g, fg, amount), _mix(b, fb, amount)
    return np.stack([r, g, b], axis=-1).astype(F)


def to_8bit(result: np.ndarray) -> np.ndarray:
    """``clamp255``: clamp to [0, 255] then truncate toward zero."""

    return np.clip(result, 0, 255).astype(np.uint8)


def export_jpeg_roundtrip(pixels: np.ndarray) -> np.ndarray:
    """Encode like the app's export and decode like the evaluator (PIL)."""

    buffer = io.BytesIO()
    Image.fromarray(pixels, "RGB").save(
        buffer, format="JPEG", quality=EXPORT_JPEG_QUALITY, subsampling=EXPORT_JPEG_SUBSAMPLING
    )
    buffer.seek(0)
    with Image.open(buffer) as decoded:
        return np.asarray(decoded.convert("RGB"))


def stripe_medians(pixels: np.ndarray, sample_boxes: Mapping[str, Iterable[int]]) -> dict[str, list[int]]:
    """The evaluator's statistic: per-channel ``int(statistics.median(...))`` over each box."""

    medians: dict[str, list[int]] = {}
    for stripe, box in sample_boxes.items():
        x1, y1, x2, y2 = (int(v) for v in box)
        crop = pixels[y1:y2, x1:x2]
        medians[str(stripe)] = [int(statistics.median(crop[..., channel].ravel().tolist())) for channel in range(3)]
    return medians


def recipe_params(recipe: Iterable[tuple]) -> dict[str, float]:
    """Translate brief steps such as ``("HSL", "Blue", "Hue", -6)`` into editor keys."""

    landscape = {"Structure": "clarity", "Sky": "sky", "Foliage": "green", "Warm Sun": "warmSun",
                 "Cool Tone": "coolTone", "HDR": "hdr"}
    edit = {"Exposure": "exposure", "Brightness": "brightness", "Contrast": "contrast",
            "Saturation": "saturation", "Temperature": "temperature", "Structure": "clarity"}
    portrait = {"Smooth": "smoothSkin", "Whiten": "whiten", "Rosy": "rosy", "Lip Color": "lipColor"}
    params: dict[str, float] = {}
    for step in recipe:
        group = step[0]
        if group == "HSL":
            _, band, mode, value = step
            suffix = {"Hue": "Hue", "Saturation": "", "Luminance": "Luminance"}[mode]
            params[f"hsl{band}{suffix}"] = float(value)
        elif group == "Filters":
            _, name, value = step
            params["filterId"] = float(FILTER_IDS[name])
            params["filterStrength"] = float(value)
        else:
            _, label, value = step
            table = {"Edit": edit, "Landscape": landscape, "Portrait": portrait}[group]
            params[table[label]] = float(value)
    return params


def displayed_value_interval(value: float) -> tuple[float, float]:
    """Stored values whose slider label (``toInt()``) reads ``value``."""

    if value > 0:
        return float(value), float(value) + 0.999
    if value < 0:
        return float(value) - 0.999, float(value)
    return -0.999, 0.999


def model_export_medians(source: np.ndarray, params: Mapping[str, float],
                         sample_boxes: Mapping[str, Iterable[int]], *, jpeg: bool = True) -> dict[str, list[int]]:
    pixels = to_8bit(apply_params(source, params))
    if jpeg:
        pixels = export_jpeg_roundtrip(pixels)
    return stripe_medians(pixels, sample_boxes)


def stripe_median_envelope(source: np.ndarray, params: Mapping[str, float],
                           sample_boxes: Mapping[str, Iterable[int]], *, random_samples: int = 256,
                           seed: int = 0) -> dict[str, list[list[int]]]:
    """Per-channel ``[min, max]`` of the stripe medians over label-preserving slider values.

    Every non-filter slider is swept over the interval of stored values that
    display the requested label (``displayed_value_interval``): all interval
    corners plus ``random_samples`` uniform interior points.  The filter id is
    discrete and fixed.  Medians are taken before the export JPEG round trip,
    whose effect is measured separately.  Only a padded crop around the boxes
    is processed, with full-frame coordinates.
    """

    keys = [key for key, value in params.items() if key != "filterId" and float(value) != 0.0]
    boxes = {stripe: tuple(int(v) for v in box) for stripe, box in sample_boxes.items()}
    height, width = source.shape[:2]
    pad = 24
    left = max(0, min(b[0] for b in boxes.values()) - pad)
    top = max(0, min(b[1] for b in boxes.values()) - pad)
    right = min(width, max(b[2] for b in boxes.values()) + pad)
    bottom = min(height, max(b[3] for b in boxes.values()) + pad)
    crop = np.asarray(source)[top:bottom, left:right, :3]
    local_boxes = {s: (b[0] - left, b[1] - top, b[2] - left, b[3] - top) for s, b in boxes.items()}
    lip_region = _detect_lip_region(np.asarray(source)[..., :3]) if float(params.get("lipColor", 0)) > 0 else None
    intervals = [displayed_value_interval(float(params[key])) for key in keys]
    trials = list(itertools.product(*intervals))
    rng = np.random.default_rng(seed)
    for _ in range(random_samples):
        trials.append(tuple(float(rng.uniform(lo, hi)) for lo, hi in intervals))
    low = {s: [255, 255, 255] for s in boxes}
    high = {s: [0, 0, 0] for s in boxes}
    for values in trials:
        trial = dict(params)
        trial.update(dict(zip(keys, values)))
        result = to_8bit(apply_params(crop, trial, origin=(left, top), full_size=(width, height),
                                      lip_region=lip_region))
        for stripe, rgb in stripe_medians(result, local_boxes).items():
            for channel in range(3):
                low[stripe][channel] = min(low[stripe][channel], rgb[channel])
                high[stripe][channel] = max(high[stripe][channel], rgb[channel])
    return {s: [[low[s][c], high[s][c]] for c in range(3)] for s in boxes}


#: The slider settings each v1 brief asks for, per evaluator profile (UI labels).
TASK_RECIPES: dict[str, tuple[tuple, ...]] = {
    "clown_side_portrait_17": (
        ("Edit", "Exposure", 6), ("Edit", "Contrast", 12), ("Edit", "Brightness", 5), ("Edit", "Temperature", -4),
        ("Portrait", "Smooth", 6), ("Portrait", "Whiten", 3), ("Portrait", "Lip Color", 8),
        ("HSL", "Blue", "Hue", -6), ("HSL", "Blue", "Saturation", 16),
        ("HSL", "Red", "Saturation", 12), ("HSL", "Red", "Luminance", -4),
        ("Filters", "Film", 18),
    ),
    "clown_front_portrait_16": (
        ("Edit", "Exposure", 4), ("Edit", "Contrast", 18), ("Edit", "Saturation", 6), ("Edit", "Temperature", -3),
        ("Portrait", "Smooth", 5), ("Portrait", "Whiten", 3), ("Portrait", "Lip Color", 14), ("Portrait", "Rosy", 5),
        ("HSL", "Cyan", "Hue", -8), ("HSL", "Cyan", "Saturation", 20),
        ("HSL", "Red", "Saturation", 18), ("HSL", "Red", "Luminance", -4),
        ("Filters", "Clean", 15),
    ),
    "standing_coast_landscape_18": (
        ("Edit", "Exposure", -4), ("Edit", "Contrast", 16), ("Edit", "Saturation", -8),
        ("Landscape", "Structure", 18), ("Landscape", "Sky", 14), ("Landscape", "Cool Tone", 6), ("Landscape", "HDR", 8),
        ("HSL", "Blue", "Saturation", 12), ("HSL", "Blue", "Luminance", -7), ("HSL", "Cyan", "Hue", -5),
        ("Filters", "Film", 22),
    ),
    "seated_coast_landscape_17": (
        ("Edit", "Exposure", 8), ("Edit", "Brightness", 6), ("Edit", "Contrast", 10), ("Edit", "Temperature", 5),
        ("Portrait", "Smooth", 8), ("Portrait", "Whiten", 4),
        ("HSL", "Orange", "Luminance", 7), ("HSL", "Blue", "Saturation", 10),
        ("Landscape", "Structure", 12),
        ("Filters", "Clean", 18),
    ),
    "indoor_cooking_portrait_20": (
        ("Edit", "Exposure", 9), ("Edit", "Brightness", 7), ("Edit", "Contrast", 6), ("Edit", "Temperature", 8),
        ("Edit", "Saturation", 5),
        ("Landscape", "Structure", 10), ("Landscape", "HDR", 12),
        ("HSL", "Orange", "Luminance", 8), ("HSL", "Orange", "Saturation", 6), ("HSL", "Yellow", "Hue", -3),
        ("Filters", "Clean", 16),
    ),
    "outdoor_cooking_portrait_16": (
        ("Landscape", "Structure", 12), ("Landscape", "Foliage", 8), ("Landscape", "Sky", 6), ("Landscape", "HDR", 10),
        ("Edit", "Exposure", 6), ("Edit", "Brightness", 5), ("Edit", "Contrast", 8), ("Edit", "Temperature", 6),
        ("HSL", "Green", "Saturation", 8), ("HSL", "Green", "Luminance", 5), ("HSL", "Orange", "Luminance", 6),
        ("Filters", "Clean", 14),
    ),
    "electric_guitar_portrait_21": (
        ("HSL", "Blue", "Hue", -4), ("HSL", "Blue", "Saturation", 18), ("HSL", "Blue", "Luminance", -6),
        ("HSL", "Cyan", "Luminance", 5),
        ("Edit", "Exposure", 4), ("Edit", "Contrast", 15), ("Edit", "Brightness", 6), ("Edit", "Temperature", -3),
        ("Landscape", "Structure", 20), ("Landscape", "HDR", 8),
        ("Filters", "Clean", 18),
        ("Edit", "Saturation", 7),
    ),
    "wood_guitar_portrait_17": (
        ("Edit", "Exposure", 5), ("Edit", "Contrast", 10), ("Edit", "Temperature", 12), ("Edit", "Brightness", 4),
        ("Landscape", "Structure", 16), ("Landscape", "Warm Sun", 10),
        ("HSL", "Orange", "Saturation", 12), ("HSL", "Orange", "Luminance", 4),
        ("HSL", "Red", "Hue", 3), ("HSL", "Yellow", "Hue", -4),
        ("Filters", "Film", 24),
    ),
}


if __name__ == "__main__":  # pragma: no cover - manual derivation aid
    import json

    from evaluators.cua_review.platforms.android import openphoto_calibration as calib

    for task_key, spec in calib.TASK_FIXTURES.items():
        for target in spec.targets:
            fixture = np.asarray(calib.decode_fixture(calib.build_fixture_bytes(spec, target)))
            params = recipe_params(TASK_RECIPES[target.profile_id])
            print(task_key, target.profile_id,
                  "nominal", json.dumps(model_export_medians(fixture, params, spec.sample_boxes)),
                  "label_range", json.dumps(stripe_median_envelope(fixture, params, spec.sample_boxes,
                                                                   random_samples=512, seed=1)),
                  flush=True)
