import os, sqlite3, secrets, string, hashlib
from datetime import datetime, timedelta, timezone
from cryptography.fernet import Fernet

DB_PATH = os.environ.get('DB_PATH', 'teilor.db')
_key = os.environ.get('FERNET_KEY', '').strip()
if not _key:
    raise RuntimeError('Falta FERNET_KEY en Render. Genera una con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"')
try:
    cipher = Fernet(_key.encode())
except Exception as exc:
    raise RuntimeError('FERNET_KEY no es válida. Debe ser una clave Fernet completa.') from exc

def encrypt(value):
    return cipher.encrypt(str(value).encode()).decode() if value else ''
def decrypt(value):
    return cipher.decrypt(value.encode()).decode() if value else ''
def now(): return datetime.now(timezone.utc)
def iso(dt=None): return (dt or now()).isoformat()
def parse_dt(value): return datetime.fromisoformat(value) if value else None
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn
def token_hash(value): return hashlib.sha256(value.encode()).hexdigest()
def random_code(length=8): return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length))
def create_code(months, devices):
    code = random_code(8)
    with db() as c:
        c.execute('INSERT INTO activation_codes(code,months,devices,created_at,expires_at) VALUES(?,?,?,?,?)',
                  (code, months, devices, iso(), iso(now()+timedelta(hours=48))))
    return code
def create_pair_code(user_id):
    code = random_code(6)
    with db() as c:
        c.execute('INSERT INTO pair_codes(code,user_id,created_at,expires_at) VALUES(?,?,?,?)',
                  (code, user_id, iso(), iso(now()+timedelta(hours=24))))
    return code
def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,status TEXT DEFAULT 'active',expires_at TEXT,max_devices INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS devices(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,install_id TEXT NOT NULL,device_name TEXT,last_seen TEXT,revoked INTEGER DEFAULT 0,UNIQUE(user_id,install_id),FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS servers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,kind TEXT,url TEXT,username_enc TEXT,password_enc TEXT,active INTEGER DEFAULT 1,created_at TEXT);
        CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,device_id INTEGER NOT NULL,token_hash TEXT NOT NULL UNIQUE,created_at TEXT,revoked INTEGER DEFAULT 0,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS activation_codes(code TEXT PRIMARY KEY,months INTEGER NOT NULL,devices INTEGER NOT NULL,created_at TEXT,expires_at TEXT,used_at TEXT,used_by INTEGER);
        CREATE TABLE IF NOT EXISTS pair_codes(code TEXT PRIMARY KEY,user_id INTEGER NOT NULL,created_at TEXT,expires_at TEXT,used_at TEXT,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);
        CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);
        ''')
