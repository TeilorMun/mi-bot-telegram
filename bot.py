import os, json, threading, secrets, time, hmac, hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from common import *

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or '9056359122:AAELN788sK9bIjCFV-5fHJ61JMjVt1RQwPI'
ADMINS = {a.strip() for a in (os.environ.get('TELEGRAM_ADMINS') or '740151755').split(',') if a.strip()}
PORT = int(os.environ.get('PORT', '10000'))

SESSION_TTL = timedelta(days=30)
SESSION_REFRESH = timedelta(days=20)
RATE_WINDOW = 60
XTREAM_TIMEOUT = 15

_rate = {}
_rate_lock = threading.Lock()

def rate_ok(key, limit, window=RATE_WINDOW):
    t = time.time()
    with _rate_lock:
        hits = [h for h in _rate.get(key, []) if t - h < window]
        if len(hits) >= limit:
            _rate[key] = hits
            return False
        hits.append(t)
        _rate[key] = hits
        return True

def is_admin(update):
    return bool(update.effective_user and str(update.effective_user.id) in ADMINS)

async def admin_only(update):
    if not is_admin(update):
        await update.effective_message.reply_text('⛔ Solo el administrador puede usar este comando.')
        return False
    return True

async def start(update, context):
    if is_admin(update):
        await update.effective_message.reply_text('👑 TEILOR PLAYER · Panel del propietario\n\nUsa /panel para ver todos los comandos de control.')
    else:
        await update.effective_message.reply_text('👋 Bienvenido a TEILOR PLAYER.\n\n⚠️ Tu cuenta aún no está autorizada. Pide al administrador que te añada y te dará un código de activación.')

async def id_cmd(update, context):
    await update.effective_message.reply_text('Tu ID de Telegram es: ' + str(update.effective_user.id))

async def panel(update, context):
    if await admin_only(update):
        await update.effective_message.reply_text('''👑 TEILOR PLAYER — CONTROL TOTAL

USUARIOS
/autorizar ID_TELEGRAM @usuario   (Da acceso a la app)
/usuarios                         (Ver todos los usuarios y su ID)
/bloquear ID_INTERNO              (Bloquear usuario)
/activar ID_INTERNO               (Reactivar usuario)
/borrar ID_INTERNO                (Eliminar usuario)

SERVIDORES
/addm3u Nombre | URL_XTREAM
/servidores                       (Ver lista de servidores)
/delserver ID_SERVIDOR            (Eliminar servidor)
/offserver ID_SERVIDOR            (Desactivar servidor)
/onserver ID_SERVIDOR             (Activar servidor)

OTROS
/crear MESES DISPOSITIVOS         (Crear código directo)''')

async def autorizar(u, c):
    if not await admin_only(u): return
    try:
        tg_id = c.args[0]
        if not tg_id.lstrip('-').isdigit(): raise ValueError
        tg_user = c.args[1].replace('@', '') if len(c.args) > 1 else 'SinNombre'
        code = create_code(12, 2, tg_id)
        await u.effective_message.reply_text(
            f'✅ USUARIO AUTORIZADO\n\nUsuario: @{tg_user} (ID: {tg_id})\nCódigo de activación: {code}\n\n'
            'El usuario debe ir a la app e introducir ese código para entrar.')
    except Exception:
        await u.effective_message.reply_text('Uso: /autorizar 123456789 @nombre_usuario')

async def usuarios(u, c):
    if not await admin_only(u): return
    with db() as x:
        x.execute('SELECT id,telegram_user,telegram_id,status,expires_at,max_devices FROM users ORDER BY id DESC LIMIT 50')
        rows = x.fetchall()
    if not rows:
        await u.effective_message.reply_text('No hay usuarios registrados.')
        return
    lines = ['👥 USUARIOS REGISTRADOS']
    for r in rows:
        vence = iso(r['expires_at'])[:10] if r['expires_at'] else 'sin fecha'
        lines.append(f"ID: {r['id']} | @{r['telegram_user'] or '-'} | TG_ID: {r['telegram_id'] or '-'} | {r['status']} | Vence: {vence}")
    await u.effective_message.reply_text('\n'.join(lines))

async def user_action(u, c, action):
    if not await admin_only(u): return
    try:
        uid = int(c.args[0])
    except Exception:
        await u.effective_message.reply_text('Uso: /' + action + ' ID_INTERNO')
        return
    with db() as x:
        if action == 'borrar':
            x.execute('DELETE FROM users WHERE id=%s', (uid,))
        elif action == 'bloquear':
            x.execute("UPDATE users SET status='blocked' WHERE id=%s", (uid,))
        elif action == 'activar':
            x.execute("UPDATE users SET status='active' WHERE id=%s", (uid,))
    await u.effective_message.reply_text('✅ Hecho: ' + action + ' sobre el usuario ' + str(uid))

async def bloquear(u, c): await user_action(u, c, 'bloquear')
async def activar(u, c): await user_action(u, c, 'activar')
async def borrar(u, c): await user_action(u, c, 'borrar')

async def addm3u(u, c):
    if not await admin_only(u): return
    texto = ' '.join(c.args)
    if '|' not in texto:
        await u.effective_message.reply_text('Uso: /addm3u Nombre | https://host:puerto')
        return
    nombre, url = [p.strip() for p in texto.split('|', 1)]
    url = url.rstrip('/')
    try:
        info = xtream_login(url)
    except Exception as e:
        await u.effective_message.reply_text('❌ No se pudo conectar: ' + str(e))
        return
    if not info:
        await u.effective_message.reply_text('❌ Credenciales Xtream rechazadas.')
        return
    with db() as x:
        x.execute('INSERT INTO servers(name,kind,url,username_enc,password_enc,active,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                  (nombre, 'xtream', url, encrypt(info['username']), encrypt(info['password']), True, iso()))
        x.execute('SELECT id FROM servers ORDER BY id DESC LIMIT 1')
        sid = x.fetchone()['id']
    await u.effective_message.reply_text(f'✅ Servidor añadido: {nombre}\nID: {sid}\n\nActívalo con /onserver {sid} si estaba desactivado.')

async def servidores(u, c):
    if not await admin_only(u): return
    with db() as x:
        x.execute('SELECT id,name,url,active FROM servers ORDER BY id')
        rows = x.fetchall()
    if not rows:
        await u.effective_message.reply_text('No hay servidores.')
        return
    lines = ['📡 SERVIDORES']
    for r in rows:
        lines.append(f"ID: {r['id']} | {r['name']} | {r['url']} | {'ACTIVO' if r['active'] else 'OFF'}")
    await u.effective_message.reply_text('\n'.join(lines))

async def server_action(u, c, action):
    if not await admin_only(u): return
    try:
        sid = int(c.args[0])
    except Exception:
        await u.effective_message.reply_text('Uso: /' + action + ' ID_SERVIDOR')
        return
    with db() as x:
        if action == 'delserver':
            x.execute('DELETE FROM servers WHERE id=%s', (sid,))
        elif action == 'offserver':
            x.execute('UPDATE servers SET active=FALSE WHERE id=%s', (sid,))
        elif action == 'onserver':
            x.execute('UPDATE servers SET active=TRUE WHERE id=%s', (sid,))
    await u.effective_message.reply_text('✅ Hecho: ' + action + ' sobre el servidor ' + str(sid))

async def delserver(u, c): await server_action(u, c, 'delserver')
async def offserver(u, c): await server_action(u, c, 'offserver')
async def onserver(u, c): await server_action(u, c, 'onserver')

async def crear(u, c):
    if not await admin_only(u): return
    try:
        meses, disp = int(c.args[0]), int(c.args[1])
    except Exception:
        await u.effective_message.reply_text('Uso: /crear MESES DISPOSITIVOS')
        return
    code = create_code(meses, disp)
    await u.effective_message.reply_text(f'✅ CÓDIGO CREADO\n\n{code}\n\n{meses} mes(es) · {disp} dispositivo(s)')

# ---------------- Xtream ----------------
def xtream_login(base):
    base = base.rstrip('/')
    u, p = get_creds()
    if not base and u:
        base = XTREAM_BASE
    if not base:
        return None
    import urllib.request
    url = f"{base}/player_api.php?username={u}&password={p}"
    with urllib.request.urlopen(url, timeout=XTREAM_TIMEOUT) as r:
        data = json.loads(r.read().decode('utf-8', 'replace'))
    if data.get('user_info', {}).get('auth') == 1:
        return {'username': u, 'password': p}
    return None

def fetch_json(base, user, pwd, params=''):
    import urllib.request
    url = f"{base}/player_api.php?username={user}&password={pwd}{params}"
    with urllib.request.urlopen(url, timeout=XTREAM_TIMEOUT) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))

def get_creds():
    return ('LTD1982', 't8nQXHgSyS')

XTREAM_BASE = 'https://av-ext.com:8443'

def server_creds(server_id):
    with db() as x:
        x.execute('SELECT url,username_enc,password_enc FROM servers WHERE id=%s AND active=TRUE', (server_id,))
        row = x.fetchone()
    if not row:
        return None
    return row['url'], decrypt(row['username_enc']), decrypt(row['password_enc'])

def build_catalog(server_id):
    creds = server_creds(server_id)
    if not creds:
        return {'live': [], 'movies': [], 'series': [], 'categorias': {'live': [], 'movies': [], 'series': []}}
    base, user, pwd = creds
    cat_live = fetch_json(base, user, pwd, '&action=get_live_categories') or []
    cat_vod = fetch_json(base, user, pwd, '&action=get_vod_categories') or []
    cat_ser = fetch_json(base, user, pwd, '&action=get_series_categories') or []
    live = fetch_json(base, user, pwd, '&action=get_live_streams') or []
    vod = fetch_json(base, user, pwd, '&action=get_vod_streams') or []
    ser = fetch_json(base, user, pwd, '&action=get_series') or []
    def cat_name(cats, cid):
        for c in cats:
            if str(c.get('category_id')) == str(cid):
                return c.get('category_name', '')
        return ''
    return {
        'live': [{'id': s.get('stream_id'), 'name': s.get('name', ''), 'logo': s.get('stream_icon', ''), 'category': cat_name(cat_live, s.get('category_id')), 'categoria': cat_name(cat_live, s.get('category_id'))} for s in live],
        'movies': [{'id': s.get('stream_id'), 'name': s.get('name', ''), 'poster': s.get('stream_icon', ''), 'rating': s.get('rating'), 'plot': s.get('plot', ''), 'categoria': cat_name(cat_vod, s.get('category_id'))} for s in vod],
        'series': [{'id': s.get('series_id'), 'name': s.get('name', ''), 'poster': s.get('cover', ''), 'rating': s.get('rating'), 'plot': s.get('plot', ''), 'categoria': cat_name(cat_ser, s.get('category_id'))} for s in ser],
        'categorias': {
            'live': [c.get('category_name', '') for c in cat_live],
            'movies': [c.get('category_name', '') for c in cat_vod],
            'series': [c.get('category_name', '') for c in cat_ser],
        }
    }

def build_stream_url(server_id, stream_id, kind):
    creds = server_creds(server_id)
    if not creds:
        return None
    base, user, pwd = creds
    if kind == 'live':
        return f"{base}/live/{user}/{pwd}/{stream_id}.m3u8"
    if kind == 'movie':
        return f"{base}/movie/{user}/{pwd}/{stream_id}.m3u8"
    return f"{base}/series/{user}/{pwd}/{stream_id}.m3u8"

def series_episodes(server_id, series_id):
    creds = server_creds(server_id)
    if not creds:
        return []
    base, user, pwd = creds
    data = fetch_json(base, user, pwd, f'&action=get_series_info&series_id={series_id}') or {}
    eps = []
    for season, lst in (data.get('episodes') or {}).items():
        for e in lst:
            eps.append({'id': e.get('id'), 'name': e.get('title') or f"T{season} E{e.get('episode_num')}", 'poster': e.get('movie_image', '')})
    return eps
    # ---------------- Sesiones ----------------
def create_session(user_id, device_id):
    token = secrets.token_urlsafe(32)
    with db() as x:
        x.execute('INSERT INTO sessions(user_id,device_id,token_hash,created_at,last_seen_at) VALUES(%s,%s,%s,%s,%s)',
                  (user_id, device_id, token_hash(token), iso(), iso()))
    return token

def user_from_token(token):
    if not token:
        return None
    with db() as x:
        x.execute('SELECT * FROM sessions WHERE token_hash=%s AND revoked=FALSE', (token_hash(token),))
        s = x.fetchone()
        if not s:
            return None
        r = parse_dt(s['last_seen_at'])
        if r and now() - r > SESSION_TTL:
            x.execute('UPDATE sessions SET revoked=TRUE WHERE id=%s', (s['id'],))
            return None
        x.execute('UPDATE sessions SET last_seen_at=%s WHERE id=%s', (iso(), s['id']))
        x.execute('SELECT * FROM users WHERE id=%s', (s['user_id'],))
        u = x.fetchone()
        if not u or u['status'] != 'active':
            return None
        if u['expires_at'] and parse_dt(u['expires_at']) and parse_dt(u['expires_at']) < now():
            return None
        return u

def public_user(u):
    return {'id': u['id'], 'telegram_user': u['telegram_user'], 'expires_at': iso(u['expires_at']) if u['expires_at'] else None, 'max_devices': u['max_devices']}

def servers_list():
    with db() as x:
        x.execute('SELECT id,name FROM servers WHERE active=TRUE ORDER BY id')
        return [{'id': r['id'], 'name': r['name']} for r in x.fetchall()]

def activate_code(code, install_id, device_name_):
    with db() as x:
        x.execute('SELECT * FROM activation_codes WHERE code=%s', (code,))
        c = x.fetchone()
        if not c or c['used_at']:
            return None, 'Código no válido o ya usado.'
        exp = parse_dt(c['expires_at'])
        if exp and exp < now():
            return None, 'Código caducado.'
        tg_id = c['allowed_telegram_id']
        x.execute('SELECT * FROM users WHERE telegram_id=%s ORDER BY id DESC LIMIT 1', (tg_id,))
        u = x.fetchone() if tg_id else None
        if u:
            base = parse_dt(u['expires_at']) if u['expires_at'] else now()
            if base < now(): base = now()
            new_exp = base + timedelta(days=30 * c['months'])
            x.execute('UPDATE users SET expires_at=%s, max_devices=%s, status=%s WHERE id=%s',
                      (iso(new_exp), c['devices'], 'active', u['id']))
            uid = u['id']
        else:
            x.execute('INSERT INTO users(status,expires_at,max_devices,telegram_user,telegram_id) VALUES(%s,%s,%s,%s,%s) RETURNING id',
                      ('active', iso(now() + timedelta(days=30 * c['months'])), c['devices'], None, tg_id))
            uid = x.fetchone()['id']
        x.execute('UPDATE activation_codes SET used_at=%s, used_by=%s WHERE code=%s', (iso(), uid, code))
        x.execute('SELECT * FROM devices WHERE user_id=%s AND revoked=FALSE', (uid,))
        devs = x.fetchall()
        if len(devs) >= (c['devices'] or 1):
            x.execute('UPDATE devices SET revoked=TRUE WHERE id=%s', (devs[0]['id'],))
        x.execute('INSERT INTO devices(user_id,install_id,device_name,last_seen) VALUES(%s,%s,%s,%s) RETURNING id',
                  (uid, install_id, device_name_, iso()))
        did = x.fetchone()['id']
        x.execute('SELECT * FROM users WHERE id=%s', (uid,))
        user = x.fetchone()
    return (user, did), None

class Handler(BaseHTTPRequestHandler):
    server_version = 'TeilorAPI/2.0'

    def log_message(self, *a): pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        raw = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, code, data): self._send(code, data)

    def _err(self, code, msg): self._json(code, {'error': msg})

    def _body(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
            return json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
        except Exception:
            return {}

    def _token(self):
        h = self.headers.get('Authorization') or ''
        return h[7:].strip() if h.startswith('Bearer ') else None

    def _auth(self):
        u = user_from_token(self._token())
        if not u: self._err(401, 'Sesión no válida.')
        return u

    def _ip(self): return self.client_address[0]

    def do_OPTIONS(self): self._send(204, '')

    def do_GET(self):
        p = urlparse(self.path)
        path, q = p.path, parse_qs(p.query)

        if path in ('/', '/index.html'):
            try:
                with open('index.html', 'rb') as f:
                    return self._send(200, f.read(), 'text/html; charset=utf-8')
            except FileNotFoundError:
                return self._err(500, 'Falta index.html en el repo.')
        if path in ('/health', '/healthz', '/api/status'):
            try:
                with db() as x:
                    x.execute('SELECT COUNT(*) AS n FROM servers')
                    n = x.fetchone()['n']
                return self._json(200, {'estado': 'en linea', 'servicio': 'API del reproductor TEILOR', 'servidores': n})
            except Exception as e:
                return self._json(200, {'estado': 'en linea', 'servicio': 'API del reproductor TEILOR', 'db': str(e)})
        if path == '/favicon.ico':
            return self._send(200, b'', 'image/x-icon')

        if not rate_ok(self._ip() + path, 90):
            return self._err(429, 'Demasiadas peticiones.')

        if path == '/api/me':
            u = self._auth()
            if not u: return
            return self._json(200, {'user': public_user(u), 'servers': servers_list(), 'server_id': (servers_list()[0]['id'] if servers_list() else None)})

        if path == '/api/catalog':
            u = self._auth()
            if not u: return
            sid = q.get('server_id', [None])[0]
            if not sid: return self._err(400, 'Falta server_id.')
            try:
                return self._json(200, build_catalog(int(sid)))
            except Exception as e:
                return self._err(502, 'El proveedor no responde: ' + str(e))

        if path.startswith('/api/series/') and path.endswith('/episodes'):
            u = self._auth()
            if not u: return
            try:
                sid = int(path.split('/')[3])
                return self._json(200, {'episodes': series_episodes(sid, path.split('/')[4])})
            except Exception as e:
                return self._err(502, str(e))

        if path == '/api/favorites':
            u = self._auth()
            if not u: return
            with db() as x:
                x.execute('SELECT item_type,item_ref,name,poster FROM favorites WHERE user_id=%s ORDER BY id DESC', (u['id'],))
                return self._json(200, {'favorites': [dict(r) for r in x.fetchall()]})

        if path == '/api/resume':
            u = self._auth()
            if not u: return
            with db() as x:
                x.execute('SELECT item_type,item_ref,percent,seconds FROM resume WHERE user_id=%s ORDER BY id DESC LIMIT 50', (u['id'],))
                return self._json(200, {'continue': [dict(r) for r in x.fetchall()]})

        return self._err(404, 'Ruta no encontrada.')

    def do_POST(self):
        path = urlparse(self.path).path
        if not rate_ok(self._ip() + path, 60):
            return self._err(429, 'Demasiadas peticiones.')

        if path == '/api/activate':
            b = self._body()
            code = (b.get('code') or '').strip().upper()
            res, err = activate_code(code, b.get('install_id'), b.get('device_name'))
            if err: return self._err(400, err)
            user, did = res
            token = create_session(user['id'], did)
            return self._json(200, {'token': token, 'user': public_user(user), 'servers': servers_list(),
                                    'server_id': (servers_list()[0]['id'] if servers_list() else None)})

        if path == '/api/stream':
            u = self._auth()
            if not u: return
            b = self._body()
            url = build_stream_url(int(b.get('server_id') or 0), b.get('stream_id'), b.get('type') or 'live')
            if not url: return self._err(400, 'Servidor no válido.')
            return self._json(200, {'url': url, 'title': b.get('title') or ''})

        if path == '/api/favorites':
            u = self._auth()
            if not u: return
            b = self._body()
            with db() as x:
                x.execute('DELETE FROM favorites WHERE user_id=%s AND item_type=%s AND item_ref=%s',
                          (u['id'], b.get('item_type'), b.get('item_ref')))
                x.execute('INSERT INTO favorites(user_id,item_type,item_ref,name,poster) VALUES(%s,%s,%s,%s,%s)',
                          (u['id'], b.get('item_type'), b.get('item_ref'), b.get('name'), b.get('poster')))
            return self._json(200, {'ok': True})

        if path == '/api/resume':
            u = self._auth()
            if not u: return
            b = self._body()
            with db() as x:
                x.execute('DELETE FROM resume WHERE user_id=%s AND item_type=%s AND item_ref=%s',
                          (u['id'], b.get('item_type'), b.get('item_ref')))
                x.execute('INSERT INTO resume(user_id,item_type,item_ref,percent,seconds) VALUES(%s,%s,%s,%s,%s)',
                          (u['id'], b.get('item_type'), b.get('item_ref'), b.get('percent') or 0, b.get('seconds') or 0))
            return self._json(200, {'ok': True})

        return self._err(404, 'Ruta no encontrada.')

    def do_DELETE(self):
        path = urlparse(self.path).path
        u = self._auth()
        if not u: return
        if path == '/api/favorites':
            b = self._body()
            with db() as x:
                x.execute('DELETE FROM favorites WHERE user_id=%s AND item_type=%s AND item_ref=%s',
                          (u['id'], b.get('item_type'), b.get('item_ref')))
            return self._json(200, {'ok': True})
        return self._err(404, 'Ruta no encontrada.')

def run_http():
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()

def main():
    init_db()
    threading.Thread(target=run_http, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('id', id_cmd))
    app.add_handler(CommandHandler('panel', panel))
    app.add_handler(CommandHandler('autorizar', autorizar))
    app.add_handler(CommandHandler('usuarios', usuarios))
    app.add_handler(CommandHandler('bloquear', bloquear))
    app.add_handler(CommandHandler('activar', activar))
    app.add_handler(CommandHandler('borrar', borrar))
    app.add_handler(CommandHandler('addm3u', addm3u))
    app.add_handler(CommandHandler('servidores', servidores))
    app.add_handler(CommandHandler('delserver', delserver))
    app.add_handler(CommandHandler('offserver', offserver))
    app.add_handler(CommandHandler('onserver', onserver))
    app.add_handler(CommandHandler('crear', crear))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
