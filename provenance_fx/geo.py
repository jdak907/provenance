"""Local coordinate frame and digital elevation model (DEM) helpers."""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
from scipy.interpolate import RegularGridInterpolator

EARTH_R = 6371008.8  # mean Earth radius, metres


@dataclass
class LocalFrame:
    """Flat east/north frame around a reference point.

    Equirectangular projection. Error is well under 0.1 percent across a
    region of about 100 km, which is far below the 100 m grid we search.
    """

    lat0: float
    lon0: float

    def to_xy(self, lat, lon):
        lat = np.asarray(lat, dtype=float)
        lon = np.asarray(lon, dtype=float)
        x = np.radians(lon - self.lon0) * EARTH_R * np.cos(np.radians(self.lat0))
        y = np.radians(lat - self.lat0) * EARTH_R
        return x, y

    def to_latlon(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        lat = self.lat0 + np.degrees(y / EARTH_R)
        lon = self.lon0 + np.degrees(x / (EARTH_R * np.cos(np.radians(self.lat0))))
        return lat, lon


class DEM:
    """Ground elevation (metres above mean sea level) on a regular lat/lon grid."""

    def __init__(self, lats, lons, elev):
        self.lats = np.asarray(lats, dtype=float)
        self.lons = np.asarray(lons, dtype=float)
        self.elev = np.asarray(elev, dtype=float)
        self._interp = RegularGridInterpolator(
            (self.lats, self.lons), self.elev, bounds_error=False, fill_value=None
        )

    @classmethod
    def flat(cls, height_m: float = 0.0):
        lats = np.array([-90.0, 90.0])
        lons = np.array([-180.0, 180.0])
        return cls(lats, lons, np.full((2, 2), float(height_m)))

    @classmethod
    def load(cls, path: str):
        """Load a DEM from .npz (keys lats, lons, elev) or a .json with a constant height."""
        if path.endswith(".json"):
            return cls.flat(json.load(open(path))["height_m"])
        if path.endswith((".tif", ".tiff")):
            return cls._load_geotiff(path)
        d = np.load(path)
        return cls(d["lats"], d["lons"], d["elev"])

    @classmethod
    def _load_geotiff(cls, path):  # pragma: no cover - optional dependency
        try:
            import rasterio
        except ImportError as e:
            raise SystemExit("GeoTIFF DEMs need 'pip install rasterio'. Or convert to .npz.") from e
        with rasterio.open(path) as src:
            elev = src.read(1).astype(float)
            t = src.transform
            lons = t.c + t.a * (np.arange(src.width) + 0.5)
            lats = t.f + t.e * (np.arange(src.height) + 0.5)
        if lats[0] > lats[-1]:
            lats = lats[::-1]
            elev = elev[::-1]
        return cls(lats, lons, elev)

    def save(self, path: str):
        np.savez_compressed(path, lats=self.lats, lons=self.lons, elev=self.elev)

    def elevation(self, lat, lon):
        lat = np.asarray(lat, dtype=float)
        lon = np.asarray(lon, dtype=float)
        pts = np.stack([lat.ravel(), lon.ravel()], axis=-1)
        return self._interp(pts).reshape(lat.shape)
