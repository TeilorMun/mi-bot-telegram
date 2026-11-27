import sqlite3, time, random, string, os, hashlib
from datetime import datetime, timedelta, timezone
from cryptography.fernet import Fernet

SECRET_KEY = Fernet.generate_key()
cipher = Fernet(SECRET_KEY)

def encrypt(text):
    if not text: return ""
    return cipher.encrypt(text.encode()).decode()

def decrypt(token):
    if not token: return ""
    return cipher.decrypt(token.encode()).decode()

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def now():
    return datetime.now(timezone.utc)

def iso(dt=None):
    if dt is None: dt = now()
    return dt.isoformat()

def parse_dt(s):
    if not s: return None
    return datetime.fromisoformat(s)

def db():
    conn = sqlite3.connect('teilor.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        # Tabla de usuarios
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT DEFAULT 'active',
            expires_at TEXT,
            max_devices INTEGER DEFAULT 1,
            telegram_user TEXT,
            telegram_id TEXT
        )''')
        # Tabla de dispositivos
        c.execute('''CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            install_id TEXT,
            device_name TEXT,
            last_seen TEXT,
            revoked INTEGER DEFAULT 0
        )''')
        # Tabla de servidores (soporta múltiples M3U)
        c.execute('''CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            kind TEXT,
            url TEXT,
            username_enc TEXT,
            password_enc TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )''')
        # Tabla de sesiones
        c.execute('''CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            device_id INTEGER,
            token_hash TEXT,
            created_at TEXT,
            revoked INTEGER DEFAULT 0
        )''')
        # Tabla de códigos de activación (generados por el admin)
        c.execute('''CREATE TABLE IF NOT EXISTS activation_codes (
            code TEXT PRIMARY KEY,
            months INTEGER,
            devices INTEGER,
            expires_at TEXT,
            used_at TEXT,
            used_by INTEGER,
            allowed_telegram_id TEXT
        )''')
        # Tabla de códigos de vinculación (para añadir más dispositivos)
        c.execute('''CREATE TABLE IF NOT EXISTS pair_codes (
            code TEXT PRIMARY KEY,
            user_id INTEGER,
            expires_at TEXT,
            used_at TEXT
        )''')

def create_code(months, devices, allowed_id=""):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    with db() as c:
        c.execute('INSERT INTO activation_codes(code, months, devices, expires_at, allowed_telegram_id) VALUES(?,?,?,?,?)',
                  (code, months, devices, iso(now() + timedelta(hours=48)), allowed_id))
    return code

def create_pair_code(user_id):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    with db() as c:
        c.execute('INSERT INTO pair_codes(code, user_id, expires_at) VALUES(?,?,?)',
                  (code, user_id, iso(now() + timedelta(hours=24))))
    return code
