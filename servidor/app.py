# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import sqlite3
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

VERSION = "2.3"
BASE = os.path.dirname(os.path.abspath(__file__))
RUTA_ENV = os.path.join(BASE, ".env")
RUTA_DB = os.path.join(BASE, "datos.db")
DIR_RESPALDOS = os.path.join(BASE, "respaldos")

POR_VIDA = -1
SESION_SEG = 30 * 86400
MAX_SESIONES = 10
MAX_CUERPO = 64 * 1024
ITERACIONES = 100_000
RE_USUARIO = re.compile(r"[A-Za-z0-9_.\-]{3,20}")
RE_PREHASH = re.compile(r"[0-9a-f]{64}")


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def leer_env():
    vals = {}
    try:
        with open(RUTA_ENV, encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if linea and not linea.startswith("#") and "=" in linea:
                    k, v = linea.split("=", 1)
                    vals[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return vals


def _ids(texto):
    return frozenset(int(x) for x in re.findall(r"\d+", texto or ""))


_env = {"mtime": None, "roles": (frozenset(), frozenset()), "proxy": False}
_env_lock = threading.Lock()


def _env_actual():
    try:
        mt = os.path.getmtime(RUTA_ENV)
    except OSError:
        mt = 0
    if mt != _env["mtime"]:
        with _env_lock:
            if mt != _env["mtime"]:
                v = leer_env()
                owners = _ids(v.get("OWNER_IDS") or os.getenv("OWNER_IDS"))
                admins = _ids(v.get("ADMIN_IDS") or os.getenv("ADMIN_IDS"))
                _env["roles"] = (owners, admins)
                _env["proxy"] = (v.get("TRUST_PROXY") or os.getenv("TRUST_PROXY") or "") == "1"
                _env["mtime"] = mt
                log(f"roles: owners={sorted(owners)} admins={sorted(admins)}")
    return _env


def roles_env():
    return _env_actual()["roles"]


db = sqlite3.connect(RUTA_DB, check_same_thread=False, isolation_level=None)
db.row_factory = sqlite3.Row
lock = threading.RLock()


def _preparar_db():
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE COLLATE NOCASE NOT NULL,
        salt TEXT NOT NULL, hash TEXT NOT NULL,
        creado REAL, visto REAL,
        vence REAL,            -- NULL sin licencia, -1 de por vida, o fecha (epoch)
        admin_vence REAL,      -- NULL no es admin, -1 admin permanente, o fecha
        baneado INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS licencias(
        clave TEXT PRIMARY KEY, tipo TEXT NOT NULL, duracion INTEGER NOT NULL,
        creada REAL, creador INTEGER, nota TEXT DEFAULT '',
        usada_por INTEGER, usada REAL);
    CREATE TABLE IF NOT EXISTS sesiones(token TEXT PRIMARY KEY, uid INTEGER, vence REAL);
    CREATE INDEX IF NOT EXISTS idx_lic_creada ON licencias(creada);
    CREATE INDEX IF NOT EXISTS idx_lic_usada_por ON licencias(usada_por);
    CREATE INDEX IF NOT EXISTS idx_ses_uid ON sesiones(uid);
    """)

    db.execute("INSERT INTO sqlite_sequence(name, seq) SELECT 'usuarios', 999 "
               "WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name='usuarios')")


with lock:
    _preparar_db()


def leer(sql, args=()):
    with lock:
        return db.execute(sql, args).fetchall()


def leer1(sql, args=()):
    with lock:
        return db.execute(sql, args).fetchone()


def escribir(sql, args=()):
    with lock:
        return db.execute(sql, args)


@contextmanager
def transaccion():
    with lock:
        db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            db.execute("ROLLBACK")
            raise
        else:
            db.execute("COMMIT")


def usuario_por_id(uid):
    return leer1("SELECT * FROM usuarios WHERE id=?", (uid,))


def activo(v):
    return v is not None and (v == POR_VIDA or v > time.time())


def extender(actual, segundos):
    if segundos == POR_VIDA or actual == POR_VIDA:
        return POR_VIDA
    base = actual if (actual and actual > time.time()) else time.time()
    return base + segundos


def rol_de(u, roles=None):
    owners, admins = roles or roles_env()
    if u["id"] in owners:
        return "owner"
    if u["id"] in admins or activo(u["admin_vence"]):
        return "admin"
    return "user"


def info(u, roles=None):
    rol = rol_de(u, roles)
    return {
        "id": u["id"], "nombre": u["nombre"], "rol": rol,
        "acceso": (not u["baneado"]) and (rol != "user" or activo(u["vence"])),
        "vence": u["vence"], "admin_vence": u["admin_vence"],
        "baneado": bool(u["baneado"]), "creado": u["creado"], "visto": u["visto"],
    }


def puede_modificar(actor, objetivo, roles):
    r_actor, r_obj = rol_de(actor, roles), rol_de(objetivo, roles)
    if r_obj == "owner":
        return False
    if r_obj == "admin":
        return r_actor == "owner" or actor["id"] == objetivo["id"]
    return r_actor in ("owner", "admin")


def pbkdf2(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), ITERACIONES).hex()


_SALT_FALSO = secrets.token_hex(16)


def nueva_clave():
    alf = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    s = "".join(secrets.choice(alf) for _ in range(16))
    return "AL-" + "-".join(s[i:i + 4] for i in range(0, 16, 4))


def normalizar_clave(c):
    s = re.sub(r"[^A-Za-z0-9]", "", str(c or "")).upper()
    if s.startswith("AL") and len(s) == 18:
        s = s[2:]
    return "AL-" + "-".join(s[i:i + 4] for i in range(0, len(s), 4))


def hash_token(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


class Limite:

    def __init__(self, maximo, ventana):
        self.maximo, self.ventana = maximo, ventana
        self.eventos = {}
        self.lock = threading.Lock()

    def _vigentes(self, clave, ahora):
        lst = [t for t in self.eventos.get(clave, ()) if ahora - t < self.ventana]
        if lst:
            self.eventos[clave] = lst
        else:
            self.eventos.pop(clave, None)
        return lst

    def lleno(self, clave):
        with self.lock:
            return len(self._vigentes(clave, time.time())) >= self.maximo

    def anotar(self, clave):
        with self.lock:
            self.eventos.setdefault(clave, []).append(time.time())

    def limpiar(self):
        with self.lock:
            ahora = time.time()
            for clave in list(self.eventos):
                self._vigentes(clave, ahora)


FALLOS = Limite(12, 600)
REGISTROS = Limite(6, 3600)


class Err(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.msg, self.code = msg, code


def _texto(d, k):
    v = d.get(k, "")
    return v.strip() if isinstance(v, str) else ""


def crear_sesion(uid):
    tok = secrets.token_hex(32)
    with transaccion():
        db.execute("INSERT INTO sesiones VALUES(?,?,?)", (hash_token(tok), uid, time.time() + SESION_SEG))
        db.execute("DELETE FROM sesiones WHERE uid=? AND token NOT IN "
                   "(SELECT token FROM sesiones WHERE uid=? ORDER BY vence DESC LIMIT ?)",
                   (uid, uid, MAX_SESIONES))
    return tok


def api_registro(d, ctx):
    nombre, pw = _texto(d, "usuario"), _texto(d, "pw")
    if not RE_USUARIO.fullmatch(nombre):
        raise Err("Usuario: 3 a 20 caracteres (letras, números, _ . -)")
    if not RE_PREHASH.fullmatch(pw):
        raise Err("Contraseña inválida")
    if REGISTROS.lleno(ctx["ip"]):
        raise Err("Demasiadas cuentas creadas desde tu red. Intenta más tarde.", 429)
    salt, ahora = secrets.token_hex(16), time.time()
    try:
        cur = escribir("INSERT INTO usuarios(nombre,salt,hash,creado,visto) VALUES(?,?,?,?,?)",
                       (nombre, salt, pbkdf2(pw, salt), ahora, ahora))
    except sqlite3.IntegrityError:
        raise Err("Ese usuario ya existe")
    REGISTROS.anotar(ctx["ip"])
    log(f"cuenta nueva: {nombre} (#{cur.lastrowid})")
    return {"token": crear_sesion(cur.lastrowid), "yo": info(usuario_por_id(cur.lastrowid))}


def api_login(d, ctx):
    if FALLOS.lleno(ctx["ip"]):
        raise Err("Demasiados intentos. Espera unos minutos.", 429)
    u = leer1("SELECT * FROM usuarios WHERE nombre=?", (_texto(d, "usuario"),))
    pw = _texto(d, "pw")

    calculado = pbkdf2(pw, u["salt"] if u else _SALT_FALSO)
    if not u or not hmac.compare_digest(calculado, u["hash"]):
        FALLOS.anotar(ctx["ip"])
        raise Err("Usuario o contraseña incorrectos")
    if u["baneado"]:
        raise Err("Tu cuenta está suspendida", 403)
    return {"token": crear_sesion(u["id"]), "yo": info(u)}


def api_yo(d, ctx):
    u, ahora = ctx["u"], time.time()
    if not u["visto"] or ahora - u["visto"] > 60:
        escribir("UPDATE usuarios SET visto=? WHERE id=?", (ahora, u["id"]))
    if ctx["sesion"]["vence"] - ahora < SESION_SEG / 2:
        escribir("UPDATE sesiones SET vence=? WHERE token=?", (ahora + SESION_SEG, ctx["sesion"]["token"]))
    return {"yo": info(u)}


def api_salir(d, ctx):
    escribir("DELETE FROM sesiones WHERE token=?", (ctx["sesion"]["token"],))
    return {"ok": True}


def api_cambiar_pw(d, ctx):
    actual, nueva = _texto(d, "actual"), _texto(d, "nueva")
    if not RE_PREHASH.fullmatch(nueva):
        raise Err("Contraseña nueva inválida")
    if FALLOS.lleno(ctx["ip"]):
        raise Err("Demasiados intentos. Espera unos minutos.", 429)
    u = ctx["u"]
    if not hmac.compare_digest(pbkdf2(actual, u["salt"]), u["hash"]):
        FALLOS.anotar(ctx["ip"])
        raise Err("La contraseña actual no es correcta")
    salt = secrets.token_hex(16)
    with transaccion():
        db.execute("UPDATE usuarios SET salt=?, hash=? WHERE id=?", (salt, pbkdf2(nueva, salt), u["id"]))

        db.execute("DELETE FROM sesiones WHERE uid=? AND token<>?", (u["id"], ctx["sesion"]["token"]))
    return {"ok": True}


def api_canjear(d, ctx):
    ip, uid = ctx["ip"], ctx["u"]["id"]
    if FALLOS.lleno(ip):
        raise Err("Demasiados intentos. Espera unos minutos.", 429)
    clave = normalizar_clave(d.get("clave"))
    with transaccion():
        lic = db.execute("SELECT * FROM licencias WHERE clave=?", (clave,)).fetchone()
        if not lic:
            FALLOS.anotar(ip)
            raise Err("Licencia inválida")
        if lic["usada_por"]:
            raise Err("Esta licencia ya fue usada")
        u = db.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone()
        if lic["tipo"] == "admin":
            db.execute("UPDATE usuarios SET admin_vence=? WHERE id=?", (POR_VIDA, uid))
        else:
            db.execute("UPDATE usuarios SET vence=? WHERE id=?", (extender(u["vence"], lic["duracion"]), uid))
        db.execute("UPDATE licencias SET usada_por=?, usada=? WHERE clave=?", (uid, time.time(), clave))
    log(f"licencia {clave} ({lic['tipo']}) activada por #{uid}")
    return {"yo": info(usuario_por_id(uid)), "tipo": lic["tipo"], "duracion": lic["duracion"]}


def _duracion(d):
    try:
        s = int(d.get("duracion"))
    except (TypeError, ValueError):
        raise Err("Duración inválida")
    if s != POR_VIDA and not 60 <= s <= 100 * 365 * 86400:
        raise Err("Duración inválida")
    return s


def api_generar(d, ctx):
    u = ctx["u"]
    tipo = "admin" if d.get("tipo") == "admin" else "user"
    if tipo == "admin" and rol_de(u) != "owner":
        raise Err("Solo el owner puede crear licencias de admin", 403)
    try:
        n = max(1, min(50, int(d.get("cantidad", 1))))
    except (TypeError, ValueError):
        raise Err("Cantidad inválida")
    dur = POR_VIDA if tipo == "admin" else _duracion(d)
    nota, ahora = _texto(d, "nota")[:60], time.time()
    claves = [nueva_clave() for _ in range(n)]
    with transaccion():
        db.executemany("INSERT INTO licencias(clave,tipo,duracion,creada,creador,nota) VALUES(?,?,?,?,?,?)",
                       [(c, tipo, dur, ahora, u["id"], nota) for c in claves])
    log(f"#{u['id']} creó {n} licencia(s) {tipo}")
    return {"claves": claves}


def api_licencias(d, ctx):
    filas = leer("""SELECT l.*, c.nombre AS creador_nombre, p.nombre AS usada_nombre
                    FROM licencias l LEFT JOIN usuarios c ON c.id=l.creador
                    LEFT JOIN usuarios p ON p.id=l.usada_por
                    ORDER BY l.creada DESC LIMIT 500""")
    return {"licencias": [dict(f) for f in filas]}


def api_borrar_licencia(d, ctx):
    lic = leer1("SELECT * FROM licencias WHERE clave=?", (normalizar_clave(d.get("clave")),))
    if not lic:
        raise Err("No existe esa licencia")
    if lic["usada_por"]:
        raise Err("Ya fue usada; para quitar el acceso usa la sección Usuarios")
    if lic["tipo"] == "admin" and rol_de(ctx["u"]) != "owner":
        raise Err("Solo el owner puede borrar licencias de admin", 403)
    escribir("DELETE FROM licencias WHERE clave=?", (lic["clave"],))
    return {"ok": True}


def api_usuarios(d, ctx):
    roles = roles_env()
    usadas = {}
    for f in leer("SELECT usada_por, COUNT(*) AS n, "
                  "(SELECT clave FROM licencias l2 WHERE l2.usada_por=l.usada_por ORDER BY usada DESC LIMIT 1) AS ult "
                  "FROM licencias l WHERE usada_por IS NOT NULL GROUP BY usada_por"):
        usadas[f["usada_por"]] = (f["n"], f["ult"])
    res = []
    for f in leer("SELECT * FROM usuarios ORDER BY id"):
        x = info(f, roles)
        x["licencias"], x["ultima_clave"] = usadas.get(f["id"], (0, None))
        res.append(x)
    return {"usuarios": res}


def api_usuario(d, ctx):
    actor, roles = ctx["u"], roles_env()
    try:
        oid = int(d.get("id"))
    except (TypeError, ValueError):
        raise Err("Usuario no encontrado", 404)
    acc = d.get("accion")
    if acc in ("hacer_admin", "quitar_admin") and rol_de(actor, roles) != "owner":
        raise Err("Solo el owner puede dar o quitar admin", 403)
    if acc in ("banear", "eliminar") and oid == actor["id"]:
        raise Err("No puedes hacer eso con tu propia cuenta")
    with transaccion():
        obj = db.execute("SELECT * FROM usuarios WHERE id=?", (oid,)).fetchone()
        if not obj:
            raise Err("Usuario no encontrado", 404)
        if not puede_modificar(actor, obj, roles):
            raise Err("No tienes permiso para modificar esta cuenta", 403)
        if acc == "dar_tiempo":
            db.execute("UPDATE usuarios SET vence=? WHERE id=?", (extender(obj["vence"], _duracion(d)), oid))
        elif acc == "quitar_licencia":
            db.execute("UPDATE usuarios SET vence=NULL WHERE id=?", (oid,))
        elif acc == "banear":
            db.execute("UPDATE usuarios SET baneado=1 WHERE id=?", (oid,))
            db.execute("DELETE FROM sesiones WHERE uid=?", (oid,))
        elif acc == "desbanear":
            db.execute("UPDATE usuarios SET baneado=0 WHERE id=?", (oid,))
        elif acc == "hacer_admin":
            db.execute("UPDATE usuarios SET admin_vence=? WHERE id=?", (POR_VIDA, oid))
        elif acc == "quitar_admin":
            db.execute("UPDATE usuarios SET admin_vence=NULL WHERE id=?", (oid,))
        elif acc == "eliminar":
            db.execute("DELETE FROM sesiones WHERE uid=?", (oid,))
            db.execute("DELETE FROM usuarios WHERE id=?", (oid,))
        else:
            raise Err("Acción desconocida")
    log(f"#{actor['id']} -> {acc} sobre #{oid}")
    if acc == "eliminar":
        return {"ok": True, "eliminado": True}
    return {"ok": True, "usuario": info(usuario_por_id(oid), roles)}


RUTAS = {
    ("GET", "/api/ping"): (lambda d, ctx: {"ok": True, "version": VERSION}, "publico"),
    ("POST", "/api/registro"): (api_registro, "publico"),
    ("POST", "/api/login"): (api_login, "publico"),
    ("GET", "/api/yo"): (api_yo, "sesion"),
    ("POST", "/api/salir"): (api_salir, "sesion"),
    ("POST", "/api/cambiar_pw"): (api_cambiar_pw, "sesion"),
    ("POST", "/api/canjear"): (api_canjear, "sesion"),
    ("POST", "/api/admin/generar"): (api_generar, "admin"),
    ("GET", "/api/admin/licencias"): (api_licencias, "admin"),
    ("POST", "/api/admin/borrar_licencia"): (api_borrar_licencia, "admin"),
    ("GET", "/api/admin/usuarios"): (api_usuarios, "admin"),
    ("POST", "/api/admin/usuario"): (api_usuario, "admin"),
}


def autenticar(headers):
    tok = (headers.get("Authorization") or "").replace("Bearer", "", 1).strip()
    if not tok:
        raise Err("Sesión expirada. Inicia sesión de nuevo.", 401)
    h = hash_token(tok)
    s = leer1("SELECT * FROM sesiones WHERE token IN (?, ?)", (h, tok))
    if s and s["token"] == tok:
        escribir("UPDATE sesiones SET token=? WHERE token=?", (h, tok))
        s = leer1("SELECT * FROM sesiones WHERE token=?", (h,))
    if not s or s["vence"] < time.time():
        raise Err("Sesión expirada. Inicia sesión de nuevo.", 401)
    u = usuario_por_id(s["uid"])
    if not u:
        raise Err("La cuenta ya no existe", 401)
    if u["baneado"]:
        raise Err("Tu cuenta está suspendida", 403)
    return s, u


class Manejador(BaseHTTPRequestHandler):
    server_version = "AutoClickerAL/" + VERSION
    protocol_version = "HTTP/1.1"
    timeout = 20
    disable_nagle_algorithm = True

    def _responder(self, code, obj):
        cuerpo = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _leer_cuerpo(self):
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            raise Err("Petición inválida")
        if largo < 0 or largo > MAX_CUERPO:
            self.close_connection = True
            raise Err("Petición muy grande", 413)
        crudo = self.rfile.read(largo) if largo else b""
        if not crudo:
            return {}
        try:
            datos = json.loads(crudo)
        except ValueError:
            raise Err("Formato inválido")
        if not isinstance(datos, dict):
            raise Err("Formato inválido")
        return datos

    def _ip(self):
        if _env_actual()["proxy"]:
            xff = self.headers.get("X-Forwarded-For")
            if xff:
                return xff.split(",")[0].strip()
        return self.client_address[0]

    def _atender(self, metodo):
        try:
            datos = self._leer_cuerpo()
            ruta = urlparse(self.path).path.rstrip("/")
            if ruta in ("", "/"):
                return self._responder(200, {"servicio": "AutoClicker AL", "version": VERSION})
            ent = RUTAS.get((metodo, ruta))
            if not ent:
                raise Err("No encontrado", 404)
            fn, nivel = ent
            ctx = {"ip": self._ip(), "u": None, "sesion": None}
            if nivel != "publico":
                ctx["sesion"], ctx["u"] = autenticar(self.headers)
                if nivel == "admin" and rol_de(ctx["u"]) == "user":
                    raise Err("No tienes permisos de administrador", 403)
            self._responder(200, fn(datos, ctx))
        except Err as e:
            self._responder(e.code, {"error": e.msg})
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            log("ERROR\n" + traceback.format_exc())
            self.close_connection = True
            try:
                self._responder(500, {"error": "Error interno del servidor"})
            except OSError:
                pass

    def do_GET(self):
        self._atender("GET")

    def do_POST(self):
        self._atender("POST")

    def log_message(self, fmt, *args):
        pass


def respaldar():
    os.makedirs(DIR_RESPALDOS, exist_ok=True)
    destino = os.path.join(DIR_RESPALDOS, f"datos-{datetime.now():%Y%m%d-%H%M}.db")
    copia = sqlite3.connect(destino)
    try:
        with lock:
            db.backup(copia)
    finally:
        copia.close()
    viejos = sorted(f for f in os.listdir(DIR_RESPALDOS) if f.startswith("datos-") and f.endswith(".db"))
    for f in viejos[:-7]:
        os.remove(os.path.join(DIR_RESPALDOS, f))
    log(f"respaldo guardado: {os.path.basename(destino)}")


def mantenimiento():
    ultimo_respaldo = 0.0
    time.sleep(60)
    while True:
        try:
            escribir("DELETE FROM sesiones WHERE vence < ?", (time.time(),))
            FALLOS.limpiar()
            REGISTROS.limpiar()
            if time.time() - ultimo_respaldo > 86400:
                respaldar()
                ultimo_respaldo = time.time()
        except Exception:
            log("ERROR en mantenimiento\n" + traceback.format_exc())
        time.sleep(3600)


class Servidor(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):

        tipo = sys.exc_info()[0]
        if tipo and issubclass(tipo, (ConnectionError, TimeoutError)):
            return
        log("ERROR de conexión\n" + traceback.format_exc())


def main():
    puerto = int(leer_env().get("PORT") or os.getenv("PORT") or os.getenv("SERVER_PORT") or 8080)
    roles_env()
    threading.Thread(target=mantenimiento, daemon=True).start()
    servidor = Servidor(("0.0.0.0", puerto), Manejador)

    def apagar(*_):
        threading.Thread(target=servidor.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, apagar)
    signal.signal(signal.SIGINT, apagar)
    log(f"AutoClicker AL - servidor v{VERSION} escuchando en el puerto {puerto}")
    try:
        servidor.serve_forever()
    finally:
        with lock:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.close()
        log("servidor detenido")


if __name__ == "__main__":
    main()
