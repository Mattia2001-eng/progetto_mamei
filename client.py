import os, time, csv, argparse, requests, glob

SENSORS = {
    'acc': 'wrist_acc.csv',
    'bvp': 'wrist_bvp.csv',
    'eda': 'wrist_eda.csv',
    'hr':  'wrist_hr.csv',
    'ibi': 'wrist_ibi.csv',
    'temp':'wrist_skin_temperature.csv',
}

def stream_folder(folder, server_url, username, interval=1.0):
    fps = {}
    for k,fname in SENSORS.items():
        path = os.path.join(folder, fname)
        if os.path.exists(path):
            fps[k] = open(path, 'r', newline='')
            next(fps[k], None)  # skip header
    try:
        while True:
            sent_any = False
            for sensor, f in list(fps.items()):
                line = f.readline()
                if not line:
                    continue
                parts = line.strip().split(',')
                # try timestamp,value else value-only
                try:
                    if len(parts) >= 2:
                        ts = float(parts[0]); val = float(parts[1])
                    else:
                        ts = time.time(); val = float(parts[0])
                except:
                    ts = time.time()
                    try: val = float(parts[-1])
                    except: continue
                payload = {"username": username, "sensor": sensor, "timestamp": ts, "value": val}
                r = requests.post(f"{server_url}/api/sensor_data", json=payload, timeout=5)
                r.raise_for_status()
                sent_any = True
            time.sleep(interval if sent_any else interval)
    finally:
        for f in fps.values():
            try: f.close()
            except: pass

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True, help="Cartella con i CSV del dataset (wrist_*.csv)")
    ap.add_argument("--server", default="http://127.0.0.1:5000", help="URL del server Flask")
    ap.add_argument("--username", required=True, help="Nome utente per associare i dati")
    ap.add_argument("--interval", type=float, default=1.0, help="Intervallo secondi tra invii")
    args = ap.parse_args()
    stream_folder(args.folder, args.server, args.username, args.interval)
