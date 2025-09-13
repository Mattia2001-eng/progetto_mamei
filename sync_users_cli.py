
import os, sys
sys.path.append(os.path.join(os.path.dirname(__file__), "app"))
from db import query_all
from firestore_db import fs_upsert_user

rows = query_all('SELECT username, email, role, created_at FROM users')
count = 0
for r in rows:
    fs_upsert_user(r['username'], r['email'], r['role'], r.get('created_at'))
    print("[FS][UPSERT][user]", r['username'])
    count += 1
print("[FS][SYNC][CLI] total:", count)
