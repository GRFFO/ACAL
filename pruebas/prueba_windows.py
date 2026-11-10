"""Prueba automatica del programa en Windows real (se ejecuta en GitHub Actions)."""
import os, sys, time, threading, traceback, subprocess, tempfile, json, urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
srv_dir = tempfile.mkdtemp()
import shutil
shutil.copy(os.path.join(RAIZ, "servidor", "app.py"), srv_dir)
open(os.path.join(srv_dir, ".env"), "w").write("OWNER_IDS=1000\nPORT=8799\n")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=srv_dir)
time.sleep(2)

os.environ["APPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(RAIZ, "cliente"))
import AutoClickerAL as A
A.leer_config_remota = lambda: {"servidor": "http://127.0.0.1:8799", "version": A.APP_VERSION}

ERRORES = []
def reportar(exc, val, tb):
    ERRORES.append("".join(traceback.format_exception(exc, val, tb)))
    print("ERROR EN CALLBACK:\n" + ERRORES[-1], flush=True)
A.tk.Tk.report_callback_exception = lambda self, e, v, t: reportar(e, v, t)

app = A.App()
def bombear(seg):
    fin = time.time() + seg
    while time.time() < fin:
        app.update()
        time.sleep(0.01)

def paso(nombre, fn):
    print(f"--- {nombre}", flush=True)
    try:
        fn()
    except Exception:
        reportar(*sys.exc_info())
    bombear(2.5)
    print("    pantalla:", type(app.pantalla).__name__, flush=True)

bombear(3)
s = app.pantalla
print("estado:", s.estado.cget("text"))
def registrar(u):
    s = app.pantalla
    s.tabs.set(1, True)
    app.update()
    s.c_user.set(u); s.c_pw.set("abcdef"); s.c_pw2.set("abcdef")
    s._enviar()
paso("registro owner", lambda: registrar("dueno"))
P = app.pantalla
if isinstance(P, A.PantallaPrincipal):
    for i in range(len(P.paginas)):
        paso(f"pagina {i}", lambda i=i: P.ir(i))
    L = P.paginas[2]
    paso("generar licencia", lambda: (L.c_cant.set("1"), L._generar()))
    paso("tipo admin", lambda: L.s_tipo.set(1, True))
    paso("cerrar sesion", app.cerrar_sesion)
    paso("registro amigo", lambda: registrar("amigo"))
    clave = sorted(L.nuevas)[0] if L.nuevas else ""
    paso("activar", lambda: (app.pantalla.campo.set(clave), app.pantalla._activar()))
    bombear(2)
    print("pantalla final:", type(app.pantalla).__name__)
app.cerrar()
srv.kill()
print("TOTAL ERRORES:", len(ERRORES))
sys.exit(1 if ERRORES else 0)
