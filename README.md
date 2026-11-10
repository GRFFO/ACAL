# AutoClicker AL

Autoclicker de mouse y teclado con cuentas, licencias y panel de administración.
Todo se controla desde este repositorio de GitHub.

```
cliente/      el programa (AutoClickerAL.py) que usan tus amigos
servidor/     el servidor de cuentas y licencias (va en tu hosting)
config.json   dirección del servidor, versión actual y anuncios
.github/      compila el .exe automáticamente en cada versión nueva
```

---

## 1. Crear el repositorio (una sola vez)
1. En GitHub crea un repositorio **público** llamado `ACAL`. Tiene que ser público para que el programa pueda leer `config.json` y descargar las actualizaciones.
2. Sube **todo** el contenido de esta carpeta, incluida la carpeta `.github`.

## 2. Servidor en el hosting
**Opción A: que el hosting lo descargue de GitHub (recomendada)**
1. En el panel (pestaña *Startup*), llena estos campos:
   - **Git Repo Address**: `https://github.com/GRFFO/ACAL`
   - **Auto Update**: `1`. Con esto, cada vez que reinicies el servidor descarga los cambios del repositorio.
   - **App py file** (o *Startup file*): `servidor/app.py`
2. Reinstala o enciende el servidor para que descargue el código.
3. En *Files*, dentro de la carpeta `servidor`, crea un archivo llamado `.env` con esto:
   ```
   OWNER_IDS=1000
   ADMIN_IDS=
   ```
   Este archivo no se sube a GitHub, así que se queda privado en tu hosting.

**Opción B: subir los archivos a mano.** Sube la carpeta `servidor` por *Files* y pon `servidor/app.py` como archivo de inicio.

Al encenderlo, la consola debe decir `escuchando en el puerto XXXX`. Anota la **IP:puerto** que aparece en la pestaña *Network*.

## 3. Poner la dirección del servidor
En GitHub, edita `config.json` (con el lápiz ✏️) y cambia la dirección:
```json
"servidor": "http://51.79.10.20:25570",
```
Los programas leen este archivo al abrirse. Si algún día cambias de hosting, solo editas esta línea y no hace falta volver a compilar.

## 4. Crear el .exe (automático)
1. En GitHub ve a **Releases → Draft a new release**.
2. En *Choose a tag* escribe `v2.0` y presiona **Publish release**.
3. Espera unos 3 minutos. En la pestaña **Actions** verás el progreso. Al terminar, el archivo `AutoClickerAL.exe` aparece dentro de la release.
4. Pásales a tus amigos el enlace de descarga:
   `https://github.com/GRFFO/ACAL/releases/latest/download/AutoClickerAL.exe`

## 5. Volverte Owner
Abre el .exe y crea tu cuenta. La primera cuenta tiene el **ID 1000**, que ya está puesto en `OWNER_IDS`. Si tu ID es otro (lo ves en *Cuenta*), cámbialo en el `.env`. El servidor lo lee solo, sin reiniciar.

---

## Publicar una actualización
1. Edita el código en `cliente/`.
2. Crea una **nueva release** con una etiqueta mayor, por ejemplo `v2.1`. Lo que escribas en la descripción se muestra como notas de la versión.
3. GitHub compila el .exe y actualiza `config.json` solo. Cuando tus amigos abran el programa, les sale "Nueva versión disponible" y se actualiza con un clic.

Para obligarlos a actualizar, pon `"obligatoria": true` en `config.json`.
Para mandarles un mensaje, escribe en `"anuncio"` y les aparece al abrir el programa.

## Actualizar el servidor
Haz los cambios en `servidor/` y reinicia el servidor desde el panel. Con *Auto Update* activado, descarga la versión nueva solo.

---

## Roles
| Rol | Cómo se obtiene | Qué puede hacer |
|---|---|---|
| **Owner** | ID en `OWNER_IDS` del `.env` | Todo, incluido crear licencias de admin y quitar admins |
| **Admin** | Activa una **licencia de admin**, su ID está en `ADMIN_IDS`, o el owner le da "Hacer admin" | Crear licencias de usuario, ver todos los usuarios y banear |
| **Usuario** | Activa una licencia normal | Usar el autoclicker durante el tiempo de la licencia |

- **Licencia de usuario**: dura el tiempo que elijas (1 día, 1 semana, 5 meses, 2 años, de por vida, etc.). El tiempo empieza a contar al activarla y se suma si activan otra.
- **Licencia de admin**: quien la activa se vuelve admin de forma permanente. Solo el owner puede crearlas.
- Cada licencia sirve **una sola vez**.

## Panel
- **Licencias**: crear licencias y ver la lista de libres y usadas, con el nombre de quién usó cada una.
- **Usuarios**: todas las cuentas registradas, con su usuario, ID, rol y tiempo restante. Puedes filtrar por *Con licencia*, *Admins* o *Baneados*. Tiene un botón para banear directo en cada fila y opciones para dar tiempo, quitar la licencia, hacer admin o eliminar.

## Respaldo
Las cuentas y licencias están en `servidor/datos.db`, en el hosting. Ese archivo no se sube a GitHub. Descárgalo de vez en cuando como copia de seguridad.
