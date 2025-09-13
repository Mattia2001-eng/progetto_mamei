import io
import os
import csv
import math
import re
import datetime as dt
import numpy as np

# Backend headless per generare immagini senza display
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from flask import send_file, request

# =========================
# Config & costanti
# =========================
UNITS = {"hr": "bpm", "temp": "°C", "eda": "µS", "bvp": "a.u.", "ibi": "s", "acc": "g"}

# CSV attesi in data_samples/<username>/
CSV_FILES = {
    "acc":  "wrist_acc.csv",
    "bvp":  "wrist_bvp.csv",
    "eda":  "wrist_eda.csv",
    "hr":   "wrist_hr.csv",
    "ibi":  "wrist_ibi.csv",
    "temp": "wrist_skin_temperature.csv",
}

# =========================
# Utility generali
# =========================
def _downsample(xs, ys, max_points=1200):
    if len(xs) <= max_points:
        return xs, ys
    idx = np.linspace(0, len(xs) - 1, max_points, dtype=int)
    return [xs[i] for i in idx], [ys[i] for i in idx]

def _has_labeled(ax):
    handles, labels = ax.get_legend_handles_labels()
    return any(lbl and not lbl.startswith("_") for lbl in labels)

def _to_float(x):
    if x is None or x == "" or str(x).lower() in ("nan", "none"):
        return None
    try:
        return float(x)
    except Exception:
        return None

def _normalize_epoch(ts_list):
    """Ritorna epoch in secondi (accetta secondi o millisecondi)."""
    xs = [float(t) for t in ts_list]
    if xs and max(xs) > 1e12:  # valori in ms
        xs = [t / 1000.0 for t in xs]
    return xs

def _parse_window_param():
    """
    Supporta:
      - ?window=all (tutto il CSV)  [default]
      - ?window=24h, 7d, 30d, 12h, 3d, ecc.
      - compat: ?days=7 -> "7d"; ?days=1 -> "24h"
    """
    raw = request.args.get("window")
    if raw:
        w = raw.strip().lower()
    else:
        d = request.args.get("days", type=int)
        if d is None:
            return "all"
        if d <= 1:
            return "24h"
        return f"{d}d"

    if w == "all":
        return "all"
    m = re.fullmatch(r"(\d+)(h|d)", w)
    if m:
        return w
    return "all"

def _window_bounds_from_dataset(max_dt, window: str):
    """Calcola start/end prendendo come 'ancora' la data massima nel CSV."""
    end = max_dt
    if window == "all":
        return None, end
    if window.endswith("h"):
        hours = int(window[:-1])
        start = end - dt.timedelta(hours=hours)
    elif window.endswith("d"):
        days = int(window[:-1])
        start = end - dt.timedelta(days=days)
    else:
        start = None
    return start, end

# =========================
# Lettura CSV per sensore
# =========================
def _read_from_csv(username, sensor):
    """
    Restituisce (timestamps_epoch_sec, values_float) dal CSV del sensore.
      - acc: timestamp, ax, ay, az  -> magnitudo sqrt(ax^2 + ay^2 + az^2)
      - ibi: timestamp, duration    -> duration(ms) convertita in secondi
      - bvp: timestamp, bvp
      - eda: timestamp, eda
      - hr : timestamp, hr
      - temp: timestamp, temp
    """
    base = os.path.join(os.path.dirname(__file__), "..", "data_samples", username)
    path = os.path.abspath(os.path.join(base, CSV_FILES.get(sensor, "")))
    if not os.path.exists(path):
        return [], []

    ts, vals = [], []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            ts.append(row.get("timestamp"))
            if sensor == "acc":
                ax = _to_float(row.get("ax"))
                ay = _to_float(row.get("ay"))
                az = _to_float(row.get("az"))
                vals.append(None if None in (ax, ay, az) else math.sqrt(ax*ax + ay*ay + az*az))
            elif sensor == "ibi":
                dur_ms = _to_float(row.get("duration"))
                vals.append(None if dur_ms is None else dur_ms / 1000.0)
            else:
                vals.append(_to_float(row.get(sensor)))

    ts = _normalize_epoch(ts)
    return ts, vals

# =========================
# Rendering helpers
# =========================
def _nodata(ax, sensor, username, msg):
    ax.set_title(f"{sensor.upper()} • {username}")
    ax.set_xlabel("tempo")
    ax.set_ylabel(UNITS.get(sensor, "valore"))
    ax.text(0.5, 0.5, msg, ha="center", va="center", transform=ax.transAxes, color="#666")
    ax.grid(True, alpha=0.3)

def _as_png(fig):
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

# =========================
# Endpoint principale
# =========================
def plot_user_sensor(username, sensor, last_n=200):
    """
    Genera un PNG del sensore leggendo i CSV **con le date originali del CSV**.
    - Nessuna alterazione dell'anno o delle date.
    - Intervallo 'window' relativo alla **data massima presente nel CSV**.
    """
    window = _parse_window_param()

    xs_epoch, ys_raw = _read_from_csv(username, sensor)

    fig, ax = plt.subplots(figsize=(7.2, 3.1), dpi=120)

    if not ys_raw:
        _nodata(ax, sensor, username, "Nessun dato disponibile")
        return _as_png(fig)

    # Converte epoch -> datetime
    xs_dt_all = [dt.datetime.fromtimestamp(e) for e in xs_epoch if e is not None]
    ys_all = [v for v in ys_raw]

    # Rimuovi eventuali None sincronamente
    xs_dt_all, ys_all = zip(*[(x, y) for x, y in zip(xs_dt_all, ys_all) if (x is not None and y is not None)])
    xs_dt_all = list(xs_dt_all); ys_all = list(ys_all)

    # Limiti finestra relativi alla data massima del dataset
    max_dt = max(xs_dt_all)
    start, end = _window_bounds_from_dataset(max_dt, window)

    if start is None:  # "all"
        xs_dt, ys = xs_dt_all, ys_all
    else:
        xs_dt, ys = [], []
        for d, v in zip(xs_dt_all, ys_all):
            if start <= d <= end:
                xs_dt.append(d); ys.append(v)

    if not ys:
        _nodata(ax, sensor, username, "Nessun dato nella finestra selezionata")
        return _as_png(fig)

    # Plot
    xs_num = mdates.date2num(xs_dt)
    xs_num_ds, ys_ds = _downsample(xs_num, ys, max_points=1200)
    ax.plot_date(xs_num_ds, ys_ds, "-", linewidth=1.2, label="Valori")

    # Layout
    ax.set_title(f"{sensor.upper()} • {username}")
    ax.set_xlabel("tempo")
    ax.set_ylabel(UNITS.get(sensor, "valore"))
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")

    # Range mostrato (se 'all' usa minimo/massimo reali)
    shown_start = xs_dt[0] if window == "all" else start
    shown_end   = xs_dt[-1] if window == "all" else end
    ax.text(1.0, 1.02,
            f"{shown_start.strftime('%Y-%m-%d %H:%M')} → {shown_end.strftime('%Y-%m-%d %H:%M')}",
            ha="right", va="bottom", transform=ax.transAxes, fontsize=8, color="#555")

    if _has_labeled(ax):
        ax.legend(loc="upper left", fontsize=8, ncol=3)

    return _as_png(fig)
