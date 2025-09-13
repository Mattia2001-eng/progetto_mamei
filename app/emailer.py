import smtplib, ssl, sys, mimetypes
from email.message import EmailMessage
import config

_last_status = {'last_sent': None, 'queue_size': 0}

def send_email(to_email, subject, body, attachments=None):
    """
    Invia una email.
    - to_email: destinatario (stringa)
    - subject: oggetto
    - body: contenuto testo (plain)
    - attachments: lista opzionale di dict:
        {
          "filename": "file.csv",
          "content":  b"...bytes..."  oppure  "stringa testo",
          "mime":     "text/csv"      (opzionale; se assente prova da mimetypes)
        }
    """
    global _last_status
    attachments = attachments or []

    if config.EMAIL_MODE == 'console':
        print('[EMAIL][CONSOLE] to:', to_email, '| subject:', subject)
        print(body[:2000])
        if attachments:
            print('[EMAIL][CONSOLE] allegati:', [a.get('filename') for a in attachments])
        _last_status['last_sent'] = 'console'
        return True

    try:
        msg = EmailMessage()
        msg['From'] = config.FROM_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.set_content(body)

        # Allegati (facoltativi)
        for att in attachments:
            filename = att.get('filename') or 'attachment.bin'
            content  = att.get('content', b'')
            mime     = att.get('mime')

            # Se content è str, convertilo in bytes (utf-8)
            if isinstance(content, str):
                content = content.encode('utf-8')

            if not mime:
                guessed, _ = mimetypes.guess_type(filename)
                mime = guessed or 'application/octet-stream'

            if '/' in mime:
                maintype, subtype = mime.split('/', 1)
            else:
                maintype, subtype = 'application', 'octet-stream'

            msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

        context = ssl.create_default_context()
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(config.SMTP_USER, config.SMTP_PASS)
            server.send_message(msg)

        _last_status['last_sent'] = 'smtp'
        return True
    except Exception as e:
        print('[EMAIL][ERROR]', e, file=sys.stderr)
        return False

def email_status():
    return _last_status
