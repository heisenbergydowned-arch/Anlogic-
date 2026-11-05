"""Independent floating-point reference for the 39-feature hardware interface.

CSV input: 1024 rows, six columns Ax,Ay,Az,Bx,By,Bz, no header, signed int16 codes.
Example: python feature_reference.py frame.csv --process 1.2 35 0.1 6000
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np

N = 1024
DEFAULT_EDGES = np.array([1, 13, 39, 65, 103, 154, 205, 257, 513])
FEATURE_NAMES = []
for point in ("a", "b"):
    FEATURE_NAMES += [f"{stat}_{point}_{axis}" for stat in ("rms", "pp", "kurt") for axis in "xyz"]
    FEATURE_NAMES += [f"band{point}{band}" for band in range(8)]
FEATURE_NAMES += ["ratio_ab", "current", "temp", "pressure", "rpm"]

def extract(raw: np.ndarray, process=(0., 0., 0., 0.), edges=DEFAULT_EDGES) -> np.ndarray:
    """raw is (6,1024). RMS/kurtosis use mean-removed, unwindowed samples.

    Bands combine three axes' one-sided Hann-windowed powers, DC excluded,
    Nyquist included. Each point's eight fractions sum to one unless all zero.
    RTL also keeps the exact frame mean using ten fractional raw-code bits.
    """
    raw = np.asarray(raw, dtype=np.float64)
    edges = np.asarray(edges)
    if raw.shape != (6, N):
        raise ValueError("Expected (6,1024), axis-major")
    if not np.all(np.isfinite(raw)) or np.any(raw < -32768) or np.any(raw > 32767):
        raise ValueError("Samples must be finite signed int16 codes")
    if not np.all(raw == np.floor(raw)):
        raise ValueError("Raw samples must be integer codes")
    if edges.shape != (9,) or edges[0] != 1 or edges[-1] != 513 or not np.all(np.diff(edges) > 0) or not np.all(edges == np.floor(edges)):
        raise ValueError("Edges must cover bins [1,513), strictly increasing")
    if len(process) != 4 or not np.all(np.isfinite(process)):
        raise ValueError("Process tuple is current A, temperature degC, pressure kPa, RPM")
    edges = edges.astype(int)
    centered = raw - raw.mean(axis=1, keepdims=True)
    variance = np.mean(centered**2, axis=1)
    rms = np.sqrt(variance) / 4096.
    pp = np.ptp(raw, axis=1) / 4096.
    kurt = np.divide(np.mean(centered**4, axis=1), variance**2,
                     out=np.zeros(6), where=variance > 0)
    hann = .5 * (1 - np.cos(2*np.pi*np.arange(N)/N))
    spectrum = np.fft.rfft(centered * hann, axis=1) / N
    power = np.abs(spectrum)**2
    power[:, 1:-1] *= 2
    result = []
    for point in range(2):
        axes = slice(point*3, point*3+3)
        merged = power[axes].sum(axis=0)
        bands = np.array([merged[edges[b]:edges[b+1]].sum() for b in range(8)])
        if bands.sum():
            bands /= bands.sum()
        result.extend(rms[axes]); result.extend(pp[axes]); result.extend(kurt[axes]); result.extend(bands)
    a, b = rms[:2].sum(), rms[3:5].sum()
    ratio = np.clip(a/b, .3, 6) if b > 0 else (1. if a == 0 else 6.)
    return np.array([*result, ratio, *process])

def process_convert(current_mean, pressure_mean, temperature_raw, period,
                    clk_hz=100_000_000, pulses_per_rev=2,
                    current_zero=16384., pressure_zero=16384.,
                    current_slope=5/32768/.185, pressure_slope=5/32768):
    """Nominal calibration. Means are raw codes; temperature input is DS18B20 /16 degC.
    FG period is the window mean of measured periods, in clk cycles.
    Sensor validity and aging belong to capture, not this numeric helper.
    """
    return ((current_mean-current_zero)*current_slope, temperature_raw/16.,
            (pressure_mean-pressure_zero)*pressure_slope,
            60*clk_hz/(period*pulses_per_rev) if period > 0 and pulses_per_rev > 0 else 0.)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--process", type=float, nargs=4, required=True,
                        metavar=("CURRENT_A", "TEMP_C", "PRESSURE_KPA", "RPM"))
    parser.add_argument("--edges", type=int, nargs=9, default=DEFAULT_EDGES.tolist())
    parser.add_argument("--fs", type=float, default=4000.)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not np.isfinite(args.fs) or args.fs <= 0: parser.error("--fs must be positive")
    raw = np.load(args.input) if args.input.suffix.lower() == ".npy" else np.loadtxt(args.input, delimiter=",")
    if raw.shape == (N, 6): raw = raw.T
    values = extract(raw, args.process, args.edges)
    payload = {"feature_names": FEATURE_NAMES, "features": values.tolist(),
               "fs_hz": args.fs, "fft_size": N, "bin_edges": args.edges,
               "edge_hz": (np.array(args.edges)*args.fs/N).tolist(),
               "note": "Configurable provisional extraction contract; real-data model retraining required."}
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded+"\n", encoding="utf-8")
    else: print(encoded)

if __name__ == "__main__": main()
