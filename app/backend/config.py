"""Configuración del backend.

Lee el archivo `.env` de la raíz del proyecto (si existe) con python-dotenv. Si falta, se usan
valores por omisión con DB_MODO=local. Las variables que ya existan en el entorno tienen
prioridad sobre el `.env` (así las pruebas pueden usar una base temporal).

Variables adicionales (solo para pruebas o despliegues especiales, no van en `.env.example`):
- TS_DB_RUTA: ruta del archivo SQLite (por omisión app/almacen/tumores.db).
- TS_MEDIA_DIR: carpeta de imágenes guardadas (por omisión app/almacen/media).
- TS_MODELOS_DIR: carpeta de versiones del modelo (por omisión app/modelos).

La clave ANTHROPIC_API_KEY solo se expone como `ANTHROPIC_API_KEY` dentro de este módulo; nunca
se escribe en registros, respuestas ni mensajes de error.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ / ".env", override=False)


def _texto(nombre, defecto=""):
    valor = os.environ.get(nombre)
    return defecto if valor is None or valor.strip() == "" else valor.strip()


def _entero(nombre, defecto):
    try:
        return int(_texto(nombre, str(defecto)))
    except ValueError:
        return defecto


def _booleano(nombre, defecto=False):
    return _texto(nombre, "true" if defecto else "false").lower() in ("1", "true", "si", "sí", "yes")


# ---------- Rutas ----------
FRONTEND = RAIZ / "app" / "frontend"
ALMACEN = RAIZ / "app" / "almacen"
DB_RUTA = Path(_texto("TS_DB_RUTA", str(ALMACEN / "tumores.db")))
MEDIA = Path(_texto("TS_MEDIA_DIR", str(ALMACEN / "media")))
MODELOS = Path(_texto("TS_MODELOS_DIR", str(RAIZ / "app" / "modelos")))
REGISTROS = Path(_texto("TS_REGISTROS_DIR", str(ALMACEN / "registros")))
DATOS = RAIZ / "datos"
RESULTADOS = RAIZ / "resultados"

# ---------- Base de datos ----------
DB_MODO = _texto("DB_MODO", "local").lower()
if DB_MODO not in ("local", "fabric"):
    DB_MODO = "local"
FABRIC_SERVIDOR = _texto("FABRIC_SERVIDOR")
FABRIC_BASE = _texto("FABRIC_BASE")
FABRIC_AUTENTICACION = _texto("FABRIC_AUTENTICACION", "ActiveDirectoryInteractive")
FABRIC_USUARIO = _texto("FABRIC_USUARIO")

# ---------- Sesión ----------
SESION_MINUTOS = _entero("SESION_MINUTOS", 480)
COOKIE_SEGURA = _booleano("COOKIE_SEGURA", False)
COOKIE_SESION = "ts_sesion"

# ---------- IA generativa ----------
ANTHROPIC_API_KEY = _texto("ANTHROPIC_API_KEY")
ANTHROPIC_MODELO = _texto("ANTHROPIC_MODELO", "claude-opus-5-5")
ASISTENTE_RESPALDO = _booleano("ASISTENTE_RESPALDO", True)       # respaldo del servidor ante rechazos
ASISTENTE_SEGUNDOS_SQL = _entero("ASISTENTE_SEGUNDOS_SQL", 10)   # tiempo máximo de la consulta
ASISTENTE_LIMITE_FILAS = _entero("ASISTENTE_LIMITE_FILAS", 200)

# ---------- Power BI ----------
POWERBI_URL = _texto("POWERBI_URL")

# ---------- Reglas de la aplicación ----------
AVISO = "Resultado de apoyo. No sustituye el diagnóstico de un médico especialista."
MAX_ARCHIVOS = 8
MAX_BYTES = 10 * 1024 * 1024
PATRON_IDENTIFICADOR = r"^[A-Z]{2,5}-\d{1,6}$"
SENSIBILIDAD_OBJETIVO = 0.98


def asistente_configurado():
    """True si hay clave de la API de Claude (no revela la clave)."""
    return bool(ANTHROPIC_API_KEY)


def asegurar_carpetas():
    for carpeta in (ALMACEN, MEDIA, REGISTROS, DB_RUTA.parent):
        carpeta.mkdir(parents=True, exist_ok=True)
