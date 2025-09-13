
import os, time, sys
sys.path.append(os.path.join(os.path.dirname(__file__), "app"))
import config
from firestore_db import fs
try:
    client = fs()
    print("[FS][OK] client init. project:", client.project)
    doc = {'when': time.time(), 'who': 'cli', 'note': 'ping from fs_diag.py'}
    client.collection('diagnostics').document('ping').set(doc, merge=True)
    print("[FS][OK] wrote diagnostics/ping")
    # read back
    snap = client.collection('diagnostics').document('ping').get()
    print("[FS][READBACK]", snap.to_dict())
except Exception as e:
    import traceback; traceback.print_exc()
    print("[FS][ERROR]", e)
