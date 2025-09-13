import os

# =========================
# Server config
# =========================
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')
DATABASE_URL = os.environ.get('DATABASE_URL', 'app.db')

# =========================
# Email config (Gmail SMTP)
# =========================
# Per inviare davvero le email, lasciamo modalità 'smtp'.
# Usa una App Password di Google (2FA attivo) e impostala in SMTP_PASS.
EMAIL_MODE = os.environ.get('EMAIL_MODE', 'smtp')  # 'console' per stampare a log, 'smtp' per inviare davvero

# Gmail SMTP settings
SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', 'mattiaavellino2001@gmail.com')
SMTP_PASS = os.environ.get('SMTP_PASS', 'ggjm xlgp mqcx qehv')  # <-- App Password consigliata; meglio via variabile d'ambiente
FROM_EMAIL = os.environ.get('FROM_EMAIL', 'mattiaavellino2001@gmail.com')

# =========================
# Anomaly detection
# =========================
MOVING_AVG_WINDOW = int(os.environ.get('MOVING_AVG_WINDOW', '10'))   # last N values
THRESHOLDS = {
    'hr':   float(os.environ.get('THRESH_HR',   '120')),  # bpm
    'temp': float(os.environ.get('THRESH_TEMP', '38.5')), # °C
    'eda':  float(os.environ.get('THRESH_EDA',  '5.0')),  # μS
    'bvp':  float(os.environ.get('THRESH_BVP',  '1.5')),  # normalized
    'acc':  float(os.environ.get('THRESH_ACC',  '2.5')),  # g
    'ibi':  float(os.environ.get('THRESH_IBI',  '1.2')),  # s
}
MOVING_AVERAGE_WINDOW = MOVING_AVG_WINDOW
ANOMALY_THRESHOLDS = THRESHOLDS

# =========================
# Feeder
# =========================
FEED_INTERVAL_SEC = float(os.environ.get('FEED_INTERVAL_SEC', '1.0'))

# =========================
# Allowed sensors
# =========================
SENSORS = ['hr', 'temp', 'eda', 'bvp', 'acc', 'ibi']

# =========================
# Firestore
# =========================
# Nome logico del database (collezioni) – lo usi nella tua app; Firestore usa il Project ID per la connessione
FIRESTORE_DATABASE = os.environ.get('FIRESTORE_DATABASE', 'databasebraccialetti')

# Percorso al file di credenziali del service account
FIRESTORE_CREDENTIALS = os.environ.get(
    'FIRESTORE_CREDENTIALS',
    os.path.join(os.path.dirname(__file__), '..', 'credentials.json')
)

# Project ID GCP da usare (deve corrispondere alle credenziali)
FIRESTORE_PROJECT_ID = os.environ.get('FIRESTORE_PROJECT_ID', 'strong-charge-465917-k4')

# =========================
# Default plot window (days)
# =========================
DEFAULT_PLOT_DAYS = int(os.environ.get('DEFAULT_PLOT_DAYS', '7'))
