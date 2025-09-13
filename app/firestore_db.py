import os
import time
import threading
import json
from google.cloud import firestore
from google.oauth2 import service_account

# Per compatibilità con firebase_admin (se necessario)
try:
    import firebase_admin
    from firebase_admin import credentials as fb_credentials
    from firebase_admin import firestore as fb_firestore
    FIREBASE_ADMIN_AVAILABLE = True
except ImportError:
    FIREBASE_ADMIN_AVAILABLE = False
    print("[FS][WARN] firebase_admin not available, using google-cloud-firestore only")

_fs_lock = threading.Lock()
_fs_client = None


def get_credentials():
    """Get Google credentials from environment variable or local file"""
    if os.environ.get('GOOGLE_CREDENTIALS'):
        # Cloud: usa la variabile d'ambiente
        try:
            credentials_info = json.loads(os.environ['GOOGLE_CREDENTIALS'])
            credentials = service_account.Credentials.from_service_account_info(credentials_info)
            print('[FS][CREDS] Using environment variable GOOGLE_CREDENTIALS')
            return credentials
        except Exception as e:
            print(f'[FS][ERROR] Failed to parse GOOGLE_CREDENTIALS: {e}')
            raise
    else:
        # Locale: usa il file
        credentials_path = os.path.join(os.path.dirname(__file__), "..", "credentials.json")
        if os.path.exists(credentials_path):
            credentials = service_account.Credentials.from_service_account_file(credentials_path)
            print(f'[FS][CREDS] Using local credentials file: {credentials_path}')
            return credentials
        else:
            print(f'[FS][WARN] Credentials file not found: {credentials_path}')
            print('[FS][INFO] Trying default application credentials')
            return None


def _init_client():
    """
    Inizializza un client Firestore usando le credenziali appropriate
    """
    global _fs_client
    with _fs_lock:
        if _fs_client is not None:
            return _fs_client

        # Ottieni project ID dall'ambiente o usa default
        project_id = os.environ.get('GOOGLE_CLOUD_PROJECT', 'strong-charge-465917-k4')
        
        print(f'[FS][INIT] Initializing Firestore client for project: {project_id}')
        
        try:
            credentials = get_credentials()
            
            if credentials:
                _fs_client = firestore.Client(credentials=credentials, project=project_id)
                print(f'[FS][SUCCESS] Connected with explicit credentials')
            else:
                # Prova con credenziali di default (quando su GCP)
                _fs_client = firestore.Client(project=project_id)
                print(f'[FS][SUCCESS] Connected with default credentials')
                
            print(f'[FS][READY] Firestore client ready for project: {_fs_client.project}')
            
        except Exception as e:
            print(f'[FS][ERROR] Failed to initialize Firestore client: {e}')
            raise

    return _fs_client


def fs():
    """Restituisce il client Firestore già inizializzato."""
    return _init_client()


# ---------- Test di connessione ----------
def test_connection():
    """Test rapido della connessione Firestore"""
    try:
        db = fs()
        # Prova una semplice operazione
        collections = db.collections()
        print(f'[FS][TEST] Connection successful, available collections: {[c.id for c in collections]}')
        return True
    except Exception as e:
        print(f'[FS][TEST] Connection failed: {e}')
        return False


# ---------- Helpers destinatari ----------

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
                        print(f'[FS][FOUND] User {username} email: {v.strip()}')
                        return v.strip()
        except Exception as e:
            print(f"[FS][WARN] fs_get_user_email/docid {col}: {e}")

    # 2) Query per campo 'username' su 'users'
    try:
        q = db.collection("users").where("username", "==", username).limit(1).stream()
        for doc in q:
            data = doc.to_dict() or {}
            for k in ("alert_email", "email", "mail"):
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    print(f'[FS][FOUND] User {username} email via query: {v.strip()}')
                    return v.strip()
    except Exception as e:
        print(f"[FS][WARN] fs_get_user_email/query users: {e}")

    print(f'[FS][NOT_FOUND] No email found for user: {username}')
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
            print(f'[FS][ALERT_EXTRAS] Found {len(out)} extra recipients')
            return out
    except Exception as e:
        print(f"[FS][WARN] fs_get_alert_extras: {e}")
    return []


# ---------- Users ----------
def fs_upsert_user(username, email, role, created_at=None):
    """Crea o aggiorna un utente"""
    db = fs()
    doc = {
        "username": username,
        "email": email,
        "role": role,
        "created_at": created_at or time.time(),
        "updated_at": time.time()
    }
    print(f'[FS][UPSERT][user] {username}: {doc}')
    try:
        db.collection("users").document(username).set(doc, merge=True)
        print(f'[FS][SUCCESS] User {username} upserted')
    except Exception as e:
        print(f'[FS][ERROR] Failed to upsert user {username}: {e}')
        raise


def fs_delete_user(username):
    """Elimina un utente"""
    db = fs()
    print(f'[FS][DELETE][user] {username}')
    try:
        db.collection("users").document(username).delete()
        print(f'[FS][SUCCESS] User {username} deleted')
    except Exception as e:
        print(f'[FS][ERROR] Failed to delete user {username}: {e}')
        raise


def fs_get_user(username):
    """Ottiene i dati di un utente"""
    db = fs()
    try:
        snap = db.collection("users").document(username).get()
        if snap.exists:
            data = snap.to_dict()
            print(f'[FS][FOUND] User {username} data retrieved')
            return data
        else:
            print(f'[FS][NOT_FOUND] User {username} does not exist')
            return None
    except Exception as e:
        print(f'[FS][ERROR] Failed to get user {username}: {e}')
        raise


def fs_list_users():
    """Lista tutti gli utenti"""
    db = fs()
    try:
        users = []
        for doc in db.collection("users").stream():
            user_data = doc.to_dict()
            user_data['id'] = doc.id
            users.append(user_data)
        print(f'[FS][LIST] Found {len(users)} users')
        return users
    except Exception as e:
        print(f'[FS][ERROR] Failed to list users: {e}')
        raise


# ---------- Readings ----------
def fs_add_reading(username, sensor, timestamp, value):
    """Aggiunge una lettura sensore"""
    db = fs()
    data = {
        "username": username,
        "sensor": sensor,
        "timestamp": float(timestamp),
        "value": float(value),
        "created_at": time.time()
    }
    print(f'[FS][ADD][reading] {username}/{sensor}: {value}')
    try:
        db.collection("readings").add(data)
        print('[FS][SUCCESS] Reading added')
    except Exception as e:
        print(f'[FS][ERROR] Failed to add reading: {e}')
        raise


def fs_get_readings(username, sensor=None, limit=100):
    """Ottiene le letture di un utente"""
    db = fs()
    try:
        query = db.collection("readings").where("username", "==", username)
        if sensor:
            query = query.where("sensor", "==", sensor)
        query = query.order_by("timestamp", direction=firestore.Query.DESCENDING).limit(limit)
        
        readings = []
        for doc in query.stream():
            reading_data = doc.to_dict()
            reading_data['id'] = doc.id
            readings.append(reading_data)
        
        print(f'[FS][GET] Retrieved {len(readings)} readings for {username}')
        return readings
    except Exception as e:
        print(f'[FS][ERROR] Failed to get readings for {username}: {e}')
        raise


# ---------- Anomalies ----------
def fs_add_anomaly(username, sensor, timestamp, value, threshold, window):
    """Aggiunge un'anomalia rilevata"""
    db = fs()
    data = {
        "username": username,
        "sensor": sensor,
        "timestamp": float(timestamp),
        "value": float(value),
        "threshold": float(threshold),
        "window": int(window),
        "created_at": time.time()
    }
    print(f'[FS][ADD][anomaly] {username}/{sensor}: {value} (threshold: {threshold})')
    try:
        db.collection("anomalies").add(data)
        print('[FS][SUCCESS] Anomaly added')
    except Exception as e:
        print(f'[FS][ERROR] Failed to add anomaly: {e}')
        raise


def fs_get_anomalies(username=None, limit=50):
    """Ottiene le anomalie"""
    db = fs()
    try:
        query = db.collection("anomalies")
        if username:
            query = query.where("username", "==", username)
        query = query.order_by("timestamp", direction=firestore.Query.DESCENDING).limit(limit)
        
        anomalies = []
        for doc in query.stream():
            anomaly_data = doc.to_dict()
            anomaly_data['id'] = doc.id
            anomalies.append(anomaly_data)
        
        print(f'[FS][GET] Retrieved {len(anomalies)} anomalies')
        return anomalies
    except Exception as e:
        print(f'[FS][ERROR] Failed to get anomalies: {e}')
        raise


# ---------- Inizializzazione e test ----------
if __name__ == "__main__":
    print("[FS][TEST] Testing Firestore connection...")
    success = test_connection()
    if success:
        print("[FS][TEST] All tests passed!")
    else:
        print("[FS][TEST] Tests failed!")