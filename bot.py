import os, re, asyncio, threading, json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from common import *

# TOKEN DE TU BOT
TOKEN = "9056359122:AAGDxJSqVie-fIOPQkpG7h5N4Qaa1cUS3os"

# TU ID DE ADMINISTRADOR
ADMINS = {"740151755"}

def is_admin(update): return bool(update.effective_user and str(update.effective_user.id) in ADMINS)
async def deny(update):
    await update.effective_message.reply_text('⛔ Esta función está reservada al propietario de TEILOR PLAYER.')
    return False
async def admin_only(update):
    if not is_admin(update): await deny(update); return False
    return True
async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.message.reply_text('👑 TEILOR PLAYER · Panel del propietario\n\nUsa /panel para ver todos los comandos.\nTu ID de Telegram: '+str(update.effective_user.id))
    else:
        await update.message.reply_text('👋 Bienvenido a TEILOR PLAYER. La activación y el reproductor se realizan desde la aplicación. Si necesitas un código, contacta con el administrador.')
async def id_cmd(update,context): await update.message.reply_text('Tu ID de Telegram es: '+str(update.effective_user.id))
async def panel(update,context):
    if not await admin_only(update): return
    await update.message.reply_text(
'''👑 TEILOR PLAYER — PANEL DE CONTROL

USUARIOS
/crear 6 1        Crear código de 6 meses y 1 dispositivo
/crear 12 2       Crear código de 12 meses y 2 dispositivos
/usuarios         Ver usuarios
/bloquear ID      Revocar acceso
/activar ID       Reactivar usuario
/borrar ID        Eliminar usuario
/renovar ID MESES Añadir meses
/limite ID 1|2    Cambiar límite de dispositivos
/dispositivos ID  Ver dispositivos
/vincular ID      Código para añadir otro dispositivo
/revocadispositivo ID DEVICE_ID  Revocar dispositivo

SERVIDORES
/addxtream Nombre | URL | Usuario | Contraseña
/addm3u Nombre | URL_M3U_XTREAM
/servidores       Ver servidores
/offserver ID     Desactivar servidor
/onserver ID      Activar servidor
/delserver ID     Eliminar servidor

/ayuda             Mostrar esta ayuda

Los códigos duran 48 horas y solo se pueden canjear una vez.''')
async def crear(update,context):
    if not await admin_only(update): return
    try:
        months=int(context.args[0]); devices=int(context.args[1])
        if months not in (6,12) or devices not in (1,2): raise ValueError()
        code=create_code(months,devices)
        await update.message.reply_text(f'✅ CÓDIGO CREADO\n\nCódigo: {code}\nDuración: {months} meses desde la activación\nDispositivos: {devices}\nCaduca sin usar en: 48 horas\n\nEnvíalo al usuario. No se puede reutilizar.')
    except Exception: await update.message.reply_text('Uso: /crear 6 1  o  /crear 12 2')
async def usuarios(update,context):
    if not await admin_only(update): return
    with db() as c: rows=c.execute('SELECT id,status,expires_at,max_devices FROM users ORDER BY id DESC LIMIT 50').fetchall()
    if not rows: await update.message.reply_text('Todavía no hay usuarios activados.'); return
    lines=['👥 ÚLTIMOS USUARIOS']
    for r in rows: lines.append(f"ID {r['id']} · {r['status']} · vence {r['expires_at'][:10]} · {r['max_devices']} dispositivo(s)")
    await update.message.reply_text('\n'.join(lines))
async def user_action(update,context,action):
    if not await admin_only(update): return
    try: uid=int(context.args[0])
    except: await update.message.reply_text('Indica el ID interno. Consulta /usuarios.'); return
    with db() as c:
        row=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        if not row: await update.message.reply_text('No existe ese usuario.'); return
        if action=='bloquear':
            c.execute('UPDATE users SET status="blocked" WHERE id=?',(uid,)); c.execute('UPDATE sessions SET revoked=1 WHERE user_id=?',(uid,)); msg='Usuario bloqueado y sesiones revocadas.'
        elif action=='activar': c.execute('UPDATE users SET status="active" WHERE id=?',(uid,)); msg='Usuario activado. Comprueba también su fecha de vencimiento.'
        elif action=='borrar': c.execute('DELETE FROM users WHERE id=?',(uid,)); msg='Usuario eliminado.'
    await update.message.reply_text('✅ '+msg)
async def bloquear(u,c): await user_action(u,c,'bloquear')
async def activar(u,c): await user_action(u,c,'activar')
async def borrar(u,c): await user_action(u,c,'borrar')
async def renovar(update,context):
    if not await admin_only(update): return
    try: uid=int(context.args[0]); months=int(context.args[1]); assert months in (1,3,6,12)
    except: await update.message.reply_text('Uso: /renovar ID MESES (1, 3, 6 o 12)'); return
    with db() as c:
        row=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        if not row: await update.message.reply_text('Usuario no encontrado.'); return
        base=max(now(),parse_dt(row['expires_at']))
        expiry=base+timedelta(days=30*months)
        c.execute('UPDATE users SET expires_at=?,status="active" WHERE id=?',(iso(expiry),uid))
    await update.message.reply_text(f'✅ Usuario {uid} renovado hasta {iso(expiry)[:10]}.')
async def limite(update,context):
    if not await admin_only(update): return
    try: uid=int(context.args[0]); n=int(context.args[1]); assert n in (1,2)
    except: await update.message.reply_text('Uso: /limite ID 1  o  /limite ID 2'); return
    with db() as c:
        c.execute('UPDATE users SET max_devices=? WHERE id=?',(n,uid))
        c.execute('''UPDATE devices SET revoked=1 WHERE user_id=? AND id NOT IN
          (SELECT id FROM devices WHERE user_id=? AND revoked=0 ORDER BY last_seen DESC LIMIT ?)''',(uid,uid,n))
    await update.message.reply_text(f'✅ Límite del usuario {uid}: {n} dispositivo(s).')
async def dispositivos(update,context):
    if not await admin_only(update): return
    try: uid=int(context.args[0])
    except: await update.message.reply_text('Uso: /dispositivos ID'); return
    with db() as c: rows=c.execute('SELECT id,install_id,device_name,last_seen,revoked FROM devices WHERE user_id=?',(uid,)).fetchall()
    if not rows: await update.message.reply_text('No hay dispositivos registrados.'); return
    await update.message.reply_text('\n'.join([f"Dispositivo interno {r['id']} · {r['device_name']} · visto {r['last_seen'][:16]} · {'revocado' if r['revoked'] else 'activo'}\nInstalación: {r['install_id']}" for r in rows]))
async def vincular(update,context):
    if not await admin_only(update): return
    try: uid=int(context.args[0]); code=create_pair_code(uid)
    except Exception as e: await update.message.reply_text('No se pudo crear el código: '+str(e)); return
    await update.message.reply_text(f'🔐 CÓDIGO PARA AÑADIR DISPOSITIVO\n\nUsuario: {uid}\nCódigo: {code}\nVálido durante 24 horas y de un solo uso.\n\nEl usuario debe introducirlo en la APK del nuevo dispositivo.')
async def revocadispositivo(update,context):
    if not await admin_only(update): return
    try: uid=int(context.args[0]); did=int(context.args[1])
    except: await update.message.reply_text('Uso: /revocadispositivo ID_USUARIO ID_DISPOSITIVO'); return
    with db() as c:
        cur=c.execute('UPDATE devices SET revoked=1 WHERE id=? AND user_id=?',(did,uid))
        if cur.rowcount: c.execute('UPDATE sessions SET revoked=1 WHERE device_id=?',(did,))
    await update.message.reply_text('✅ Dispositivo revocado.' if cur.rowcount else 'No se encontró ese dispositivo para ese usuario.')

async def addxtream(update,context):
    if not await admin_only(update): return
    raw=' '.join(context.args); parts=[x.strip() for x in raw.split('|')]
    if len(parts)!=4: await update.message.reply_text('Uso: /addxtream Nombre | URL | Usuario | Contraseña'); return
    name,url,user,pw=parts
    if not url.startswith(('http://','https://')): await update.message.reply_text('La URL debe comenzar por http:// o https://'); return
    with db() as c: c.execute('INSERT INTO servers(name,kind,url,username_enc,password_enc,active,created_at) VALUES(?,?,?,?,?,?,?)',(name,'xtream',url.rstrip('/'),encrypt(user),encrypt(pw),1,iso()))
    await update.message.reply_text(f'✅ Servidor «{name}» añadido y disponible para todos los usuarios activos.')
async def addm3u(update,context):
    if not await admin_only(update): return
    raw=' '.join(context.args); parts=[x.strip() for x in raw.split('|',1)]
    if len(parts)!=2: await update.message.reply_text('Uso: /addm3u Nombre | URL_M3U_XTREAM'); return
    name,link=parts
    try:
        u=urlparse(link); q=parse_qs(u.query); username=q.get('username',[''])[0]; password=q.get('password',[''])[0]
        if not (username and password):
            parts=[x for x in u.path.strip('/').split('/') if x]
            if len(parts)>=2: username,password=parts[-2],parts[-1]
        if not (u.scheme in ('http','https') and u.netloc and username and password): raise ValueError()
        base=f'{u.scheme}://{u.netloc}'
    except: await update.message.reply_text('Este reproductor necesita una URL M3U de tipo Xtream que contenga username y password. Las listas M3U genéricas todavía no están soportadas por la lógica original del HTML.'); return
    with db() as c: c.execute('INSERT INTO servers(name,kind,url,username_enc,password_enc,active,created_at) VALUES(?,?,?,?,?,?,?)',(name,'xtream_m3u',base,encrypt(username),encrypt(password),1,iso()))
    await update.message.reply_text(f'✅ Fuente «{name}» añadida desde el enlace M3U Xtream.')
async def servidores(update,context):
    if not await admin_only(update): return
    with db() as c: rows=c.execute('SELECT id,name,kind,url,active FROM servers ORDER BY id').fetchall()
    if not rows: await update.message.reply_text('No hay servidores. Usa /addxtream o /addm3u.'); return
    await update.message.reply_text('\n'.join([f"ID {r['id']} · {r['name']} · {r['kind']} · {'ACTIVO' if r['active'] else 'INACTIVO'}\n{r['url']}" for r in rows]))
async def server_action(update,context,action):
    if not await admin_only(update): return
    try: sid=int(context.args[0])
    except: await update.message.reply_text('Indica el ID del servidor. Consulta /servidores.'); return
    with db() as c:
        if action=='delete': c.execute('DELETE FROM servers WHERE id=?',(sid,))
        else: c.execute('UPDATE servers SET active=? WHERE id=?',(1 if action=='on' else 0,sid))
        changed=c.total_changes
    await update.message.reply_text('✅ Operación aplicada. Los usuarios verán el cambio al actualizar sus servidores o reabrir la aplicación.')
async def offserver(u,c): await server_action(u,c,'off')
async def onserver(u,c): await server_action(u,c,'on')
async def delserver(u,c): await server_action(u,c,'delete')
async def ayuda(update,context): await panel(update,context)

# --- SERVIDOR WEB PARA EL REPRODUCTOR HTML ---
class WebHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        
        # Leemos qué está pidiendo el HTML
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data) if post_data else {}
            action = data.get("action", "")
            
            if action == "get_servers":
                with db() as c:
                    rows = c.execute('SELECT id, name, kind, url, username_enc, password_enc FROM servers WHERE active=1').fetchall()
                
                servers_list = []
                for r in rows:
                    servers_list.append({
                        "id": r["id"],
                        "name": r["name"],
                        "kind": r["kind"],
                        "url": r["url"],
                        "username": decrypt(r["username_enc"]),
                        "password": decrypt(r["password_enc"])
                    })
                response = {"status": "success", "servers": servers_list}
            else:
                # Respuesta genérica de activación
                response = {"status": "success", "message": "Activación correcta", "token": "test_token_123"}
                
        except Exception as e:
            response = {"status": "error", "message": str(e)}

        self.wfile.write(json.dumps(response).encode('utf-8'))
        
    def do_GET(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status": "online"}')

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), WebHandler)
    print(f"Servidor Web escuchando en el puerto {port}")
    server.serve_forever()

def main():
    if not TOKEN: raise SystemExit('Configura TELEGRAM_BOT_TOKEN en .env')
    init_db(); 
    app=Application.builder().token(TOKEN).build()
    for cmd,fn in [('start',start),('id',id_cmd),('panel',panel),('ayuda',ayuda),('crear',crear),('usuarios',usuarios),('bloquear',bloquear),('activar',activar),('borrar',borrar),('renovar',renovar),('limite',limite),('dispositivos',dispositivos),('vincular',vincular),('revocadispositivo',revocadispositivo),('addxtream',addxtream),('addm3u',addm3u),('servidores',servidores),('offserver',offserver),('onserver',onserver),('delserver',delserver)]: app.add_handler(CommandHandler(cmd,fn))
    
    # Arrancamos el servidor web en un hilo paralelo
    web_thread = threading.Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()
    
    print('TEILOR bot iniciado y Web escuchando...')
    app.run_polling()

if __name__=='__main__': main()
