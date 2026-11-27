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

def is_admin(update): return bool(update.effective_user and str(update.effective_user.id) in ADMINS)
async def admin_only(update):
    if not is_admin(update): await update.effective_message.reply_text('⛔ Solo el administrador puede usar este comando.'); return False
    return True
async def start(update, context):
    msg = ('👑 TEILOR PLAYER · Panel del propietario\nUsa /panel. Tu ID: '+str(update.effective_user.id)) if is_admin(update) else '👋 Bienvenido a TEILOR PLAYER. Solicita tu código de activación al administrador.'
    await update.effective_message.reply_text(msg)
async def id_cmd(update, context): await update.effective_message.reply_text('Tu ID de Telegram: '+str(update.effective_user.id))
async def panel(update, context):
    if await admin_only(update): await update.effective_message.reply_text('''TEILOR PLAYER — ADMIN\n/crear 6 1 | /crear 12 2\n/usuarios\n/bloquear ID | /activar ID | /borrar ID\n/renovar ID MESES | /limite ID 1|2\n/dispositivos ID | /vincular ID | /revocadispositivo ID DEVICE_ID\n/addxtream Nombre | URL | Usuario | Contraseña\n/addm3u Nombre | URL_M3U_XTREAM\n/servidores | /offserver ID | /onserver ID | /delserver ID''')
async def crear(u,c):
    if not await admin_only(u): return
    try:
        m,d=int(c.args[0]),int(c.args[1]); assert m in (1,3,6,12) and d in (1,2,3,4)
        code=create_code(m,d); await u.effective_message.reply_text(f'Código: {code}\nDuración: {m} meses desde activación\nDispositivos: {d}\nVálido 48 horas, un solo uso.')
    except Exception: await u.effective_message.reply_text('Uso: /crear 6 1 (meses 1,3,6,12; dispositivos 1-4)')
async def usuarios(u,c):
    if not await admin_only(u): return
    with db() as x: rows=x.execute('SELECT id,status,expires_at,max_devices FROM users ORDER BY id DESC LIMIT 50').fetchall()
    await u.effective_message.reply_text('\n'.join([f"ID {r['id']} · {r['status']} · vence {(r['expires_at'] or 'sin fecha')[:10]} · {r['max_devices']} disp." for r in rows]) or 'No hay usuarios.')
async def user_action(u,c,action):
    if not await admin_only(u): return
    try: uid=int(c.args[0])
    except: await u.effective_message.reply_text('Indica el ID de usuario.'); return
    with db() as x:
        row=x.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        if not row: await u.effective_message.reply_text('Usuario no encontrado.'); return
        if action=='block': x.execute("UPDATE users SET status='blocked' WHERE id=?",(uid,)); x.execute('UPDATE sessions SET revoked=1 WHERE user_id=?',(uid,)); msg='Usuario bloqueado y sesiones revocadas.'
        elif action=='enable': x.execute("UPDATE users SET status='active' WHERE id=?",(uid,)); msg='Usuario activado. Comprueba su vencimiento.'
        else: x.execute('DELETE FROM users WHERE id=?',(uid,)); msg='Usuario eliminado.'
    await u.effective_message.reply_text(msg)
async def bloquear(u,c): await user_action(u,c,'block')
async def activar(u,c): await user_action(u,c,'enable')
async def borrar(u,c): await user_action(u,c,'delete')
async def renovar(u,c):
    if not await admin_only(u): return
    try: uid,m=int(c.args[0]),int(c.args[1]); assert m in (1,3,6,12)
    except: await u.effective_message.reply_text('Uso: /renovar ID MESES (1,3,6,12)'); return
    with db() as x:
        r=x.execute('SELECT expires_at FROM users WHERE id=?',(uid,)).fetchone()
        if not r: await u.effective_message.reply_text('Usuario no encontrado.'); return
        base=max(now(),parse_dt(r['expires_at']) or now()); exp=base+timedelta(days=30*m)
        x.execute("UPDATE users SET expires_at=?,status='active' WHERE id=?",(iso(exp),uid))
    await u.effective_message.reply_text(f'Renovado hasta {iso(exp)[:10]}.')
async def limite(u,c):
    if not await admin_only(u): return
    try: uid,n=int(c.args[0]),int(c.args[1]); assert n in (1,2,3,4)
    except: await u.effective_message.reply_text('Uso: /limite ID 1|2|3|4'); return
    with db() as x: x.execute('UPDATE users SET max_devices=? WHERE id=?',(n,uid))
    await u.effective_message.reply_text('Límite actualizado.')
async def dispositivos(u,c):
    if not await admin_only(u): return
    try: uid=int(c.args[0])
    except: await u.effective_message.reply_text('Uso: /dispositivos ID'); return
    with db() as x: rows=x.execute('SELECT id,device_name,last_seen,revoked FROM devices WHERE user_id=?',(uid,)).fetchall()
    await u.effective_message.reply_text('\n'.join([f"Dispositivo {r['id']} · {r['device_name']} · {r['last_seen']} · {'revocado' if r['revoked'] else 'activo'}" for r in rows]) or 'Sin dispositivos.')
async def vincular(u,c):
    if not await admin_only(u): return
    try: uid=int(c.args[0]); code=create_pair_code(uid); await u.effective_message.reply_text(f'Código adicional: {code}\nVálido 24 horas y un solo uso. En el reproductor, introdúcelo en el campo de activación.')
    except: await u.effective_message.reply_text('Uso: /vincular ID')
async def revocadispositivo(u,c):
    if not await admin_only(u): return
    try: uid,did=int(c.args[0]),int(c.args[1])
    except: await u.effective_message.reply_text('Uso: /revocadispositivo ID_USUARIO ID_DISPOSITIVO'); return
    with db() as x:
        cur=x.execute('UPDATE devices SET revoked=1 WHERE id=? AND user_id=?',(did,uid)); x.execute('UPDATE sessions SET revoked=1 WHERE device_id=?',(did,))
    await u.effective_message.reply_text('Dispositivo revocado.' if cur.rowcount else 'No encontrado.')
async def addxtream(u,c):
    if not await admin_only(u): return
    p=[z.strip() for z in ' '.join(c.args).split('|')]
    if len(p)!=4: await u.effective_message.reply_text('Uso: /addxtream Nombre | URL | Usuario | Contraseña'); return
    name,url,user,pw=p
    if not url.startswith(('https://','http://')): await u.effective_message.reply_text('URL inválida.'); return
    with db() as x: x.execute('INSERT INTO servers(name,kind,url,username_enc,password_enc,active,created_at) VALUES(?,?,?,?,?,?,?)',(name,'xtream',url.rstrip('/'),encrypt(user),encrypt(pw),1,iso()))
    await u.effective_message.reply_text(f'Servidor {name} añadido.')
async def addm3u(u,c):
    if not await admin_only(u): return
    p=' '.join(c.args).split('|',1)
    if len(p)!=2: await u.effective_message.reply_text('Uso: /addm3u Nombre | URL_M3U_XTREAM'); return
    name,link=p[0].strip(),p[1].strip(); z=urlparse(link); q=parse_qs(z.query); user=q.get('username',[''])[0]; pw=q.get('password',[''])[0]
    if not user or not pw:
        parts=[v for v in z.path.strip('/').split('/') if v]
        if len(parts)>=2: user,pw=parts[-2:]
    if z.scheme not in ('http','https') or not z.netloc or not user or not pw: await u.effective_message.reply_text('Se necesita enlace Xtream con usuario y contraseña.'); return
    with db() as x: x.execute('INSERT INTO servers(name,kind,url,username_enc,password_enc,active,created_at) VALUES(?,?,?,?,?,?,?)',(name,'xtream_m3u',f'{z.scheme}://{z.netloc}',encrypt(user),encrypt(pw),1,iso()))
    await u.effective_message.reply_text(f'Fuente {name} añadida.')
async def servidores(u,c):
    if not await admin_only(u): return
    with db() as x: rows=x.execute('SELECT id,name,kind,url,active FROM servers ORDER BY id').fetchall()
    await u.effective_message.reply_text('\n'.join([f"{r['id']} · {r['name']} · {r['kind']} · {'ACTIVO' if r['active'] else 'INACTIVO'}\n{r['url']}" for r in rows]) or 'No hay servidores.')
async def server_action(u,c,action):
    if not await admin_only(u): return
    try: sid=int(c.args[0])
    except: await u.effective_message.reply_text('Indica el ID de servidor.'); return
    with db() as x:
        cur=x.execute('DELETE FROM servers WHERE id=?',(sid,)) if action=='delete' else x.execute('UPDATE servers SET active=? WHERE id=?',(1 if action=='on' else 0,sid))
    await u.effective_message.reply_text('Operación aplicada.' if cur.rowcount else 'Servidor no encontrado.')
async def offserver(u,c): await server_action(u,c,'off')
async def onserver(u,c): await server_action(u,c,'on')
async def delserver(u,c): await server_action(u,c,'delete')
async def ayuda(u,c): await panel(u,c)

# ---------------- API WEB PARA EL HTML ----------------
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
    code=str(data.get('code','')).strip().upper(); install=str(data.get('install_id','')).strip(); name=str(data.get('device_name','Dispositivo'))[:120]
    if not code or not install: return api_error(h,'Código o identificador de dispositivo no válido.',400)
    with db() as x:
        pair=x.execute('SELECT * FROM pair_codes WHERE code=? AND used_at IS NULL',(code,)).fetchone()
        if pair:
            if parse_dt(pair['expires_at'])<=now(): return api_error(h,'El código adicional ha caducado.',403)
            user=x.execute('SELECT * FROM users WHERE id=?',(pair['user_id'],)).fetchone()
            if not user or user['status']!='active' or not parse_dt(user['expires_at']) or parse_dt(user['expires_at'])<=now(): return api_error(h,'La cuenta no está activa.',403)
            uid=user['id']
        else:
            row=x.execute('SELECT * FROM activation_codes WHERE code=? AND used_at IS NULL',(code,)).fetchone()
            if not row: return api_error(h,'Código incorrecto o ya utilizado.',403)
            if parse_dt(row['expires_at'])<=now(): return api_error(h,'El código de activación ha caducado.',403)
            exp=now()+timedelta(days=30*row['months'])
            cur=x.execute("INSERT INTO users(status,expires_at,max_devices) VALUES('active',?,?)",(iso(exp),row['devices'])); uid=cur.lastrowid
            x.execute('UPDATE activation_codes SET used_at=?,used_by=? WHERE code=?',(iso(),uid,code))
        dev=x.execute('SELECT * FROM devices WHERE user_id=? AND install_id=?',(uid,install)).fetchone()
        if not dev:
            active=x.execute('SELECT COUNT(*) n FROM devices WHERE user_id=? AND revoked=0',(uid,)).fetchone()['n']
            cap=x.execute('SELECT max_devices FROM users WHERE id=?',(uid,)).fetchone()['max_devices']
            if active>=cap: return api_error(h,'Has alcanzado el límite de dispositivos de esta cuenta.',403)
            did=x.execute('INSERT INTO devices(user_id,install_id,device_name,last_seen,revoked) VALUES(?,?,?,?,0)',(uid,install,name,iso())).lastrowid
        else:
            if dev['revoked']: return api_error(h,'Este dispositivo ha sido revocado.',403)
            did=dev['id']; x.execute('UPDATE devices SET device_name=?,last_seen=? WHERE id=?',(name,iso(),did))
        if pair:
            x.execute('UPDATE pair_codes SET used_at=? WHERE code=?',(iso(),code))
        raw=secrets.token_urlsafe(36)
        x.execute('INSERT INTO sessions(user_id,device_id,token_hash,created_at,revoked) VALUES(?,?,?,?,0)',(uid,did,token_hash(raw),iso()))
    h.send_json({'status':'success','session_token':raw,'user_id':uid,'servers':list_servers()})
def list_servers():
    with db() as x: rows=x.execute('SELECT id,name,kind,url,username_enc,password_enc FROM servers WHERE active=1 ORDER BY id').fetchall()
    return [{'id':r['id'],'name':r['name'],'kind':r['kind'],'url':r['url'],'username':decrypt(r['username_enc']),'password':decrypt(r['password_enc'])} for r in rows]
class Handler(BaseHTTPRequestHandler):
    def send_json(self,data,status=200):
        body=json.dumps(data,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS,HEAD'); self.send_header('Access-Control-Allow-Headers','Content-Type, Authorization'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers()
        if self.command!='HEAD': self.wfile.write(body)
    def do_OPTIONS(self): self.send_json({'status':'ok'})
    def do_HEAD(self): self.send_json({'status':'online'})
    def do_GET(self):
        if self.path in ('/','/health','/healthz'): 
            self.send_json({'status':'online','service':'TEILOR PLAYER API'})
        elif self.path=='/api/servers': 
            self.servers()
        else: 
            api_error(self,'Ruta no encontrada.',404)
    def do_POST(self):
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<0 or n>100000: return api_error(self,'Petición demasiado grande.',413)
            data=json.loads(self.rfile.read(n).decode() or '{}')
            if not isinstance(data,dict): return api_error(self,'JSON no válido.')
            path=urlparse(self.path).path
            if path=='/api/activate': return activate_code(self,data)
            row=get_auth_session(self)
            if not session_ok(row): return api_error(self,'Sesión inválida, revocada o caducada. Vuelve a activar el dispositivo.',401)
            with db() as x: x.execute('UPDATE devices SET last_seen=? WHERE id=?',(iso(),row['device_id']))
            if path=='/api/heartbeat': return self.send_json({'status':'success','user_id':row['user_id']})
            if path=='/api/servers': return self.send_json({'status':'success','servers':list_servers()})
            if path=='/api/logout':
                with db() as x: x.execute('UPDATE sessions SET revoked=1 WHERE id=?',(row['session_id'],))
                return self.send_json({'status':'success'})
            return api_error(self,'Ruta no encontrada.',404)
        except (ValueError,TypeError,json.JSONDecodeError): return api_error(self,'JSON o datos no válidos.',400)
        except Exception as e:
            print('API error:',repr(e)); return api_error(self,'Error interno del servidor.',500)
    def servers(self):
        row=get_auth_session(self)
        if not session_ok(row): return api_error(self,'Sesión inválida o caducada.',401)
        self.send_json({'status':'success','servers':list_servers()})
    def log_message(self,fmt,*args): print('[HTTP]',fmt%args)
def run_http():
    port=int(os.environ.get('PORT','10000')); ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
def main():
    if not TOKEN: raise SystemExit('Configura TELEGRAM_BOT_TOKEN en Render.')
    init_db(); threading.Thread(target=run_http,daemon=True).start()
    app=Application.builder().token(TOKEN).build()
    cmds=[('start',start),('id',id_cmd),('panel',panel),('ayuda',ayuda),('crear',crear),('usuarios',usuarios),('bloquear',bloquear),('activar',activar),('borrar',borrar),('renovar',renovar),('limite',limite),('dispositivos',dispositivos),('vincular',vincular),('revocadispositivo',revocadispositivo),('addxtream',addxtream),('addm3u',addm3u),('servidores',servidores),('offserver',offserver),('onserver',onserver),('delserver',delserver)]
    for name,fn in cmds: app.add_handler(CommandHandler(name,fn))
    print('TEILOR PLAYER API + Telegram arrancados'); app.run_polling()
if __name__=='__main__': main()
