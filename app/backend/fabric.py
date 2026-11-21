"""Conexión a la SQL database de Microsoft Fabric con un token de Microsoft Entra ID.

Por qué así: `Authentication=ActiveDirectoryInteractive` del driver ODBC falla desde un proceso
sin consola (FA004, "Failed to authenticate the user '' in Entra ID"). En su lugar se obtiene el
token con azure-identity (`InteractiveBrowserCredential`, abre el navegador la primera vez) y se
pasa al driver con el atributo SQL_COPT_SS_ACCESS_TOKEN (1256).

- La credencial se crea UNA vez por proceso.
- El caché de tokens es persistente (`TokenCachePersistenceOptions(name="tumores_cerebrales")`,
  cifrado por el sistema operativo) y el `AuthenticationRecord` se guarda en
  app/almacen/fabric_auth.json (ignorado por git). Así el servidor, el proceso de reentrenamiento
  y la carga reutilizan la sesión sin volver a abrir el navegador.
- El token se pide de nuevo solo cuando le quedan menos de 5 minutos.
- Si FABRIC_USUARIO tiene valor se usa como `login_hint`.

El modo de solo lectura (para el asistente) agrega `ApplicationIntent=ReadOnly`. En una base sin
réplica de lectura eso no impide escribir: la protección real es que el asistente use un usuario
con solo `db_datareader` (ver sql/README.md).

Este módulo no se ha ejecutado contra Fabric desde este equipo; scripts/probar_fabric.py es la
prueba que se corre con el usuario presente.
"""
import re
import struct
import threading
import time

from . import config

ALCANCE = "https://database.windows.net/.default"
SQL_COPT_SS_ACCESS_TOKEN = 1256
NOMBRE_CACHE = "tumores_cerebrales"
MARGEN_RENOVACION_S = 300

_candado = threading.Lock()
_credencial = None
_token = None   # azure.core.credentials.AccessToken (token, expires_on)


def _ruta_registro():
    return config.ALMACEN / "fabric_auth.json"


def credencial():
    """InteractiveBrowserCredential única por proceso (con caché persistente y registro guardado)."""
    global _credencial
    with _candado:
        if _credencial is not None:
            return _credencial
        from azure.identity import AuthenticationRecord, InteractiveBrowserCredential, TokenCachePersistenceOptions
        opciones = {"cache_persistence_options": TokenCachePersistenceOptions(name=NOMBRE_CACHE)}
        if config.FABRIC_USUARIO:
            opciones["login_hint"] = config.FABRIC_USUARIO
        ruta = _ruta_registro()
        registro = None
        if ruta.is_file():
            try:
                registro = AuthenticationRecord.deserialize(ruta.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - registro dañado: se vuelve a iniciar sesión
                registro = None
        if registro is not None:
            opciones["authentication_record"] = registro
        _credencial = InteractiveBrowserCredential(**opciones)
        if registro is None:
            # Primera vez en este equipo: abre el navegador y guarda el registro para los demás procesos.
            nuevo = _credencial.authenticate(scopes=[ALCANCE])
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(nuevo.serialize(), encoding="utf-8")
        return _credencial


def token_bytes():
    """Token de acceso empaquetado como lo pide el driver ODBC. Se renueva cerca de su vencimiento."""
    global _token
    cred = credencial()
    with _candado:
        if _token is None or _token.expires_on - time.time() < MARGEN_RENOVACION_S:
            _token = cred.get_token(ALCANCE)
        datos = _token.token.encode("utf-16-le")
    return struct.pack("=i", len(datos)) + datos


def cadena_odbc(solo_lectura=False):
    """Cadena ODBC SIN credenciales (el token va aparte)."""
    if not (config.FABRIC_SERVIDOR and config.FABRIC_BASE):
        raise RuntimeError("DB_MODO=fabric requiere FABRIC_SERVIDOR y FABRIC_BASE en el archivo .env.")
    servidor = config.FABRIC_SERVIDOR
    if not re.search(r",\d+$", servidor):
        servidor += ",1433"
    partes = ["Driver={ODBC Driver 18 for SQL Server}", f"Server={servidor}", f"Database={config.FABRIC_BASE}",
              "Encrypt=yes", "TrustServerCertificate=no"]
    if solo_lectura:
        partes.append("ApplicationIntent=ReadOnly")
    return ";".join(partes) + ";"


def conectar(solo_lectura=False):
    """Conexión pyodbc nueva con el token vigente (se usa como `creator` de SQLAlchemy)."""
    import pyodbc
    return pyodbc.connect(cadena_odbc(solo_lectura), attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_bytes()})


def lotes_tsql(texto):
    """Divide un script T-SQL en lotes separados por líneas 'GO'. Omite lotes que solo tienen comentarios."""
    lotes = []
    for lote in re.split(r"^\s*GO\s*$", texto, flags=re.M | re.I):
        sin_comentarios = re.sub(r"/\*.*?\*/", "", lote, flags=re.S)
        sin_comentarios = re.sub(r"--[^\n]*", "", sin_comentarios)
        if sin_comentarios.strip():
            lotes.append(lote.strip())
    return lotes


def ejecutar_script(motor, ruta):
    """Ejecuta un script T-SQL por lotes en autocommit. Devuelve el número de lotes."""
    lotes = lotes_tsql(ruta.read_text(encoding="utf-8"))
    crudo = motor.raw_connection()
    try:
        crudo.dbapi_connection.autocommit = True
        cursor = crudo.cursor()
        for lote in lotes:
            cursor.execute(lote)
            while cursor.nextset():   # consume los conteos de cada sentencia del lote
                pass
        cursor.close()
    finally:
        try:
            crudo.dbapi_connection.autocommit = False   # la conexión regresa al pool en modo normal
        finally:
            crudo.close()
    return len(lotes)
