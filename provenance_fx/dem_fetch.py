"""Fetch free terrain elevation for a search box (no account needed).

Source: the AWS Open Data "Terrain Tiles" (Mapzen/Tilezen terrarium PNG tiles),
https://registry.opendata.aws/terrain-tiles/ . Each 256x256 PNG encodes elevation as
    metres = R * 256 + G + B / 256 - 32768.
In the US the source data is mostly USGS 3DEP (about 10 m) and SRTM elsewhere.
Zoom 12 gives roughly 29 m pixels at 40 degrees latitude.
Tiles are cached under ~/.cache/provenance/terrarium.
"""
from __future__ import annotations

import io
import math
import os
import urllib.request

import numpy as np

from .geo import DEM

URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
CACHE = os.path.expanduser("~/.cache/provenance/terrarium")


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile_y_to_lat(y, z):
    n = 2 ** z
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))


def decode_terrarium(rgb):
    rgb = np.asarray(rgb, dtype=np.float64)
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


def _get_tile(z, x, y, log=print):
    from PIL import Image

    path = os.path.join(CACHE, str(z), str(x), f"{y}.png")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with urllib.request.urlopen(URL.format(z=z, x=x, y=y), timeout=30) as r:
            data = r.read()
        with open(path, "wb") as fh:
            fh.write(data)
    img = Image.open(path).convert("RGB")
    return decode_terrarium(np.array(img))


def fetch_dem(bbox, zoom: int = 12, margin_deg: float = 0.05, log=print) -> DEM:
    """bbox = (lat_min, lat_max, lon_min, lon_max). Returns a DEM covering it plus a margin."""
    la0, la1, lo0, lo1 = bbox
    la0, la1, lo0, lo1 = la0 - margin_deg, la1 + margin_deg, lo0 - margin_deg, lo1 + margin_deg
    x0, y1 = lonlat_to_tile(lo0, la0, zoom)
    x1, y0 = lonlat_to_tile(lo1, la1, zoom)
    xs = range(int(x0), int(x1) + 1)
    ys = range(int(y0), int(y1) + 1)
    log(f"DEM: fetching {len(xs) * len(ys)} terrain tiles at zoom {zoom}")
    rows = []
    for ty in ys:
        rows.append(np.concatenate([_get_tile(zoom, tx, ty, log) for tx in xs], axis=1))
    mosaic = np.concatenate(rows, axis=0)  # north at top
    H, W = mosaic.shape
    px_y = ys[0] + (np.arange(H) + 0.5) / 256.0
    px_x = xs[0] + (np.arange(W) + 0.5) / 256.0
    lats = np.array([tile_y_to_lat(v, zoom) for v in px_y])
    lons = px_x / (2 ** zoom) * 360.0 - 180.0
    # ascending latitude for the interpolator
    lats, mosaic = lats[::-1], mosaic[::-1]
    # Terrarium includes sea-floor depth; a listener is on land or at the water surface,
    # so clamp at 0 m. (This would be wrong below sea level, e.g. Death Valley.)
    mosaic = np.maximum(mosaic, 0.0)
    log(f"DEM: {H}x{W} pixels, elevation {mosaic.min():.0f} to {mosaic.max():.0f} m")
    return DEM(lats, lons, mosaic)
