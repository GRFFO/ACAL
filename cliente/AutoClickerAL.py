# -*- coding: utf-8 -*-

import hashlib
import http.client
import io
import json
import math
import os
import platform
import queue
import random
import re
import socket
import sys
import threading
import time
import urllib.request
from collections import OrderedDict
from datetime import datetime
from urllib.parse import urlsplit


GITHUB_REPO = "GRFFO/ACAL"
GITHUB_RAMA = "main"
SERVIDOR = "http://fi18.bot-hosting.cloud:26369"
APP_NOMBRE = "AutoClicker AL"
APP_VERSION = "2.4"
ES_WINDOWS = platform.system() == "Windows"


sys.setswitchinterval(0.001)


def carpeta_app():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def leer_config_remota():
    if "TU-USUARIO" in GITHUB_REPO:
        return None
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_RAMA}/config.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AutoClickerAL", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=6) as r:
            d = json.loads(r.read())
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def version_tupla(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3]) or (0,)


def url_servidor(remota=None):
    url = SERVIDOR
    if remota and remota.get("servidor") and "TU-IP" not in remota["servidor"]:
        url = remota["servidor"]
    try:
        with open(os.path.join(carpeta_app(), "servidor.txt"), encoding="utf-8") as f:
            t = f.read().strip()
            if t and "TU-IP" not in t:
                url = t
    except OSError:
        pass
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


class ErrorAPI(Exception):
    def __init__(self, msg, codigo=0):
        super().__init__(msg)
        self.msg, self.codigo = msg, codigo


class ClienteAPI:

    INACTIVA = 12
    _CAIDAS = (http.client.RemoteDisconnected, http.client.CannotSendRequest,
               ConnectionResetError, ConnectionAbortedError, BrokenPipeError)

    def __init__(self):
        self.token = None
        self.url = ""
        self._dest = None
        self._conn = None
        self._uso = 0.0
        self._lock = threading.Lock()
        self.usar(url_servidor())

    def usar(self, url):
        try:
            p = urlsplit(url)
            dest = (p.scheme, p.hostname or "", p.port or (443 if p.scheme == "https" else 80), p.path.rstrip("/"))
        except ValueError:
            dest = ("http", "", 0, "")
        with self._lock:
            if dest != self._dest:
                self._cerrar()
                self._dest = dest
        self.url = url

    def _cerrar(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _conectar(self):
        esquema, host, puerto, _ = self._dest
        if not host or not puerto:
            raise OSError("direccion del servidor invalida")
        clase = http.client.HTTPSConnection if esquema == "https" else http.client.HTTPConnection
        self._conn = clase(host, puerto, timeout=10)
        self._conn.connect()
        try:
            self._conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

    def llamar(self, metodo, ruta, datos=None, token=None):
        cuerpo = json.dumps(datos).encode() if datos is not None else None
        cab = {"Content-Type": "application/json", "User-Agent": f"AutoClickerAL/{APP_VERSION}"}
        token = token or self.token
        if token:
            cab["Authorization"] = f"Bearer {token}"
        with self._lock:
            for intento in (1, 2):
                reutilizada = self._conn is not None and time.monotonic() - self._uso < self.INACTIVA
                try:
                    if not reutilizada:
                        self._cerrar()
                        self._conectar()
                    self._conn.request(metodo, self._dest[3] + ruta, body=cuerpo, headers=cab)
                    resp = self._conn.getresponse()
                    crudo = resp.read()
                    self._uso = time.monotonic()
                    if resp.will_close:
                        self._cerrar()
                    break
                except self._CAIDAS:
                    self._cerrar()
                    if reutilizada and intento == 1:
                        continue
                    raise ErrorAPI("No se pudo conectar con el servidor", 0)
                except Exception:
                    self._cerrar()
                    raise ErrorAPI("No se pudo conectar con el servidor", 0)
        try:
            obj = json.loads(crudo or b"{}")
        except ValueError:
            obj = {}
        if resp.status >= 400:
            raise ErrorAPI(obj.get("error") or tr("Error del servidor ({c})", c=resp.status), resp.status)
        return obj


def prehash(usuario, pw):

    return hashlib.sha256(f"AL|{usuario.strip().lower()}|{pw}".encode()).hexdigest()


class Local:

    def __init__(self):
        base = os.getenv("APPDATA") or os.path.expanduser("~")
        self.dir = os.path.join(base, "AutoClickerAL")
        os.makedirs(self.dir, exist_ok=True)
        self.ruta = os.path.join(self.dir, "local.json")
        self.datos = {"token": None, "ultimo_usuario": "", "recordar": True, "config": {}}
        try:
            with open(self.ruta, encoding="utf-8") as f:
                self.datos.update(json.load(f))
        except Exception:
            pass

    def guardar(self):
        try:
            tmp = self.ruta + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.datos, f, indent=1, ensure_ascii=False)
            os.replace(tmp, self.ruta)
        except Exception:
            pass

    def cfg(self, uid):
        return self.datos["config"].setdefault(str(uid), {})


LOGO = {"pil": None, "version": 0}
SONIDO = {"on": True}


def reproducir(tipo):
    if not ES_WINDOWS or not SONIDO["on"]:
        return

    def tocar():
        try:
            import winsound
            for frec, ms in ((900, 55), (1250, 70)) if tipo == "on" else ((700, 60), (460, 85)):
                winsound.Beep(frec, ms)
        except Exception:
            pass
    threading.Thread(target=tocar, daemon=True).start()


def _url_logo(valor):
    valor = str(valor or "").strip()
    if not valor:
        return ""
    if valor.startswith(("http://", "https://")):
        return valor
    return f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_RAMA}/{valor.lstrip('/')}"


def cargar_logo_cache(local):
    ruta = os.path.join(local.dir, "logo.png")
    if os.path.exists(ruta):
        try:
            LOGO["pil"] = Image.open(ruta).convert("RGBA")
            LOGO["version"] += 1
        except Exception:
            LOGO["pil"] = None


def sincronizar_logo(remota, local, al_cambiar):
    ruta = os.path.join(local.dir, "logo.png")
    url = _url_logo((remota or {}).get("logo"))
    if not url:
        if local.datos.get("logo_url"):
            local.datos["logo_url"] = ""
            local.guardar()
            try:
                os.remove(ruta)
            except OSError:
                pass
            LOGO["pil"], LOGO["version"] = None, LOGO["version"] + 1
            al_cambiar()
        return
    if url == local.datos.get("logo_url") and LOGO["pil"] is not None:
        return
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AutoClickerAL", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=10) as r:
            crudo = r.read(8 * 1024 * 1024)
        im = Image.open(io.BytesIO(crudo)).convert("RGBA")
        im.thumbnail((256, 256), Image.LANCZOS)
        im.save(ruta, "PNG")
        LOGO["pil"], LOGO["version"] = im, LOGO["version"] + 1
        local.datos["logo_url"] = url
        local.guardar()
        al_cambiar()
    except Exception:
        pass


UNIDADES = [("Horas", 3600), ("Días", 86400), ("Semanas", 604800), ("Meses", 2592000), ("Años", 31536000)]
PRESETS = [("1 día", 86400), ("2 días", 172800), ("1 semana", 604800), ("1 mes", 2592000),
           ("3 meses", 7776000), ("6 meses", 15552000), ("1 año", 31536000), ("2 años", 63072000),
           ("De por vida", -1)]


_DUR_ES = (("año", "años", 31536000), ("mes", "meses", 2592000), ("semana", "semanas", 604800),
           ("día", "días", 86400), ("hora", "horas", 3600))
_DUR_EN = (("year", "years", 31536000), ("month", "months", 2592000), ("week", "weeks", 604800),
           ("day", "days", 86400), ("hour", "hours", 3600))


def fmt_duracion(s):
    if s is None:
        return "—"
    s = int(s)
    if s < 0:
        return tr("De por vida")
    for sing, plur, u in (_DUR_EN if IDIOMA == "en" else _DUR_ES):
        if s >= u and s % u == 0:
            n = s // u
            return f"{n} {sing if n == 1 else plur}"
    return f"{s // 3600} h"


def fmt_restante(vence):
    if vence is None:
        return "Sin licencia" if IDIOMA != "en" else "No license"
    if vence < 0:
        return tr("De por vida")
    r = vence - time.time()
    if r <= 0:
        return "Vencida" if IDIOMA != "en" else "Expired"
    d, h, m = int(r // 86400), int(r % 86400 // 3600), int(r % 3600 // 60)
    mn = "min" if IDIOMA != "en" else "min"
    if d >= 1:
        return f"{d} d {h} h"
    if h >= 1:
        return f"{h} h {m} {mn}"
    return f"{max(1, m)} {mn}"


def fmt_fecha(ts):
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


VK_NOMBRES = {
    0x08: "BACKSPACE", 0x09: "TAB", 0x0D: "ENTER", 0x10: "SHIFT", 0x11: "CTRL", 0x12: "ALT",
    0x14: "MAYÚS", 0x1B: "ESC", 0x20: "ESPACIO", 0x21: "RE PÁG", 0x22: "AV PÁG", 0x23: "FIN",
    0x24: "INICIO", 0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓", 0x2D: "INSERT", 0x2E: "SUPR",
    0xA0: "SHIFT", 0xA1: "SHIFT DER", 0xA2: "CTRL", 0xA3: "CTRL DER", 0xBA: "Ñ", 0xBB: "+",
    0xBC: ",", 0xBD: "-", 0xBE: ".",
}
for _i in range(26):
    VK_NOMBRES[0x41 + _i] = chr(0x41 + _i)
for _i in range(10):
    VK_NOMBRES[0x30 + _i] = str(_i)
    VK_NOMBRES[0x60 + _i] = f"NUM {_i}"
for _i in range(24):
    VK_NOMBRES[0x70 + _i] = f"F{_i + 1}"
VK_EXTENDIDAS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0x6F, 0xA3, 0xA5}


def nombre_vk(vk):
    return VK_NOMBRES.get(vk, f"TECLA {vk}")


if ES_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _UNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    user32.MapVirtualKeyW.restype = wintypes.UINT
    user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
    user32.GetSystemMetrics.restype = ctypes.c_int

    _MOUSE = {"izq": (0x0002, 0x0004), "der": (0x0008, 0x0010), "med": (0x0020, 0x0040)}

    def _enviar(lista):
        arr = (INPUT * len(lista))(*lista)
        user32.SendInput(len(lista), arr, ctypes.sizeof(INPUT))

    def _mi(flags):
        i = INPUT()
        i.type = 0
        i.mi = MOUSEINPUT(0, 0, 0, flags, 0, 0)
        return i

    def _ki(vk, scan, flags):
        i = INPUT()
        i.type = 1
        i.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
        return i

    def _mover_absoluto(x, y):
        vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        vw, vh = max(2, user32.GetSystemMetrics(78)), max(2, user32.GetSystemMetrics(79))
        nx = int(round((x - vx) * 65535 / (vw - 1)))
        ny = int(round((y - vy) * 65535 / (vh - 1)))
        i = INPUT()
        i.type = 0
        i.mi = MOUSEINPUT(nx, ny, 0, 0x0001 | 0x8000 | 0x4000, 0, 0)
        _enviar([i])

    def hacer_clic(boton="izq", doble=False, pos=None, modo_juego=True, parar=None):
        d, u = _MOUSE[boton]
        if not modo_juego:
            if pos:
                user32.SetCursorPos(int(pos[0]), int(pos[1]))
            _enviar([_mi(d), _mi(u)] * (2 if doble else 1))
            return


        esperar = parar.wait if parar else time.sleep
        x, y = pos if pos else posicion_cursor()
        _mover_absoluto(x, y)
        esperar(0.008)
        for n in range(2 if doble else 1):
            if n:
                esperar(0.045)
            _enviar([_mi(d)])
            try:
                esperar(0.04)
            finally:
                _enviar([_mi(u)])

    def presionar_tecla(vk, mantener_ms=25, parar=None):
        scan = user32.MapVirtualKeyW(vk, 0)
        if scan:
            fl = 0x0008 | (0x0001 if vk in VK_EXTENDIDAS else 0)
            abajo, arriba = _ki(0, scan, fl), _ki(0, scan, fl | 0x0002)
        else:
            abajo, arriba = _ki(vk, 0, 0), _ki(vk, 0, 0x0002)
        _enviar([abajo])
        try:
            (parar.wait if parar else time.sleep)(mantener_ms / 1000)
        finally:
            _enviar([arriba])

    def posicion_cursor():
        p = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y

    def tecla_abajo(vk):
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    try:
        ctypes.WinDLL("winmm").timeBeginPeriod(1)
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
else:
    def hacer_clic(*_a, **_k):
        raise RuntimeError("Los clics solo funcionan en Windows")

    def _mover_absoluto(_x, _y):
        pass

    presionar_tecla = hacer_clic

    def posicion_cursor():
        return 0, 0

    def tecla_abajo(_vk):
        return False


class Motor:
    def __init__(self):
        self._parar = threading.Event()
        self.activo, self.contador = False, 0
        self.inicio = self.fin = 0.0
        self.error, self.completado = None, False
        self.ultimo = time.monotonic()
        self.intervalo = 0.1

    def iniciar(self, accion, intervalo, repeticiones=0):
        if self.activo:
            return
        self._parar.clear()
        self.contador, self.error, self.completado = 0, None, False
        self.inicio, self.fin, self.activo = time.time(), 0.0, True
        self.ultimo, self.intervalo = time.monotonic(), intervalo
        threading.Thread(target=self._loop, args=(accion, intervalo, repeticiones), daemon=True).start()

    def detener(self, motivo=None):
        if motivo and self.activo and not self.error:
            self.error = motivo
        self._parar.set()

    def _loop(self, accion, intervalo, rep):
        parar = self._parar
        intervalo = max(0.001, intervalo)
        try:
            prox = time.perf_counter()
            while not parar.is_set():
                accion(parar)
                self.ultimo = time.monotonic()
                self.contador += 1
                if rep and self.contador >= rep:
                    self.completado = True
                    break
                prox += intervalo
                resto = prox - time.perf_counter()
                if resto < -0.25:
                    prox = time.perf_counter()
                elif resto > 0:

                    if resto > 0.002 and parar.wait(resto - 0.0015):
                        break
                    while not parar.is_set() and time.perf_counter() < prox:
                        time.sleep(0)
                self.ultimo = time.monotonic()
        except Exception as e:
            self.error = str(e)
        finally:
            self.fin, self.activo = time.time(), False


class VigilanteAtajos(threading.Thread):

    def __init__(self, cola, motores):
        super().__init__(daemon=True)
        self.cola, self.motores = cola, motores
        self.atajos, self.habilitado, self._prev = {}, False, {}
        self.esquina = True
        self.vigia = True
        self.latido_ui = time.monotonic()
        self._esquina_antes = False
        self._ultima_revision = 0.0

    def detener_todo(self, motivo):
        hubo = False
        for m in self.motores.values():
            if m.activo:
                hubo = True
                m.detener(motivo)
        return hubo

    def _revisar_proteccion(self):
        ahora = time.monotonic()
        activos = [m for m in self.motores.values() if m.activo]

        if self.esquina:
            x, y = posicion_cursor()
            vx = user32.GetSystemMetrics(76) if ES_WINDOWS else 0
            vy = user32.GetSystemMetrics(77) if ES_WINDOWS else 0
            en_esquina = x <= vx + 2 and y <= vy + 2
            if en_esquina and not self._esquina_antes and activos:
                self.detener_todo("Parada de emergencia: mouse en la esquina")
                self.cola.put("proteccion")
            self._esquina_antes = en_esquina
        if not self.vigia or not activos or ahora - self._ultima_revision < 0.5:
            return
        self._ultima_revision = ahora

        if ahora - self.latido_ui > 8.0:
            self.detener_todo("La ventana dejó de responder; se detuvo todo por seguridad")
            return

        for m in activos:
            limite = max(5.0, m.intervalo * 2 + 3.0)
            if ahora - m.ultimo > limite:
                m.detener("Una acción se trabó; se detuvo por seguridad")
                self.cola.put("proteccion")

    def run(self):
        while True:
            try:
                if self.habilitado:
                    for nombre, vk in list(self.atajos.items()):
                        ab = tecla_abajo(vk)
                        if ab and not self._prev.get(nombre):
                            if nombre == "stop":

                                self.detener_todo(None)
                            self.cola.put(nombre)
                        self._prev[nombre] = ab
                else:
                    self._prev.clear()
                self._revisar_proteccion()
            except Exception:
                pass
            time.sleep(0.02)


import tkinter as tk
import tkinter.font as tkfont

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageTk
except ImportError:
    Image = None

TEMAS = {
    "oscuro": {"BG": "#0b0d14", "PANEL": "#131722", "PANEL2": "#1b2030", "BORDE": "#283049",
               "TEXTO": "#eef0f8", "SUB": "#8c95b0", "ACENTO": "#7c5cff", "ACENTO2": "#00d4ff",
               "OK": "#2ee59d", "ERROR": "#ff4d6d", "AVISO": "#ffb84d", "ORO": "#ffc857",
               "SOMBRA": "#07080d", "SOBRE": "#ffffff", "oscuro": True},
    "claro": {"BG": "#e9edf6", "PANEL": "#ffffff", "PANEL2": "#eff3fb", "BORDE": "#d4dcec",
              "TEXTO": "#172036", "SUB": "#5e6a86", "ACENTO": "#6b4dff", "ACENTO2": "#0b93c2",
              "OK": "#10a267", "ERROR": "#df2f55", "AVISO": "#c17f10", "ORO": "#b2851c",
              "SOMBRA": "#c6cdda", "SOBRE": "#ffffff", "oscuro": False},
}
TEMA = "oscuro"
ES_OSCURO = True
BG = PANEL = PANEL2 = BORDE = TEXTO = SUB = ACENTO = ACENTO2 = OK = ERROR = AVISO = ORO = SOMBRA = SOBRE = "#000000"


def aplicar_tema(nombre):
    global TEMA, ES_OSCURO, BG, PANEL, PANEL2, BORDE, TEXTO, SUB
    global ACENTO, ACENTO2, OK, ERROR, AVISO, ORO, SOMBRA, SOBRE
    TEMA = nombre if nombre in TEMAS else "oscuro"
    t = TEMAS[TEMA]
    BG, PANEL, PANEL2, BORDE = t["BG"], t["PANEL"], t["PANEL2"], t["BORDE"]
    TEXTO, SUB, ACENTO, ACENTO2 = t["TEXTO"], t["SUB"], t["ACENTO"], t["ACENTO2"]
    OK, ERROR, AVISO, ORO = t["OK"], t["ERROR"], t["AVISO"], t["ORO"]
    SOMBRA, SOBRE, ES_OSCURO = t["SOMBRA"], t["SOBRE"], t["oscuro"]
    try:
        _CACHE.clear()
    except NameError:
        pass


aplicar_tema("oscuro")
FUENTE = "Segoe UI" if ES_WINDOWS else "Helvetica"
MONO = "Consolas" if ES_WINDOWS else "Courier"
ESCALA = 1.0
SS = 3


IDIOMA = "es"
_EN = {
    "Iniciar sesión": "Log in", "Crear cuenta": "Sign up", "Usuario": "Username",
    "Contraseña": "Password", "Repite la contraseña": "Repeat password",
    "Inventa un usuario y contraseña. No uses datos reales.": "Make up a username and password. Don't use real details.",
    "Mantener la sesión iniciada": "Keep me signed in", "Entrar": "Enter", "Conectando…": "Connecting…",
    "● Servidor en línea": "● Server online", "● Sin conexión con el servidor · reintentando…": "● No connection · retrying…",
    "● Conectando con el servidor…": "● Connecting to the server…",
    "Escribe tu usuario y contraseña": "Enter your username and password",
    "Usuario: 3 a 20 caracteres (letras, números, _ . -)": "Username: 3 to 20 characters (letters, numbers, _ . -)",
    "La contraseña debe tener al menos 6 caracteres": "The password must be at least 6 characters",
    "Las contraseñas no coinciden": "The passwords don't match",
    "Activa tu licencia": "Activate your license", "Licencia": "License", "Activar licencia": "Activate license",
    "← Cerrar sesión": "← Log out", "La licencia está incompleta": "The license is incomplete",
    "Verificando…": "Checking…", "Tu licencia venció. Activa una nueva para seguir.": "Your license expired. Activate a new one to continue.",
    "Mouse": "Mouse", "Teclado": "Keyboard", "Licencias": "Licenses", "Usuarios": "Users", "Cuenta": "Account",
    "Clics automáticos a la velocidad que elijas.": "Automatic clicks at the speed you choose.",
    "Repite una tecla una y otra vez.": "Repeat a key over and over.",
    "Crea licencias y revisa quién las usó.": "Create licenses and see who used them.",
    "Quién tiene el programa, su licencia y sus permisos.": "Who has the program, their license and permissions.",
    "Tu información, licencia y ajustes.": "Your information, license and settings.",
    "Intervalo": "Interval", "milisegundos": "milliseconds", "Botón": "Button", "Izquierdo": "Left",
    "Derecho": "Right", "Medio": "Middle", "Clic": "Click", "Simple": "Single", "Doble": "Double",
    "Posición": "Position", "Cursor": "Cursor", "Punto fijo": "Fixed point", "Elegir punto": "Pick point",
    "Repetir": "Repeat", "Siempre": "Always", "Veces": "Times", "Modo juego": "Game mode",
    "Roblox y otros juegos": "Roblox and other games",
    "Clics que los juegos sí detectan.\nApágalo solo si quieres la máxima velocidad.":
        "Clicks that games actually detect.\nTurn it off only if you want maximum speed.",
    "Mantiene la tecla 40 ms para que el juego la note.\nApágalo para la máxima velocidad.":
        "Holds the key 40 ms so the game notices it.\nTurn it off for maximum speed.",
    "Tecla": "Key", "la que se repite": "the one that repeats", "Cambiar tecla": "Change key",
    "clics": "clicks", "pulsaciones": "presses", "Tiempo": "Time", "Por seg.": "Per sec.",
    "CREAR LICENCIAS": "CREATE LICENSES", "Tipo": "Type", "Admin": "Admin",
    "Duración (empieza al activarla)": "Duration (starts when activated)", "Licencia de ADMIN": "ADMIN license",
    "Quien la active se convierte en cuenta\nde administrador (permanente).\n\nPodrá crear licencias de usuario,\nver usuarios y banear.":
        "Whoever activates it becomes an\nadministrator account (permanent).\n\nThey can create user licenses,\nsee users and ban.",
    "Cantidad": "Amount", "Nota (opcional)": "Note (optional)", "Generar licencias": "Generate licenses",
    "Se copian solas al portapapeles.": "They're copied to the clipboard automatically.",
    "LICENCIAS CREADAS": "CREATED LICENSES", "Todas": "All", "Libres": "Free", "Usadas": "Used",
    "No hay licencias todavía.": "No licenses yet.", "Admin permanente": "Permanent admin", "Copiar": "Copy",
    "Generando…": "Generating…", "Licencia borrada": "License deleted",
    "Buscar": "Search", "Todos": "All", "Con licencia": "With license", "Admins": "Admins", "Baneados": "Banned",
    "Sin resultados.": "No results.", "Banear": "Ban", "Desbanear": "Unban", "BANEADO": "BANNED",
    "Acceso total": "Full access", "Elige un usuario de la lista\npara ver sus opciones.":
        "Pick a user from the list\nto see their options.",
    "Vence": "Expires", "Licencias usadas": "Licenses used", "Última licencia": "Last license",
    "Creada": "Created", "Última vez": "Last seen",
    "No tienes permiso para modificar\nesta cuenta.": "You can't modify\nthis account.",
    "DAR TIEMPO": "GIVE TIME", "Agregar tiempo": "Add time", "Quitar licencia": "Remove license",
    "Hacer admin": "Make admin", "Quitar admin": "Remove admin", "Eliminar cuenta": "Delete account",
    "ATAJOS DE TECLADO": "KEYBOARD SHORTCUTS", "Detener todo": "Stop everything",
    "AL INICIAR CON EL BOTÓN": "WHEN STARTING WITH THE BUTTON",
    "Espera para que muevas el mouse.": "Delay so you can move the mouse.",
    "Ventana siempre encima": "Window always on top", "PROTECCIÓN": "PROTECTION",
    "Esquina de emergencia": "Emergency corner",
    "Mouse a la esquina superior izquierda = parar": "Mouse to the top-left corner = stop",
    "Parar si algo se traba": "Stop if something freezes",
    "Detiene todo si un clic o la ventana se congela": "Stops everything if a click or the window freezes",
    "Cerrar sesión": "Log out", "Tu ID": "Your ID", "AGREGAR OTRA LICENCIA": "ADD ANOTHER LICENSE",
    "El tiempo se suma al que ya tienes.": "The time adds to what you already have.", "Canjear": "Redeem",
    "CAMBIAR CONTRASEÑA": "CHANGE PASSWORD", "Actual": "Current", "Cambiar": "Change",
    "Nueva (mínimo 6 caracteres)": "New (at least 6 characters)", "De por vida": "Lifetime",
    "Detenido": "Stopped", "Activo": "Active", "OWNER": "OWNER", "ADMIN": "ADMIN", "USUARIO": "USER",
    "Nueva versión disponible": "New version available", "Actualizar ahora": "Update now",
    "Más tarde": "Later", "Descargando…": "Downloading…", "Reiniciando…": "Restarting…", "Reintentar": "Retry",
    "APARIENCIA": "APPEARANCE", "Tema": "Theme", "Oscuro": "Dark", "Claro": "Light", "Idioma": "Language",
    "Sonido al iniciar y detener": "Sound on start and stop", "Español": "Spanish", "Inglés": "English",
    "INICIAR": "START", "DETENER": "STOP", "CANCELAR": "CANCEL",
    "Falta la librería Pillow.\nAbre CMD y ejecuta:  pip install pillow":
        "Pillow is missing.\nOpen CMD and run:  pip install pillow",
    "Pon el mouse donde quieres el clic…": "Put the mouse where you want the click…",
    "Esa tecla no se puede usar": "That key can't be used", "¿Borrar?": "Delete?", "¿Seguro?": "Sure?",
    "Esa tecla ya se usa en otro atajo": "That key is already used by another shortcut",
    "Presiona una tecla…": "Press a key…", "Presiona…": "Press…",
    "Tu licencia no está activa": "Your license is not active",
    "Los clics solo funcionan en Windows": "Clicks only work on Windows", "Todo detenido": "Everything stopped",
    "Cuenta creada. ¡Bienvenido!": "Account created. Welcome!", "ID copiado": "ID copied",
    "Licencia copiada": "License copied", "Escribe tu contraseña actual": "Enter your current password",
    "La nueva debe tener al menos 6 caracteres": "The new one must be at least 6 characters",
    "Ahora eres administrador": "You're an administrator now",
    "Contraseña cambiada. Se cerró la sesión en tus otras PCs.": "Password changed. Your other PCs were signed out.",
    "Autoclicker de mouse y teclado · v{v}": "Mouse and keyboard autoclicker · v{v}",
    "Hola {n}, pega la licencia que te dieron.\nCada licencia se puede usar una sola vez.":
        "Hi {n}, paste the license you were given.\nEach license can be used only once.",
    "Tu ID: {id}": "Your ID: {id}", "Atajo:  {k}": "Shortcut:  {k}",
    "Emergencia: {k}": "Emergency: {k}", "o mouse a la esquina ↖": "or mouse to the corner ↖",
    "Listo: {n} {u}": "Done: {n} {u}", "Hola, {n}": "Hi, {n}",
    "Se agregó {d}": "Added {d}", "Punto guardado: {x}, {y}": "Point saved: {x}, {y}",
    "Elige en {n}…": "Pick in {n}…", "{k} es un atajo. Elige otra.": "{k} is a shortcut. Pick another.",
    "Atajo cambiado a {k}": "Shortcut changed to {k}", "{n} cuenta · {c} con acceso": "{n} account · {c} with access",
    "{n} cuentas · {c} con acceso": "{n} accounts · {c} with access",
    "Mostrando {m} de {n} · usa el buscador": "Showing {m} of {n} · use the search box",
    "{n} baneado": "{n} banned", "{n} desbaneado": "{n} unbanned", "Usuario baneado": "User banned",
    "Usuario desbaneado": "User unbanned", "Licencia quitada": "License removed",
    "Ya no es admin": "No longer admin", "Ahora es admin": "Now admin", "Cuenta eliminada": "Account deleted",
    "Se agregó {d}": "Added {d}", "{n} licencia(s) de {d} copiadas": "{n} license(s) of {d} copied",
    "Licencia activada: {d}": "License activated: {d}",
    "Acceso total ({r})": "Full access ({r})", "{r} restantes · vence {f}": "{r} left · expires {f}",
    "No se pudo conectar con el servidor": "Couldn't connect to the server",
    "Error del servidor ({c})": "Server error ({c})", "Tu cuenta está suspendida": "Your account is suspended",
    "Sesión expirada. Inicia sesión de nuevo.": "Session expired. Log in again.",
    "Usuario o contraseña incorrectos": "Wrong username or password", "Ese usuario ya existe": "That username already exists",
    "Esta licencia ya fue usada": "This license was already used", "Licencia inválida": "Invalid license",
    "Demasiados intentos. Espera unos minutos.": "Too many attempts. Wait a few minutes.",
    "1 día": "1 day", "2 días": "2 days", "1 semana": "1 week", "1 mes": "1 month", "3 meses": "3 months",
    "6 meses": "6 months", "1 año": "1 year", "2 años": "2 years", "Por vida": "Lifetime",
    "10 ms": "10 ms", "100 ms": "100 ms", "1 seg": "1 sec", "↻": "↻",
}
_UNIDADES_EN = {"Horas": "Hours", "Días": "Days", "Semanas": "Weeks", "Meses": "Months", "Años": "Years",
                "Sem.": "Wk."}


def tr(s, **kw):
    s = str(s)
    base = (_EN.get(s) or _UNIDADES_EN.get(s) or s) if IDIOMA == "en" else s
    try:
        return base.format(**kw) if kw else base
    except (KeyError, IndexError, ValueError):
        return base


def px(v):
    return int(round(v * ESCALA))


def F(tam, peso="normal"):
    return (FUENTE, tam, peso)


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def mezclar(a, b, t):
    t = round(max(0.0, min(1.0, t)) * 16) / 16
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(int(ra[i] + (rb[i] - ra[i]) * t) for i in range(3))


def ease_out(t):
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_back(t):
    c = 1.70158
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def lineal(t):
    return t


def rebote(s0, t):
    return 1 - (1 - s0) * math.cos(3 * math.pi * t) * (1 - t) ** 2


_FUENTES = {}


def medir(texto, tam, peso="normal"):
    f = _FUENTES.get((tam, peso))
    if f is None:
        f = _FUENTES[(tam, peso)] = tkfont.Font(family=FUENTE, size=tam, weight=peso)
    return f.measure(texto)


def minimizada(w):
    try:
        return w.winfo_toplevel().state() == "iconic"
    except tk.TclError:
        return False


_CACHE = OrderedDict()


def _foto(clave, crear):
    ph = _CACHE.get(clave)
    if ph is None:
        ph = ImageTk.PhotoImage(crear())
        _CACHE[clave] = ph
        if len(_CACHE) > 900:
            _CACHE.popitem(last=False)
    else:
        _CACHE.move_to_end(clave)
    return ph


def img_rr(w, h, r, fill=None, outline=None, ow=1):
    w, h, r = max(2, int(w)), max(2, int(h)), int(r)

    def crear():
        im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
        rad = max(0, min(r, w // 2, h // 2)) * SS
        ImageDraw.Draw(im).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=rad, fill=fill,
                                             outline=outline, width=max(1, ow * SS) if outline else 0)
        return im.resize((w, h), Image.LANCZOS)
    return _foto(("rr", w, h, r, fill, outline, ow), crear)


def img_oval(d, fill=None, outline=None, ow=1):
    d = max(2, int(d))

    def crear():
        im = Image.new("RGBA", (d * SS, d * SS), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((0, 0, d * SS - 1, d * SS - 1), fill=fill, outline=outline,
                                   width=max(1, ow * SS) if outline else 0)
        return im.resize((d, d), Image.LANCZOS)
    return _foto(("ov", d, fill, outline, ow), crear)


def img_esquinas(r, fill, outline):
    clave = ("esq", r, fill, outline)
    if clave not in _CACHE:
        Z = 2 * r + 2
        im = Image.new("RGBA", (Z * SS, Z * SS), (0, 0, 0, 0))
        ImageDraw.Draw(im).rounded_rectangle((0, 0, Z * SS - 1, Z * SS - 1), radius=r * SS, fill=fill,
                                             outline=outline, width=SS)
        im = im.resize((Z, Z), Image.LANCZOS)
        _CACHE[clave] = tuple(ImageTk.PhotoImage(im.crop(b)) for b in
                              ((0, 0, r, r), (Z - r, 0, Z, r), (0, Z - r, r, Z), (Z - r, Z - r, Z, Z)))
    return _CACHE[clave]


def img_ojo(w, h, color, tachado):
    def crear():
        W, H, L = w * SS, h * SS, max(2, int(1.6 * SS))
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((L, H * 0.18, W - L, H * 0.82), outline=color, width=L)
        r = H * 0.2
        d.ellipse((W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r), fill=color)
        if tachado:
            d.line((W * 0.15, H * 0.05, W * 0.85, H * 0.95), fill=PANEL2, width=L * 3)
            d.line((W * 0.15, H * 0.05, W * 0.85, H * 0.95), fill=color, width=L)
        return im.resize((w, h), Image.LANCZOS)
    return _foto(("ojo", w, h, color, tachado), crear)


def img_glow(r, color):
    def crear():

        k = 4
        rr = r / k
        sigma = rr * 0.6
        s = int(2 * (rr + 3 * sigma)) + 2
        im = Image.new("RGBA", (s, s), _rgb(color) + (0,))
        ImageDraw.Draw(im).ellipse((s / 2 - rr, s / 2 - rr, s / 2 + rr, s / 2 + rr), fill=_rgb(color) + (70,))
        return im.filter(ImageFilter.GaussianBlur(sigma)).resize((s * k, s * k), Image.BICUBIC)
    return _foto(("glow", int(r), color), crear)


def img_logo(S, t):
    t = round(t * 20) / 20

    def crear():
        Z = S * SS
        g = Image.linear_gradient("L").rotate(45 + 90 * t).resize((Z, Z))
        a = Image.new("RGB", (Z, Z), ACENTO)
        b = Image.new("RGB", (Z, Z), ACENTO2)
        im = Image.composite(b, a, g).convert("RGBA")
        m = Image.new("L", (Z, Z), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, Z - 1, Z - 1), radius=int(Z * 0.28), fill=255)
        im.putalpha(m)
        return im.resize((S, S), Image.LANCZOS)
    return _foto(("logo", S, t), crear)


def img_logo_personal(S, version):
    def crear():
        Z = S * SS
        im = ImageOps.fit(LOGO["pil"], (Z, Z), Image.LANCZOS, centering=(0.5, 0.5))
        m = Image.new("L", (Z, Z), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, Z - 1, Z - 1), radius=int(Z * 0.28), fill=255)
        im.putalpha(m)
        return im.resize((S, S), Image.LANCZOS)
    return _foto(("logop", S, version), crear)


def img_power(S, color="#ffffff"):
    def crear():
        Z, lw = S * SS, max(3, int(S * SS * 0.11))
        im = Image.new("RGBA", (Z, Z), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        p = lw
        d.arc((p, p + lw * 0.6, Z - p, Z - p + lw * 0.6), start=-55, end=235, fill=color, width=lw)
        d.line((Z / 2, lw * 0.2, Z / 2, Z / 2), fill=color, width=lw)
        for y in (lw * 0.2, Z / 2):
            d.ellipse((Z / 2 - lw / 2, y - lw / 2, Z / 2 + lw / 2, y + lw / 2), fill=color)
        return im.resize((S, S), Image.LANCZOS)
    return _foto(("pow", S, color), crear)


def img_arco(w, h, color, lw):
    def crear():
        W, H, L = w * SS, h * SS, lw * SS
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.arc((L / 2, L / 2, W - L / 2, W - L / 2), start=180, end=360, fill=color, width=L)
        d.rectangle((L / 2 - L / 2, W / 2, L / 2 + L / 2, H), fill=color)
        d.rectangle((W - L, W / 2, W, H), fill=color)
        return im.resize((w, h), Image.LANCZOS)
    return _foto(("arco", w, h, color, lw), crear)


class Anim:
    def __init__(self, w):
        self.w, self.jobs = w, {}

    def run(self, clave, dur, fn, done=None, ease=ease_out):
        self.cancel(clave)
        t0 = time.perf_counter()

        def tick():
            try:
                t = min(1.0, (time.perf_counter() - t0) * 1000.0 / max(1, dur))
                fn(ease(t))
                if t < 1:
                    self.jobs[clave] = self.w.after(15, tick)
                else:
                    self.jobs.pop(clave, None)
                    if done:
                        done()
            except tk.TclError:
                self.jobs.pop(clave, None)
        tick()

    def cancel(self, clave):
        j = self.jobs.pop(clave, None)
        if j:
            try:
                self.w.after_cancel(j)
            except Exception:
                pass


class Lienzo(tk.Canvas):

    def __init__(self, master, w, h, bg=None, **kw):
        self.pbg = bg or master.cget("bg")
        super().__init__(master, width=w, height=h, bg=self.pbg, highlightthickness=0, bd=0, **kw)
        self.refs = []
        self.anim = Anim(self)

    def limpiar(self):
        self.delete("all")
        self.refs = []

    def img(self, x, y, foto, anchor="nw", **kw):
        self.refs.append(foto)
        return self.create_image(x, y, image=foto, anchor=anchor, **kw)

    def animar(self, attr, dest, dur, ease=ease_out):
        ini = getattr(self, attr)

        def fn(t):
            setattr(self, attr, ini + (dest - ini) * t)
            self.dibujar()
        self.anim.run(attr, dur, fn, ease=ease)

    def dibujar(self):
        pass


class Boton(Lienzo):

    def __init__(self, master, texto, command=None, ancho=150, alto=40, estilo="primario",
                 fuente=None, bg=None, color=None):
        self.bw, self.bh, self.m = px(ancho), px(alto), px(4)
        super().__init__(master, self.bw + 2 * self.m, self.bh + 2 * self.m, bg=bg, cursor="hand2")
        self.texto, self.command, self.estilo = texto, command, estilo
        self.color = color or (ACENTO if estilo == "primario" else PANEL2)
        self.fuente = fuente or F(10, "bold")
        self.ht, self.escala, self.flash = 0.0, 1.0, 0.0
        self.habilitado, self._pres = True, False
        self.bind("<Enter>", lambda e: self.animar("ht", 1, 160))
        self.bind("<Leave>", self._salir)
        self.bind("<ButtonPress-1>", self._presionar)
        self.bind("<ButtonRelease-1>", self._soltar)
        self.dibujar()

    def dibujar(self):
        self.limpiar()
        s = round(self.escala, 2)
        w, h = self.bw * s, self.bh * s
        lift = px(2) * self.ht
        x, y = self.m + (self.bw - w) / 2, self.m + (self.bh - h) / 2 - lift
        r = px(10)
        if not self.habilitado:
            fill, fg, out = mezclar(self.color, self.pbg, 0.55), mezclar(TEXTO, self.pbg, 0.5), None
        else:
            if self.estilo == "primario":
                fill = mezclar(mezclar(self.color, "#ffffff", 0.14 * self.ht), "#ffffff", 0.3 * self.flash)
                out = None
                fg = SOBRE
            else:
                fill = mezclar(mezclar(self.color, BORDE, 0.6 * self.ht), "#ffffff", 0.15 * self.flash)
                out = mezclar(BORDE, ACENTO, self.ht)
                fg = TEXTO
            if self.ht > 0.05:
                sombra = _rgb(SOMBRA) + (int((70 if ES_OSCURO else 120) * self.ht),)
                self.img(x + px(2), y + px(4) + lift, img_rr(w - px(4), h, r, fill=sombra))
        self.img(x, y, img_rr(w, h, r, fill=fill, outline=out, ow=1))
        self.create_text(x + w / 2, y + h / 2, text=tr(self.texto), fill=fg, font=self.fuente)

    def _salir(self, _e):
        self.animar("ht", 0, 220)
        if self._pres:
            self._pres = False
            self.animar("escala", 1, 150)

    def _presionar(self, _e):
        if self.habilitado:
            self._pres = True
            self.animar("escala", 0.93, 90)

    def _soltar(self, e):
        if not self._pres:
            return
        self._pres = False
        s0 = self.escala

        def fn(t):
            self.escala, self.flash = rebote(s0, t), 1 - t
            self.dibujar()
        self.anim.run("escala", 380, fn, ease=lineal)
        if 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height() and self.command:
            self.after(1, self.command)

    def set_texto(self, t):
        self.texto = t
        self.dibujar()

    def set_color(self, c):
        self.color = c
        self.dibujar()

    def set_habilitado(self, b):
        self.habilitado = b
        self.config(cursor="hand2" if b else "arrow")
        self.dibujar()


class Interruptor(Lienzo):
    def __init__(self, master, valor=False, command=None, bg=None):
        self.W, self.H = px(46), px(26)
        super().__init__(master, self.W, self.H, bg=bg, cursor="hand2")
        self.valor, self.command, self.t = bool(valor), command, 1.0 if valor else 0.0
        self.bind("<Button-1>", lambda e: self.set(not self.valor, True))
        self.dibujar()

    def dibujar(self):
        self.limpiar()
        self.img(0, 0, img_rr(self.W, self.H, self.H // 2, fill=mezclar(BORDE, ACENTO, self.t)))
        k = self.H - px(8)
        self.img(px(4) + (self.W - px(8) - k) * self.t, px(4), img_oval(k, fill="#ffffff"))

    def set(self, v, notificar=False):
        self.valor = bool(v)
        ini, fin = self.t, 1.0 if self.valor else 0.0

        def fn(t):
            self.t = ini + (fin - ini) * t
            self.dibujar()
        self.anim.run("t", 280, fn, ease=ease_back)
        if notificar and self.command:
            self.command(self.valor)

    def get(self):
        return self.valor


class Segmentado(Lienzo):

    def __init__(self, master, opciones, indice=0, command=None, ancho=None, alto=34, bg=None):
        self.ops = list(opciones)
        self.W, self.H = px(ancho or 84 * len(self.ops)), px(alto)
        super().__init__(master, self.W, self.H, bg=bg, cursor="hand2")
        self.idx, self.command, self.pos, self.hover = indice, command, float(indice), -1
        self.bind("<Button-1>", lambda e: self.set(self._i(e.x), True))
        self.bind("<Motion>", lambda e: self._hov(self._i(e.x)))
        self.bind("<Leave>", lambda e: self._hov(-1))
        self.dibujar()

    def _i(self, x):
        return max(0, min(len(self.ops) - 1, int(x // (self.W / len(self.ops)))))

    def _hov(self, i):
        if i != self.hover:
            self.hover = i
            self.dibujar()

    def dibujar(self):
        self.limpiar()
        seg = self.W / len(self.ops)
        self.img(0, 0, img_rr(self.W, self.H, px(10), fill=PANEL2, outline=BORDE))
        self.img(self.pos * seg + px(3), px(3), img_rr(seg - px(6), self.H - px(6), px(8), fill=ACENTO))
        for i, o in enumerate(self.ops):
            cerca = max(0.0, 1 - abs(self.pos - i))
            col = mezclar(SUB, "#ffffff", max(cerca, 0.55 if i == self.hover else 0))
            self.create_text(seg * i + seg / 2, self.H / 2, text=tr(o), fill=col, font=F(9, "bold"))

    def set(self, i, notificar=False):
        cambio = i != self.idx
        self.idx, ini = i, self.pos

        def fn(t):
            self.pos = ini + (i - ini) * t
            self.dibujar()
        self.anim.run("pos", 320, fn, ease=ease_back)
        if notificar and cambio and self.command:
            self.command(i)

    def get(self):
        return self.idx


class Campo(Lienzo):

    def __init__(self, master, ancho=260, alto=40, show="", justify="left", fuente=None, bg=None, ojo=False):
        self.W, self.H = px(ancho), px(alto)
        super().__init__(master, self.W, self.H, bg=bg)
        self.ojo, self.oculto, self.ojo_h = ojo and bool(show), bool(show), 0.0
        self.var = tk.StringVar()
        self.e = tk.Entry(self, textvariable=self.var, bg=PANEL2, fg=TEXTO, insertbackground=ACENTO2,
                          relief="flat", bd=0, font=fuente or F(11), show=show, justify=justify,
                          disabledbackground=PANEL2, disabledforeground=mezclar(SUB, PANEL2, 0.3),
                          highlightthickness=0)
        extra = px(32) if self.ojo else 0
        self.create_window(px(12), self.H / 2, window=self.e, anchor="w", width=self.W - px(24) - extra)
        self.t, self.on = 0.0, True
        self.e.bind("<FocusIn>", lambda e: self.animar("t", 1, 200))
        self.e.bind("<FocusOut>", lambda e: self.animar("t", 0, 220))
        self.bind("<Button-1>", self._clic)
        if self.ojo:
            self.bind("<Motion>", lambda e: self._hov_ojo(e.x > self.W - px(38)))
            self.bind("<Leave>", lambda e: self._hov_ojo(False))
        self.dibujar()

    def _hov_ojo(self, dentro):
        self.config(cursor="hand2" if dentro else "xterm")
        if (self.ojo_h > 0.5) != dentro:
            self.ojo_h = 1.0 if dentro else 0.0
            self.dibujar()

    def _clic(self, e):
        if self.ojo and e.x > self.W - px(38):
            self.oculto = not self.oculto
            self.e.config(show="•" if self.oculto else "")
            self.dibujar()
        self.e.focus_set()

    def dibujar(self):
        for i in self.find_withtag("fondo"):
            self.delete(i)
        self.refs = []
        out = mezclar(BORDE, ACENTO, self.t) if self.on else mezclar(BORDE, PANEL2, 0.5)
        self.img(0, 0, img_rr(self.W, self.H, px(10), fill=PANEL2, outline=out, ow=1), tags="fondo")
        if self.ojo:
            col = mezclar(SUB, TEXTO, self.ojo_h) if self.oculto else ACENTO2
            self.img(self.W - px(16), self.H / 2, img_ojo(px(22), px(15), col, self.oculto), anchor="e", tags="fondo")
        self.tag_lower("fondo")

    def get(self):
        return self.var.get()

    def set(self, v):
        self.var.set(str(v))

    def al_enter(self, cb):
        self.e.bind("<Return>", lambda e: cb())

    def habilitar(self, b):
        self.on = b
        self.e.config(state="normal" if b else "disabled")
        self.dibujar()


class Tarjeta(tk.Frame):

    def __init__(self, master, pad=20, color=PANEL, borde=BORDE):
        super().__init__(master, bg=master.cget("bg"))
        self.color, self.borde = color, borde
        self.fondo = Lienzo(self, 10, 10, bg=master.cget("bg"))
        self.fondo.place(x=0, y=0, relwidth=1, relheight=1)
        self.cuerpo = tk.Frame(self, bg=color)
        self.cuerpo.pack(fill="both", expand=True, padx=px(pad), pady=px(pad))
        self._tam = None
        self.bind("<Configure>", self._redibujar)

    def _redibujar(self, e):
        if (e.width, e.height) == self._tam:
            return
        self._tam = (e.width, e.height)
        f = self.fondo
        f.limpiar()
        w, h, r = e.width, e.height, px(14)
        if w <= 2 * r or h <= 2 * r:
            return
        tl, tr, bl, br = img_esquinas(r, self.color, self.borde)
        f.img(0, 0, tl)
        f.img(w - r, 0, tr)
        f.img(0, h - r, bl)
        f.img(w - r, h - r, br)
        f.create_rectangle(r, 0, w - r, h, fill=self.color, outline="")
        f.create_rectangle(0, r, w, h - r, fill=self.color, outline="")
        f.create_line(r, 0, w - r, 0, fill=self.borde)
        f.create_line(r, h - 1, w - r, h - 1, fill=self.borde)
        f.create_line(0, r, 0, h - r, fill=self.borde)
        f.create_line(w - 1, r, w - 1, h - r, fill=self.borde)


class TarjetaFlotante:

    def __init__(self, fondo, pad=30, radio=16):
        self.fondo, self.pad, self.r = fondo, px(pad), px(radio)
        self.cuerpo = tk.Frame(fondo.master, bg=PANEL)
        self._item, self._tam, self._foto = None, None, None
        self.cuerpo.bind("<Configure>", self._ajustar)

    def place(self, **kw):
        self.cuerpo.place(**kw)

    def place_configure(self, **kw):
        self.cuerpo.place_configure(**kw)

    def _ajustar(self, e):
        x, y = e.x - self.pad, e.y - self.pad
        tam = (e.width + 2 * self.pad, e.height + 2 * self.pad)
        if tam != self._tam:
            self._tam = tam
            self._foto = img_rr(tam[0], tam[1], self.r, fill=PANEL, outline=BORDE)
            if self._item is None:
                self._item = self.fondo.create_image(x, y, image=self._foto, anchor="nw", tags="tarjeta")
            else:
                self.fondo.itemconfigure(self._item, image=self._foto)
        self.fondo.coords(self._item, x, y)
        self.fondo.tag_raise("tarjeta")


class Toast:
    def __init__(self, root):
        self.root, self.c, self.anim = root, None, Anim(root)

    def mostrar(self, msg, tipo="info", ms=2600):
        msg = tr(msg)
        col = {"ok": OK, "error": ERROR, "aviso": AVISO}.get(tipo, ACENTO2)
        ico = {"ok": "✔", "error": "✖", "aviso": "⚠"}.get(tipo, "ℹ")
        if self.c is not None:
            try:
                self.c.destroy()
            except Exception:
                pass
        msg = msg if len(msg) <= 110 else msg[:107] + "…"
        W, H = min(medir(msg, 10) + px(70), max(px(300), self.root.winfo_width() - px(40))), px(44)
        c = Lienzo(self.root, W, H, bg=BG)
        c.img(0, 0, img_rr(W, H, px(12), fill=PANEL2, outline=col, ow=1))
        c.create_text(px(22), H / 2, text=ico, fill=col, font=F(12, "bold"))
        c.create_text(px(42), H / 2, text=msg, fill=TEXTO, font=F(10), anchor="w")
        c.place(relx=0.5, y=-px(60), anchor="n")
        tk.Misc.tkraise(c)
        self.c = c

        def irse():
            self.anim.run("toast", 260, lambda t: c.place_configure(y=int(px(18) - px(90) * t)),
                          done=c.destroy, ease=ease_in_out)
        self.anim.run("toast", 380, lambda t: c.place_configure(y=int(-px(60) + px(78) * t)), ease=ease_back,
                      done=lambda: self.root.after(ms, lambda: c.winfo_exists() and irse()))

    def arriba(self):
        try:
            if self.c is not None:
                tk.Misc.tkraise(self.c)
        except tk.TclError:
            pass


class FondoAnimado(Lienzo):

    def __init__(self, master):
        super().__init__(master, 10, 10, bg=BG)
        cols = [ACENTO, ACENTO2, "#ff4fd8", ACENTO, ACENTO2]
        self.orbes = [{"x": random.random(), "y": random.random(), "r": px(random.uniform(90, 170)),
                       "vx": random.uniform(-.001, .001), "vy": random.uniform(-.001, .001),
                       "c": cols[i]} for i in range(5)]
        self.items = []
        self._loop()

    def _loop(self):
        try:
            if minimizada(self):
                self.after(400, self._loop)
                return
            w, h = max(1, self.winfo_width()), max(1, self.winfo_height())
            if not self.items:
                self.items = [self.img(0, 0, img_glow(o["r"], o["c"]), anchor="center") for o in self.orbes]
                self.tag_raise("tarjeta")
            for o, it in zip(self.orbes, self.items):
                o["x"] += o["vx"]
                o["y"] += o["vy"]
                if not -0.1 < o["x"] < 1.1:
                    o["vx"] *= -1
                if not -0.1 < o["y"] < 1.1:
                    o["vy"] *= -1
                self.coords(it, o["x"] * w, o["y"] * h)
            self.after(40, self._loop)
        except tk.TclError:
            pass


class Logo(Lienzo):
    def __init__(self, master, tam=44, bg=None):
        self.S = px(tam)
        super().__init__(master, self.S, self.S, bg=bg)
        self.f = random.uniform(0, 6)
        self._modo = None
        self._ver = -1
        self._loop()

    def _loop(self):
        try:
            if LOGO["pil"] is not None:
                if self._modo != "personal" or self._ver != LOGO["version"]:
                    self._modo, self._ver = "personal", LOGO["version"]
                    self.limpiar()
                    self._fondo = self.img(0, 0, img_logo_personal(self.S, LOGO["version"]))
            elif not minimizada(self):
                nuevo = self._modo != "al"
                if nuevo:
                    self._modo = "al"
                    self.limpiar()
                self.f += 0.05
                foto = img_logo(self.S, (math.sin(self.f) + 1) / 2)
                if nuevo:
                    self._fondo = self.img(0, 0, foto)
                    self.create_text(self.S / 2, self.S / 2, text="AL", fill="#ffffff",
                                     font=(FUENTE, max(8, int(self.S / ESCALA * 0.3)), "bold"))
                elif foto is not self.refs[0]:
                    self.refs[0] = foto
                    self.itemconfigure(self._fondo, image=foto)
            self.after(80, self._loop)
        except tk.TclError:
            pass


class BotonPower(Lienzo):
    def __init__(self, master, tam=150, command=None, bg=None):
        self.S = px(tam)
        self.C = self.S + px(46)
        super().__init__(master, self.C, self.C, bg=bg, cursor="hand2")
        self.command = command
        self.estado, self.cuenta = "off", 0
        self.t_on, self.ht, self.escala, self.fase = 0.0, 0.0, 1.0, 0.0
        self._jc = self._jp = None
        self.bind("<Enter>", lambda e: self.animar("ht", 1, 180))
        self.bind("<Leave>", lambda e: self.animar("ht", 0, 220))
        self.bind("<ButtonPress-1>", lambda e: self.animar("escala", 0.93, 90))
        self.bind("<ButtonRelease-1>", self._soltar)
        self.dibujar()

    def _rebotar(self):
        s0 = min(self.escala, 0.93)

        def fn(t):
            self.escala = rebote(s0, t)
            self.dibujar()
        self.anim.run("escala", 420, fn, ease=lineal)

    def _soltar(self, _e):
        self._rebotar()
        if self.command:
            self.after(1, self.command)

    def dibujar(self):
        self.limpiar()
        c = self.C / 2
        R = int(self.S / 2 * round(self.escala * (1 + 0.025 * self.ht), 2))
        color = AVISO if self.estado == "cuenta" else mezclar(ACENTO, OK, self.t_on)
        if self.estado == "on":
            for k in range(3):
                f = round(((self.fase + k / 3) % 1) * 12) / 12
                rr = int(R + px(4) + f * px(20))
                self.img(c, c, img_oval(rr * 2, outline=mezclar(color, self.pbg, 0.2 + 0.8 * f), ow=2), "center")
        self.img(c, c, img_oval((R + px(6)) * 2, outline=mezclar(self.pbg, color, 0.3 + 0.3 * self.ht), ow=2), "center")
        self.img(c, c, img_oval(R * 2, fill=mezclar(PANEL2, color, 0.14 + 0.2 * self.t_on + 0.08 * self.ht),
                                outline=color, ow=3), "center")
        if self.estado == "cuenta":
            self.create_text(c, c - R * 0.08, text=str(self.cuenta), fill="#ffffff", font=F(36, "bold"))
            txt = "CANCELAR"
        else:
            self.img(c, c - R * 0.12, img_power(int(R * 0.62)), "center")
            txt = "DETENER" if self.estado == "on" else "INICIAR"
        self.create_text(c, c + R * 0.5, text=txt, fill=mezclar(SUB, "#ffffff", 0.6 + 0.4 * self.ht),
                         font=F(9, "bold"))

    def _pulso(self):
        if self.estado != "on":
            self._jp = None
            return
        try:
            if not minimizada(self):
                self.fase = (self.fase + 0.025) % 1
                self.dibujar()
            self._jp = self.after(40, self._pulso)
        except tk.TclError:
            self._jp = None

    def set_on(self, on):
        self.cancelar_cuenta(False)
        self.estado = "on" if on else "off"
        self.animar("t_on", 1.0 if on else 0.0, 350)
        if on and not self._jp:
            self._pulso()

    def cuenta_regresiva(self, n, al_terminar):
        self.cancelar_cuenta(False)
        self.estado, self.cuenta = "cuenta", n

        def paso():
            if self.estado != "cuenta":
                return
            if self.cuenta <= 0:
                self._jc = None
                al_terminar()
                return
            self._rebotar()
            self._jc = self.after(1000, siguiente)

        def siguiente():
            self.cuenta -= 1
            paso()
        paso()

    def cancelar_cuenta(self, redibujar=True):
        if self._jc:
            try:
                self.after_cancel(self._jc)
            except Exception:
                pass
            self._jc = None
        if self.estado == "cuenta":
            self.estado = "off"
        if redibujar:
            self.dibujar()


class TeclaVisual(Lienzo):
    def __init__(self, master, texto="E", bg=None):
        self.W, self.H = px(120), px(52)
        super().__init__(master, self.W, self.H, bg=bg)
        self.texto, self.dy, self.brillo = texto, 0.0, 0.0
        self.dibujar()

    def dibujar(self):
        self.limpiar()
        W, H, d = self.W, self.H, px(5)
        self.img(0, d, img_rr(W, H - d, px(10), fill="#07080d"))
        self.img(0, self.dy, img_rr(W, H - d, px(10), fill=mezclar(PANEL2, ACENTO, 0.18 + 0.5 * self.brillo),
                                    outline=mezclar(BORDE, ACENTO2, self.brillo)))
        self.create_text(W / 2, (H - d) / 2 + self.dy, text=self.texto, fill="#ffffff",
                         font=F(15 if len(self.texto) <= 5 else 10, "bold"))

    def set(self, texto):
        self.texto = texto

        def fn(t):
            self.dy = px(4) * math.sin(math.pi * min(1, t * 2)) if t < 0.5 else 0
            self.brillo = 1 - t
            self.dibujar()
        self.anim.run("p", 600, fn, ease=lineal)


class Candado(Lienzo):
    def __init__(self, master, bg=None):
        self.S = px(70)
        super().__init__(master, self.S, self.S + px(10), bg=bg)
        self.abierto, self.t_ok, self.f = 0.0, 0.0, 0.0
        self._loop()

    def _loop(self):
        try:
            if not minimizada(self):
                self.f += 0.07
                self.dibujar()
            self.after(45, self._loop)
        except tk.TclError:
            pass

    def dibujar(self):
        self.limpiar()
        S = self.S
        col = mezclar(ACENTO, OK, self.t_ok)
        fl = math.sin(self.f) * px(2) * (1 - self.t_ok) + px(10)
        aw = int(S * 0.5)
        self.img((S - aw) / 2, S * 0.08 + fl - self.abierto * px(12), img_arco(aw, int(S * 0.5), col, max(3, px(6))))
        self.img(S * 0.16, S * 0.42 + fl, img_rr(S * 0.68, S * 0.5, px(10), fill=col))
        self.img(S / 2, S * 0.64 + fl, img_oval(px(11), fill=PANEL), "center")

    def abrir(self, done):
        def fn(t):
            self.abierto = self.t_ok = t
        self.anim.run("abrir", 650, fn, done=done, ease=ease_back)


class Insignia(Lienzo):

    def __init__(self, master, rol, bg=None):
        txt, col = {"owner": ("OWNER", ORO), "admin": ("ADMIN", ACENTO2)}.get(rol, ("USUARIO", SUB))
        txt = tr(txt)
        W, H = medir(txt, 7, "bold") + px(16), px(20)
        super().__init__(master, W, H, bg=bg)
        self.img(0, 0, img_rr(W, H, px(6), fill=mezclar(master.cget("bg"), col, 0.18), outline=col))
        self.create_text(W / 2, H / 2, text=txt, fill=col, font=F(7, "bold"))


class Avatar(Lienzo):
    def __init__(self, master, nombre, tam=36, bg=None):
        S = px(tam)
        super().__init__(master, S, S, bg=bg)
        h = int(hashlib.md5(nombre.lower().encode()).hexdigest()[:2], 16) / 255
        self.img(0, 0, img_oval(S, fill=mezclar(ACENTO, ACENTO2, h)))
        self.create_text(S / 2, S / 2, text=(nombre[:1] or "?").upper(), fill="#fff",
                         font=F(max(8, int(tam * 0.36)), "bold"))


class Navegacion(Lienzo):

    def __init__(self, master, items, command, ancho=176):
        self.items, self.command = items, command
        self.IH, self.Wd = px(44), px(ancho)
        super().__init__(master, self.Wd, self.IH * len(items) + px(4), cursor="hand2")
        self.sel, self.y_sel, self.hover, self.hy = 0, 0.0, -1, 0.0
        self.bind("<Button-1>", lambda e: self._clic(e.y))
        self.bind("<Motion>", lambda e: self._hov(e.y))
        self.bind("<Leave>", lambda e: self._hov(None))
        self.dibujar()

    def _idx(self, y):
        return max(0, min(len(self.items) - 1, int(y // self.IH)))

    def _hov(self, y):
        h = -1 if y is None else self._idx(y)
        if h != self.hover:
            self.hover = h
            if h >= 0:
                self.animar("hy", h * self.IH, 140)
            else:
                self.dibujar()

    def _clic(self, y):
        i = self._idx(y)
        if i != self.sel:
            self.seleccionar(i)
            self.command(i)

    def seleccionar(self, i, animar=True):
        self.sel = i
        if animar:
            self.animar("y_sel", i * self.IH, 380, ease=ease_back)
        else:
            self.y_sel = i * self.IH
            self.dibujar()

    def dibujar(self):
        self.limpiar()
        W, IH = self.Wd, self.IH
        if self.hover >= 0 and self.hover != self.sel:
            self.img(0, self.hy + px(2), img_rr(W, IH - px(4), px(10), fill=PANEL2))
        self.img(0, self.y_sel + px(2), img_rr(W, IH - px(4), px(10), fill=mezclar(PANEL2, ACENTO, 0.22)))
        self.img(px(6), self.y_sel + IH / 2 - px(9), img_rr(px(4), px(18), px(2), fill=ACENTO2))
        for i, (ico, txt) in enumerate(self.items):
            y = i * IH + IH / 2
            act = i == self.sel
            col = "#ffffff" if act else (TEXTO if i == self.hover else SUB)
            self.create_text(px(26), y, text=ico, fill=ACENTO2 if act else col, font=F(12))
            self.create_text(px(48), y, text=tr(txt), fill=col, font=F(10, "bold"), anchor="w")


class ListaScroll(tk.Frame):

    def __init__(self, master, bg=PANEL):
        super().__init__(master, bg=bg)
        self.c = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.c.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.c, bg=bg)
        self.win = self.c.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.c.configure(scrollregion=self.c.bbox("all")))
        self.c.bind("<Configure>", lambda e: self.c.itemconfigure(self.win, width=e.width))

    def _rueda(self, e):
        if self.inner.winfo_height() > self.c.winfo_height():
            self.c.yview_scroll(int(-e.delta / 120) * 3, "units")

    def limpiar(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.c.yview_moveto(0)


def etiqueta(master, texto, tam=10, color=SUB, peso="normal", **kw):
    return tk.Label(master, text=tr(texto), bg=master.cget("bg"), fg=color, font=F(tam, peso), **kw)


def enlace(master, texto, cb, color=SUB):
    l = etiqueta(master, texto, 9, color, cursor="hand2")
    l.bind("<Button-1>", lambda e: cb())
    l.bind("<Enter>", lambda e: l.config(fg=TEXTO))
    l.bind("<Leave>", lambda e: l.config(fg=color))
    return l


def sacudir(widget, anim):
    anim.run("sacudir", 480, lambda t: widget.place_configure(
        x=int(px(12) * math.sin(t * math.pi * 7) * (1 - t))), ease=lineal)


def leer_entero(texto, minimo, maximo, nombre):
    try:
        v = int(str(texto).strip())
    except ValueError:
        raise ValueError(f"{nombre}: escribe un número entero")
    if not minimo <= v <= maximo:
        raise ValueError(f"{nombre}: debe estar entre {minimo:,} y {maximo:,}")
    return v


def registrar_error(texto):
    try:
        base = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "AutoClickerAL")
        os.makedirs(base, exist_ok=True)
        ruta = os.path.join(base, "errores.log")
        if os.path.exists(ruta) and os.path.getsize(ruta) > 512 * 1024:
            os.replace(ruta, ruta + ".viejo")
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] v{APP_VERSION}\n{texto}\n")
    except Exception:
        pass


def seguro(fn):
    def w(*a, **k):
        try:
            return fn(*a, **k)
        except tk.TclError as e:

            if "invalid command name" not in str(e) and "bad window path" not in str(e):
                import traceback
                registrar_error(traceback.format_exc())
    return w


def puede_editar(yo, u):
    if u["rol"] == "owner":
        return False
    if u["rol"] == "admin":
        return yo["rol"] == "owner" or yo["id"] == u["id"]
    return yo["rol"] in ("owner", "admin")


class SelectorDuracion(tk.Frame):

    def __init__(self, master, presets=PRESETS, cols=3, ancho_chip=108):
        super().__init__(master, bg=master.cget("bg"))
        self.chips = []
        grid = tk.Frame(self, bg=self.cget("bg"))
        grid.pack(anchor="w")
        for i, (txt, seg) in enumerate(presets):
            b = Boton(grid, txt, lambda s=seg, k=i: self._preset(s, k), ancho=ancho_chip, alto=32,
                      estilo="sec", fuente=F(9, "bold"))
            b.grid(row=i // cols, column=i % cols, padx=(0, px(2)), pady=px(1))
            self.chips.append((b, seg))
        fila = tk.Frame(self, bg=self.cget("bg"))
        fila.pack(anchor="w", pady=(px(8), 0))
        self.num = Campo(fila, ancho=64, alto=34, justify="center")
        self.num.pack(side="left")
        self.num.var.trace_add("write", lambda *a: self._marcar(None))
        self.unidad = Segmentado(fila, ["Horas", "Días", "Sem.", "Meses", "Años"], 1,
                                 command=lambda i: self._marcar(None), ancho=ancho_chip * cols - 74, alto=34)
        self.unidad.pack(side="left", padx=(px(8), 0))
        self.por_vida = False
        self._preset(604800, 2)

    def _marcar(self, k):
        if getattr(self, "_bloq", False):
            return
        if k is None:
            self.por_vida = False
        for i, (b, _s) in enumerate(self.chips):
            b.set_color(ACENTO if i == k else PANEL2)
        self.num.habilitar(not self.por_vida)

    def _preset(self, seg, k):
        self._bloq = True
        self.por_vida = seg < 0
        if not self.por_vida:
            for i in range(len(UNIDADES) - 1, -1, -1):
                u = UNIDADES[i][1]
                if seg % u == 0:
                    self.num.set(seg // u)
                    self.unidad.set(i)
                    break
        self._bloq = False
        self._marcar(k)

    def segundos(self):
        if self.por_vida:
            return -1
        n = leer_entero(self.num.get(), 1, 100000, "Duración")
        s = n * UNIDADES[self.unidad.get()][1]
        if s > 100 * 31536000:
            raise ValueError("Duración: máximo 100 años")
        return s


class PantallaAuth(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=BG)
        self.app, self.anim = app, Anim(self)
        fondo = FondoAnimado(self)
        fondo.place(x=0, y=0, relwidth=1, relheight=1)
        self.card = TarjetaFlotante(fondo, pad=30)
        self.card.place(relx=0.5, rely=0.5, anchor="center")
        c = self.card.cuerpo

        cab = tk.Frame(c, bg=PANEL)
        cab.pack(fill="x")
        Logo(cab, 46).pack(side="left")
        t = tk.Frame(cab, bg=PANEL)
        t.pack(side="left", padx=px(12))
        etiqueta(t, APP_NOMBRE, 18, TEXTO, "bold").pack(anchor="w")
        etiqueta(t, tr("Autoclicker de mouse y teclado · v{v}", v=APP_VERSION), 9).pack(anchor="w")

        self.tabs = Segmentado(c, ["Iniciar sesión", "Crear cuenta"], 0, command=self._construir,
                               ancho=330, alto=38)
        self.tabs.pack(pady=(px(22), px(14)))
        self.form = tk.Frame(c, bg=PANEL)
        self.form.pack(fill="x")
        self.estado = etiqueta(c, "● Conectando con el servidor…", 8, SUB)
        self.estado.pack(pady=(px(14), 0))
        self._construir(0)
        self._reintento = None
        if app.conexion_iniciada:
            self.verificar_servidor()

    def verificar_servidor(self):
        if self._reintento:
            self.after_cancel(self._reintento)
            self._reintento = None
        self.app.api("GET", "/api/ping", None, seguro(self._en_linea), seguro(self._sin_conexion))

    def _en_linea(self, _r):
        self.estado.config(text=tr("● Servidor en línea"), fg=OK)
        self.app.intentar_auto_login()

    def _sin_conexion(self, _e):
        self.estado.config(text=tr("● Sin conexión con el servidor · reintentando…"), fg=ERROR)
        self._reintento = self.after(5000, seguro(self.verificar_servidor))

    def _construir(self, modo):
        for w in self.form.winfo_children():
            w.destroy()
        self.modo = modo
        etiqueta(self.form, "Usuario", 9, SUB, "bold").pack(anchor="w")
        self.c_user = Campo(self.form, ancho=330)
        self.c_user.pack(pady=(px(4), px(10)))
        etiqueta(self.form, "Contraseña", 9, SUB, "bold").pack(anchor="w")
        self.c_pw = Campo(self.form, ancho=330, show="•", ojo=True)
        self.c_pw.pack(pady=(px(4), px(10)))
        self.c_pw2 = None
        if modo == 1:
            etiqueta(self.form, "Repite la contraseña", 9, SUB, "bold").pack(anchor="w")
            self.c_pw2 = Campo(self.form, ancho=330, show="•", ojo=True)
            self.c_pw2.pack(pady=(px(4), px(6)))
            etiqueta(self.form, "Inventa un usuario y contraseña. No uses datos reales.", 8, AVISO).pack(anchor="w")
        else:
            self.c_user.set(self.app.local.datos.get("ultimo_usuario", ""))
            f = tk.Frame(self.form, bg=PANEL)
            f.pack(fill="x")
            self.t_rec = Interruptor(f, self.app.local.datos.get("recordar", True))
            self.t_rec.pack(side="left")
            etiqueta(f, "Mantener la sesión iniciada", 9).pack(side="left", padx=px(8))
        self.lbl_error = etiqueta(self.form, "", 9, ERROR)
        self.lbl_error.pack(anchor="w", pady=(px(6), 0))
        self.btn = Boton(self.form, "Entrar" if modo == 0 else "Crear cuenta", self._enviar,
                         ancho=330, alto=44, fuente=F(11, "bold"))
        self.btn.pack(pady=(px(4), 0))
        self.c_user.al_enter(lambda: self.c_pw.e.focus_set())
        if self.c_pw2:
            self.c_pw.al_enter(lambda: self.c_pw2.e.focus_set())
        (self.c_pw2 or self.c_pw).al_enter(self._enviar)
        foco = self.c_pw if (modo == 0 and self.c_user.get()) else self.c_user
        self.after(60, seguro(foco.e.focus_set))
        self.anim.run("form", 300, lambda t: self.form.pack_configure(padx=(int(px(30) * (1 - t)), 0)))

    def _error(self, msg):
        self.lbl_error.config(text=tr(msg))
        self.btn.set_habilitado(True)
        self.btn.set_texto("Entrar" if self.modo == 0 else "Crear cuenta")
        sacudir(self.card, self.anim)

    def _enviar(self):
        if not self.btn.habilitado:
            return
        u, p = self.c_user.get().strip(), self.c_pw.get()
        if self.modo == 1:
            if not re.fullmatch(r"[A-Za-z0-9_.\-]{3,20}", u):
                return self._error("Usuario: 3 a 20 caracteres (letras, números, _ . -)")
            if len(p) < 6:
                return self._error("La contraseña debe tener al menos 6 caracteres")
            if p != self.c_pw2.get():
                return self._error("Las contraseñas no coinciden")
        elif not u or not p:
            return self._error("Escribe tu usuario y contraseña")
        self.btn.set_habilitado(False)
        self.btn.set_texto("Conectando…")
        recordar = self.t_rec.get() if self.modo == 0 else True
        ruta = "/api/login" if self.modo == 0 else "/api/registro"
        self.app.api("POST", ruta, {"usuario": u, "pw": prehash(u, p)},
                     seguro(lambda r: self.app.entrar(r["token"], r["yo"], recordar, nuevo=self.modo == 1)),
                     seguro(lambda e: self._error(e.msg)))


def formatear_clave(campo):
    est = {"ocupado": False}

    def fn(*_):
        if est["ocupado"]:
            return
        est["ocupado"] = True
        s = re.sub(r"[^A-Za-z0-9]", "", campo.get()).upper()
        if s.startswith("AL"):
            s = s[2:]
        s = s[:16]
        nuevo = ("AL-" + "-".join(s[i:i + 4] for i in range(0, len(s), 4))) if s else ""
        if nuevo != campo.get():
            campo.set(nuevo)
            campo.e.icursor("end")
        est["ocupado"] = False
    campo.var.trace_add("write", fn)


class PantallaLicencia(tk.Frame):
    def __init__(self, app, aviso=""):
        super().__init__(app, bg=BG)
        self.app, self.anim = app, Anim(self)
        fondo = FondoAnimado(self)
        fondo.place(x=0, y=0, relwidth=1, relheight=1)
        self.card = TarjetaFlotante(fondo, pad=32)
        self.card.place(relx=0.5, rely=0.5, anchor="center")
        c = self.card.cuerpo
        self.candado = Candado(c)
        self.candado.pack()
        etiqueta(c, "Activa tu licencia", 17, TEXTO, "bold").pack(pady=(px(6), px(2)))
        yo = app.yo
        etiqueta(c, aviso or tr("Hola {n}, pega la licencia que te dieron.\nCada licencia se puede usar una sola vez.", n=yo['nombre']),
                 9, AVISO if aviso else SUB, justify="center").pack()
        etiqueta(c, tr("Tu ID: {id}", id=yo['id']), 9, ACENTO2, "bold").pack(pady=(px(8), 0))
        etiqueta(c, "Licencia", 9, SUB, "bold").pack(anchor="w", pady=(px(12), px(4)))
        self.campo = Campo(c, ancho=360, alto=46, fuente=(MONO, 13, "bold"), justify="center")
        self.campo.pack()
        formatear_clave(self.campo)
        self.campo.al_enter(self._activar)
        self.lbl_error = etiqueta(c, "", 9, ERROR)
        self.lbl_error.pack(pady=(px(6), 0))
        self.btn = Boton(c, "Activar licencia", self._activar, ancho=360, alto=44, fuente=F(11, "bold"))
        self.btn.pack(pady=(px(2), px(8)))
        enlace(c, "← Cerrar sesión", app.cerrar_sesion).pack()
        self.after(80, seguro(self.campo.e.focus_set))

    def _error(self, msg):
        self.lbl_error.config(text=tr(msg))
        self.btn.set_habilitado(True)
        self.btn.set_texto("Activar licencia")
        sacudir(self.card, self.anim)

    def _activar(self):
        if not self.btn.habilitado:
            return
        if len(re.sub(r"[^A-Z0-9]", "", self.campo.get())) != 18:
            return self._error("La licencia está incompleta")
        self.btn.set_habilitado(False)
        self.btn.set_texto("Verificando…")
        self.app.api("POST", "/api/canjear", {"clave": self.campo.get()}, seguro(self._ok), seguro(lambda e: self._error(e.msg)))

    def _ok(self, r):
        self.app.yo = r["yo"]
        self.lbl_error.config(text="")
        self.app.toast.mostrar(tr("Licencia activada: {d}", d=fmt_duracion(r['duracion'])), "ok")
        self.candado.abrir(lambda: self.after(250, lambda: self.app.mostrar(PantallaPrincipal)))


class Pagina(tk.Frame):
    titulo = subtitulo = ""

    def __init__(self, master, app, principal):
        super().__init__(master, bg=BG)
        self.app, self.principal = app, principal
        cab = tk.Frame(self, bg=BG)
        cab.pack(fill="x", pady=(0, px(14)))
        etiqueta(cab, self.titulo, 19, TEXTO, "bold").pack(anchor="w")
        etiqueta(cab, self.subtitulo, 10).pack(anchor="w")
        self.cuerpo = tk.Frame(self, bg=BG)
        self.cuerpo.pack(fill="both", expand=True)

    def al_mostrar(self):
        pass

    @staticmethod
    def fila(master, titulo, ayuda=""):
        f = tk.Frame(master, bg=PANEL)
        f.pack(fill="x", pady=px(8))
        izq = tk.Frame(f, bg=PANEL, width=px(112), height=px(40))
        izq.pack(side="left", fill="y")
        izq.pack_propagate(False)
        etiqueta(izq, titulo, 10, TEXTO, "bold").pack(anchor="w")
        if ayuda:
            etiqueta(izq, ayuda, 8).pack(anchor="w")
        der = tk.Frame(f, bg=PANEL)
        der.pack(side="left", fill="x", expand=True)
        return der


class PaginaClicker(Pagina):
    clave = unidad = atajo = ""

    def __init__(self, master, app, principal):
        super().__init__(master, app, principal)
        self.cfg = app.local.cfg(app.yo["id"]).get(self.clave, {})
        p = Tarjeta(self.cuerpo, pad=16)
        p.pack(side="right", fill="y", padx=(px(14), 0))
        pc = p.cuerpo
        self.power = BotonPower(pc, 146, command=lambda: principal.alternar(self.clave, True))
        self.power.pack()
        self.lbl_cont = etiqueta(pc, "0", 24, TEXTO, "bold")
        self.lbl_cont.pack()
        etiqueta(pc, self.unidad, 9).pack()
        st = tk.Frame(pc, bg=PANEL)
        st.pack(pady=(px(12), 0), fill="x")
        self.lbl_tiempo = self._stat(st, "Tiempo", "00:00")
        self.lbl_cps = self._stat(st, "Por seg.", "0.0")
        self.lbl_atajo = etiqueta(pc, "", 9, ACENTO2, "bold")
        self.lbl_atajo.pack(pady=(px(12), 0))
        self.lbl_emerg = etiqueta(pc, "", 8, SUB, justify="center")
        self.lbl_emerg.pack(pady=(px(4), 0))
        self.refrescar_atajo()
        self._mostrado, self._estaba = 0, False
        card = Tarjeta(self.cuerpo, pad=20)
        card.pack(side="left", fill="both", expand=True)
        self.card = card.cuerpo

    def _stat(self, master, t, v):
        f = tk.Frame(master, bg=PANEL2, padx=px(8), pady=px(6))
        f.pack(side="left", expand=True, fill="x", padx=px(3))
        tk.Label(f, text=tr(t), bg=PANEL2, fg=SUB, font=F(8)).pack()
        l = tk.Label(f, text=v, bg=PANEL2, fg=TEXTO, font=F(11, "bold"))
        l.pack()
        return l

    def refrescar_atajo(self):
        aj = self.app.ajustes()
        self.lbl_atajo.config(text=tr("Atajo:  {k}", k=nombre_vk(aj[self.atajo])))
        txt = tr("Emergencia: {k}", k=nombre_vk(aj['hk_stop']))
        if aj.get("esquina", True):
            txt += "\n" + tr("o mouse a la esquina ↖")
        self.lbl_emerg.config(text=txt)

    def fila_intervalo(self):
        der = self.fila(self.card, "Intervalo", "milisegundos")
        self.c_int = Campo(der, ancho=78, alto=36, justify="center")
        self.c_int.set(self.cfg.get("intervalo", "100"))
        self.c_int.pack(side="left")
        for txt, v in (("10 ms", 10), ("100 ms", 100), ("1 seg", 1000)):
            Boton(der, txt, lambda v=v: self.c_int.set(v), ancho=64, alto=32, estilo="sec",
                  fuente=F(8, "bold")).pack(side="left", padx=(px(2), 0))

    def fila_repetir(self):
        der = self.fila(self.card, "Repetir")
        self.s_rep = Segmentado(der, ["Siempre", "Veces"], self.cfg.get("rep", 0),
                                command=lambda i: self.c_veces.habilitar(i == 1), ancho=160)
        self.s_rep.pack(side="left")
        self.c_veces = Campo(der, ancho=86, alto=36, justify="center")
        self.c_veces.set(self.cfg.get("veces", "100"))
        self.c_veces.pack(side="left", padx=(px(10), 0))
        self.c_veces.habilitar(self.s_rep.get() == 1)

    def fila_juego(self, ayuda):
        der = self.fila(self.card, "Modo juego", "Roblox y otros juegos")
        self.t_juego = Interruptor(der, self.cfg.get("juego", True))
        self.t_juego.pack(side="left")
        etiqueta(der, ayuda, 8, justify="left").pack(side="left", padx=(px(10), 0))

    def tiempos(self):
        iv = leer_entero(self.c_int.get(), 1, 3_600_000, "Intervalo")
        rep = leer_entero(self.c_veces.get(), 1, 100_000_000, "Repeticiones") if self.s_rep.get() == 1 else 0
        return iv / 1000, rep

    def config_base(self):
        return {"intervalo": self.c_int.get(), "rep": self.s_rep.get(), "veces": self.c_veces.get(),
                "juego": self.t_juego.get()}

    def actualizar(self, m):
        real = m.contador
        if self._mostrado != real:
            dif = real - self._mostrado
            self._mostrado += dif if abs(dif) < 3 else max(1, int(dif * 0.35)) * (1 if dif > 0 else -1)
            self.lbl_cont.config(text=f"{self._mostrado:,}")
        if m.inicio:
            dur = (time.time() if m.activo else m.fin) - m.inicio
            self.lbl_tiempo.config(text=f"{int(dur // 60):02d}:{int(dur % 60):02d}")
            self.lbl_cps.config(text=f"{(real / dur) if dur > 0.2 else 0:.1f}")
        if self._estaba and not m.activo:
            self.power.set_on(False)
            reproducir("off")
            if m.error:
                self.app.toast.mostrar(m.error, "error")
            elif m.completado:
                self.app.toast.mostrar(tr("Listo: {n} {u}", n=f"{real:,}", u=tr(self.unidad)), "ok")
        self._estaba = m.activo


class PaginaMouse(PaginaClicker):
    titulo, subtitulo = "Mouse", "Clics automáticos a la velocidad que elijas."
    clave, unidad, atajo = "mouse", "clics", "hk_mouse"

    def __init__(self, master, app, principal):
        super().__init__(master, app, principal)
        cfg = self.cfg
        self.fila_intervalo()
        der = self.fila(self.card, "Botón")
        self.s_boton = Segmentado(der, ["Izquierdo", "Derecho", "Medio"], cfg.get("boton", 0), ancho=252)
        self.s_boton.pack(side="left")
        der = self.fila(self.card, "Clic")
        self.s_tipo = Segmentado(der, ["Simple", "Doble"], cfg.get("tipo", 0), ancho=160)
        self.s_tipo.pack(side="left")
        der = self.fila(self.card, "Posición")
        self.s_pos = Segmentado(der, ["Cursor", "Punto fijo"], cfg.get("pos", 0), command=self._pos, ancho=180)
        self.s_pos.pack(side="left")
        self.punto = tuple(cfg.get("punto", (0, 0)))
        self.b_punto = Boton(der, "", self._elegir, ancho=118, alto=34, estilo="sec", fuente=F(9, "bold"))
        self.b_punto.pack(side="left", padx=(px(8), 0))
        self._pos(self.s_pos.get())
        self.fila_repetir()
        self.fila_juego("Clics que los juegos sí detectan.\nApágalo solo si quieres la máxima velocidad.")

    def _pos(self, i):
        self.b_punto.set_texto(f"⌖ {self.punto[0]}, {self.punto[1]}" if i == 1 else "Elegir punto")
        self.b_punto.set_habilitado(i == 1)

    def _elegir(self):
        if not self.b_punto.habilitado:
            return
        self.b_punto.set_habilitado(False)
        self.app.toast.mostrar("Pon el mouse donde quieres el clic…", "info", 2400)

        def paso(n):
            if n == 0:
                self.punto = posicion_cursor()
                self.b_punto.set_habilitado(True)
                self._pos(1)
                self.app.toast.mostrar(tr("Punto guardado: {x}, {y}", x=self.punto[0], y=self.punto[1]), "ok")
                return
            self.b_punto.set_texto(tr("Elige en {n}…", n=n))
            self.after(1000, seguro(lambda: paso(n - 1)))
        paso(3)

    def preparar(self):
        iv, rep = self.tiempos()
        boton = ["izq", "der", "med"][self.s_boton.get()]
        doble = self.s_tipo.get() == 1
        pos = self.punto if self.s_pos.get() == 1 else None
        juego = self.t_juego.get()
        return (lambda p: hacer_clic(boton, doble, pos, juego, p)), iv, rep

    def obtener_config(self):
        d = self.config_base()
        d.update(boton=self.s_boton.get(), tipo=self.s_tipo.get(), pos=self.s_pos.get(), punto=list(self.punto))
        return d


class PaginaTeclado(PaginaClicker):
    titulo, subtitulo = "Teclado", "Repite una tecla una y otra vez."
    clave, unidad, atajo = "teclado", "pulsaciones", "hk_teclado"

    def __init__(self, master, app, principal):
        super().__init__(master, app, principal)
        self.vk = self.cfg.get("vk", 0x45)
        self.capturando = False
        der = self.fila(self.card, "Tecla", "la que se repite")
        self.tecla = TeclaVisual(der, nombre_vk(self.vk))
        self.tecla.pack(side="left")
        self.b_cap = Boton(der, "Cambiar tecla", self._capturar, ancho=130, alto=36, estilo="sec", fuente=F(9, "bold"))
        self.b_cap.pack(side="left", padx=(px(10), 0))
        self.fila_intervalo()
        self.fila_repetir()
        self.fila_juego("Mantiene la tecla 40 ms para que el juego la note.\nApágalo para la máxima velocidad.")

    def _capturar(self):
        if self.capturando:
            return self._fin()
        self.capturando = True
        self.app.vigilante.habilitado = False
        self.b_cap.set_texto("Presiona una tecla…")
        self.b_cap.set_color(ACENTO)
        self.app.focus_set()
        self.app.bind_all("<KeyPress>", self._tecla)

    def _tecla(self, e):
        vk = e.keycode if ES_WINDOWS else 0x45
        if not vk:
            self.app.toast.mostrar("Esa tecla no se puede usar", "aviso")
        elif vk in self.app.vks_atajo():
            self.app.toast.mostrar(tr("{k} es un atajo. Elige otra.", k=nombre_vk(vk)), "aviso")
        else:
            self.vk = vk
            self.tecla.set(nombre_vk(vk))
        self._fin()
        return "break"

    def _fin(self):
        self.capturando = False
        self.app.unbind_all("<KeyPress>")
        self.b_cap.set_texto("Cambiar tecla")
        self.b_cap.set_color(PANEL2)

    def preparar(self):
        iv, rep = self.tiempos()
        vk, mantener = self.vk, (40 if self.t_juego.get() else 8)
        return (lambda p: presionar_tecla(vk, mantener, p)), iv, rep

    def obtener_config(self):
        d = self.config_base()
        d["vk"] = self.vk
        return d


class PaginaLicencias(Pagina):
    titulo, subtitulo = "Licencias", "Crea licencias y revisa quién las usó."

    def __init__(self, master, app, principal):
        super().__init__(master, app, principal)
        es_owner = app.yo["rol"] == "owner"
        izq = Tarjeta(self.cuerpo, pad=18)
        izq.pack(side="left", fill="y")
        c = izq.cuerpo
        etiqueta(c, "CREAR LICENCIAS", 8, ACENTO2, "bold").pack(anchor="w")
        self.s_tipo = None
        if es_owner:
            etiqueta(c, "Tipo", 9, SUB, "bold").pack(anchor="w", pady=(px(10), px(4)))
            self.s_tipo = Segmentado(c, ["Usuario", "Admin"], 0, ancho=200, command=self._tipo)
            self.s_tipo.pack(anchor="w")
        self.zona_dur = tk.Frame(c, bg=PANEL)
        self.zona_dur.pack(anchor="w", fill="x")
        self.f_dur = tk.Frame(self.zona_dur, bg=PANEL)
        self.f_dur.pack(anchor="w")
        etiqueta(self.f_dur, "Duración (empieza al activarla)", 9, SUB, "bold").pack(anchor="w", pady=(px(10), px(4)))
        self.dur = SelectorDuracion(self.f_dur)
        self.dur.pack(anchor="w")
        self.f_admin = tk.Frame(self.zona_dur, bg=PANEL)
        nota = Tarjeta(self.f_admin, pad=14, color=mezclar(PANEL, ACENTO2, 0.1), borde=mezclar(PANEL, ACENTO2, 0.5))
        nota.pack(fill="x", pady=(px(14), px(4)))
        etiqueta(nota.cuerpo, "Licencia de ADMIN", 11, ACENTO2, "bold").pack(anchor="w")
        etiqueta(nota.cuerpo, "Quien la active se convierte en cuenta\nde administrador (permanente).\n\n"
                              "Podrá crear licencias de usuario,\nver usuarios y banear.", 9, TEXTO,
                 justify="left").pack(anchor="w", pady=(px(4), 0))
        f = tk.Frame(c, bg=PANEL)
        f.pack(fill="x", pady=(px(12), 0))
        g1 = tk.Frame(f, bg=PANEL)
        g1.pack(side="left")
        etiqueta(g1, "Cantidad", 9, SUB, "bold").pack(anchor="w")
        self.c_cant = Campo(g1, ancho=72, alto=36, justify="center")
        self.c_cant.set("1")
        self.c_cant.pack(pady=(px(4), 0))
        g2 = tk.Frame(f, bg=PANEL)
        g2.pack(side="left", padx=(px(10), 0))
        etiqueta(g2, "Nota (opcional)", 9, SUB, "bold").pack(anchor="w")
        self.c_nota = Campo(g2, ancho=240, alto=36)
        self.c_nota.pack(pady=(px(4), 0))
        self.btn = Boton(c, "Generar licencias", self._generar, ancho=322, alto=44, fuente=F(11, "bold"))
        self.btn.pack(pady=(px(14), 0))
        etiqueta(c, "Se copian solas al portapapeles.", 8).pack()

        der = Tarjeta(self.cuerpo, pad=18)
        der.pack(side="left", fill="both", expand=True, padx=(px(14), 0))
        d = der.cuerpo
        top = tk.Frame(d, bg=PANEL)
        top.pack(fill="x")
        etiqueta(top, "LICENCIAS CREADAS", 8, ACENTO2, "bold").pack(side="left")
        Boton(top, "↻", self.cargar, ancho=34, alto=28, estilo="sec", fuente=F(10, "bold")).pack(side="right")
        self.filtro = Segmentado(d, ["Todas", "Libres", "Usadas"], 0, command=lambda i: self._pintar(), ancho=240, alto=30)
        self.filtro.pack(anchor="w", pady=(px(8), px(8)))
        self.lista = ListaScroll(d)
        self.lista.pack(fill="both", expand=True)
        self.datos, self.nuevas = [], set()

    def _tipo(self, i):
        self.f_dur.pack_forget()
        self.f_admin.pack_forget()
        (self.f_admin if i == 1 else self.f_dur).pack(anchor="w", fill="x")

    def al_mostrar(self):
        self.cargar()

    def cargar(self):
        self.app.api("GET", "/api/admin/licencias", None, seguro(self._recibir))

    def _recibir(self, r):
        self.datos = r["licencias"]
        self._pintar()

    def _pintar(self):
        self.lista.limpiar()
        f = self.filtro.get()
        filas = [l for l in self.datos if f == 0 or (f == 1) == (not l["usada_por"])]
        if not filas:
            etiqueta(self.lista.inner, "No hay licencias todavía.", 9).pack(pady=px(20))
        for l in filas[:150]:
            self._fila(l)

    def _fila(self, l):
        nueva = l["clave"] in self.nuevas
        bg = mezclar(PANEL, ACENTO, 0.12) if nueva else PANEL
        fr = tk.Frame(self.lista.inner, bg=bg, padx=px(8), pady=px(6))
        fr.pack(fill="x", pady=px(1))
        izq = tk.Frame(fr, bg=bg)
        izq.pack(side="left", fill="x", expand=True)
        tk.Label(izq, text=l["clave"], bg=bg, fg=TEXTO, font=(MONO, 10, "bold")).pack(anchor="w")
        tipo = "Admin" if l["tipo"] == "admin" else "Usuario"
        if l["usada_por"]:
            est, col = f"Usada por {l.get('usada_nombre') or '#' + str(l['usada_por'])}", SUB
        else:
            est, col = "Libre", OK
        info = ("Admin permanente" if l["tipo"] == "admin" else f"{fmt_duracion(l['duracion'])} · {tipo}") + \
            (f" · {l['nota']}" if l.get("nota") else "")
        linea = tk.Frame(izq, bg=bg)
        linea.pack(anchor="w")
        tk.Label(linea, text=info + "  ·  ", bg=bg, fg=SUB, font=F(8)).pack(side="left")
        tk.Label(linea, text=est, bg=bg, fg=col, font=F(8, "bold")).pack(side="left")
        if not l["usada_por"]:
            borrar = tk.Label(fr, text="✕", bg=bg, fg=SUB, font=F(10, "bold"), cursor="hand2")
            borrar.pack(side="right", padx=(px(6), 0))
            borrar.bind("<Button-1>", lambda e, c=l["clave"], b=borrar: self._borrar(c, b))
            borrar.bind("<Enter>", lambda e: borrar.config(fg=ERROR))
            borrar.bind("<Leave>", lambda e: borrar.cget("text") == "✕" and borrar.config(fg=SUB))
            copiar = tk.Label(fr, text="Copiar", bg=bg, fg=ACENTO2, font=F(9, "bold"), cursor="hand2")
            copiar.pack(side="right")
            copiar.bind("<Button-1>", lambda e, c=l["clave"]: self.app.copiar(c, "Licencia copiada"))

    def _generar(self):
        if not self.btn.habilitado:
            return
        tipo = "admin" if self.s_tipo and self.s_tipo.get() == 1 else "user"
        try:
            seg = -1 if tipo == "admin" else self.dur.segundos()
            n = leer_entero(self.c_cant.get(), 1, 50, "Cantidad")
        except ValueError as e:
            return self.app.toast.mostrar(str(e), "error")
        self.btn.set_habilitado(False)
        self.btn.set_texto("Generando…")

        def ok(r):
            self.btn.set_habilitado(True)
            self.btn.set_texto("Generar licencias")
            self.nuevas = set(r["claves"])
            desc = "admin" if tipo == "admin" else fmt_duracion(seg)
            self.app.copiar("\n".join(r["claves"]), tr("{n} licencia(s) de {d} copiadas", n=len(r['claves']), d=desc))
            self.filtro.set(0)
            self.cargar()

        def err(e):
            self.btn.set_habilitado(True)
            self.btn.set_texto("Generar licencias")
            self.app.toast.mostrar(e.msg, "error")
        self.app.api("POST", "/api/admin/generar", {"cantidad": n, "duracion": seg, "tipo": tipo,
                                                    "nota": self.c_nota.get().strip()}, seguro(ok), seguro(err))

    def _borrar(self, clave, etiqueta_x):
        if etiqueta_x.cget("text") == "✕":
            etiqueta_x.config(text="¿Borrar?", fg=ERROR)
            etiqueta_x.after(3000, seguro(lambda: etiqueta_x.config(text="✕", fg=SUB)))
            return
        self.app.api("POST", "/api/admin/borrar_licencia", {"clave": clave},
                     seguro(lambda r: (self.app.toast.mostrar("Licencia borrada", "ok"), self.cargar())))


class PaginaUsuarios(Pagina):
    titulo, subtitulo = "Usuarios", "Quién tiene el programa, su licencia y sus permisos."

    def __init__(self, master, app, principal):
        super().__init__(master, app, principal)
        izq = Tarjeta(self.cuerpo, pad=16)
        izq.pack(side="left", fill="both", expand=True)
        c = izq.cuerpo
        top = tk.Frame(c, bg=PANEL)
        top.pack(fill="x", pady=(0, px(8)))
        self.buscar = Campo(top, ancho=260, alto=36)
        self.buscar.pack(side="left")
        self._job_buscar = None
        self.buscar.var.trace_add("write", lambda *a: self._programar_pintado())
        etiqueta(top, "Buscar", 9).pack(side="left", padx=px(8))
        Boton(top, "↻", self.cargar, ancho=34, alto=28, estilo="sec", fuente=F(10, "bold")).pack(side="right")
        fil = tk.Frame(c, bg=PANEL)
        fil.pack(fill="x", pady=(0, px(8)))
        self.filtro = Segmentado(fil, ["Todos", "Con licencia", "Admins", "Baneados"], 0,
                                 command=lambda i: self._pintar(), ancho=380, alto=30)
        self.filtro.pack(side="left")
        self.lbl_cuenta = etiqueta(fil, "", 8)
        self.lbl_cuenta.pack(side="right")
        self.lista = ListaScroll(c)
        self.lista.pack(fill="both", expand=True)

        self.det = Tarjeta(self.cuerpo, pad=16)
        self.det.pack(side="left", fill="y", padx=(px(14), 0))
        self.detalle = self.det.cuerpo
        tk.Frame(self.detalle, bg=PANEL, width=px(290)).pack()
        self.datos, self.sel = [], None
        self._vacio()

    def al_mostrar(self):
        self.cargar()

    def _programar_pintado(self):
        if self._job_buscar:
            self.after_cancel(self._job_buscar)
        self._job_buscar = self.after(180, seguro(self._pintar))

    def cargar(self):
        self.app.api("GET", "/api/admin/usuarios", None, seguro(self._recibir))

    def _recibir(self, r):
        self.datos = r["usuarios"]
        self._pintar()
        if self.sel is not None:
            u = next((x for x in self.datos if x["id"] == self.sel), None)
            self._mostrar(u) if u else self._vacio()

    MAX_FILAS = 120

    def _pintar(self):
        self._job_buscar = None
        self.lista.limpiar()
        b = self.buscar.get().strip().lower()
        f = self.filtro.get()
        pruebas = [lambda u: True, lambda u: u["rol"] == "user" and u["acceso"],
                   lambda u: u["rol"] != "user", lambda u: u["baneado"]]
        filas = [u for u in self.datos if pruebas[f](u) and (not b or b in u["nombre"].lower() or b in str(u["id"]))]
        con = sum(1 for u in self.datos if u["acceso"] and not u["baneado"])
        n = len(self.datos)
        clave = "{n} cuenta · {c} con acceso" if n == 1 else "{n} cuentas · {c} con acceso"
        self.lbl_cuenta.config(text=tr(clave, n=n, c=con))
        if not filas:
            etiqueta(self.lista.inner, "Sin resultados.", 9).pack(pady=px(20))
        for u in filas[:self.MAX_FILAS]:
            self._fila(u)
        if len(filas) > self.MAX_FILAS:
            etiqueta(self.lista.inner, tr("Mostrando {m} de {n} · usa el buscador", m=self.MAX_FILAS, n=len(filas)),
                     8).pack(pady=px(10))

    def _fila(self, u):
        sel = u["id"] == self.sel
        bg = mezclar(PANEL, ACENTO, 0.16) if sel else PANEL
        fr = tk.Frame(self.lista.inner, bg=bg, padx=px(8), pady=px(6), cursor="hand2")
        fr.pack(fill="x", pady=px(1))
        Avatar(fr, u["nombre"], 30, bg=bg).pack(side="left")
        t = tk.Frame(fr, bg=bg)
        t.pack(side="left", padx=px(8))
        tk.Label(t, text=u["nombre"], bg=bg, fg=TEXTO, font=F(10, "bold")).pack(anchor="w")
        tk.Label(t, text=f"ID {u['id']}", bg=bg, fg=SUB, font=F(8)).pack(anchor="w")
        if u["baneado"]:
            est, col = "BANEADO", ERROR
        elif u["rol"] != "user":
            est, col = "Acceso total", ORO if u["rol"] == "owner" else ACENTO2
        else:
            est = fmt_restante(u["vence"])
            col = OK if u["acceso"] else SUB
        if puede_editar(self.app.yo, u) and u["id"] != self.app.yo["id"]:
            txt_b = "Desbanear" if u["baneado"] else "Banear"
            ban = tk.Label(fr, text=txt_b, bg=bg, fg=OK if u["baneado"] else ERROR, font=F(8, "bold"),
                           cursor="hand2", padx=px(6))
            ban.pack(side="right")
            ban.bind("<Button-1>", lambda e, u=u: (self._accion(
                u, "desbanear" if u["baneado"] else "banear",
                tr("{n} desbaneado" if u["baneado"] else "{n} baneado", n=u['nombre'])), "break")[1])
        tk.Label(fr, text=est, bg=bg, fg=col, font=F(9, "bold")).pack(side="right", padx=(0, px(6)))
        Insignia(fr, u["rol"], bg=bg).pack(side="right", padx=px(8))
        pend = [fr]
        while pend:
            w = pend.pop()
            if isinstance(w, tk.Label) and w.cget("text") in ("Banear", "Desbanear"):
                continue
            w.bind("<Button-1>", lambda e, u=u: self._seleccionar(u))
            pend.extend(w.winfo_children())

    def _seleccionar(self, u):
        self.sel = u["id"]
        self._pintar()
        self._mostrar(u)

    def _limpiar_det(self):
        for w in self.detalle.winfo_children()[1:]:
            w.destroy()

    def _vacio(self):
        self._limpiar_det()
        etiqueta(self.detalle, "Elige un usuario de la lista\npara ver sus opciones.", 10, justify="center").pack(pady=px(60))

    def _mostrar(self, u):
        self._limpiar_det()
        d = self.detalle
        yo = self.app.yo
        cab = tk.Frame(d, bg=PANEL)
        cab.pack(fill="x")
        Avatar(cab, u["nombre"], 44).pack(side="left")
        t = tk.Frame(cab, bg=PANEL)
        t.pack(side="left", padx=px(10))
        etiqueta(t, u["nombre"], 13, TEXTO, "bold").pack(anchor="w")
        etiqueta(t, f"ID {u['id']}", 9).pack(anchor="w")
        Insignia(cab, u["rol"]).pack(side="right")
        for k, v in (("Licencia", "Acceso total" if u["rol"] != "user" else fmt_restante(u["vence"])),
                     ("Vence", "—" if not u["vence"] or u["vence"] < 0 else fmt_fecha(u["vence"])),
                     ("Licencias usadas", str(u.get("licencias", 0))),
                     ("Última licencia", u.get("ultima_clave") or "—"),
                     ("Creada", fmt_fecha(u["creado"])), ("Última vez", fmt_fecha(u["visto"]))):
            f = tk.Frame(d, bg=PANEL)
            f.pack(fill="x", pady=(px(3), 0))
            etiqueta(f, k, 9).pack(side="left")
            etiqueta(f, v, 9, TEXTO, "bold").pack(side="right")
        if not puede_editar(yo, u):
            etiqueta(d, "No tienes permiso para modificar\nesta cuenta.", 9, AVISO, justify="center").pack(pady=px(20))
            return
        etiqueta(d, "DAR TIEMPO", 8, ACENTO2, "bold").pack(anchor="w", pady=(px(14), px(4)))
        dur = SelectorDuracion(d, presets=[("1 día", 86400), ("1 semana", 604800), ("1 mes", 2592000),
                                           ("1 año", 31536000), ("Por vida", -1)], cols=3, ancho_chip=94)
        dur.pack(anchor="w")

        def dar():
            try:
                s = dur.segundos()
            except ValueError as e:
                return self.app.toast.mostrar(str(e), "error")
            self._accion(u, "dar_tiempo", tr("Se agregó {d}", d=fmt_duracion(s)), duracion=s)
        Boton(d, "Agregar tiempo", dar, ancho=284, alto=38).pack(pady=(px(8), px(10)))
        g = tk.Frame(d, bg=PANEL)
        g.pack()
        acciones = [("Quitar licencia", lambda: self._accion(u, "quitar_licencia", "Licencia quitada"))]
        if u["id"] != yo["id"]:
            acciones.append(("Desbanear" if u["baneado"] else "Banear",
                             lambda: self._accion(u, "desbanear" if u["baneado"] else "banear",
                                                  "Usuario desbaneado" if u["baneado"] else "Usuario baneado")))
        if yo["rol"] == "owner":
            if u["admin_vence"] is not None:
                acciones.append(("Quitar admin", lambda: self._accion(u, "quitar_admin", "Ya no es admin")))
            else:
                acciones.append(("Hacer admin", lambda: self._accion(u, "hacer_admin", "Ahora es admin")))
        if u["id"] != yo["id"]:
            acciones.append(("Eliminar cuenta", None))
        for i, (txt, cb) in enumerate(acciones):
            b = Boton(g, txt, cb, ancho=140, alto=34, estilo="sec", fuente=F(9, "bold"))
            b.grid(row=i // 2, column=i % 2, padx=px(1), pady=px(1))
            if cb is None:
                b.set_color(mezclar(PANEL2, ERROR, 0.25))
                b.command = lambda b=b: self._eliminar(u, b)

    def _eliminar(self, u, b):
        if b.texto != "¿Seguro?":
            b.set_texto("¿Seguro?")
            b.set_color(ERROR)
            return
        self._accion(u, "eliminar", "Cuenta eliminada")

    def _accion(self, u, accion, msg, **extra):
        datos = {"id": u["id"], "accion": accion, **extra}

        def ok(r):
            self.app.toast.mostrar(msg, "ok")
            if r.get("eliminado"):
                self.sel = None
            self.cargar()
            if u["id"] == self.app.yo["id"]:
                self.app.refrescar_yo()
        self.app.api("POST", "/api/admin/usuario", datos, seguro(ok))


class PaginaCuenta(Pagina):
    titulo, subtitulo = "Cuenta", "Tu información, licencia y ajustes."

    def __init__(self, master, app, principal):
        super().__init__(master, app, principal)
        yo = app.yo
        izq = Tarjeta(self.cuerpo, pad=20)
        izq.pack(side="left", fill="both", expand=True)
        c = izq.cuerpo
        cab = tk.Frame(c, bg=PANEL)
        cab.pack(fill="x")
        Avatar(cab, yo["nombre"], 56).pack(side="left")
        t = tk.Frame(cab, bg=PANEL)
        t.pack(side="left", padx=px(12))
        etiqueta(t, yo["nombre"], 15, TEXTO, "bold").pack(anchor="w")
        Insignia(t, yo["rol"]).pack(anchor="w", pady=(px(4), 0))
        f = tk.Frame(c, bg=PANEL2, padx=px(12), pady=px(8))
        f.pack(fill="x", pady=(px(16), 0))
        etiqueta(f, "Tu ID", 8).pack(side="left")
        etiqueta(f, str(yo["id"]), 12, ACENTO2, "bold").pack(side="left", padx=px(10))
        Boton(f, "Copiar", lambda: app.copiar(str(yo["id"]), "ID copiado"), ancho=72, alto=28, estilo="sec",
              fuente=F(8, "bold"), bg=PANEL2).pack(side="right")
        self.lbl_lic = etiqueta(c, "", 10, TEXTO, "bold")
        etiqueta(c, "Licencia", 9).pack(anchor="w", pady=(px(14), 0))
        self.lbl_lic.pack(anchor="w")
        self._pintar_lic()
        etiqueta(c, "AGREGAR OTRA LICENCIA", 8, ACENTO2, "bold").pack(anchor="w", pady=(px(18), px(4)))
        etiqueta(c, "El tiempo se suma al que ya tienes.", 8).pack(anchor="w")
        f = tk.Frame(c, bg=PANEL)
        f.pack(fill="x", pady=(px(6), 0))
        self.c_lic = Campo(f, ancho=250, alto=38, fuente=(MONO, 11, "bold"), justify="center")
        self.c_lic.pack(side="left")
        formatear_clave(self.c_lic)
        self.c_lic.al_enter(self._canjear)
        Boton(f, "Canjear", self._canjear, ancho=96, alto=38).pack(side="left", padx=(px(6), 0))

        etiqueta(c, "CAMBIAR CONTRASEÑA", 8, ACENTO2, "bold").pack(anchor="w", pady=(px(18), px(4)))
        self.c_pw_act = Campo(c, ancho=250, alto=38, show="•", ojo=True)
        self.c_pw_act.pack(anchor="w")
        etiqueta(c, "Actual", 8).pack(anchor="w")
        f = tk.Frame(c, bg=PANEL)
        f.pack(fill="x", pady=(px(4), 0))
        self.c_pw_nueva = Campo(f, ancho=250, alto=38, show="•", ojo=True)
        self.c_pw_nueva.pack(side="left")
        self.b_pw = Boton(f, "Cambiar", self._cambiar_pw, ancho=96, alto=38, estilo="sec")
        self.b_pw.pack(side="left", padx=(px(6), 0))
        etiqueta(c, "Nueva (mínimo 6 caracteres)", 8).pack(anchor="w")
        self.c_pw_act.al_enter(lambda: self.c_pw_nueva.e.focus_set())
        self.c_pw_nueva.al_enter(self._cambiar_pw)

        der = Tarjeta(self.cuerpo, pad=20)
        der.pack(side="left", fill="both", padx=(px(14), 0))
        d = der.cuerpo
        etiqueta(d, "ATAJOS DE TECLADO", 8, ACENTO2, "bold").pack(anchor="w")
        self.b_hk = {}
        for k, txt in (("hk_mouse", "Mouse"), ("hk_teclado", "Teclado"), ("hk_stop", "Detener todo")):
            f = tk.Frame(d, bg=PANEL)
            f.pack(fill="x", pady=px(4))
            etiqueta(f, txt, 10, TEXTO).pack(side="left")
            b = Boton(f, nombre_vk(app.ajustes()[k]), lambda k=k: self._hk(k), ancho=96, alto=32, estilo="sec",
                      fuente=F(9, "bold"))
            b.pack(side="right", padx=(px(30), 0))
            self.b_hk[k] = b
        self.capt = None
        etiqueta(d, "AL INICIAR CON EL BOTÓN", 8, ACENTO2, "bold").pack(anchor="w", pady=(px(16), px(4)))
        ops = [0, 1, 2, 3, 5]
        Segmentado(d, [f"{o} s" for o in ops], ops.index(app.ajustes()["retraso"]) if app.ajustes()["retraso"] in ops else 2,
                   command=lambda i: self._set("retraso", ops[i]), ancho=250, alto=32).pack(anchor="w")
        etiqueta(d, "Espera para que muevas el mouse.", 8).pack(anchor="w")
        f = tk.Frame(d, bg=PANEL)
        f.pack(fill="x", pady=(px(14), 0))
        etiqueta(f, "Ventana siempre encima", 10, TEXTO).pack(side="left")
        Interruptor(f, app.ajustes()["encima"], command=self._encima).pack(side="right")
        etiqueta(d, "PROTECCIÓN", 8, ACENTO2, "bold").pack(anchor="w", pady=(px(16), px(2)))
        for clave, txt, ayuda in (("esquina", "Esquina de emergencia", "Mouse a la esquina superior izquierda = parar"),
                                  ("vigia", "Parar si algo se traba", "Detiene todo si un clic o la ventana se congela")):
            f = tk.Frame(d, bg=PANEL)
            f.pack(fill="x", pady=px(4))
            t = tk.Frame(f, bg=PANEL)
            t.pack(side="left")
            etiqueta(t, txt, 10, TEXTO).pack(anchor="w")
            etiqueta(t, ayuda, 8).pack(anchor="w")
            Interruptor(f, app.ajustes()[clave], command=lambda v, c=clave: self._proteccion(c, v)).pack(side="right")
        etiqueta(d, "APARIENCIA", 8, ACENTO2, "bold").pack(anchor="w", pady=(px(16), px(4)))
        f = tk.Frame(d, bg=PANEL)
        f.pack(fill="x", pady=px(3))
        etiqueta(f, "Tema", 10, TEXTO).pack(side="left")
        Segmentado(f, ["Oscuro", "Claro"], 0 if TEMA == "oscuro" else 1,
                   command=lambda i: self._tema("oscuro" if i == 0 else "claro"), ancho=160, alto=32).pack(side="right")
        f = tk.Frame(d, bg=PANEL)
        f.pack(fill="x", pady=px(3))
        etiqueta(f, "Idioma", 10, TEXTO).pack(side="left")
        Segmentado(f, ["Español", "Inglés"], 0 if IDIOMA == "es" else 1,
                   command=lambda i: self._idioma("es" if i == 0 else "en"), ancho=160, alto=32).pack(side="right")
        f = tk.Frame(d, bg=PANEL)
        f.pack(fill="x", pady=px(3))
        etiqueta(f, "Sonido al iniciar y detener", 10, TEXTO).pack(side="left")
        Interruptor(f, SONIDO["on"], command=self._sonido).pack(side="right")
        Boton(d, "Cerrar sesión", app.cerrar_sesion, ancho=250, alto=40,
              color=mezclar(PANEL, ERROR, 0.7)).pack(side="bottom", pady=(px(14), 0))

    def _pintar_lic(self):
        yo = self.app.yo
        if yo["rol"] != "user":
            txt = tr("Acceso total ({r})", r=yo["rol"])
        elif yo["vence"] is not None and yo["vence"] < 0:
            txt = tr("De por vida")
        else:
            txt = tr("{r} restantes · vence {f}", r=fmt_restante(yo['vence']), f=fmt_fecha(yo['vence']))
        self.lbl_lic.config(text=txt)

    def al_mostrar(self):
        self._pintar_lic()

    def _canjear(self):
        if len(re.sub(r"[^A-Z0-9]", "", self.c_lic.get())) != 18:
            return self.app.toast.mostrar("La licencia está incompleta", "error")

        def ok(r):
            self.c_lic.set("")
            if r["tipo"] == "admin":
                self.app.toast.mostrar("Ahora eres administrador", "ok")
            else:
                self.app.toast.mostrar(tr("Se agregó {d}", d=fmt_duracion(r['duracion'])), "ok")
            self.app.aplicar_yo(r["yo"])
        self.app.api("POST", "/api/canjear", {"clave": self.c_lic.get()}, seguro(ok))

    def _cambiar_pw(self):
        if not self.b_pw.habilitado:
            return
        actual, nueva = self.c_pw_act.get(), self.c_pw_nueva.get()
        if not actual:
            return self.app.toast.mostrar("Escribe tu contraseña actual", "error")
        if len(nueva) < 6:
            return self.app.toast.mostrar("La nueva debe tener al menos 6 caracteres", "error")
        nombre = self.app.yo["nombre"]
        self.b_pw.set_habilitado(False)

        def listo(r=None, error=None):
            self.b_pw.set_habilitado(True)
            if error:
                return self.app.toast.mostrar(error.msg, "error")
            self.c_pw_act.set("")
            self.c_pw_nueva.set("")
            self.app.toast.mostrar("Contraseña cambiada. Se cerró la sesión en tus otras PCs.", "ok", 4000)
        self.app.api("POST", "/api/cambiar_pw", {"actual": prehash(nombre, actual), "nueva": prehash(nombre, nueva)},
                     seguro(lambda r: listo(r)), seguro(lambda e: listo(error=e)))

    def _set(self, k, v):
        self.app.ajustes()[k] = v
        self.app.local.guardar()

    def _proteccion(self, clave, v):
        self._set(clave, v)
        self.app.aplicar_atajos()
        self.principal.refrescar_atajos()

    def _encima(self, v):
        self._set("encima", v)
        self.app.attributes("-topmost", v)

    def _tema(self, nombre):
        self.app.local.datos["tema"] = nombre
        self.app.local.guardar()
        self.app.after(60, lambda: self.app.recargar(self.principal.actual))

    def _idioma(self, codigo):
        global IDIOMA
        IDIOMA = codigo
        self.app.local.datos["idioma"] = codigo
        self.app.local.guardar()
        self.app.after(60, lambda: self.app.recargar(self.principal.actual))

    def _sonido(self, v):
        SONIDO["on"] = bool(v)
        self.app.local.datos["sonido"] = bool(v)
        self.app.local.guardar()
        if v:
            reproducir("on")

    def _hk(self, k):
        if self.capt:
            return
        self.capt = k
        self.app.vigilante.habilitado = False
        self.b_hk[k].set_texto("Presiona…")
        self.b_hk[k].set_color(ACENTO)
        self.app.focus_set()
        self.app.bind_all("<KeyPress>", self._hk_tecla)

    def _hk_tecla(self, e):
        k = self.capt
        vk = e.keycode if ES_WINDOWS else 0x78
        aj = self.app.ajustes()
        if vk in [v for kk, v in aj.items() if kk.startswith("hk_") and kk != k]:
            self.app.toast.mostrar("Esa tecla ya se usa en otro atajo", "aviso")
        else:
            aj[k] = vk
            self.app.local.guardar()
            self.app.aplicar_atajos()
            self.principal.refrescar_atajos()
            self.app.toast.mostrar(tr("Atajo cambiado a {k}", k=nombre_vk(vk)), "ok")
        self.b_hk[k].set_texto(nombre_vk(aj[k]))
        self.b_hk[k].set_color(PANEL2)
        self.capt = None
        self.app.unbind_all("<KeyPress>")
        return "break"


class PantallaPrincipal(tk.Frame):
    def __init__(self, app, inicio=0):
        super().__init__(app, bg=BG)
        self.app, self.anim = app, Anim(self)
        self._inicio = inicio
        yo = app.yo
        es_admin = yo["rol"] in ("owner", "admin")

        side = tk.Frame(self, bg=PANEL, width=px(206))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(self, bg=BORDE, width=max(1, px(1))).pack(side="left", fill="y")
        cab = tk.Frame(side, bg=PANEL)
        cab.pack(fill="x", padx=px(16), pady=(px(20), px(22)))
        Logo(cab, 38).pack(side="left")
        t = tk.Frame(cab, bg=PANEL)
        t.pack(side="left", padx=px(10))
        etiqueta(t, "AutoClicker", 12, TEXTO, "bold").pack(anchor="w")
        etiqueta(t, "AL  ·  v" + APP_VERSION, 8, ACENTO2, "bold").pack(anchor="w")

        clases = [("◎", "Mouse", PaginaMouse), ("⌨", "Teclado", PaginaTeclado)]
        if es_admin:
            clases += [("✦", "Licencias", PaginaLicencias), ("☰", "Usuarios", PaginaUsuarios)]
        clases.append(("⚙", "Cuenta", PaginaCuenta))
        self.nav = Navegacion(side, [(a, b) for a, b, _ in clases], self.ir)
        self.nav.pack(padx=px(14))

        est = tk.Frame(side, bg=PANEL)
        est.pack(side="bottom", fill="x", padx=px(14), pady=px(16))
        self.puntos = {}
        for clave, txt in (("mouse", "Mouse"), ("teclado", "Teclado")):
            f = tk.Frame(est, bg=PANEL)
            f.pack(fill="x", pady=px(2))
            dot = tk.Label(f, text="●", bg=PANEL, fg=BORDE, font=F(9))
            dot.pack(side="left")
            tk.Label(f, text=tr(txt), bg=PANEL, fg=SUB, font=F(9)).pack(side="left", padx=px(6))
            st = tk.Label(f, text=tr("Detenido"), bg=PANEL, fg=SUB, font=F(8))
            st.pack(side="right")
            self.puntos[clave] = (dot, st)
        self.tarjeta_usr = tk.Frame(est, bg=PANEL)
        self.tarjeta_usr.pack(fill="x", pady=(px(10), 0))
        self.refrescar_usuario()

        self.area = tk.Frame(self, bg=BG)
        self.area.pack(side="left", fill="both", expand=True)
        self.paginas = [cls(self.area, app, self) for _, _, cls in clases]
        self.mouse, self.teclado = self.paginas[0], self.paginas[1]
        self.actual = None
        self._parp = 0
        inicio = self._inicio if self._inicio < len(self.paginas) else 0
        self.after(20, seguro(lambda: self.ir(inicio, False)))

    def refrescar_usuario(self):
        for w in self.tarjeta_usr.winfo_children():
            w.destroy()
        yo = self.app.yo
        t = Tarjeta(self.tarjeta_usr, pad=10, color=PANEL2, borde=PANEL2)
        t.pack(fill="x")
        c = t.cuerpo
        Avatar(c, yo["nombre"], 32, bg=PANEL2).pack(side="left")
        u = tk.Frame(c, bg=PANEL2)
        u.pack(side="left", padx=px(8))
        tk.Label(u, text=yo["nombre"], bg=PANEL2, fg=TEXTO, font=F(10, "bold")).pack(anchor="w")
        if yo["rol"] == "user":
            tk.Label(u, text="● " + fmt_restante(yo["vence"]), bg=PANEL2, fg=OK, font=F(8)).pack(anchor="w")
        else:
            Insignia(u, yo["rol"], bg=PANEL2).pack(anchor="w", pady=(px(2), 0))

    def ir(self, i, animar=True):
        if i == self.actual:
            return
        if self.actual is not None:
            self.paginas[self.actual].place_forget()
        self.actual = i
        self.nav.seleccionar(i, animar)
        p, pad = self.paginas[i], px(24)
        p.al_mostrar()

        def entrar(t):
            p.place(x=pad, y=int(pad + px(36) * (1 - t)), relwidth=1, relheight=1, width=-2 * pad, height=-2 * pad)
        if animar:
            self.anim.run("pag", 340, entrar)
        else:
            entrar(1)

    def refrescar_atajos(self):
        self.mouse.refrescar_atajo()
        self.teclado.refrescar_atajo()

    def capturando(self):
        return self.teclado.capturando or any(getattr(p, "capt", None) for p in self.paginas)

    def alternar(self, clave, desde_boton=False):
        pag = self.mouse if clave == "mouse" else self.teclado
        motor = self.app.motores[clave]
        if pag.power.estado == "cuenta":
            pag.power.cancelar_cuenta()
            return
        if motor.activo:
            motor.detener()
            return
        if not self.app.yo.get("acceso"):
            return self.app.toast.mostrar("Tu licencia no está activa", "error")
        if not ES_WINDOWS:
            return self.app.toast.mostrar("Los clics solo funcionan en Windows", "error")
        try:
            accion, iv, rep = pag.preparar()
        except ValueError as e:
            return self.app.toast.mostrar(str(e), "error")
        self.app.guardar_config()

        def arrancar():
            motor.iniciar(accion, iv, rep)
            pag._mostrado, pag._estaba = 0, True
            pag.power.set_on(True)
            reproducir("on")
        r = self.app.ajustes()["retraso"]
        if desde_boton and r > 0:
            pag.power.cuenta_regresiva(r, arrancar)
        else:
            arrancar()

    def detener_todo(self, msg=True):
        for clave, m in self.app.motores.items():
            (self.mouse if clave == "mouse" else self.teclado).power.cancelar_cuenta()
            m.detener()
        if msg:
            self.app.toast.mostrar("Todo detenido", "aviso", 1500)

    def actualizar(self):
        self._parp = (self._parp + 1) % 16
        for clave, pag in (("mouse", self.mouse), ("teclado", self.teclado)):
            m = self.app.motores[clave]
            pag.actualizar(m)
            dot, st = self.puntos[clave]
            if m.activo:
                dot.config(fg=OK if self._parp < 10 else mezclar(OK, PANEL, 0.6))
                st.config(text=tr("Activo"), fg=OK)
            else:
                dot.config(fg=BORDE)
                st.config(text=tr("Detenido"), fg=SUB)

    def config_actual(self):
        return {"mouse": self.mouse.obtener_config(), "teclado": self.teclado.obtener_config()}


AJUSTES_DEF = {"hk_mouse": 0x75, "hk_teclado": 0x76, "hk_stop": 0x77, "retraso": 2, "encima": False,
               "esquina": True, "vigia": True}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        global ESCALA, IDIOMA
        self.local = Local()
        aplicar_tema(self.local.datos.get("tema", "oscuro"))
        IDIOMA = self.local.datos.get("idioma", "es")
        SONIDO["on"] = bool(self.local.datos.get("sonido", True))
        cargar_logo_cache(self.local)
        _CACHE.clear()
        _FUENTES.clear()
        try:
            ESCALA = max(1.0, min(3.0, self.winfo_fpixels("1i") / 96.0)) if ES_WINDOWS else 1.0
        except Exception:
            ESCALA = 1.0
        self.title(APP_NOMBRE)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        ancho, alto = min(px(1060), sw - px(20)), min(px(680), sh - px(80))
        x, y = max(0, (sw - ancho) // 2), max(0, (sh - alto) // 2 - px(20))
        self.geometry(f"{ancho}x{alto}+{x}+{y}")
        self.minsize(min(px(990), ancho), min(px(640), alto))
        self.configure(bg=BG)
        self._icono()
        self.aplicar_titulo()
        self.cliente = ClienteAPI()
        self.toast = Toast(self)
        self.anim = Anim(self)
        self.yo = None
        self.pantalla = None
        self.capa_update = None
        self.conexion_iniciada = False
        self._auto_login = False
        self._ultimo_refresco = 0.0
        self.remota = self.local.datos.get("remota") or {}
        self.cliente.usar(url_servidor(self.remota))
        self.motores = {"mouse": Motor(), "teclado": Motor()}
        self.cola_atajos = queue.Queue()
        self.cola_ui = queue.Queue()
        self.vigilante = VigilanteAtajos(self.cola_atajos, self.motores)
        self.vigilante.start()
        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.bind_all("<MouseWheel>", self._rueda)
        self.mostrar(PantallaAuth)
        try:
            self.attributes("-alpha", 0.0)
            self.anim.run("alpha", 450, lambda t: self.attributes("-alpha", t))
        except tk.TclError:
            pass


        threading.Thread(target=lambda: self.cola_ui.put((self._config_nueva, leer_config_remota(), False, None)),
                         daemon=True).start()
        if self.remota:
            self.after(1, self._iniciar_conexion)
        self._tick()
        self.after(60_000, self._latido)


    def _update_obligatoria(self):
        return bool(self.remota.get("obligatoria")) and \
            version_tupla(self.remota.get("version", "0")) > version_tupla(APP_VERSION)

    def _iniciar_conexion(self):
        if self.conexion_iniciada:
            return
        self.conexion_iniciada = True
        if isinstance(self.pantalla, PantallaAuth):
            self.pantalla.verificar_servidor()

    def intentar_auto_login(self):
        tok = self.local.datos.get("token")
        if (not tok or not self.local.datos.get("recordar", True) or self._auto_login
                or not isinstance(self.pantalla, PantallaAuth) or self._update_obligatoria()):
            return
        self._auto_login = True
        self.cliente.token = tok

        def fin_ok(r):
            self._auto_login = False
            self.entrar(tok, r["yo"], True)

        def fin_error(e):
            self._auto_login = False
            if e.codigo in (401, 403):
                self.local.datos["token"] = None
                self.local.guardar()
        self.api("GET", "/api/yo", None, fin_ok, fin_error)

    def _config_nueva(self, remota):
        if remota:
            cambio = url_servidor(remota) != self.cliente.url
            self.remota = remota
            self.local.datos["remota"] = remota
            self.local.guardar()
            self.cliente.usar(url_servidor(remota))
            if cambio and self.conexion_iniciada and isinstance(self.pantalla, PantallaAuth):
                self.pantalla.verificar_servidor()
            threading.Thread(target=lambda: sincronizar_logo(
                remota, self.local, lambda: self.cola_ui.put((lambda _r: self._icono(), None, False, None))),
                daemon=True).start()
        self._iniciar_conexion()
        if self.remota.get("anuncio"):
            self.after(1500, lambda: self.toast.mostrar(str(self.remota["anuncio"])[:120], "info", 6000))
        if version_tupla(self.remota.get("version", "0")) > version_tupla(APP_VERSION):
            self.after(900, self._ofrecer_actualizacion)

    def _ofrecer_actualizacion(self):
        if self.capa_update is not None:
            return
        r = self.remota
        obligatoria = bool(r.get("obligatoria"))
        capa = self.capa_update = tk.Frame(self, bg=BG)
        capa.place(x=0, y=0, relwidth=1, relheight=1)
        t = Tarjeta(capa, pad=28)
        t.place(relx=0.5, rely=0.5, anchor="center")
        c = t.cuerpo
        Logo(c, 52).pack()
        etiqueta(c, "Nueva versión disponible", 16, TEXTO, "bold").pack(pady=(px(10), px(2)))
        etiqueta(c, f"v{APP_VERSION}  →  v{r.get('version')}", 11, ACENTO2, "bold").pack()
        if r.get("notas"):
            etiqueta(c, str(r["notas"])[:400], 9, SUB, wraplength=px(340), justify="center").pack(pady=(px(8), 0))
        self.lbl_desc = etiqueta(c, "", 9, SUB)
        self.lbl_desc.pack(pady=(px(10), 0))
        b = Boton(c, "Actualizar ahora", None, ancho=300, alto=44, fuente=F(11, "bold"))
        b.command = lambda: self._actualizar(b)
        b.pack(pady=(px(4), px(6)))
        if not obligatoria:
            def despues():
                capa.destroy()
                self.capa_update = None
            enlace(c, "Más tarde", despues).pack()
        self.toast.arriba()

    def _actualizar(self, boton):
        url = self.remota.get("descarga") or \
            f"https://github.com/{GITHUB_REPO}/releases/latest/download/AutoClickerAL.exe"
        if not getattr(sys, "frozen", False):
            import webbrowser
            webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/latest")
            return
        boton.set_habilitado(False)
        boton.set_texto("Descargando…")
        destino = sys.executable + ".nuevo"
        prog = {"p": 0.0, "fin": None}

        def bajar():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "AutoClickerAL"})
                with urllib.request.urlopen(req, timeout=30) as r, open(destino, "wb") as f:
                    total = int(r.headers.get("Content-Length") or 0)
                    hecho = 0
                    while True:
                        bloque = r.read(256 * 1024)
                        if not bloque:
                            break
                        f.write(bloque)
                        hecho += len(bloque)
                        prog["p"] = hecho / total if total else 0
                with open(destino, "rb") as f:
                    es_exe = f.read(2) == b"MZ"
                tam = os.path.getsize(destino)
                if not es_exe or tam < 1_000_000 or (total and tam != total):
                    raise RuntimeError("el archivo llegó incompleto")
                prog["fin"] = "ok"
            except PermissionError:
                prog["fin"] = "No tengo permiso de escribir en la carpeta del programa. Descárgalo desde GitHub."
            except Exception as e:
                prog["fin"] = f"No se pudo descargar ({e})"
                try:
                    os.remove(destino)
                except OSError:
                    pass

        def vigilar():
            if prog["fin"] is None:
                self.lbl_desc.config(text=f"{int(prog['p'] * 100)} %")
                return self.after(150, vigilar)
            if prog["fin"] != "ok":
                boton.set_habilitado(True)
                boton.set_texto("Reintentar")
                return self.lbl_desc.config(text=prog["fin"], fg=ERROR)
            self.lbl_desc.config(text=tr("Reiniciando…"), fg=OK)
            self.after(400, lambda: self._reemplazar_exe(destino))
        threading.Thread(target=bajar, daemon=True).start()
        vigilar()

    def _reemplazar_exe(self, nuevo):
        import subprocess
        import tempfile
        exe = sys.executable
        bat = os.path.join(tempfile.gettempdir(), "actualizar_autoclicker_al.bat")
        with open(bat, "w", encoding="mbcs" if ES_WINDOWS else "utf-8") as f:
            f.write(f'''@echo off
set n=0
:esperar
ping 127.0.0.1 -n 2 >nul
move /y "{nuevo}" "{exe}" >nul 2>&1
if errorlevel 1 (
  set /a n+=1
  if %n% lss 20 goto esperar
)
start "" "{exe}"
del "%~f0"
''')
        subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000)
        self.cerrar()

    def report_callback_exception(self, exc, val, tb):
        import traceback
        texto = "".join(traceback.format_exception(exc, val, tb))
        registrar_error(texto)
        try:
            self.toast.mostrar(f"Error: {val}"[:110], "error", 5000)
        except Exception:
            pass

    def _icono(self):
        try:
            if LOGO["pil"] is not None:
                im = ImageOps.fit(LOGO["pil"], (64, 64), Image.LANCZOS)
            else:
                im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                d = ImageDraw.Draw(im)
                d.rounded_rectangle((0, 0, 63, 63), radius=16, fill=ACENTO)
                d.polygon([(20, 14), (20, 50), (29, 41), (36, 54), (42, 51), (35, 38), (47, 38)], fill="#ffffff")
            self._ico = ImageTk.PhotoImage(im)
            self.iconphoto(True, self._ico)
        except Exception:
            pass

    def aplicar_titulo(self):
        if not ES_WINDOWS:
            return
        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            dwm = ctypes.windll.dwmapi
            modo = ctypes.c_int(1 if ES_OSCURO else 0)
            for attr in (20, 19):
                try:
                    dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(modo), ctypes.sizeof(modo))
                except Exception:
                    pass

            def col(hexc):
                r, g, b = _rgb(hexc)
                return ctypes.c_int(r | (g << 8) | (b << 16))
            for attr, color in ((35, PANEL), (36, TEXTO), (34, BORDE)):
                try:
                    c = col(color)
                    dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(c), 4)
                except Exception:
                    pass
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
        except Exception:
            pass

    def recargar(self, pagina=0):
        aplicar_tema(self.local.datos.get("tema", "oscuro"))
        self.configure(bg=BG)
        self.aplicar_titulo()
        self.toast = Toast(self)
        if self.capa_update is not None:
            self.capa_update = None
        destino = PantallaPrincipal if isinstance(self.pantalla, PantallaPrincipal) else PantallaAuth
        vieja = self.pantalla
        kw = {"inicio": pagina} if destino is PantallaPrincipal else {}
        self.pantalla = destino(self, **kw)
        self.pantalla.place(x=0, y=0, relwidth=1, relheight=1)
        if vieja is not None:
            vieja.destroy()

    def _rueda(self, e):
        w = self.winfo_containing(e.x_root, e.y_root)
        while w is not None:
            if isinstance(w, ListaScroll):
                return w._rueda(e)
            w = getattr(w, "master", None)


    def api(self, metodo, ruta, datos=None, ok=None, err=None, token=None):
        def trabajo():
            try:
                self.cola_ui.put((ok, self.cliente.llamar(metodo, ruta, datos, token), False, err))
            except ErrorAPI as e:
                self.cola_ui.put((ok, e, True, err))
        threading.Thread(target=trabajo, daemon=True).start()

    def _resolver(self, ok, val, es_error, err):
        if not es_error:
            if ok:
                ok(val)
            return
        if val.codigo in (401, 403) and self.yo and isinstance(self.pantalla, (PantallaPrincipal, PantallaLicencia)):
            self.toast.mostrar(val.msg, "error", 3500)
            return self.cerrar_sesion(avisar=False)
        if err:
            err(val)
        else:
            self.toast.mostrar(val.msg, "error")


    def entrar(self, token, yo, recordar, nuevo=False):
        if not isinstance(self.pantalla, PantallaAuth):
            return
        self.cliente.token, self.yo = token, yo
        self.local.datos.update(token=token if recordar else None, recordar=recordar, ultimo_usuario=yo["nombre"])
        self.local.guardar()
        if nuevo:
            self.toast.mostrar("Cuenta creada. ¡Bienvenido!", "ok")
        elif yo["acceso"]:
            self.toast.mostrar(tr("Hola, {n}", n=yo['nombre']), "ok")
        self.mostrar(PantallaPrincipal if yo["acceso"] else PantallaLicencia)

    def aplicar_yo(self, nuevo):
        viejo, self.yo = self.yo, nuevo
        p = self.pantalla
        if not isinstance(p, PantallaPrincipal):
            return
        if not nuevo["acceso"]:
            p.detener_todo(False)
            self.vigilante.habilitado = False
            self.mostrar(PantallaLicencia, aviso="Tu licencia venció. Activa una nueva para seguir.")
        elif viejo and viejo["rol"] != nuevo["rol"]:
            p.detener_todo(False)
            self.guardar_config()
            self.mostrar(PantallaPrincipal)
        else:
            p.refrescar_usuario()

    def refrescar_yo(self):
        if not self.yo:
            return
        self._ultimo_refresco = time.monotonic()
        self.api("GET", "/api/yo", None, seguro(lambda r: self.aplicar_yo(r["yo"])), lambda e: None)

    def _latido(self):

        if isinstance(self.pantalla, PantallaPrincipal):
            self.refrescar_yo()
        self.after(60_000, self._latido)

    def _revisar_vencimiento(self):
        yo = self.yo
        if (yo and yo["rol"] == "user" and yo.get("vence") and yo["vence"] > 0 and yo["vence"] < time.time()
                and time.monotonic() - self._ultimo_refresco > 10):
            self.refrescar_yo()

    def cerrar_sesion(self, avisar=True):
        self.guardar_config()
        for m in self.motores.values():
            m.detener()
        self.vigilante.habilitado = False
        self.vigilante.atajos = {}
        try:
            self.attributes("-topmost", False)
        except tk.TclError:
            pass
        if avisar and self.cliente.token:
            self.api("POST", "/api/salir", {}, None, lambda e: None, token=self.cliente.token)
        self.cliente.token = None
        self.local.datos["token"] = None
        self.local.guardar()
        self.yo = None
        self.mostrar(PantallaAuth, direccion=-1)


    def mostrar(self, clase, direccion=1, **kw):
        vieja = self.pantalla
        nueva = clase(self, **kw)
        self.pantalla = nueva
        W = self.winfo_width() if self.winfo_width() > 1 else px(1060)
        if vieja is None:
            nueva.place(x=0, y=0, relwidth=1, relheight=1)
        else:
            nueva.place(x=W * direccion, y=0, relwidth=1, relheight=1)

            def fn(t):
                nueva.place_configure(x=int(W * direccion * (1 - t)))
                vieja.place_configure(x=int(-W * direccion * t))
            self.anim.run("pantalla", 460, fn, ease=ease_in_out, done=vieja.destroy)
        if self.capa_update is not None:
            tk.Misc.tkraise(self.capa_update)
        self.toast.arriba()

    def copiar(self, texto, msg):
        self.clipboard_clear()
        self.clipboard_append(texto)
        self.toast.mostrar(msg, "ok")


    def ajustes(self):
        aj = self.local.cfg(self.yo["id"] if self.yo else 0).setdefault("ajustes", {})
        for k, v in AJUSTES_DEF.items():
            aj.setdefault(k, v)
        return aj

    def vks_atajo(self):
        return [v for k, v in self.ajustes().items() if k.startswith("hk_")]

    def aplicar_atajos(self):
        aj = self.ajustes()
        self.vigilante.atajos = {"mouse": aj["hk_mouse"], "teclado": aj["hk_teclado"], "stop": aj["hk_stop"]}
        self.vigilante.esquina = bool(aj.get("esquina", True))
        self.vigilante.vigia = bool(aj.get("vigia", True))

    def guardar_config(self):
        if self.yo and isinstance(self.pantalla, PantallaPrincipal):
            self.local.cfg(self.yo["id"]).update(self.pantalla.config_actual())
        self.local.guardar()


    def _tick(self):
        self.vigilante.latido_ui = time.monotonic()
        try:
            while not self.cola_ui.empty():
                ok, val, es_err, err = self.cola_ui.get_nowait()
                try:
                    self._resolver(ok, val, es_err, err)
                except tk.TclError:
                    pass
                except Exception:
                    self.report_callback_exception(*sys.exc_info())
            p = self.pantalla
            if isinstance(p, PantallaPrincipal):
                if not self.vigilante.atajos:
                    self.aplicar_atajos()
                    self.attributes("-topmost", self.ajustes()["encima"])
                self.vigilante.habilitado = not p.capturando()
                while not self.cola_atajos.empty():
                    ev = self.cola_atajos.get_nowait()
                    if ev == "stop":
                        p.detener_todo()
                    elif ev == "proteccion":
                        p.detener_todo(False)
                    else:
                        p.alternar(ev)
                p.actualizar()
                self._revisar_vencimiento()
            else:
                while not self.cola_atajos.empty():
                    self.cola_atajos.get_nowait()
        finally:
            self.after(60, self._tick)

    def cerrar(self):
        for m in self.motores.values():
            m.detener()
        self.guardar_config()
        self.destroy()


def unica_instancia():
    if not ES_WINDOWS:
        return True
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    globals()["_MUTEX"] = k32.CreateMutexW(None, False, "Local\\AutoClickerAL_unico")
    if ctypes.get_last_error() != 183:
        return True
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    hwnd = user32.FindWindowW(None, APP_NOMBRE)
    if hwnd:
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
    return False


if __name__ == "__main__":
    if Image is None:
        import tkinter.messagebox as mb
        tk.Tk().withdraw()
        mb.showerror(APP_NOMBRE, "Falta la librería Pillow.\nAbre CMD y ejecuta:  pip install pillow")
        sys.exit(1)
    if unica_instancia():
        App().mainloop()
