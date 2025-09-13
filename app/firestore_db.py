import os
import time
import threading

import config

# Path & cred
from google.oauth2 import service_account
from google.cloud import firestore as gcf  # client ufficiale (supporta database=...)

# Per compatibilità: lo useremo solo se stai usando il DB (default)
import firebase_admin
from firebase_admin import credentials as fb_credentials
from firebase_admin import firestore as fb_firestore

_fs_lock = threading.Lock()
_fs_client = None
_fs_mode = None  # "gcf" (google-cloud-firestore) oppure "admin" (firebase_admin)


def _abs_credentials_path():
    cred_path = config.FIRESTORE_CREDENTIALS
    if not os.path.isabs(cred_path):
        cred_path = os.path.abspath(cred_path)
    if not os.path.exists(cred_path):
        raise FileNotFoundError(f'Credentials file not found: {cred_path}')
    return cred_path


def _init_client():
    """
    Inizializza un client Firestore:
      - se FIRESTORE_DATABASE == "(default)" => usa firebase_admin
      - altrimenti                        => usa google-cloud-firestore con database=<id>
    """
    global _fs_client, _fs_mode
    with _fs_lock:
        if _fs_client is not None:
            return _fs_client

        cred_path = _abs_credentials_path()
        project_id = config.FIRESTORE_PROJECT_ID
        db_id = (config.FIRESTORE_DATABASE or "(default)").strip()

        print('[FS][INIT] using credentials:', cred_path)
        print('[FS][PROJECT from config]', project_id)
        print('[FS][DATABASE from config]', db_id)

        if db_id != "(default)":
            # === Modalità google-cloud-firestore (supporta multi-database) ===
            creds = service_account.Credentials.from_service_account_file(cred_path)
            _fs_client = gcf.Client(project=project_id, credentials=creds, database=db_id)
            _fs_mode = "gcf"
            print('[FS][MODE] google-cloud-firestore')
            print('[FS][PROJECT from client]', _fs_client.project)
            print(f'[FS][READY] connected to project: {_fs_client.project} / database: {db_id}')
        else:
            # === Modalità firebase_admin (solo (default)) ===
            try:
                firebase_admin.get_app()
            except ValueError:
                fb_cred = fb_credentials.Certificate(cred_path)
                firebase_admin.initialize_app(fb_cred, {'projectId': project_id})
            _fs_client = fb_firestore.client()
            _fs_mode = "admin"
            print('[FS][MODE] firebase_admin (default database)')
            print('[FS][PROJECT from client]', _fs_client.project)
            print(f'[FS][READY] connected to project: {_fs_client.project} / database: (default)')

    return _fs_client


def fs():
    """Restituisce il client Firestore già inizializzato."""
    return _init_client()


# ---------- Helpers destinatari (NUOVI) ----------

def fs_get_user_email(username: str):
    """
    Ritorna l'email dell'utente da Firestore.
    1) prova doc-id = username nelle collezioni comuni
    2) poi query su collection('users') where username == <username>
    Cerca i campi: 'alert_email', 'email', 'mail'.
    """
    db = fs()

    # 1) Prova doc id = username su collezioni plausibili
    for col in ("users", "profiles", "utenti"):
        try:
            snap = db.collection(col).document(username).get()
            if snap.exists:
                data = snap.to_dict() or {}
                for k in ("alert_email", "email", "mail"):
                    v = data.get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
        except Exception as e:
            print("[FS][WARN] fs_get_user_email/docid", col, e)

    # 2) Query per campo 'username' su 'users'
    try:
        q = db.collection("users").where("username", "==", username).limit(1).stream()
        for doc in q:
            data = doc.to_dict() or {}
            for k in ("alert_email", "email", "mail"):
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    except Exception as e:
        print("[FS][WARN] fs_get_user_email/query users", e)

    return None


def fs_get_alert_extras():
    """
    Ritorna una lista di destinatari extra dalle impostazioni su Firestore:
      collection('settings').document('alerts') -> { emails: ['a@x', 'b@y'] }
    Se non trovate, torna [].
    Accetta anche stringa CSV nel campo 'emails' o 'recipients'.
    """
    db = fs()
    try:
        snap = db.collection("settings").document("alerts").get()
        if snap.exists:
            data = snap.to_dict() or {}
            emails = data.get("emails") or data.get("recipients") or []
            if isinstance(emails, str):
                emails = [e.strip() for e in emails.split(",") if e.strip()]
            # normalizza & filtra
            out = []
            for v in emails:
                if isinstance(v, str) and v.strip():
                    out.append(v.strip())
            return out
    except Exception as e:
        print("[FS][WARN] fs_get_alert_extras", e)
    return []


# ---------- Users ----------
def fs_upsert_user(username, email, role, created_at=None):
    db = fs()
    doc = {
        "email": email,
        "role": role,
        "created_at": created_at or time.time()
    }
    print('[FS][UPSERT][user]', username, doc)
    db.collection("users").document(username).set(doc, merge=True)


def fs_delete_user(username):
    db = fs()
    print('[FS][DELETE][user]', username)
    db.collection("users").document(username).delete()


# ---------- Readings ----------
def fs_add_reading(username, sensor, timestamp, value):
    db = fs()
    data = {
        "username": username,
        "sensor": sensor,
        "timestamp": float(timestamp),
        "value": float(value)
    }
    print('[FS][ADD][reading]', data)
    db.collection("readings").add(data)


# ---------- Anomalies ----------
def fs_add_anomaly(username, sensor, timestamp, value, threshold, window):
    db = fs()
    data = {
        "username": username,
        "sensor": sensor,
        "timestamp": float(timestamp),
        "value": float(value),
        "threshold": float(threshold),
        "window": int(window)
    }
    print('[FS][ADD][anomaly]', data)
    db.collection("anomalies").add(data)
