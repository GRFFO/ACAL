"""Prueba en Windows real: clics que llegan de verdad y protecciones."""
import os, sys, time, tempfile, threading
os.environ["APPDATA"] = tempfile.mkdtemp()
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "cliente"))
import AutoClickerAL as A
import tkinter as tk

FALLOS = []
def comprobar(cond, msg):
    print(("OK    " if cond else "FALLO ") + msg, flush=True)
    if not cond:
        FALLOS.append(msg)

# ---------- 1) clics reales en una ventana de prueba ----------
root = tk.Tk()
root.geometry("300x300+200+200")
root.attributes("-topmost", True)
eventos = []
root.bind("<ButtonPress-1>", lambda e: eventos.append(("down", e.time)))
root.bind("<ButtonRelease-1>", lambda e: eventos.append(("up", e.time)))
root.update(); root.focus_force(); time.sleep(0.5); root.update()
cx, cy = root.winfo_rootx() + 150, root.winfo_rooty() + 150

def contar(modo_juego, n=10, doble=False):
    eventos.clear()
    m = A.Motor()
    m.iniciar(lambda p: A.hacer_clic("izq", doble, (cx, cy), modo_juego, p), 0.1, n)
    fin = time.time() + 5
    while (m.activo or time.time() < fin - 3.5) and time.time() < fin:
        root.update(); time.sleep(0.005)
    for _ in range(30):
        root.update(); time.sleep(0.01)
    downs = [t for k, t in eventos if k == "down"]
    ups = [t for k, t in eventos if k == "up"]
    duraciones = [u - d for d, u in zip(downs, ups)]
    return len(downs), duraciones, m

n, dur, m = contar(True)
print("modo juego -> clics:", n, "duraciones ms:", dur)
comprobar(n == 10, f"modo juego: llegaron {n}/10 clics")
comprobar(dur and min(dur) >= 30, f"modo juego: el boton se mantiene presionado >=30 ms (min {min(dur) if dur else '-'})")
n, dur, m = contar(True, 5, doble=True)
comprobar(n == 10, f"modo juego doble clic: llegaron {n}/10 pulsaciones")
n, dur, m = contar(False)
comprobar(n == 10, f"modo rapido: llegaron {n}/10 clics")

# ---------- 1b) teclado en modo juego: la tecla se mantiene ~40 ms ----------
teclas = []
root.bind("<KeyPress-a>", lambda e: teclas.append(("down", e.time)))
root.bind("<KeyRelease-a>", lambda e: teclas.append(("up", e.time)))
root.focus_force(); root.update()
def teclear():   # en otro hilo, como el programa real, mientras la ventana procesa eventos
    for _ in range(5):
        A.presionar_tecla(0x41, 40)
        time.sleep(0.06)
hilo = threading.Thread(target=teclear)
hilo.start()
while hilo.is_alive():
    root.update(); time.sleep(0.002)
for _ in range(20):
    root.update(); time.sleep(0.01)
downs = [t for k, t in teclas if k == "down"]
ups = [t for k, t in teclas if k == "up"]
dur = [u - d for d, u in zip(downs, ups)]
comprobar(len(downs) >= 5, f"teclado: llegaron {len(downs)}/5 pulsaciones")
comprobar(dur and min(dur) >= 30, f"teclado modo juego: tecla mantenida >=30 ms (duraciones {dur})")

# ---------- 1c) precision del ritmo ----------
def medir_ritmo(intervalo, carga=False):
    parar = threading.Event()
    def ocupar():   # simula la ventana dibujando animaciones al mismo tiempo
        while not parar.is_set():
            sum(i * i for i in range(2000))
    if carga:
        threading.Thread(target=ocupar, daemon=True).start()
    m = A.Motor()
    m.iniciar(lambda p: None, intervalo)
    time.sleep(2.0)
    m.detener()
    parar.set()
    time.sleep(0.05)
    return m.contador / 2.0

for iv, carga in ((0.010, False), (0.005, False), (0.002, False), (0.010, True), (0.005, True)):
    esperado = 1 / iv
    real = medir_ritmo(iv, carga)
    error = abs(real - esperado) / esperado
    comprobar(error < 0.05, f"ritmo {iv*1000:.0f} ms{' con la ventana ocupada' if carga else ''}: "
                            f"{real:.0f}/s (esperado {esperado:.0f}, error {error*100:.1f} %)")

# ---------- 2) protecciones ----------
cola = __import__("queue").Queue()
motores = {"mouse": A.Motor(), "teclado": A.Motor()}
vig = A.VigilanteAtajos(cola, motores)
vig.atajos = {"mouse": 0x75, "teclado": 0x76, "stop": 0x77}
vig.habilitado = True
vig.start()

def latir(seg):
    fin = time.time() + seg
    while time.time() < fin:
        vig.latido_ui = time.monotonic(); root.update(); time.sleep(0.02)

# a) esquina de emergencia
A.user32.SetCursorPos(600, 400)
motores["mouse"].iniciar(lambda p: p.wait(0.01), 0.05)
latir(0.5)
A.user32.SetCursorPos(0, 0)
latir(1.0)
comprobar(not motores["mouse"].activo, "esquina: el motor se detuvo")
comprobar("esquina" in (motores["mouse"].error or ""), f"esquina: motivo = {motores['mouse'].error!r}")
A.user32.SetCursorPos(600, 400)
latir(0.3)

# b) tecla de emergencia F8 (detiene sin pasar por la ventana)
motores["teclado"].iniciar(lambda p: p.wait(0.01), 0.05)
latir(0.5)
A.presionar_tecla(0x77, 60)
latir(0.5)
comprobar(not motores["teclado"].activo, "F8: el motor se detuvo")

# c) accion trabada
motores["mouse"].iniciar(lambda p: time.sleep(9), 0.05)
t0 = time.time(); latir(7)
comprobar(motores["mouse"]._parar.is_set(), f"accion trabada: se ordeno parar ({time.time()-t0:.1f}s)")
comprobar("trab" in (motores["mouse"].error or ""), f"accion trabada: motivo = {motores['mouse'].error!r}")
latir(3)

# d) ventana congelada (no se actualiza el latido)
motores["teclado"].iniciar(lambda p: p.wait(0.01), 0.05)
latir(0.3)
time.sleep(9.5)  # la "ventana" no responde (el limite es 8 s)
comprobar(not motores["teclado"].activo, "ventana congelada: el motor se detuvo")
comprobar("ventana" in (motores["teclado"].error or ""), f"ventana congelada: motivo = {motores['teclado'].error!r}")

# e) con la proteccion apagada no se detiene por la esquina
vig.esquina = False
motores["mouse"].iniciar(lambda p: p.wait(0.01), 0.05)
latir(0.3); A.user32.SetCursorPos(0, 0); latir(0.8)
comprobar(motores["mouse"].activo, "esquina apagada: el motor sigue")
motores["mouse"].detener(); latir(0.3)

root.destroy()
print("FALLOS:", len(FALLOS))
sys.exit(1 if FALLOS else 0)
