import sqlite3, os, threading, time
from contextlib import contextmanager

import config

_lock = threading.Lock()

def init_db():
    with get_conn() as con:
        cur = con.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            email TEXT,
            password_hash TEXT,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS readings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            sensor TEXT,
            timestamp REAL,
            value REAL
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS anomalies(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            sensor TEXT,
            timestamp REAL,
            value REAL,
            threshold REAL,
            window INTEGER
        )''')
        con.commit()

@contextmanager
def get_conn():
    # SQLite connects by filename
    con = sqlite3.connect(config.DATABASE_URL, check_same_thread=False)
    try:
        yield con
    finally:
        con.close()

def exec_write(sql, params=()):
    with _lock:
        with get_conn() as con:
            cur = con.cursor()
            cur.execute(sql, params)
            con.commit()
            return cur.lastrowid

def exec_many(sql, seq_of_params):
    with _lock:
        with get_conn() as con:
            cur = con.cursor()
            cur.executemany(sql, seq_of_params)
            con.commit()

def query_all(sql, params=()):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

def query_one(sql, params=()):
    rows = query_all(sql, params)
    return rows[0] if rows else None
