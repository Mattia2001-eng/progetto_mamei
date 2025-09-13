import os
import csv
import io
import json
import time
import threading
from firestore_db import fs_get_user_email
from db import query_one  # se non c’è già


from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    jsonify, abort, current_app, send_file
)
from flask_login import (
    LoginManager, current_user, login_user, logout_user, login_required
)

import config
from db import init_db, exec_write, query_all, query_one
from auth import (
    validate_login, create_user, find_user_by_username, all_users,
    User, delete_user, sync_users_to_firestore
)
from analytics import last_week_stats, moving_average_anomaly, recent_anomalies, stats_by_window
from emailer import send_email, email_status
from firestore_db import fs_add_reading
from plots import plot_user_sensor


# --------------------------------------------------------------------------------------
# App & Login
# --------------------------------------------------------------------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY
init_db()

@login_required
@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')

login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    row = query_one('SELECT * FROM users WHERE id=?', (user_id,))
    if not row:
        return None
    return User(row['id'], row['username'], row['email'], row['role'])


# --------------------------------------------------------------------------------------
# Bootstrap admin
# --------------------------------------------------------------------------------------
if not find_user_by_username('admin'):
    try:
        create_user('admin', 'admin@example.com', 'admin123', role='admin')
        print('[INIT] created default admin: admin / admin123')
    except Exception as e:
        print('[INIT] admin create error:', e)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def _window_stats(usernames, days):
    """
    Ritorna, per ogni sensore, media/min/max/N nel periodo selezionato.
    'usernames' può essere stringa o lista di stringhe.
    """
    if not isinstance(usernames, (list, tuple)):
        usernames = [usernames]

    start_ts = time.time() - (days * 24 * 3600)
    placeholders = ",".join(["?"] * len(usernames))

    rows = query_all(
        f"SELECT sensor, value FROM readings "
        f"WHERE username IN ({placeholders}) AND timestamp>=?",
        tuple(usernames) + (start_ts,)
    )

    agg = {}
    for r in rows:
        s = r['sensor']
        v = r['value']
        if v is None:
            continue
        b = agg.setdefault(s, {"sum": 0.0, "n": 0, "min": None, "max": None})
        b["sum"] += v
        b["n"] += 1
        b["min"] = v if b["min"] is None else min(b["min"], v)
        b["max"] = v if b["max"] is None else max(b["max"], v)

    out = {}
    for s, b in agg.items():
        out[s] = {
            "avg": (b["sum"] / b["n"]) if b["n"] else None,
            "min": b["min"],
            "max": b["max"],
            "n": b["n"]
        }
    return out


# --------------------------------------------------------------------------------------
# Routes - base / auth
# --------------------------------------------------------------------------------------
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/about')
@login_required
def about():
    return render_template('about.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = validate_login(request.form.get('username'), request.form.get('password'))
        if u:
            login_user(u)
            return redirect(url_for('dashboard'))
        flash('Credenziali non valide')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# --------------------------------------------------------------------------------------
# Routes - dashboard / analytics / plots
# --------------------------------------------------------------------------------------
@app.route('/dashboard')
@login_required
def dashboard():
    # periodo selezionato
    days = request.args.get('days', type=int, default=getattr(config, 'DEFAULT_PLOT_DAYS', 7))

    # lista utenti: admin vede tutti (escluso 'admin'), user vede solo se stesso
    if current_user.is_admin():
        users = [u['username'] for u in all_users() if u['username'].lower() != 'admin']
    else:
        users = [current_user.username]

    # statistiche
    stats_window = _window_stats(users, days)

    target = None if current_user.is_admin() else current_user.username
    stats_avg, stats_total = last_week_stats(target)
    stats_week, total_week = stats_by_window(7, target)
    stats_month, total_month = stats_by_window(30, target)
    anomalies_list = recent_anomalies()

    # piccoli dataset per tabelline (ultimi 50 valori per sensore)
    chart_data = {}
    for uname in users:
        chart_data[uname] = {}
        for s in config.SENSORS:
            rows = query_all(
                'SELECT value FROM readings WHERE username=? AND sensor=? '
                'ORDER BY timestamp ASC LIMIT 50',
                (uname, s)
            )
            chart_data[uname][s] = {'values': [r['value'] for r in rows]}

    return render_template(
        'dashboard.html',
        users=users,
        stats_window=stats_window, days=days,
        stats_avg=stats_avg, stats_total=stats_total,
        stats_week=stats_week, total_week=total_week,
        stats_month=stats_month, total_month=total_month,
        anomalies=[{
            'username': a['username'],
            'sensor_type': a['sensor'],
            'value': a['value'],
            'threshold': a['threshold'],
            'timestamp': a['timestamp']
        } for a in anomalies_list],
        chart_data=chart_data
    )

@app.route('/analytics')
@login_required
def analytics():
    days = request.args.get('days', type=int, default=getattr(config, 'DEFAULT_PLOT_DAYS', 7))

    username = request.args.get('user_id') or current_user.username
    if (not current_user.is_admin()) and username != current_user.username:
        flash('Accesso negato')
        return redirect(url_for('dashboard'))

    stats_window = _window_stats(username, days)
    stats_avg, stats_total = last_week_stats(username)
    stats_week, total_week = stats_by_window(7, username)
    stats_month, total_month = stats_by_window(30, username)

    return render_template(
        'analytics.html',
        stats_window=stats_window, days=days,
        target_username=username, stats_avg=stats_avg, stats_total=stats_total,
        stats_week=stats_week, total_week=total_week,
        stats_month=stats_month, total_month=total_month
    )

@app.route('/plot/<sensor>/<username>.png')
@login_required
def plot_sensor(sensor, username):
    # grafico PNG generato da matplotlib
    return plot_user_sensor(username, sensor, last_n=300)


# --------------------------------------------------------------------------------------
# Routes - pagine informative
# --------------------------------------------------------------------------------------
@app.route('/help/exports')
@login_required
def help_exports():
    return render_template('help_exports.html')

@app.route('/users')
@login_required
def users_page():
    if current_user.is_admin():
        users = all_users()
    else:
        me = find_user_by_username(current_user.username)
        users = [{
            'username': me.username,
            'email': me.email,
            'role': me.role,
            'created_at': ''
        }] if me else []
    return render_template('users.html', users=users)


# --------------------------------------------------------------------------------------
# Routes - admin
# --------------------------------------------------------------------------------------
@app.route('/admin')
@login_required
def admin_home():
    if not current_user.is_admin():
        flash('Solo amministratori')
        return redirect(url_for('dashboard'))
    return render_template('admin.html')

@app.route('/admin/new_user', methods=['GET', 'POST'])
@login_required
def admin_new_user():
    if not current_user.is_admin():
        flash('Solo amministratori')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        try:
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip()
            password = request.form.get('password')
            role = 'admin' if request.form.get('is_admin') == 'on' else 'user'
            create_user(username, email, password, role)
            send_email(email, 'Account creato', f'Username: {username}\nPassword: {password}')
            flash('Utente creato e email inviata')
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f'Errore creazione utente: {e}')
    return render_template('admin_new_user.html')

@app.route('/admin/delete_user', methods=['POST'])
@login_required
def admin_delete_user():
    if not current_user.is_admin():
        return ('forbidden', 403)
    username = request.form.get('username')
    delete_user(username)
    flash('Utente eliminato (SQLite + Firestore)')
    return redirect(url_for('admin_home'))

# --- Feeder supervisor (server-side) ---
_feeder_threads = {}
_feeder_stop = {}

def _run_feeder(uname, folder):
    print('[FEEDER] start for', uname, 'folder', folder)
    files = {
        'acc': 'wrist_acc.csv',
        'bvp': 'wrist_bvp.csv',
        'eda': 'wrist_eda.csv',
        'hr':  'wrist_hr.csv',
        'ibi': 'wrist_ibi.csv',
        'temp':'wrist_skin_temperature.csv',
    }
    # Lettori CSV semplici: attesi "timestamp,value" o solo "value"
    fps = {}
    for k, fname in files.items():
        path = os.path.join(folder, fname)
        if os.path.exists(path):
            fps[k] = open(path, 'r', newline='')
            next(fps[k], None)  # salta header

    try:
        while not _feeder_stop.get(uname):
            sent_something = False
            for sensor, f in list(fps.items()):
                line = f.readline()
                if not line:
                    continue
                parts = line.strip().split(',')
                # Prova parsing: timestamp,value OPPURE value (usa time.time() per timestamp)
                try:
                    if len(parts) >= 2:
                        ts = float(parts[0])
                        val = float(parts[1])
                    else:
                        ts = time.time()
                        val = float(parts[0])
                except Exception:
                    ts = time.time()
                    try:
                        val = float(parts[-1])
                    except Exception:
                        continue

                exec_write(
                    'INSERT INTO readings(username,sensor,timestamp,value) VALUES(?,?,?,?)',
                    (uname, sensor, ts, val)
                )
                # anomaly check (salva eventuale anomalia e notifica)
                moving_average_anomaly(uname, sensor)
                sent_something = True

            time.sleep(config.FEED_INTERVAL_SEC)
    finally:
        for f in fps.values():
            try:
                f.close()
            except Exception:
                pass
        print('[FEEDER] stop for', uname)

@app.route('/admin/start_feeder', methods=['POST'])
@login_required
def admin_start_feeder():
    if not current_user.is_admin():
        return ('forbidden', 403)
    # usa /data_samples/<username>/ come cartelle dati
    base = os.path.abspath(os.path.join(app.root_path, os.pardir, 'data_samples'))
    for uname in os.listdir(base):
        folder = os.path.join(base, uname)
        if not os.path.isdir(folder):
            continue
        if _feeder_threads.get(uname) and _feeder_threads[uname].is_alive():
            continue
        _feeder_stop[uname] = False
        t = threading.Thread(target=_run_feeder, args=(uname, folder), daemon=True)
        _feeder_threads[uname] = t
        t.start()
    flash('Feeder avviati')
    return redirect(url_for('admin_home'))

@app.route('/admin/stop_feeder', methods=['POST'])
@login_required
def admin_stop_feeder():
    if not current_user.is_admin():
        return ('forbidden', 403)
    for uname in list(_feeder_stop.keys()):
        _feeder_stop[uname] = True
    flash('Stop richiesto ai feeder')
    return redirect(url_for('admin_home'))

# --- Email helpers ---
@app.route('/admin/email_status')
@login_required
def admin_email_status():
    if not current_user.is_admin():
        flash('Solo amministratori')
        return redirect(url_for('dashboard'))
    return render_template('email_status.html', email_status=email_status())

@app.route('/admin/email_csv_user', methods=['POST'])
@login_required
def admin_email_csv_user():
    if not current_user.is_admin():
        return ('forbidden', 403)

    uname = request.form.get('username', '').strip()
    if not uname:
        flash('Username mancante')
        return redirect(url_for('admin_home'))

    # 1) Firestore → 2) DB users → 3) campo form → se nulla => errore
    email = fs_get_user_email(uname)
    if not email:
        row = query_one('SELECT email FROM users WHERE username=?', (uname,))
        email = (row.get('email') if row else None) or request.form.get('email', '').strip()

    if not email:
        flash(f'Nessuna email trovata per utente {uname}')
        return redirect(url_for('admin_home'))

    rows = query_all(
        'SELECT id, username, sensor, value, timestamp FROM readings WHERE username=? ORDER BY timestamp DESC LIMIT 1000',
        (uname,)
    )
    if not rows:
        flash(f'Nessun dato per {uname}')
        return redirect(url_for('admin_home'))

    # Crea CSV in memoria (UTF-8)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['id','username','sensor','value','timestamp'])
    for r in rows[:500]:
        writer.writerow([
            r.get('id',''),
            r.get('username',''),
            r.get('sensor',''),
            r.get('value',''),
            r.get('timestamp',''),
        ])
    csv_bytes = buf.getvalue().encode('utf-8')

    # Nome file: username + timestamp
    ts_label = time.strftime('%Y%m%d_%H%M%S', time.localtime())
    fname = f"{uname}_readings_{ts_label}.csv"

    subject = f'I tuoi dati CSV — {uname}'
    body = (
        f'Ciao {uname},\n\n'
        f'in allegato trovi i tuoi ultimi dati (max 500 righe).\n\n'
        '— Sistema di monitoraggio'
    )

    ok = send_email(
        email,
        subject,
        body,
        attachments=[{"filename": fname, "content": csv_bytes, "mime": "text/csv"}]
    )

    if ok:
        flash(f'Email con CSV inviata a {email}')
    else:
        flash('Invio email fallito (controlla configurazione SMTP)')

    return redirect(url_for('admin_home'))

@app.route('/admin/email_csv_all', methods=['POST'])
@login_required
def admin_email_csv_all():
    if not current_user.is_admin():
        return ('forbidden', 403)
    users_list = all_users()
    for u in users_list:
        rows = query_all(
            'SELECT * FROM readings WHERE username=? ORDER BY timestamp DESC LIMIT 500',
            (u['username'],)
        )
        body = '\n'.join('{}, {}, {}, {}'.format(r['id'], r['username'], r['sensor'], r['value']) for r in rows[:300])
        send_email(u['email'], 'CSV dati personali', body)
    flash('Email CSV inviate')
    return redirect(url_for('admin_home'))

@app.route('/admin/email_unblock', methods=['POST'])
@login_required
def admin_email_unblock():
    if not current_user.is_admin():
        return ('forbidden', 403)
    email = request.form.get('email')
    send_email(email, 'Sblocco email', 'Richiesta sblocco eseguita.')
    flash('Email sbloccata (simulazione)')
    return redirect(url_for('admin_home'))

@app.route('/admin/export_user_csv', methods=['GET'])
@login_required
def admin_export_user_csv():
    if not current_user.is_authenticated:
        return ('forbidden', 403)

    username = request.args.get('username')
    if not username:
        return ('bad request: missing username', 400)

    # solo admin o l’utente stesso
    if (not current_user.is_admin()) and (username != current_user.username):
        return ('forbidden', 403)

    rows = query_all(
        'SELECT id, username, sensor, timestamp, value FROM readings '
        'WHERE username=? ORDER BY timestamp ASC',
        (username,)
    )

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['id', 'username', 'sensor', 'timestamp', 'timestamp_iso', 'value'])

    for r in rows:
        ts = float(r['timestamp']) if r['timestamp'] is not None else ''
        ts_iso = ''
        if ts != '':
            try:
                from datetime import datetime, timezone
                from zoneinfo import ZoneInfo
                ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc)\
                                 .astimezone(ZoneInfo('Europe/Rome')).isoformat()
            except Exception:
                pass
        w.writerow([r['id'], r['username'], r['sensor'], r['timestamp'], ts_iso, r['value']])

    data = buf.getvalue().encode('utf-8')
    return send_file(io.BytesIO(data), mimetype='text/csv', as_attachment=True,
                     download_name=f'{username}_readings.csv')

@app.route('/admin/notify_user', methods=['POST'])
@login_required
def admin_notify_user():
    if not current_user.is_admin():
        return ('forbidden', 403)
    uname = request.form.get('username')
    msg = request.form.get('message')
    send_email(f'{uname}@example.com', 'Notifica dal sistema', msg or '(vuoto)')
    flash('Notifica inviata (email)')
    return redirect(url_for('admin_home'))

@app.route('/admin/sync_users')
@login_required
def admin_sync_users():
    if not current_user.is_admin():
        abort(403)
    n = sync_users_to_firestore()
    flash(f'Utenti sincronizzati su Firestore: {n}')
    return redirect(url_for('admin_home'))

@app.route('/admin/fs_status')
@login_required
def admin_fs_status():
    if not current_user.is_admin():
        abort(403)
    # Mostra config e prova client
    try:
        from firestore_db import fs
        client = fs()
        proj = client.project
        msg = f"Firestore OK. Project: {proj}"
    except Exception as e:
        proj = None
        msg = f"Firestore ERROR: {e}"
    return render_template(
        'fs_status.html',
        message=msg,
        project=proj,
        cred_path=current_app.config.get('FIRESTORE_CREDENTIALS', None)
    )

@app.route('/admin/fs_test_write')
@login_required
def admin_fs_test_write():
    if not current_user.is_admin():
        abort(403)
    try:
        from firestore_db import fs
        client = fs()
        doc = {'when': time.time(), 'who': current_user.username, 'note': 'ping from app'}
        client.collection('diagnostics').document('ping').set(doc, merge=True)
        flash('Test write OK: diagnostics/ping aggiornato.')
    except Exception as e:
        import traceback
        traceback.print_exc()
        flash(f'Test write FAILED: {e}')
    return redirect(url_for('admin_home'))


# --------------------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------------------
@app.route('/api/sensor_data', methods=['POST'])
def api_sensor_data():
    try:
        data = request.get_json(force=True)
        username = data.get('username')
        sensor = data.get('sensor')
        ts = float(data.get('timestamp', time.time()))
        val = float(data.get('value'))

        if sensor not in config.SENSORS:
            return jsonify({'ok': False, 'error': 'bad sensor'}), 400

        exec_write(
            'INSERT INTO readings(username,sensor,timestamp,value) VALUES(?,?,?,?)',
            (username, sensor, ts, val)
        )

        try:
            fs_add_reading(username, sensor, ts, val)
        except Exception as e:
            print('[FS][WARN] fs_add_reading:', e)

        moving_average_anomaly(username, sensor)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/api/user_data/<username>')
@login_required
def api_user_data(username):
    if (not current_user.is_admin()) and username != current_user.username:
        return ('forbidden', 403)
    rows = query_all(
        'SELECT sensor, timestamp, value FROM readings '
        'WHERE username=? ORDER BY timestamp ASC LIMIT 1000',
        (username,)
    )
    return jsonify(rows)


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
# Alla fine del file app/app.py, assicurati che ci sia:
if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
