"""Pruebas del servidor (cualquier sistema). Uso: python pruebas/prueba_servidor.py"""
import hashlib
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FALLOS = []


def comprobar(cond, msg):
    print(("OK    " if cond else "FALLO ") + msg, flush=True)
    if not cond:
        FALLOS.append(msg)


def puerto_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def ph(u, p):
    return hashlib.sha256(f"AL|{u.lower()}|{p}".encode()).hexdigest()


class Cliente:
    def __init__(self, puerto):
        self.puerto, self.token, self.conn = puerto, None, None

    def __call__(self, metodo, ruta, datos=None, nueva=False):
        if self.conn is None or nueva:
            self.conn = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        cuerpo = json.dumps(datos).encode() if datos is not None else None
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        self.conn.request(metodo, ruta, body=cuerpo, headers=h)
        r = self.conn.getresponse()
        return r.status, json.loads(r.read() or b"{}")


def arrancar(carpeta, puerto, owner="1000"):
    with open(os.path.join(carpeta, ".env"), "w") as f:
        f.write(f"OWNER_IDS={owner}\nPORT={puerto}\n")
    p = subprocess.Popen([sys.executable, "app.py"], cwd=carpeta, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", puerto), 0.2).close()
            return p
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("el servidor no arrancó")


def main():
    carpeta = tempfile.mkdtemp()
    shutil.copy(os.path.join(RAIZ, "servidor", "app.py"), carpeta)
    puerto = puerto_libre()
    srv = arrancar(carpeta, puerto)
    try:
        c = Cliente(puerto)
        s, r = c("GET", "/api/ping")
        comprobar(s == 200 and r["ok"], "ping")

        # --- registro y login ---
        s, r = c("POST", "/api/registro", {"usuario": "Dueno", "pw": ph("Dueno", "secreto1")})
        comprobar(s == 200 and r["yo"]["id"] == 1000 and r["yo"]["rol"] == "owner", "el primer usuario es owner #1000")
        owner = Cliente(puerto)
        owner.token = r["token"]
        s, r = c("POST", "/api/registro", {"usuario": "dueno", "pw": ph("dueno", "x" * 8)})
        comprobar(s == 400 and "existe" in r["error"], "nombre repetido (sin importar mayúsculas)")
        s, r = c("POST", "/api/registro", {"usuario": "a b", "pw": ph("a b", "x" * 8)})
        comprobar(s == 400, "nombre inválido rechazado")
        s, r = c("POST", "/api/login", {"usuario": "DUENO", "pw": ph("Dueno", "secreto1")})
        comprobar(s == 200, "login sin importar mayúsculas")
        s, r = c("POST", "/api/login", {"usuario": "Dueno", "pw": ph("Dueno", "mal")})
        comprobar(s == 400, "contraseña incorrecta")
        s, r = c("POST", "/api/login", {"usuario": "noexiste", "pw": ph("noexiste", "mal")})
        comprobar(s == 400 and r["error"] == "Usuario o contraseña incorrectos", "usuario inexistente: mismo mensaje")

        # --- registros simultaneos con el mismo nombre ---
        resultados = []

        def reg():
            resultados.append(Cliente(puerto)("POST", "/api/registro", {"usuario": "carrera", "pw": ph("carrera", "123456")})[0])
        hilos = [threading.Thread(target=reg) for _ in range(5)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        comprobar(sorted(resultados).count(200) == 1 and 500 not in resultados,
                  f"5 registros simultáneos: 1 éxito, sin errores 500 ({sorted(resultados)})")

        # --- conexion persistente (keep-alive) ---
        t0 = time.perf_counter()
        for _ in range(20):
            owner("GET", "/api/yo")
        dt = (time.perf_counter() - t0) / 20
        comprobar(owner.conn.sock is not None, f"conexión reutilizada (keep-alive), {dt*1000:.1f} ms por petición")
        s, r = owner("POST", "/api/nada", {"x": 1})
        s2, r2 = owner("GET", "/api/yo")
        comprobar(s == 404 and s2 == 200, "tras un 404 con cuerpo, la conexión sigue sana")
        s, r = owner("POST", "/api/canjear", None)
        comprobar(s == 400, "petición sin cuerpo no rompe el servidor")

        # --- licencias ---
        s, r = owner("POST", "/api/admin/generar", {"cantidad": 3, "duracion": 86400, "nota": "prueba"})
        comprobar(s == 200 and len(r["claves"]) == 3, "generar 3 licencias de 1 día")
        claves = r["claves"]
        s, r = owner("POST", "/api/admin/generar", {"cantidad": 1, "tipo": "admin"})
        clave_admin = r["claves"][0]
        s, r = owner("GET", "/api/admin/licencias")
        comprobar(s == 200 and len(r["licencias"]) == 4, "listar licencias")

        amigo = Cliente(puerto)
        s, r = amigo("POST", "/api/registro", {"usuario": "amigo", "pw": ph("amigo", "123456")})
        amigo.token = r["token"]
        comprobar(not r["yo"]["acceso"], "usuario nuevo sin acceso")
        s, r = amigo("GET", "/api/admin/usuarios")
        comprobar(s == 403, "usuario normal no ve el panel admin")
        s, r = amigo("POST", "/api/canjear", {"clave": claves[0].lower().replace("-", " ")})
        comprobar(s == 200 and r["yo"]["acceso"], "canjear licencia (en minúsculas y con espacios)")
        v1 = r["yo"]["vence"]
        s, r = amigo("POST", "/api/canjear", {"clave": claves[0]})
        comprobar(s == 400 and "usada" in r["error"], "licencia de un solo uso")

        # canjes simultaneos de 2 licencias: el tiempo se debe sumar completo
        res = []

        def canjear(k):
            cc = Cliente(puerto)
            cc.token = amigo.token
            res.append(cc("POST", "/api/canjear", {"clave": k}))
        hilos = [threading.Thread(target=canjear, args=(k,)) for k in claves[1:]]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        s, r = amigo("GET", "/api/yo")
        dias = (r["yo"]["vence"] - v1) / 86400
        comprobar(abs(dias - 2) < 0.01, f"2 canjes simultáneos suman 2 días ({dias:.3f})")

        s, r = amigo("POST", "/api/canjear", {"clave": clave_admin})
        comprobar(s == 200 and r["yo"]["rol"] == "admin", "licencia de admin convierte la cuenta en admin")
        s, r = amigo("POST", "/api/admin/generar", {"cantidad": 1, "tipo": "admin"})
        comprobar(s == 403, "un admin no puede crear licencias de admin")
        s, r = amigo("POST", "/api/admin/usuario", {"id": 1000, "accion": "banear"})
        comprobar(s == 403, "un admin no puede banear al owner")

        # --- acciones del owner ---
        s, r = owner("POST", "/api/admin/usuario", {"id": 1000, "accion": "banear"})
        comprobar(s == 400, "el owner no puede banearse a sí mismo")
        uid_amigo = r_amigo = None
        s, r = owner("GET", "/api/admin/usuarios")
        for u in r["usuarios"]:
            if u["nombre"] == "amigo":
                uid_amigo, r_amigo = u["id"], u
        comprobar(r_amigo and r_amigo["licencias"] == 4, f"conteo de licencias usadas ({r_amigo and r_amigo['licencias']})")
        s, r = owner("POST", "/api/admin/usuario", {"id": uid_amigo, "accion": "quitar_admin"})
        comprobar(s == 200 and r["usuario"]["rol"] == "user", "quitar admin")
        s, r = owner("POST", "/api/admin/usuario", {"id": uid_amigo, "accion": "dar_tiempo", "duracion": -1})
        comprobar(s == 200 and r["usuario"]["vence"] == -1, "dar tiempo de por vida")
        s, r = owner("POST", "/api/admin/usuario", {"id": uid_amigo, "accion": "banear"})
        comprobar(s == 200 and r["usuario"]["baneado"], "banear")
        s, r = amigo("GET", "/api/yo")
        comprobar(s == 401, "al banear se cierran sus sesiones")
        s, r = amigo("POST", "/api/login", {"usuario": "amigo", "pw": ph("amigo", "123456")})
        comprobar(s == 403, "un baneado no puede entrar")
        owner("POST", "/api/admin/usuario", {"id": uid_amigo, "accion": "desbanear"})
        s, r = amigo("POST", "/api/login", {"usuario": "amigo", "pw": ph("amigo", "123456")})
        comprobar(s == 200, "desbanear")
        amigo.token = r["token"]

        # --- cambiar contraseña ---
        otra = Cliente(puerto)
        otra.token = amigo("POST", "/api/login", {"usuario": "amigo", "pw": ph("amigo", "123456")})[1]["token"]
        s, r = amigo("POST", "/api/cambiar_pw", {"actual": ph("amigo", "mal"), "nueva": ph("amigo", "nueva123")})
        comprobar(s == 400, "cambiar contraseña con la actual incorrecta")
        s, r = amigo("POST", "/api/cambiar_pw", {"actual": ph("amigo", "123456"), "nueva": ph("amigo", "nueva123")})
        comprobar(s == 200, "cambiar contraseña")
        comprobar(amigo("GET", "/api/yo")[0] == 200, "la sesión actual sigue abierta")
        comprobar(otra("GET", "/api/yo")[0] == 401, "las otras sesiones se cierran")
        s, r = amigo("POST", "/api/login", {"usuario": "amigo", "pw": ph("amigo", "nueva123")})
        comprobar(s == 200, "entrar con la contraseña nueva")

        # --- la licencia borrada ---
        s, r = owner("POST", "/api/admin/generar", {"cantidad": 1, "duracion": 3600})
        k = r["claves"][0]
        s, r = owner("POST", "/api/admin/borrar_licencia", {"clave": k})
        comprobar(s == 200, "borrar licencia libre")
        s, r = amigo("POST", "/api/canjear", {"clave": k})
        comprobar(s == 400, "una licencia borrada ya no sirve")

        # --- tokens guardados cifrados ---
        import sqlite3
        con = sqlite3.connect(os.path.join(carpeta, "datos.db"))
        guardados = {t for (t,) in con.execute("SELECT token FROM sesiones")}
        con.close()
        comprobar(owner.token not in guardados and hashlib.sha256(owner.token.encode()).hexdigest() in guardados,
                  "los tokens se guardan cifrados")

        # --- limite de intentos ---
        malo = Cliente(puerto)
        codigos = [malo("POST", "/api/login", {"usuario": "Dueno", "pw": ph("Dueno", f"x{i}")})[0] for i in range(13)]
        comprobar(codigos[-1] == 429, "límite de intentos fallidos")
        s, r = malo("POST", "/api/login", {"usuario": "Dueno", "pw": ph("Dueno", "secreto1")}, nueva=True)
        comprobar(s == 429, "con el límite activo ni la correcta pasa")
        h = http.client.HTTPConnection("127.0.0.1", puerto, timeout=5)
        h.request("POST", "/api/login", body=json.dumps({"usuario": "Dueno", "pw": ph("Dueno", "secreto1")}),
                  headers={"X-Forwarded-For": "1.2.3.4", "Content-Type": "application/json"})
        comprobar(h.getresponse().status == 429, "no se puede saltar el límite con X-Forwarded-For")

        # --- peticiones raras ---
        h = http.client.HTTPConnection("127.0.0.1", puerto, timeout=5)
        h.request("POST", "/api/login", body=b"{no es json", headers={"Content-Type": "application/json"})
        comprobar(h.getresponse().status == 400, "JSON inválido -> 400")
        h = http.client.HTTPConnection("127.0.0.1", puerto, timeout=5)
        h.request("POST", "/api/login", body=b"[1,2]")
        comprobar(h.getresponse().status == 400, "JSON que no es objeto -> 400")
        h = http.client.HTTPConnection("127.0.0.1", puerto, timeout=5)
        h.putrequest("POST", "/api/login")
        h.putheader("Content-Length", "999999999")
        h.endheaders()
        comprobar(h.getresponse().status == 413, "petición enorme -> 413")
        comprobar(Cliente(puerto)("GET", "/api/ping")[0] == 200, "el servidor sigue vivo")
    finally:
        srv.terminate()
        salida = srv.communicate(timeout=10)[0].decode(errors="replace")
    comprobar("ERROR" not in salida, "sin errores internos en el registro del servidor")
    if "ERROR" in salida:
        print(salida)

    # --- migracion: base de datos de la version anterior ---
    viejo = os.path.join(RAIZ, "pruebas", "datos_v22.db")
    if os.path.exists(viejo):
        carpeta2 = tempfile.mkdtemp()
        shutil.copy(os.path.join(RAIZ, "servidor", "app.py"), carpeta2)
        shutil.copy(viejo, os.path.join(carpeta2, "datos.db"))
        p2 = puerto_libre()
        srv = arrancar(carpeta2, p2)
        try:
            c = Cliente(p2)
            c.token = "a" * 64   # token guardado sin cifrar por la v2.2
            s, r = c("GET", "/api/yo")
            comprobar(s == 200 and r["yo"]["nombre"] == "Viejo", "migración: la sesión de la versión anterior sigue válida")
            s, r = c("GET", "/api/yo")
            comprobar(s == 200, "migración: la sesión se cifró y sigue funcionando")
            s, r = c("POST", "/api/login", {"usuario": "viejo", "pw": ph("Viejo", "123456")})
            comprobar(s == 200, "migración: login de una cuenta antigua")
        finally:
            srv.terminate()
            srv.communicate(timeout=10)

    print("FALLOS:", len(FALLOS))
    sys.exit(1 if FALLOS else 0)


if __name__ == "__main__":
    main()
