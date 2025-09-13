# Pervasive Computing & Cloud — Empatica E4 Monitor (Flask, SQLite)

Questo progetto implementa **end-to-end** i requisiti:
- Client che legge i CSV e invia riga per riga via **HTTP** al server.
- Server Flask che riceve e salva su **SQLite**.
- **Utenti** e **amministratori** (login, ruoli, gestione utenti).
- **Grafici** server-side (Matplotlib) senza JS.
- **Statistiche settimanali** (medie, conteggi).
- **Media mobile** + **soglie** → anomalie (viste in dashboard).
- **Notifiche email** (console per default, SMTP configurabile).
- **Client dinamici**: avvia feeder per ogni cartella in `data_samples/<username>/`.

## Avvio locale
```bash
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
cd app
python app.py
```
Admin predefinito: **admin / admin123**

### Feeder lato server
1. Copia i CSV del dataset ufficiale (wrist_*.csv) nelle sottocartelle:
   - `data_samples/alice/`
   - `data_samples/samu/`
   - `data_samples/asmaa/`
2. Vai su **/admin** e premi **Avvia** → i feeder leggono i CSV e inviano dati al DB (simulazione IoT).

### Feeder client esterno (opzionale)
```bash
python client.py --folder "C:\path\al\dataset" --server "http://127.0.0.1:5000" --username alice --interval 1.0
```

## Deploy su Cloud
- Puoi usare **Railway**, **Render** o **Fly.io**.
- Imposta `SECRET_KEY` e (opzionale) `EMAIL_MODE=smtp` + SMTP_* env.
- Avvia `python app/app.py` come comando.

## Struttura
```
.
├─ app/
│  ├─ app.py            # server Flask
│  ├─ auth.py           # utenti/login
│  ├─ analytics.py      # stats e anomalie
│  ├─ plots.py          # PNG grafici
│  ├─ db.py             # SQLite helpers
│  ├─ emailer.py        # email stub/smtp
│  ├─ config.py         # config e soglie
│  └─ templates/…       # HTML unificati
├─ client.py            # feeder HTTP standalone
├─ data_samples/…       # cartelle utenti con CSV
├─ requirements.txt
└─ README.md
```

## Dataset
Usa i file dal dataset **FatigueSet** (Empatica E4):  
`wrist_acc.csv, wrist_bvp.csv, wrist_eda.csv, wrist_hr.csv, wrist_ibi.csv, wrist_skin_temperature.csv`

I CSV di esempio inclusi sono artificiali, solo per test. Per l'esame, sostituiscili con quelli reali.

## Slides
Sono sufficienti **4–5 slide** su:
1. Obiettivo & architettura (client HTTP → server Flask → DB SQLite).
2. Modello dati e sicurezza (ruoli).
3. Grafici e statistiche (settimanali, moving average).
4. Gestione anomalie & notifiche (email/console).
5. Deploy su Cloud (env vars, comandi).


## Firestore (Cloud)
- Inserisci il file `credentials.json` (service account) nella **radice del progetto** (già incluso in questa build).
- Configurazione in `app/config.py`: `FIRESTORE_DATABASE`, `FIRESTORE_CREDENTIALS`.
- Il sistema scrive **in parallelo** su SQLite e **Firestore**:
  - **users**: creazione/eliminazione da Admin → riflesso su `users/{username}`
  - **readings**: ogni POST su `/api/sensor_data` → insert su `readings` (collezione) in Firestore
  - **anomalies**: quando rilevate → insert su `anomalies` (collezione)


## Troubleshooting Firestore
1. Verifica credenziali e progetto:
   ```bash
   python fs_diag.py
   ```
   Dovresti vedere il project ID e una scrittura su `diagnostics/ping`.
2. Dal pannello **Admin** usa:
   - **Verifica connessione** → mostra project rilevato
   - **Scrittura di test** → crea/aggiorna `diagnostics/ping`
3. Se non vedi gli utenti creati:
   - usa **🔄 Sincronizza utenti su Firestore** (backfill)
   - controlla che `FIRESTORE_PROJECT_ID` corrisponda al progetto dove guardi la console
   - assicurati che il service account abbia almeno ruolo *Editor*
