from flask_login import UserMixin
import hashlib
from db import query_one, exec_write, query_all
from firestore_db import fs_upsert_user, fs_delete_user

def hash_pw(pw: str) -> str:
    return hashlib.sha256(('pepper:'+pw).encode()).hexdigest()

class User(UserMixin):
    def __init__(self, id, username, email, role):
        self.id = id
        self.username = username
        self.email = email
        self.role = role

    def is_admin(self):
        return (self.role or '').lower() == 'admin'

def create_user(username, email, pw, role='user'):
    if not username or not email or not pw:
        raise ValueError('username, email, password required')
    ph = hash_pw(pw)
    rid = exec_write('INSERT INTO users(username,email,password_hash,role) VALUES(?,?,?,?)',
                      (username, email, ph, role))
    try:
        fs_upsert_user(username, email, role)
    except Exception as e:
        print('[FS][WARN] create_user:', e)
    return rid

def find_user_by_username(username):
    row = query_one('SELECT * FROM users WHERE username=?', (username,))
    if not row: return None
    return User(row['id'], row['username'], row['email'], row['role'])

def validate_login(username, password):
    row = query_one('SELECT * FROM users WHERE username=?', (username,))
    if not row: return None
    if row['password_hash'] == hash_pw(password):
        return User(row['id'], row['username'], row['email'], row['role'])
    return None

def all_users():
    return query_all('SELECT id, username, email, role, created_at FROM users ORDER BY username')


def delete_user(username):
    # Delete from SQLite
    exec_write('DELETE FROM users WHERE username=?', (username,))
    # Mirror in Firestore
    try:
        fs_delete_user(username)
    except Exception as e:
        print('[FS][WARN] delete_user:', e)


def sync_users_to_firestore():
    rows = query_all('SELECT username, email, role, created_at FROM users')
    synced = 0
    for r in rows:
        try:
            fs_upsert_user(r['username'], r['email'], r['role'], r.get('created_at'))
            synced += 1
        except Exception as e:
            print('[FS][WARN] sync user', r['username'], e)
    print(f'[FS][SYNC] users mirrored to Firestore: {synced}')
    return synced
