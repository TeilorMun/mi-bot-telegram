import os, json, threading, secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from common import *

# --- CONFIGURACIÓN ---
TOKEN = "9056359122:AAGDxJSqVie-fIOPQkpG7h5N4Qaa1cUS3os"
ADMINS = {"740151755"}

# ---------------- Telegram helpers ----------------
def is_admin(update): return bool(update.effective_user and str(update.effective_user.id) in ADMINS)
async def admin_only(update):
    if not is_admin(update): await update.effective_message.reply_text('⛔ Solo el administrador puede usar este comando.'); return False
    return True

async def start(update, context):
    if is_admin(update):
        await update.effective_message.reply_text('👑 TEILOR PLAYER · Panel del propietario\n\nUsa /panel para ver todos los comandos de control.')
    else:
        await update.effective_message.reply_text('👋 Bienvenido a TEILOR PLAYER.\n\n⚠️ Tu cuenta aún no está autorizada. Pide al administrador que te añada y te dará un código de activación.')

async def id_cmd(update, context): 
    await update.effective_message.reply_text('Tu ID de Telegram es: '+str(update.effective_user.id))

async def panel(update, context):
    if await admin_only(update): 
        await update.effective_message.reply_text('''👑 TEILOR PLAYER — CONTROL TOTAL

USUARIOS
/autorizar ID_TELEGRAM @usuario   (Da acceso a la app)
/usuarios                         (Ver todos los usuarios y su ID)
/bloquear ID_INTERNO              (Bloquear usuario)
/activar ID_INTERNO               (Reactivar usuario)
/borrar ID_INTERNO                (Eliminar usuario)

SERVIDORES (M3U)
/addm3u Nombre | URL_M3U_XTREAM
/servidores                       (Ver lista de servidores)
/delserver ID_SERVIDOR            (Eliminar servidor)
/offserver ID_SERVIDOR            (Desactivar servidor)
/onserver ID_SERVIDOR             (Activar servidor)

OTROS
/crear MESES DISPOSITIVOS         (Crear código directo)''')

async def autorizar(u,c):
    if not await admin_only(u): return
    try:
        tg_id = c.args[0]
        tg_user = c.args[1].replace('@', '') if len(c.args) > 1 else 'SinNombre'
        
        # Creamos un código de activación ya vinculado a este Telegram
        code = create_code(12, 2, tg_id)
        
        await u.effective_message.reply_text(f'✅ USUARIO AUTORIZADO\n\nUsuario: @{tg_user} (ID: {tg_id})\nCódigo de activación: {code}\n\nEl usuario debe ir a la app e introducir ese código para entrar.')
    except Exception: 
        await u.effective_message.reply_text('Uso: /autorizar 123456789 @nombre_usuario')

async def usuarios(u,c):
    if not await admin_only(u): return
    with db() as x: 
        rows=x.execute('SELECT id,telegram_user,telegram_id,status,expires_at,max_devices FROM users ORDER BY id DESC LIMIT 50').fetchall()
    if not rows: await u.effective_message.reply_text('No hay usuarios registrados.')
    else: 
        lines = ['👥 USUARIOS REGISTRADOS']
        for r in rows:
            lines.append(f"ID: {r['id']} | @{r['telegram_user']} | TG_ID: {r['telegram_id']} | {r['status']} | Vence: {(r['expires_at'] or 'sin fecha')[:10]}")
        await u.effective_message.reply_text('\n'.join(lines))

async def user_action(u,c,action):
    if not await admin_only(u): return
    try: uid=int(c.args[0])
    except: await u.effective_message.reply_text('Indica el ID interno del usuario (ej: 1). Consulta /usuarios.'); return
    with db() as x:
        row=x.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        if not row: await u.effective_message.reply_text('Usuario no encontrado.'); return
        if action=='block': x.execute("UPDATE users SET status='blocked' WHERE id=?",(uid,)); x.execute('UPDATE sessions SET revoked=1 WHERE user_id=?',(uid,)); msg='Usuario bloqueado.'
        elif action=='enable': x.execute("UPDATE users SET status='active' WHERE id=?",(uid,)); msg='Usuario reactivado.'
        else: x.execute('DELETE FROM users WHERE id=?',(uid,)); msg='Usuario eliminado.'
    await u.effective_message.reply_text('✅ ' + msg)

async def bloquear(u,c): await user_action(u,c,'block')
async def activar(u,c): await user_action(u,c,'enable')
async def borrar(u,c): await user_action(u,c,'delete')

async def crear(u,c):
    if not await admin_only(u): return
    try:
        m,d=int(c.args[0]),int(c.args[1]); assert m in (1,3,6,12) and d in (1,2,3,4)
        code=create_code(m,d)
        await u.effective_message.reply_text(f'✅ Código genérico: {code}\nDuración: {m} meses\nDispositivos: {d}')
    except Exception: await u.effective_message.reply_text('Uso: /crear 6 1')

async def addm3u(u,c):
    if not await admin_only(u): return
    p=' '.join(c.args).split('|',1)
    if len(p)!=2: await u.effective_message.reply_text('Uso: /addm3u Nombre | URL_M3U_XTREAM'); return
    name,link=p[0].strip(),p[1].strip(); z=urlparse(link); q=parse_qs(z.query); user=q.get('username',[''])[0]; pw=q.get('password',[''])[0]
    if not user or not pw:
        parts=[v for v in z.path.strip('/').split('/') if v]
        if len(parts)>=2: user,pw=parts[-2:]
    if z.scheme not in ('http','https') or not z.netloc or not user or not pw: await u.effective_message.reply_text('Enlace inválido.'); return
    with db() as x: x.execute('INSERT INTO servers(name,kind,url,username_enc,password_enc,active,created_at) VALUES(?,?,?,?,?,?,?)',(name,'xtream_m3u',f'{z.scheme}://{z.netloc}',encrypt(user),encrypt(pw),1,iso()))
    await u.effective_message.reply_text(f'✅ Servidor «{name}» añadido a la lista global.')

async def servidores(u,c):
    if not await admin_only(u): return
    with db() as x: rows=x.execute('SELECT id,name,kind,url,active FROM servers ORDER BY id').fetchall()
    await u.effective_message.reply_text('\n'.join([f"ID {r['id']} · {r['name']} · {'ACTIVO' if r['active'] else 'INACTIVO'}\n{r['url']}" for r in rows]) or 'No hay servidores.')

async def server_action(u,c,action):
    if not await admin_only(u): return
    try: sid=int(c.args[0])
    except: await u.effective_message.reply_text('Indica el ID de servidor.'); return
    with db() as x:
        cur=x.execute('DELETE FROM servers WHERE id=?',(sid,)) if action=='delete' else x.execute('UPDATE servers SET active=? WHERE id=?',(1 if action=='on' else 0,sid))
    await u.effective_message.reply_text('✅ Operación aplicada.' if cur.rowcount else 'Servidor no encontrado.')

async def offserver(u,c): await server_action(u,c,'off')
async def onserver(u,c): await server_action(u,c,'on')
async def delserver(u,c): await server_action(u,c,'delete')

# ---------------- API WEB ----------------
def get_auth_session(handler):
    auth=handler.headers.get('Authorization','')
    if not auth.startswith('Bearer '): return None
    digest=token_hash(auth[7:].strip())
    with db() as x:
        return x.execute('''SELECT s.id session_id,s.user_id,s.device_id,u.status,u.expires_at,d.revoked device_revoked
            FROM sessions s JOIN users u ON u.id=s.user_id JOIN devices d ON d.id=s.device_id
            WHERE s.token_hash=? AND s.revoked=0''',(digest,)).fetchone()

def session_ok(row):
    if not row or row['status']!='active' or row['device_revoked']: return False
    exp=parse_dt(row['expires_at']); return bool(exp and exp>now())

def api_error(h,msg,status=400): h.send_json({'status':'error','message':msg,'detail':msg},status)

def activate_code(h,data):
    code=str(data.get('code','')).strip().upper()
    install=str(data.get('install_id','')).strip()
    name=str(data.get('device_name','Dispositivo'))[:120]
    
    if not code or not install: return api_error(h,'Código o dispositivo no válido.',400)
    
    with db() as x:
        row=x.execute('SELECT * FROM activation_codes WHERE code=? AND used_at IS NULL',(code,)).fetchone()
        if not row: return api_error(h,'Código incorrecto, ya utilizado o no autorizado.',403)
        if parse_dt(row['expires_at'])<=now(): return api_error(h,'El código ha caducado.',403)
        
        # Creamos el usuario con los datos del código (que ya tenía el ID autorizado)
        exp=now()+timedelta(days=30*row['months'])
        cur=x.execute("INSERT INTO users(status,expires_at,max_devices,telegram_id) VALUES('active',?,?,?)",(iso(exp),row['devices'],row['allowed_telegram_id'])); uid=cur.lastrowid
        x.execute('UPDATE activation_codes SET used_at=?,used_by=? WHERE code=?',(iso(),uid,code))
        
        dev=x.execute('SELECT * FROM devices WHERE user_id=? AND install_id=?',(uid,install)).fetchone()
        if not dev:
            active=x.execute('SELECT COUNT(*) n FROM devices WHERE user_id=? AND revoked=0',(uid,)).fetchone()['n']
            cap=x.execute('SELECT max_devices FROM users WHERE id=?',(uid,)).fetchone()['max_devices']
            if active>=cap: return api_error(h,'Límite de dispositivos alcanzado.',403)
            did=x.execute('INSERT INTO devices(user_id,install_id,device_name,last_seen,revoked) VALUES(?,?,?,?,0)',(uid,install,name,iso())).lastrowid
        else:
            if dev['revoked']: return api_error(h,'Dispositivo revocado.',403)
            did=dev['id']; x.execute('UPDATE devices SET device_name=?,last_seen=? WHERE id=?',(name,iso(),did))
            
        raw=secrets.token_urlsafe(36)
        x.execute('INSERT INTO sessions(user_id,device_id,token_hash,created_at,revoked) VALUES(?,?,?,?,0)',(uid,did,token_hash(raw),iso()))
    
    # DEVOLVEMOS TODOS LOS SERVIDORES ACTIVOS (Multi-servidor)
    h.send_json({'status':'success','session_token':raw,'user_id':uid,'servers':list_servers()})

def list_servers():
    with db() as x: 
        rows=x.execute('SELECT id,name,kind,url,username_enc,password_enc FROM servers WHERE active=1 ORDER BY id').fetchall()
    return [{'id':r['id'],'name':r['name'],'kind':r['kind'],'url':r['url'],'username':decrypt(r['username_enc']),'password':decrypt(r['password_enc'])} for r in rows]

class Handler(BaseHTTPRequestHandler):
    def send_json(self,data,status=200):
        body=json.dumps(data,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS,HEAD'); self.send_header('Access-Control-Allow-Headers','Content-Type, Authorization'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers()
        if self.command!='HEAD': self.wfile.write(body)
    def do_OPTIONS(self): self.send_json({'status':'ok'})
    def do_HEAD(self): self.send_json({'status':'online'})
    def do_GET(self):
        if self.path in ('/','/health','/healthz'): self.send_json({'status':'online','service':'TEILOR PLAYER API'})
        elif self.path=='/api/servers': self.servers()
        else: api_error(self,'Ruta no encontrada.',404)
    def do_POST(self):
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<0 or n>100000: return api_error(self,'Petición demasiado grande.',413)
            data=json.loads(self.rfile.read(n).decode() or '{}')
            if not isinstance(data,dict): return api_error(self,'JSON no válido.')
            path=urlparse(self.path).path
            if path=='/api/activate': return activate_code(self,data)
            
            row=get_auth_session(self)
            if not session_ok(row): return api_error(self,'Sesión inválida o caducada.',401)
            
            with db() as x: x.execute('UPDATE devices SET last_seen=? WHERE id=?',(iso(),row['device_id']))
            if path=='/api/heartbeat': return self.send_json({'status':'success','user_id':row['user_id']})
            if path=='/api/servers': return self.send_json({'status':'success','servers':list_servers()})
            if path=='/api/logout':
                with db() as x: x.execute('UPDATE sessions SET revoked=1 WHERE id=?',(row['session_id'],))
                return self.send_json({'status':'success'})
            return api_error(self,'Ruta no encontrada.',404)
        except Exception as e:
            print('API error:',repr(e)); return api_error(self,'Error interno.',500)
    def servers(self):
        row=get_auth_session(self)
        if not session_ok(row): return api_error(self,'Sesión inválida.',401)
        self.send_json({'status':'success','servers':list_servers()})
    def log_message(self,fmt,*args): pass

def run_http():
    port=int(os.environ.get('PORT','10000')); ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()

def main():
    if not TOKEN: raise SystemExit('Configura TELEGRAM_BOT_TOKEN en Render.')
    init_db(); threading.Thread(target=run_http,daemon=True).start()
    app=Application.builder().token(TOKEN).build()
    cmds=[
        ('start',start),('id',id_cmd),('panel',panel),('ayuda',panel),
        ('autorizar',autorizar),('usuarios',usuarios),('bloquear',bloquear),('activar',activar),('borrar',borrar),('crear',crear),
        ('addm3u',addm3u),('servidores',servidores),('offserver',offserver),('onserver',onserver),('delserver',delserver)
    ]
    for name,fn in cmds: app.add_handler(CommandHandler(name,fn))
    print('TEILOR PLAYER API + Telegram arrancados'); app.run_polling()

if __name__=='__main__': main()
