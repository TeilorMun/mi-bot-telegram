import os, json, threading, secrets, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from common import *

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or '9056359122:AAELN788sK9bIjCFV-5fHJ61JMjVt1RQwPI'
ADMINS = {a.strip() for a in (os.environ.get('TELEGRAM_ADMINS') or '740151755').split(',') if a.strip()}

SESSION_TTL = timedelta(days=30)
SESSION_REFRESH = timedelta(days=20)
RATE_WINDOW = 60

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

SERVIDORES (Xtream)
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
        await u.effective_message.reply_text('Indica el ID interno del usuario (ej: 1). Consulta /usuarios.')
        return
    with db() as x:
        x.execute('SELECT id FROM users WHERE id=%s', (uid,))
        if not x.fetchone():
            await u.effective_message.reply_text('Usuario no encontrado.')
            return
        if action == 'block':
            x.execute("UPDATE users SET status='blocked' WHERE id=%s", (uid,))
            x.execute('UPDATE sessions SET revoked=TRUE WHERE user_id=%s', (uid,))
            msg = 'Usuario bloqueado.'
        elif action == 'enable':
            x.execute("UPDATE users SET status='active' WHERE id=%s", (uid,))
            msg = 'Usuario reactivado.'
        else:
            x.execute('DELETE FROM users WHERE id=%s', (uid,))
            msg = 'Usuario eliminado.'
    await u.effective_message.reply_text('✅ ' + msg)

async def bloquear(u, c): await user_action(u, c, 'block')
async def activar(u, c): await user_action(u, c, 'enable')
async def borrar(u, c): await user_action(u, c, 'delete')

async def crear(u, c):
    if not await admin_only(u): return
    try:
        m, d = int(c.args[0]), int(c.args[1])
        code = create_code(m, d)
        await u.effective_message.reply_text(f'✅ Código genérico: {code}\nDuración: {m} meses\nDispositivos: {d}')
    except Exception:
        await u.effective_message.reply_text('Uso: /crear 6 1')

async def addm3u(u, c):
    if not await admin_only(u): return
    p = ' '.join(c.args).split('|', 1)
    if len(p) != 2:
        await u.effective_message.reply_text('Uso: /addm3u Nombre | URL_XTREAM'); return
    name, link = p[0].strip(), p[1].strip()[:300]
    z = urlparse(link); q = parse_qs(z.query)
    usr = q.get('username', [''])[0]; pw = q.get('password', [''])[0]
    if not usr or not pw:
        parts = [v for v in z.path.strip('/').split('/') if v]
        if len(parts) >= 2: usr, pw = parts[-2:]
    if z.scheme not in ('http', 'https') or not z.netloc or not usr or not pw:
        await u.effective_message.reply_text('Enlace inválido.'); return
    with db() as x:
        x.execute('INSERT INTO servers(name,kind,url,username_enc,password_enc,active,created_at) VALUES(%s,%s,%s,%s,%s,TRUE,%s)',
                  (name[:80], 'xtream', f'{z.scheme}://{z.netloc}', encrypt(usr), encrypt(pw), now()))
    await u.effective_message.reply_text(f'✅ Servidor «{name}» añadido.')

async def servidores(u, c):
    if not await admin_only(u): return
    with db() as x:
        x.execute('SELECT id,name,url,active FROM servers ORDER BY id')
        rows = x.fetchall()
    if not rows:
        await u.effective_message.reply_text('No hay servidores.'); return
    await u.effective_message.reply_text('\n'.join(
        f"ID {r['id']} · {r['name']} · {'ACTIVO' if r['active'] else 'INACTIVO'}\n{r['url']}" for r in rows))

async def server_action(u, c, action):
    if not await admin_only(u): return
    try:
        sid = int(c.args[0])
    except Exception:
        await u.effective_message.reply_text('Indica el ID de servidor.'); return
    with db() as x:
        if action == 'delete':
            x.execute('DELETE FROM servers WHERE id=%s', (sid,))
        else:
            x.execute('UPDATE servers SET active=%s WHERE id=%s', (action == 'on', sid))
        n = x.rowcount
    await u.effective_message.reply_text('✅ Operación aplicada.' if n else 'Servidor no encontrado.')

async def offserver(u, c): await server_action(u, c, 'off')
async def onserver(u, c): await server_action(u, c, 'on')
async def delserver(u, c): await server_action(u, c, 'delete')

def list_servers():
    with db() as x:
        x.execute('SELECT id,name,kind,url,username_enc,password_enc FROM servers WHERE active=TRUE ORDER BY id')
        rows = x.fetchall()
    return [{'id': r['id'], 'name': r['name'], 'kind': r['kind'], 'url': r['url'],
             'username': decrypt(r['username_enc']), 'password': decrypt(r['password_enc'])} for r in rows]

def get_auth_session(h):
    auth = h.headers.get('Authorization', '')
    if not auth.startswith('Bearer '): return None
    digest = token_hash(auth[7:].strip())
    with db() as x:
        x.execute('''SELECT s.id session_id, s.user_id, s.device_id, s.created_at, s.revoked,
                            u.status, u.expires_at, d.revoked device_revoked
                     FROM sessions s JOIN users u ON u.id=s.user_id JOIN devices d ON d.id=s.device_id
                     WHERE s.token_hash=%s AND s.revoked=FALSE''', (digest,))
        return x.fetchone()

def session_ok(row):
    if not row or row['status'] != 'active' or row['device_revoked'] or row['revoked']:
        return False
    uexp = parse_dt(row['expires_at'])
    if not uexp or uexp <= now(): return False
    created = parse_dt(row['created_at'])
    if created and created + SESSION_TTL <= now(): return False
    return True

def api_error(h, msg, status=400):
    h.send_json({'status': 'error', 'message': msg, 'detail': msg}, status)

def activate_code(h, data):
    if not rate_ok('act:' + h.client_address[0], 10):
        return api_error(h, 'Demasiados intentos. Espera un minuto.', 429)
    code = str(data.get('code', '')).strip().upper()
    install = str(data.get('install_id', '')).strip()[:128]
    name = str(data.get('device_name', 'Dispositivo'))[:120]
    if not code or not install:
        return api_error(h, 'Código o dispositivo no válido.', 400)
    raw = secrets.token_urlsafe(36)

    with db() as x:
        x.execute('SELECT * FROM activation_codes WHERE code=%s AND used_at IS NULL', (code,))
        row = x.fetchone()
        if not row: return api_error(h, 'Código incorrecto, ya utilizado o no autorizado.', 403)
        exp_code = parse_dt(row['expires_at'])
        if not exp_code or exp_code <= now(): return api_error(h, 'El código ha caducado.', 403)

        exp = now() + timedelta(days=30 * row['months'])
        x.execute("INSERT INTO users(status,expires_at,max_devices,telegram_id) VALUES('active',%s,%s,%s) RETURNING id",
                  (exp, row['devices'], row['allowed_telegram_id']))
        uid = x.fetchone()['id']
        x.execute('UPDATE activation_codes SET used_at=%s, used_by=%s WHERE code=%s', (now(), uid, code))

        x.execute('SELECT * FROM devices WHERE user_id=%s AND install_id=%s', (uid, install))
        dev = x.fetchone()
        if dev:
            x.execute('UPDATE devices SET device_name=%s,last_seen=%s WHERE id=%s', (name, now(), dev['id']))
            did = dev['id']
        else:
            x.execute('SELECT count(*) n FROM devices WHERE user_id=%s AND revoked=FALSE', (uid,))
            if x.fetchone()['n'] >= row['devices']:
                x.execute('DELETE FROM users WHERE id=%s', (uid,))
                x.execute('UPDATE activation_codes SET used_at=NULL, used_by=NULL WHERE code=%s', (code,))
                return api_error(h, 'Límite de dispositivos alcanzado.', 403)
            x.execute('INSERT INTO devices(user_id,install_id,device_name,last_seen,revoked) VALUES(%s,%s,%s,%s,FALSE) RETURNING id',
                      (uid, install, name, now()))
            did = x.fetchone()['id']

        x.execute('INSERT INTO sessions(user_id,device_id,token_hash,created_at,revoked) VALUES(%s,%s,%s,%s,FALSE)',
                  (uid, did, token_hash(raw), now()))

    h.send_json({'status': 'success', 'session_token': raw, 'user_id': uid, 'servers': list_servers()})

def refresh_session(row):
    created = parse_dt(row['created_at'])
    if created and created + SESSION_REFRESH <= now():
        with db() as x:
            x.execute('UPDATE sessions SET created_at=%s WHERE id=%s', (now(), row['session_id']))

class Handler(BaseHTTPRequestHandler):
    server_version = 'TEILOR'
    sys_version = ''

    def cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS,HEAD')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.cors()
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_OPTIONS(self): self.send_json({'status': 'ok'})
    def do_HEAD(self): self.send_json({'status': 'online'})

    def do_GET(self):
        try:
            if self.path in ('/', '/health', '/healthz'):
                return self.send_json({'status': 'online', 'service': 'TEILOR PLAYER API'})
            row = get_auth_session(self)
            if not session_ok(row): return api_error(self, 'Sesión inválida o caducada.', 401)
            refresh_session(row)
            with db() as x:
                x.execute('UPDATE devices SET last_seen=%s WHERE id=%s', (now(), row['device_id']))
            if self.path == '/api/servers':
                return self.send_json({'status': 'success', 'servers': list_servers()})
            return api_error(self, 'Ruta no encontrada.', 404)
        except Exception as e:
            print('API error GET:', repr(e)); return api_error(self, 'Error interno.', 500)

    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if n <= 0 or n > 100000: return api_error(self, 'Petición demasiado grande.', 413)
            data = json.loads(self.rfile.read(n).decode() or '{}')
            if not isinstance(data, dict): return api_error(self, 'JSON no válido.')
            path = urlparse(self.path).path
            if path == '/api/activate':
                return activate_code(self, data)

            row = get_auth_session(self)
            if not session_ok(row): return api_error(self, 'Sesión inválida o caducada.', 401)
            refresh_session(row)
            with db() as x:
                x.execute('UPDATE devices SET last_seen=%s WHERE id=%s', (now(), row['device_id']))

            if path == '/api/heartbeat':
                return self.send_json({'status': 'success', 'user_id': row['user_id']})
            if path == '/api/servers':
                return self.send_json({'status': 'success', 'servers': list_servers()})
            if path == '/api/logout':
                with db() as x:
                    x.execute('UPDATE sessions SET revoked=TRUE WHERE id=%s', (row['session_id'],))
                return self.send_json({'status': 'success'})
            return api_error(self, 'Ruta no encontrada.', 404)
        except Exception as e:
            print('API error POST:', repr(e)); return api_error(self, 'Error interno.', 500)

    def log_message(self, fmt, *args):
        print('%s - %s' % (self.address_string(), fmt % args))

def run_http():
    port = int(os.environ.get('PORT', '10000'))
    srv = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    srv.daemon_threads = True
    srv.serve_forever()

def main():
    if not TOKEN or TOKEN.startswith('PEGA'):
        raise SystemExit('Configura TELEGRAM_BOT_TOKEN.')
    if not ADMINS:
        raise SystemExit('Configura TELEGRAM_ADMINS.')
    init_db()
    threading.Thread(target=run_http, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    cmds = [('start', start), ('id', id_cmd), ('panel', panel), ('ayuda', panel),
            ('autorizar', autorizar), ('usuarios', usuarios), ('bloquear', bloquear),
            ('activar', activar), ('borrar', borrar), ('crear', crear),
            ('addm3u', addm3u), ('servidores', servidores), ('offserver', offserver),
            ('onserver', onserver), ('delserver', delserver)]
    for name, fn in cmds:
        app.add_handler(CommandHandler(name, fn))
    print('TEILOR PLAYER API + Telegram arrancados')
    app.run_polling()

if __name__ == '__main__':
    main()
