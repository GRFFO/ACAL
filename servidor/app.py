# -*- coding: utf-8 -*-
"""
AutoClicker AL - Servidor de cuentas y licencias.

Se sube al hosting (panel tipo Pterodactyl con Python). No necesita librerias extra.
Configuracion en el archivo .env (junto a este archivo):
    OWNER_IDS=1000            IDs con control total (separados por coma)
    ADMIN_IDS=1001,1002       IDs admin permanentes
    PORT=                     (opcional) si se deja vacio usa SERVER_PORT del panel
Los cambios del .env se aplican solos, sin reiniciar.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

VERSION = "2.0"
BASE = os.path.dirname(os.path.abspath(__file__))
RUTA_ENV = os.path.join(BASE, ".env")
RUTA_DB = os.path.join(BASE, "datos.db")
SESION_DIAS = 30
POR_VIDA = -1


# ─────────────────────────────── .env ────────────────────────────────
_env = {"mtime": None, "owners": set(), "admins": set()}


def _leer_env():
    vals = {}
    try:
        with open(RUTA_ENV, encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if linea and not linea.startswith("#") and "=" in linea:
                    k, v = linea.split("=", 1)
                    vals[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return vals


def roles_env():
    """Relee el .env si cambio (asi no hay que reiniciar para agregar admins)."""
    try:
        mt = os.path.getmtime(RUTA_ENV)
    except OSError:
        mt = 0
    if mt != _env["mtime"]:
        v = _leer_env()
        ids = lambda s: {int(x) for x in re.findall(r"\d+", s or "")}
        _env["owners"] = ids(v.get("OWNER_IDS") or os.getenv("OWNER_IDS"))
        _env["admins"] = ids(v.get("ADMIN_IDS") or os.getenv("ADMIN_IDS"))
        _env["mtime"] = mt
        print(f"[env] owners={sorted(_env['owners'])} admins={sorted(_env['admins'])}", flush=True)
    return _env["owners"], _env["admins"]


# ─────────────────────────── base de datos ───────────────────────────
db = sqlite3.connect(RUTA_DB, check_same_thread=False)
db.row_factory = sqlite3.Row
lock = threading.RLock()
with lock:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE COLLATE NOCASE NOT NULL,
        salt TEXT NOT NULL, hash TEXT NOT NULL,
        creado REAL, visto REAL,
        vence REAL,            -- NULL sin licencia, -1 de por vida, o fecha (epoch)
        admin_vence REAL,      -- igual que vence, pero para el rol admin
        baneado INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS licencias(
        clave TEXT PRIMARY KEY, tipo TEXT NOT NULL, duracion INTEGER NOT NULL,
        creada REAL, creador INTEGER, nota TEXT DEFAULT '',
        usada_por INTEGER, usada REAL);
    CREATE TABLE IF NOT EXISTS sesiones(token TEXT PRIMARY KEY, uid INTEGER, vence REAL);
    """)
    # los IDs de usuario empiezan en 1000
    db.execute("INSERT INTO sqlite_sequence(name, seq) SELECT 'usuarios', 999 "
               "WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name='usuarios')")
    db.commit()


def q(sql, args=(), uno=False):
    with lock:
        cur = db.execute(sql, args)
        filas = cur.fetchall()
        db.commit()
    return (filas[0] if filas else None) if uno else filas


def activo(v):
    return v is not None and (v == POR_VIDA or v > time.time())


def extender(actual, segundos):
    if segundos == POR_VIDA or actual == POR_VIDA:
        return POR_VIDA
    base = actual if (actual and actual > time.time()) else time.time()
    return base + segundos


def rol_de(u):
    owners, admins = roles_env()
    if u["id"] in owners:
        return "owner"
    if u["id"] in admins or activo(u["admin_vence"]):
        return "admin"
    return "user"


def info(u):
    rol = rol_de(u)
    return {
        "id": u["id"], "nombre": u["nombre"], "rol": rol,
        "acceso": (not u["baneado"]) and (rol != "user" or activo(u["vence"])),
        "vence": u["vence"], "admin_vence": u["admin_vence"],
        "baneado": bool(u["baneado"]), "creado": u["creado"], "visto": u["visto"],
    }


def _pbkdf2(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100_000).hex()


def nueva_clave():
    alf = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    s = "".join(secrets.choice(alf) for _ in range(16))
    return "AL-" + "-".join(s[i:i + 4] for i in range(0, 16, 4))


def normalizar_clave(c):
    s = re.sub(r"[^A-Za-z0-9]", "", c or "").upper()
    if s.startswith("AL") and len(s) == 18:
        s = s[2:]
    return "AL-" + "-".join(s[i:i + 4] for i in range(0, len(s), 4))


# ─────────────────────── limite de intentos ─────────────────────────
_fallos = {}


def bloqueado(ip):
    ahora = time.time()
    lst = [t for t in _fallos.get(ip, []) if ahora - t < 600]
    _fallos[ip] = lst
    return len(lst) >= 12


def fallo(ip):
    _fallos.setdefault(ip, []).append(time.time())


# ───────────────────────────── API ──────────────────────────────────
class Err(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.msg, self.code = msg, code


def crear_sesion(uid):
    tok = secrets.token_hex(32)
    q("INSERT INTO sesiones VALUES(?,?,?)", (tok, uid, time.time() + SESION_DIAS * 86400))
    return tok


def api_registro(d, ip, _u):
    nombre = str(d.get("usuario", "")).strip()
    pw = str(d.get("pw", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{3,20}", nombre):
        raise Err("Usuario: 3 a 20 caracteres (letras, números, _ . -)")
    if not re.fullmatch(r"[0-9a-f]{64}", pw):
        raise Err("Contraseña inválida")
    if q("SELECT 1 FROM usuarios WHERE nombre=?", (nombre,), True):
        raise Err("Ese usuario ya existe")
    salt = secrets.token_hex(16)
    now = time.time()
    with lock:
        cur = db.execute("INSERT INTO usuarios(nombre,salt,hash,creado,visto) VALUES(?,?,?,?,?)",
                         (nombre, salt, _pbkdf2(pw, salt), now, now))
        db.commit()
        uid = cur.lastrowid
    u = q("SELECT * FROM usuarios WHERE id=?", (uid,), True)
    return {"token": crear_sesion(uid), "yo": info(u)}


def api_login(d, ip, _u):
    if bloqueado(ip):
        raise Err("Demasiados intentos. Espera unos minutos.", 429)
    u = q("SELECT * FROM usuarios WHERE nombre=?", (str(d.get("usuario", "")).strip(),), True)
    if not u or not hmac.compare_digest(_pbkdf2(str(d.get("pw", "")), u["salt"]), u["hash"]):
        fallo(ip)
        raise Err("Usuario o contraseña incorrectos")
    if u["baneado"]:
        raise Err("Tu cuenta está suspendida", 403)
    return {"token": crear_sesion(u["id"]), "yo": info(u)}


def api_yo(d, ip, u):
    q("UPDATE usuarios SET visto=? WHERE id=?", (time.time(), u["id"]))
    return {"yo": info(u)}


def api_salir(d, ip, u):
    q("DELETE FROM sesiones WHERE token=?", (d.get("_token"),))
    return {"ok": True}


def api_canjear(d, ip, u):
    if bloqueado(ip):
        raise Err("Demasiados intentos. Espera unos minutos.", 429)
    clave = normalizar_clave(str(d.get("clave", "")))
    with lock:
        lic = q("SELECT * FROM licencias WHERE clave=?", (clave,), True)
        if not lic:
            fallo(ip)
            raise Err("Licencia inválida")
        if lic["usada_por"]:
            raise Err("Esta licencia ya fue usada")
        if lic["tipo"] == "admin":
            # licencia de admin: la cuenta pasa a ser admin (permanente)
            q("UPDATE usuarios SET admin_vence=? WHERE id=?", (POR_VIDA, u["id"]))
        else:
            q("UPDATE usuarios SET vence=? WHERE id=?", (extender(u["vence"], lic["duracion"]), u["id"]))
        q("UPDATE licencias SET usada_por=?, usada=? WHERE clave=?", (u["id"], time.time(), clave))
    u = q("SELECT * FROM usuarios WHERE id=?", (u["id"],), True)
    return {"yo": info(u), "tipo": lic["tipo"], "duracion": lic["duracion"]}


# ───────────────────────────── admin ────────────────────────────────
def _duracion(d):
    try:
        s = int(d.get("duracion"))
    except (TypeError, ValueError):
        raise Err("Duración inválida")
    if s != POR_VIDA and not 60 <= s <= 100 * 365 * 86400:
        raise Err("Duración inválida")
    return s


def api_generar(d, ip, u):
    rol = rol_de(u)
    tipo = "admin" if d.get("tipo") == "admin" else "user"
    if tipo == "admin" and rol != "owner":
        raise Err("Solo el owner puede crear licencias de admin", 403)
    try:
        n = max(1, min(50, int(d.get("cantidad", 1))))
    except (TypeError, ValueError):
        raise Err("Cantidad inválida")
    dur = POR_VIDA if tipo == "admin" else _duracion(d)
    nota = str(d.get("nota", ""))[:60]
    claves = []
    for _ in range(n):
        c = nueva_clave()
        q("INSERT INTO licencias(clave,tipo,duracion,creada,creador,nota) VALUES(?,?,?,?,?,?)",
          (c, tipo, dur, time.time(), u["id"], nota))
        claves.append(c)
    return {"claves": claves}


def api_licencias(d, ip, u):
    filas = q("""SELECT l.*, c.nombre AS creador_nombre, p.nombre AS usada_nombre
                 FROM licencias l LEFT JOIN usuarios c ON c.id=l.creador
                 LEFT JOIN usuarios p ON p.id=l.usada_por
                 ORDER BY l.creada DESC LIMIT 400""")
    return {"licencias": [dict(f) for f in filas]}


def api_borrar_licencia(d, ip, u):
    lic = q("SELECT * FROM licencias WHERE clave=?", (normalizar_clave(d.get("clave")),), True)
    if not lic:
        raise Err("No existe esa licencia")
    if lic["usada_por"]:
        raise Err("Ya fue usada; para quitar el acceso usa la sección Usuarios")
    if lic["tipo"] == "admin" and rol_de(u) != "owner":
        raise Err("Solo el owner puede borrar licencias de admin", 403)
    q("DELETE FROM licencias WHERE clave=?", (lic["clave"],))
    return {"ok": True}


def api_usuarios(d, ip, u):
    filas = q("SELECT * FROM usuarios ORDER BY id")
    usadas = {}
    for l in q("SELECT usada_por, clave FROM licencias WHERE usada_por IS NOT NULL ORDER BY usada"):
        n, _ = usadas.get(l["usada_por"], (0, None))
        usadas[l["usada_por"]] = (n + 1, l["clave"])
    res = []
    for f in filas:
        d = info(f)
        d["licencias"], d["ultima_clave"] = usadas.get(f["id"], (0, None))
        res.append(d)
    return {"usuarios": res}


def api_usuario(d, ip, u):
    rol_yo = rol_de(u)
    try:
        objetivo = q("SELECT * FROM usuarios WHERE id=?", (int(d.get("id")),), True)
    except (TypeError, ValueError):
        objetivo = None
    if not objetivo:
        raise Err("Usuario no encontrado", 404)
    rol_obj = rol_de(objetivo)
    acc = d.get("accion")
    if rol_obj == "owner":
        raise Err("No se puede modificar a un owner", 403)
    if rol_obj == "admin" and rol_yo != "owner" and objetivo["id"] != u["id"]:
        raise Err("Solo el owner puede modificar a otros admins", 403)
    if acc in ("hacer_admin", "quitar_admin") and rol_yo != "owner":
        raise Err("Solo el owner puede dar o quitar admin", 403)
    oid = objetivo["id"]
    if acc == "dar_tiempo":
        q("UPDATE usuarios SET vence=? WHERE id=?", (extender(objetivo["vence"], _duracion(d)), oid))
    elif acc == "quitar_licencia":
        q("UPDATE usuarios SET vence=NULL WHERE id=?", (oid,))
    elif acc == "banear":
        if oid == u["id"]:
            raise Err("No puedes banearte a ti mismo")
        q("UPDATE usuarios SET baneado=1 WHERE id=?", (oid,))
        q("DELETE FROM sesiones WHERE uid=?", (oid,))
    elif acc == "desbanear":
        q("UPDATE usuarios SET baneado=0 WHERE id=?", (oid,))
    elif acc == "hacer_admin":
        q("UPDATE usuarios SET admin_vence=? WHERE id=?", (POR_VIDA, oid))
    elif acc == "quitar_admin":
        q("UPDATE usuarios SET admin_vence=NULL WHERE id=?", (oid,))
    elif acc == "eliminar":
        if oid == u["id"]:
            raise Err("No puedes eliminar tu propia cuenta")
        q("DELETE FROM usuarios WHERE id=?", (oid,))
        q("DELETE FROM sesiones WHERE uid=?", (oid,))
        return {"ok": True, "eliminado": True}
    else:
        raise Err("Acción desconocida")
    return {"ok": True, "usuario": info(q("SELECT * FROM usuarios WHERE id=?", (oid,), True))}


# (metodo, ruta) -> (funcion, nivel)   nivel: publico | sesion | admin
RUTAS = {
    ("GET", "/api/ping"): (lambda d, ip, u: {"ok": True, "version": VERSION}, "publico"),
    ("POST", "/api/registro"): (api_registro, "publico"),
    ("POST", "/api/login"): (api_login, "publico"),
    ("GET", "/api/yo"): (api_yo, "sesion"),
    ("POST", "/api/salir"): (api_salir, "sesion"),
    ("POST", "/api/canjear"): (api_canjear, "sesion"),
    ("POST", "/api/admin/generar"): (api_generar, "admin"),
    ("GET", "/api/admin/licencias"): (api_licencias, "admin"),
    ("POST", "/api/admin/borrar_licencia"): (api_borrar_licencia, "admin"),
    ("GET", "/api/admin/usuarios"): (api_usuarios, "admin"),
    ("POST", "/api/admin/usuario"): (api_usuario, "admin"),
}


class Manejador(BaseHTTPRequestHandler):
    server_version = "AutoClickerAL/" + VERSION

    def _responder(self, code, obj):
        cuerpo = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _atender(self, metodo):
        try:
            ruta = urlparse(self.path).path.rstrip("/")
            if ruta in ("", "/"):
                return self._responder(200, {"servicio": "AutoClicker AL", "version": VERSION})
            ent = RUTAS.get((metodo, ruta))
            if not ent:
                raise Err("No encontrado", 404)
            fn, nivel = ent
            datos = {}
            largo = int(self.headers.get("Content-Length") or 0)
            if largo:
                if largo > 65536:
                    raise Err("Petición muy grande", 413)
                datos = json.loads(self.rfile.read(largo) or b"{}")
                if not isinstance(datos, dict):
                    raise Err("Formato inválido")
            ip = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()
            u = None
            if nivel != "publico":
                tok = (self.headers.get("Authorization") or "").replace("Bearer ", "").strip()
                s = q("SELECT * FROM sesiones WHERE token=?", (tok,), True) if tok else None
                if not s or s["vence"] < time.time():
                    raise Err("Sesión expirada. Inicia sesión de nuevo.", 401)
                u = q("SELECT * FROM usuarios WHERE id=?", (s["uid"],), True)
                if not u:
                    raise Err("La cuenta ya no existe", 401)
                if u["baneado"]:
                    raise Err("Tu cuenta está suspendida", 403)
                if nivel == "admin" and rol_de(u) == "user":
                    raise Err("No tienes permisos de administrador", 403)
                datos["_token"] = tok
            self._responder(200, fn(datos, ip, u))
        except Err as e:
            self._responder(e.code, {"error": e.msg})
        except Exception as e:  # nunca tumbar el servidor
            print("[error]", repr(e), flush=True)
            self._responder(500, {"error": "Error interno del servidor"})

    def do_GET(self):
        self._atender("GET")

    def do_POST(self):
        self._atender("POST")

    def log_message(self, fmt, *args):
        pass


def limpiar_sesiones():
    while True:
        try:
            q("DELETE FROM sesiones WHERE vence < ?", (time.time(),))
        except Exception:
            pass
        time.sleep(3600)


if __name__ == "__main__":
    puerto = int(_leer_env().get("PORT") or os.getenv("PORT") or os.getenv("SERVER_PORT") or 8080)
    roles_env()
    threading.Thread(target=limpiar_sesiones, daemon=True).start()
    print(f"AutoClicker AL - servidor v{VERSION} escuchando en el puerto {puerto}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", puerto), Manejador).serve_forever()
