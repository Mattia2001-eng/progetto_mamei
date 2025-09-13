import time, math
from collections import deque, defaultdict
from db import query_all, exec_write, query_one
from firestore_db import fs_add_anomaly, fs_get_user_email, fs_get_alert_extras
from emailer import send_email
import config


# =========================
# Utility timestamp & label
# =========================

def _to_seconds(ts):
    """Converte timestamp ms->s se necessario, altrimenti lo lascia in s."""
    t = float(ts)
    # Soglia robusta: >1e11 è quasi certamente millisecondi (1973 in ms).
    return t / 1000.0 if t > 1e11 else t


def _labels():
    """Etichette leggibili per i sensori."""
    return {
        'hr': 'Frequenza cardiaca',
        'temp': 'Temperatura cutanea',
        'eda': 'Conduttanza cutanea',
        'bvp': 'BVP',
        'acc': 'Accelerazione',
        'ibi': 'IBI'
    }


# =========================
# Statistiche di finestra
# =========================

def stats_by_window(days=7, username=None):
    start_ts = time.time() - days*24*3600  # secondi
    params = ()
    user_clause = ''
    if username:
        user_clause = ' AND username=?'
        params = (username,)

    rows = query_all(f"""
        SELECT sensor, AVG(value) as avg_v, COUNT(*) as n
        FROM readings
        WHERE timestamp >= ? {user_clause}
        GROUP BY sensor
    """, (start_ts,) + params)
    out = {r['sensor']: r['avg_v'] for r in rows}
    total = sum(r['n'] for r in rows) if rows else 0
    return out, total


def last_week_stats(username=None):
    week_ago = time.time() - 7*24*3600
    params = ()
    user_clause = ''
    if username:
        user_clause = ' AND username=?'
        params = (username,)
    rows = query_all(f"""
        SELECT sensor, AVG(value) as avg_v, COUNT(*) as n
        FROM readings
        WHERE timestamp >= ? {user_clause}
        GROUP BY sensor
    """, (week_ago,) + params)
    out = {r['sensor']: r['avg_v'] for r in rows}
    total = sum(r['n'] for r in rows) if rows else 0
    return out, total


# =========================
# Notifiche email & cooldown
# =========================

def _last_anomaly_ts(username, sensor):
    """Ritorna il timestamp (come float) dell'ultima anomalia registrata, None se assente."""
    row = query_one(
        'SELECT timestamp FROM anomalies WHERE username=? AND sensor=? ORDER BY timestamp DESC LIMIT 1',
        (username, sensor)
    )
    if not row:
        return None
    return float(row['timestamp'])


def _recipient_for(username):
    """Destinatario principale preso da Firestore; fallback su FROM_EMAIL."""
    em = fs_get_user_email(username)
    if em:
        return em
    return getattr(config, 'FROM_EMAIL', None)


def _extra_recipients():
    """
    Destinatari extra da Firestore (settings/alerts.emails),
    fallback su config.ALERT_EXTRA (CSV) se non presenti.
    """
    extras = fs_get_alert_extras()
    if extras:
        return extras
    raw = getattr(config, 'ALERT_EXTRA', '') or ''
    return [e.strip() for e in raw.split(',') if e.strip()]


def _should_email(prev_ts, current_ts):
    """Applica il cooldown (in secondi) normalizzando entrambi i timestamp."""
    cooldown = int(getattr(config, 'ALERT_COOLDOWN_SEC', 900))  # default 15 min
    if prev_ts is None:
        return True
    prev_s = _to_seconds(prev_ts)
    curr_s = _to_seconds(current_ts)
    return (curr_s - prev_s) >= cooldown


# =========================
# Rilevazione anomalie
# =========================

def moving_average_anomaly(username, sensor):
    """
    Calcola la media mobile sugli ultimi N valori; se supera la soglia:
      - registra l'anomalia in SQLite (timestamp SALVATO in secondi)
      - replica su Firestore (timestamp in secondi)
      - invia email di allerta (rispettando un cooldown configurabile)
    """
    n = int(getattr(config, 'MOVING_AVG_WINDOW', 10))
    rows = query_all(
        'SELECT value, timestamp FROM readings WHERE username=? AND sensor=? ORDER BY timestamp DESC LIMIT ?',
        (username, sensor, n)
    )
    if not rows or len(rows) < n:
        return None  # non abbastanza dati

    vals = [r['value'] for r in rows][::-1]
    ma = sum(vals) / len(vals)

    thr = getattr(config, 'THRESHOLDS', {}).get(sensor, None)
    if thr is None:
        return None

    if ma > thr:
        # Timestamp più recente della finestra; normalizzato ai secondi per persistenza/notifica
        ts_raw = rows[-1]['timestamp']
        ts_sec = _to_seconds(ts_raw)

        # Verifica cooldown rispetto all'ultima anomalia *precedente*
        prev_ts = _last_anomaly_ts(username, sensor)

        # Registra l'anomalia su DB **in secondi**
        exec_write(
            'INSERT INTO anomalies(username,sensor,timestamp,value,threshold,window) VALUES(?,?,?,?,?,?)',
            (username, sensor, ts_sec, ma, thr, n)
        )

        # Replica su Firestore (timestamp in secondi)
        try:
            fs_add_anomaly(username, sensor, ts_sec, ma, thr, n)
        except Exception as e:
            print('[FS][WARN] fs_add_anomaly:', e)

        # Invio email se rispettiamo il cooldown
        if _should_email(prev_ts, ts_sec):
            label = _labels().get(sensor, sensor.upper())
            subject = f"[ALLERTA] {username} — {label} sopra soglia"
            ts_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts_sec))

            body = (
                "Ciao,\n\n"
                "È stata rilevata un'anomalia.\n\n"
                f"Utente: {username}\n"
                f"Sensore: {sensor} ({label})\n"
                f"Media mobile (ultimi {n}): {ma:.3f}\n"
                f"Soglia: {thr:.3f}\n"
                f"Timestamp: {ts_str}\n\n"
                "— Sistema di monitoraggio"
            )

            # Costruisce lista destinatari (principale + extra), con deduplica
            recips = []
            main = _recipient_for(username)
            if main:
                recips.append(main)
            recips.extend(_extra_recipients())
            seen = set()
            recipients = [r for r in recips if not (r in seen or seen.add(r))]

            for r in recipients:
                ok = send_email(r, subject, body)
                if not ok:
                    print('[ALERT][WARN] invio email fallito per', r)

        return {
            'username': username,
            'sensor': sensor,
            'timestamp': ts_sec,   # ritorniamo secondi
            'value': ma,
            'threshold': thr,
            'window': n
        }

    return None


def recent_anomalies(limit=20):
    return query_all('SELECT * FROM anomalies ORDER BY timestamp DESC LIMIT ?', (limit,))
