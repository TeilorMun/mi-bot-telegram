import os, secrets, string, hashlib, hmac
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import psycopg2
import psycopg2.extras
from cryptography.fernet import Fernet, InvalidToken

# --- DATOS DE CONEXIÓN ---
# El usuario y la contraseña van aquí escritos para que no haya que pegar URLs largas.
DB_HOST = 'aws-0-eu-central-1.pooler.supabase.com'
DB_PORT = '5432'
DB_USER = 'postgres.hotekovqnkpwwevulwrt'
DB_PASS = 'I5724180t.@'
DB_NAME = 'postgres'

DATABASE_URL = (
    f"postgresql://{DB_USER}:{quote(DB_PASS, safe='')}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode=require"
)

# Clave Fernet fija: NO cambiarla nunca o las credenciales guardadas dejan de abrirse.
ENCRYPT_KEY = 'FFbj9Huz7DbWp16juLVrzzoeNB1Fx-pWKzMWBLURxHc='

# Clave para firmar los hashes de sesión.
SECRET_KEY = 'TlszO3JNgUMZbOgF-kfwQccpVkLEjBbmGkMJ-_qIt18='

_cipher = Fernet(ENCRYPT_KEY.encode())
_HMAC_KEY = SECRET_KEY.encode()

def encrypt(text):
    if not text: return ""
    return _cipher.encrypt(text.encode()).decode()

def decrypt(token):
    if not token: return ""
    try:
        return _cipher.decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ""

def token_hash(token):
    return hmac.new(_HMAC_KEY, token.encode(), hashlib.sha256).hexdigest()

def now():
    return datetime.now(timezone.utc)

def iso(dt=None):
    if dt is None: dt = now()
    return dt.isoformat()

def parse_dt(s):
    if not s: return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt

@contextmanager
def db():
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            status TEXT DEFAULT 'active',
            expires_at TIMESTAMPTZ,
            max_devices INTEGER DEFAULT 1,
            telegram_user TEXT,
            telegram_id TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS devices (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            install_id TEXT,
            device_name TEXT,
            last_seen TIMESTAMPTZ,
            revoked BOOLEAN DEFAULT FALSE
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS servers (
            id SERIAL PRIMARY KEY,
            name TEXT,
            kind TEXT,
            url TEXT,
            username_enc TEXT,
            password_enc TEXT,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE,
            token_hash TEXT UNIQUE,
            created_at TIMESTAMPTZ,
            last_seen_at TIMESTAMPTZ,
            revoked BOOLEAN DEFAULT FALSE
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS activation_codes (
            code TEXT PRIMARY KEY,
            months INTEGER NOT NULL,
            devices INTEGER NOT NULL,
            expires_at TIMESTAMPTZ,
            used_at TIMESTAMPTZ,
            used_by INTEGER,
            allowed_telegram_id TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS pair_codes (
            code TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            expires_at TIMESTAMPTZ,
            used_at TIMESTAMPTZ
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_devices_install ON devices(install_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_codes_used ON activation_codes(used_at)')

_ALPHABET = string.ascii_uppercase + string.digits

def _gen_code(n):
    return ''.join(secrets.choice(_ALPHABET) for _ in range(n))

def create_code(months, devices, allowed_id=""):
    if months not in (1, 3, 6, 12): raise ValueError('Meses no válidos')
    if devices not in (1, 2, 3, 4): raise ValueError('Dispositivos no válidos')
    with db() as c:
        for _ in range(10):
            code = _gen_code(12)
            c.execute('SELECT 1 FROM activation_codes WHERE code=%s', (code,))
            if c.fetchone(): continue
            c.execute('INSERT INTO activation_codes(code, months, devices, expires_at, allowed_telegram_id) VALUES(%s,%s,%s,%s,%s)',
                      (code, months, devices, now() + timedelta(hours=48), allowed_id))
            return code
    raise RuntimeError('No se pudo generar un código único')

def create_pair_code(user_id):
    with db() as c:
        for _ in range(10):
            code = _gen_code(8)
            c.execute('SELECT 1 FROM pair_codes WHERE code=%s', (code,))
            if c.fetchone(): continue
            c.execute('INSERT INTO pair_codes(code, user_id, expires_at) VALUES(%s,%s,%s)',
                      (code, user_id, now() + timedelta(hours=24)))
            return code
    raise RuntimeError('No se pudo generar un código único')
