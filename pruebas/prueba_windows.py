"""Prueba del programa completo en Windows real (GitHub Actions).

Levanta un servidor local, recorre todas las pantallas como lo haria una persona,
toma capturas de cada una (se imprimen en base64 para poder revisarlas) y falla
si aparece cualquier error.
"""
import base64
import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
srv_dir = tempfile.mkdtemp()
shutil.copy(os.path.join(RAIZ, "servidor", "app.py"), srv_dir)
with open(os.path.join(srv_dir, ".env"), "w") as f:
    f.write("OWNER_IDS=1000\nPORT=8799\n")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=srv_dir)
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", 8799), 0.2).close()
        break
    except OSError:
        time.sleep(0.1)

os.environ["APPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(RAIZ, "cliente"))
import AutoClickerAL as A  # noqa: E402
from PIL import ImageGrab  # noqa: E402

A.leer_config_remota = lambda: {"servidor": "http://127.0.0.1:8799", "version": A.APP_VERSION}

ERRORES, FALLOS = [], []


def comprobar(cond, msg):
    print(("OK    " if cond else "FALLO ") + msg, flush=True)
    if not cond:
        FALLOS.append(msg)


def reportar(exc, val, tb):
    ERRORES.append("".join(traceback.format_exception(exc, val, tb)))
    print("ERROR EN CALLBACK:\n" + ERRORES[-1], flush=True)


A.tk.Tk.report_callback_exception = lambda self, e, v, t: reportar(e, v, t)


def seguro_estricto(fn):           # en la prueba, cualquier error de Tk cuenta
    def w(*a, **k):
        try:
            return fn(*a, **k)
        except A.tk.TclError as e:
            if "invalid command name" not in str(e) and "bad window path" not in str(e):
                reportar(*sys.exc_info())
    return w


A.seguro = seguro_estricto

t0 = time.perf_counter()
app = A.App()


def bombear(seg):
    fin = time.time() + seg
    while time.time() < fin:
        app.update()
        time.sleep(0.01)


def esperar(cond, seg=8):
    fin = time.time() + seg
    while time.time() < fin:
        app.update()
        if cond():
            return True
        time.sleep(0.01)
    return False


def captura(nombre):
    app.update()
    app.lift()
    app.attributes("-topmost", True)
    bombear(0.6)
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    im = ImageGrab.grab((x, y, x + w, y + h)).convert("RGB")
    im.thumbnail((900, 900))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=72)
    print(f"@@CAPTURA {nombre} {base64.b64encode(buf.getvalue()).decode()}", flush=True)


ok = esperar(lambda: "en línea" in app.pantalla.estado.cget("text"))
comprobar(ok, f"pantalla de acceso lista y servidor en línea ({time.perf_counter() - t0:.2f} s desde que abre)")
captura("acceso")


def registrar(u, pw="abcdef"):
    s = app.pantalla
    s.tabs.set(1, True)
    app.update()
    s.c_user.set(u)
    s.c_pw.set(pw)
    s.c_pw2.set(pw)
    s._enviar()


registrar("Dueno")
comprobar(esperar(lambda: isinstance(app.pantalla, A.PantallaPrincipal)), "registro del owner entra al panel")
P = app.pantalla
nombres = ["mouse", "teclado", "licencias", "usuarios", "cuenta"]
for i, n in enumerate(nombres):
    P.ir(i)
    bombear(1.0)
    captura(n)

# licencias
L = P.paginas[2]
L.c_cant.set("2")
L._generar()
comprobar(esperar(lambda: len(L.nuevas) == 2 and len(L.datos) >= 2), "generar 2 licencias")
clave = sorted(L.nuevas)[0]
L.s_tipo.set(1, True)
app.update()
L._generar()
comprobar(esperar(lambda: any(x["tipo"] == "admin" for x in L.datos)), "generar licencia de admin")
clave_admin = next(x["clave"] for x in L.datos if x["tipo"] == "admin")
captura("licencias_admin")

# cuenta regresiva del boton grande: 2 s exactos
M = P.paginas[0]
inicio, fin = time.perf_counter(), []
M.power.cuenta_regresiva(2, lambda: fin.append(time.perf_counter()))
esperar(lambda: fin, 5)
dur = (fin[0] - inicio) if fin else 99
comprobar(1.9 < dur < 2.3, f"cuenta regresiva de 2 s dura {dur:.2f} s")

# cambiar contraseña
C = P.paginas[4]
C.c_pw_act.set("abcdef")
C.c_pw_nueva.set("nueva123")
C._cambiar_pw()
bombear(1.5)

app.cerrar_sesion()
comprobar(esperar(lambda: isinstance(app.pantalla, A.PantallaAuth)), "cerrar sesión")
s = app.pantalla
s.c_user.set("Dueno")
s.c_pw.set("nueva123")
s._enviar()
comprobar(esperar(lambda: isinstance(app.pantalla, A.PantallaPrincipal)), "entrar con la contraseña nueva")
app.cerrar_sesion()
esperar(lambda: isinstance(app.pantalla, A.PantallaAuth))
bombear(0.6)

# amigo: licencia, luego licencia de admin => el panel se reconstruye con las secciones nuevas
registrar("amigo")
comprobar(esperar(lambda: isinstance(app.pantalla, A.PantallaLicencia)), "usuario nuevo va a activar licencia")
bombear(0.6)
captura("licencia")
app.pantalla.campo.set(clave)
app.pantalla._activar()
comprobar(esperar(lambda: isinstance(app.pantalla, A.PantallaPrincipal), 6), "activar licencia entra al panel")
bombear(0.8)
P = app.pantalla
comprobar(len(P.paginas) == 3, "un usuario normal ve 3 secciones")
C = P.paginas[-1]
C.c_lic.set(clave_admin)
C._canjear()
comprobar(esperar(lambda: isinstance(app.pantalla, A.PantallaPrincipal) and app.pantalla is not P
                  and len(app.pantalla.paginas) == 5, 6), "con licencia de admin el panel muestra 5 secciones")
bombear(0.8)

# tema claro e inglés
P = app.pantalla
P.ir(len(P.paginas) - 1)
bombear(0.6)
C = P.paginas[-1]
C._tema("claro")
comprobar(esperar(lambda: A.TEMA == "claro" and isinstance(app.pantalla, A.PantallaPrincipal)), "cambio a tema claro")
bombear(1.0)
captura("tema_claro")
app.pantalla.paginas[-1]._idioma("en")
comprobar(esperar(lambda: A.IDIOMA == "en" and isinstance(app.pantalla, A.PantallaPrincipal)), "cambio a inglés")
app.pantalla.ir(0)
bombear(1.0)
captura("ingles_claro")
comprobar(A.tr("Mouse") == "Mouse" and A.tr("Cuenta") == "Account", "textos traducidos a inglés")
app.pantalla.paginas[-1]._tema("oscuro")
bombear(0.6)
app.pantalla.paginas[-1]._idioma("es")
bombear(0.6)

# aviso de actualizacion
app.remota = dict(app.remota, version="99.0", notas="Prueba de actualización")
app._ofrecer_actualizacion()
bombear(0.8)
captura("actualizacion")
comprobar(app.capa_update is not None, "aparece el aviso de actualización")

# reabrir: auto-login
app.cerrar()
app = A.App()
comprobar(esperar(lambda: isinstance(app.pantalla, A.PantallaPrincipal), 8), "al reabrir entra solo (sesión recordada)")
app.cerrar()
srv.kill()
print("TOTAL ERRORES:", len(ERRORES), "FALLOS:", len(FALLOS))
sys.exit(1 if (ERRORES or FALLOS) else 0)
