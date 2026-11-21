"""Conexión a la base y utilidades comunes (SQLAlchemy Core).

- DB_MODO=local: SQLite en app/almacen/tumores.db (o TS_DB_RUTA). Se activa WAL y una espera
  de bloqueo para que el proceso de reentrenamiento y el servidor escriban sin chocar.
- DB_MODO=fabric: SQL database de Microsoft Fabric (motor SQL Server) con pyodbc y
  "ODBC Driver 18 for SQL Server". El motor se crea con `create_engine("mssql+pyodbc://",
  creator=...)`: cada conexión nueva recibe un token de Microsoft Entra ID obtenido con
  azure-identity (ver app/backend/fabric.py). El esquema se crea ejecutando
  sql/01_crear_tablas.sql (DATETIME2(0), CHECK, índices), no con metadata.create_all.
  Este modo no se ha ejecutado contra Fabric desde este equipo: scripts/probar_fabric.py.

Todas las consultas del proyecto son parametrizadas (Core o text() con parámetros). Las
comparaciones booleanas usan `== True/False` (SQL Server no acepta `IS 1`).
"""
import json
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, event, func, insert, select, text

from . import config
from .tablas import VISTAS, bitacora, dim_diagnostico, dim_fecha, metadata

ACCIONES = ["LOGIN_OK", "LOGIN_FALLIDO", "LOGOUT", "ACCESO_DENEGADO", "ESTUDIO_CREADO", "ESTUDIO_CONFIRMADO",
            "ENTRENAMIENTO_INICIADO", "ENTRENAMIENTO_TERMINADO", "ENTRENAMIENTO_CANCELADO", "ENTRENAMIENTO_ERROR",
            "MODELO_APROBADO", "MODELO_REVERTIDO", "UMBRAL_ACTUALIZADO", "USUARIO_CREADO", "USUARIO_ACTUALIZADO",
            "CONSULTA_IA", "CONSULTA_IA_BLOQUEADA", "CARGA_DATOS"]

DIAGNOSTICOS = [
    (1, "sin_tumor", "Sin tumor", False),
    (2, "tumor", "Tumor (tipo no especificado)", True),
    (3, "glioma", "Glioma", True),
    (4, "meningioma", "Meningioma", True),
    (5, "pituitary", "Tumor hipofisario", True),
]
ID_DIAGNOSTICO = {clave: i for i, clave, _, _ in DIAGNOSTICOS}
CLAVE_DIAGNOSTICO = {i: clave for i, clave, _, _ in DIAGNOSTICOS}
NOMBRE_DIAGNOSTICO = {clave: nombre for _, clave, nombre, _ in DIAGNOSTICOS}
ES_TUMOR = {clave: t for _, clave, _, t in DIAGNOSTICOS}

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
FECHA_INICIO, FECHA_FIN = date(2025, 1, 1), date(2027, 12, 31)

_motor = None
_motor_lectura = None
SCRIPT_TSQL = config.RAIZ / "sql" / "01_crear_tablas.sql"


def url_conexion():
    """URL de SQLAlchemy (solo SQLite; Fabric usa `creator` con token y no lleva credenciales en la URL)."""
    if config.DB_MODO == "fabric":
        return "mssql+pyodbc://"
    config.DB_RUTA.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{config.DB_RUTA.as_posix()}"


def _motor_fabric(solo_lectura=False):
    from . import fabric
    # pool_recycle: las conexiones se renuevan antes de que venza el token (dura ~60-90 min).
    return create_engine("mssql+pyodbc://", creator=lambda: fabric.conectar(solo_lectura), pool_pre_ping=True,
                         pool_recycle=1800, fast_executemany=True)


def motor():
    """Motor único por proceso."""
    global _motor
    if _motor is None:
        if config.DB_MODO == "fabric":
            _motor = _motor_fabric()
        else:
            _motor = create_engine(url_conexion(), connect_args={"check_same_thread": False, "timeout": 30})

            @event.listens_for(_motor, "connect")
            def _pragmas(conexion, _registro):
                cursor = conexion.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
    return _motor


def motor_lectura():
    """Motor de SOLO LECTURA para el asistente en Fabric (ApplicationIntent=ReadOnly).

    En SQLite el asistente abre su propia conexión con mode=ro (ver asistente.ejecutar).
    """
    global _motor_lectura
    if config.DB_MODO != "fabric":
        raise RuntimeError("motor_lectura solo se usa con DB_MODO=fabric.")
    if _motor_lectura is None:
        _motor_lectura = _motor_fabric(solo_lectura=True)
    return _motor_lectura


def es_sqlite():
    return motor().dialect.name == "sqlite"


def crear_esquema():
    """Crea las tablas y vistas que falten. Es seguro llamarlo varias veces.

    SQLite: metadata.create_all + CREATE VIEW IF NOT EXISTS. Fabric: ejecuta sql/01_crear_tablas.sql
    por lotes (GO), que solo crea lo que falta y recrea las vistas con CREATE OR ALTER.
    """
    m = motor()
    if m.dialect.name != "sqlite":
        from . import fabric
        return fabric.ejecutar_script(m, SCRIPT_TSQL)
    metadata.create_all(m)
    with m.begin() as c:
        for nombre, cuerpo in VISTAS.items():
            c.execute(text(f"CREATE VIEW IF NOT EXISTS {nombre} AS {cuerpo}"))
    return None


def ahora():
    """Fecha y hora local sin zona, al segundo."""
    return datetime.now().replace(microsecond=0)


def iso(valor):
    """Convierte date/datetime (o texto de SQLite) a ISO 8601."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.replace(microsecond=0).isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor).replace(" ", "T")


def id_fecha(d):
    return d.year * 10000 + d.month * 100 + d.day


def fila_fecha(d):
    return {"fecha_id": id_fecha(d), "fecha": d, "anio": d.year, "mes": d.month, "nombre_mes": MESES[d.month - 1],
            "semana": int(d.isocalendar()[1]), "dia_semana": DIAS[d.weekday()]}


def asegurar_fecha(c, d):
    """Garantiza que la fecha exista en dim_fecha (fuera del rango precargado se agrega). Devuelve fecha_id."""
    fid = id_fecha(d)
    if c.execute(select(dim_fecha.c.fecha_id).where(dim_fecha.c.fecha_id == fid)).first() is None:
        c.execute(insert(dim_fecha), [fila_fecha(d)])
    return fid


def llenar_dimensiones():
    """Carga dim_diagnostico (5 claves) y dim_fecha (2025-01-01 a 2027-12-31) si faltan filas."""
    with motor().begin() as c:
        existentes = {r[0] for r in c.execute(select(dim_diagnostico.c.diagnostico_id))}
        nuevas = [{"diagnostico_id": i, "clave": k, "nombre": n, "es_tumor": t}
                  for i, k, n, t in DIAGNOSTICOS if i not in existentes]
        if nuevas:
            c.execute(insert(dim_diagnostico), nuevas)
        ya = {r[0] for r in c.execute(select(dim_fecha.c.fecha_id).where(
            dim_fecha.c.fecha_id.between(id_fecha(FECHA_INICIO), id_fecha(FECHA_FIN))))}
        filas, d = [], FECHA_INICIO
        while d <= FECHA_FIN:
            if id_fecha(d) not in ya:
                filas.append(fila_fecha(d))
            d += timedelta(days=1)
        if filas:
            c.execute(insert(dim_fecha), filas)
    return {"diagnosticos_nuevos": len(nuevas), "fechas_nuevas": len(filas)}


def registrar(accion, detalle="", usuario=None, ip=None, exito=True, conexion=None):
    """Agrega un evento a la bitácora. `usuario` es un dict con usuario_id, usuario y rol (o None)."""
    usuario = usuario or {}
    fila = {"fecha_hora": ahora(), "usuario_id": usuario.get("usuario_id"), "usuario": usuario.get("usuario"),
            "rol": usuario.get("rol"), "accion": accion, "detalle": (detalle or "")[:1000],
            "ip": (ip or None), "exito": bool(exito)}
    if conexion is not None:
        conexion.execute(insert(bitacora), [fila])
    else:
        with motor().begin() as c:
            c.execute(insert(bitacora), [fila])


def solicitante_entrenamiento(c, entrenamiento_id):
    """(usuario dict o None, ip) de quien pidió un entrenamiento, para firmar los eventos del proceso de fondo."""
    from .tablas import entrenamientos, usuarios
    fila = c.execute(select(usuarios.c.usuario_id, usuarios.c.usuario, usuarios.c.rol, entrenamientos.c.parametros)
                     .select_from(entrenamientos.outerjoin(usuarios,
                                                           usuarios.c.usuario_id == entrenamientos.c.solicitado_por))
                     .where(entrenamientos.c.entrenamiento_id == entrenamiento_id)).mappings().first()
    if fila is None:
        return None, None
    ip = (de_json(fila["parametros"], {}) or {}).get("ip_solicitud")
    quien = None if fila["usuario_id"] is None else {"usuario_id": fila["usuario_id"], "usuario": fila["usuario"],
                                                     "rol": fila["rol"]}
    return quien, ip


def a_json(valor):
    return None if valor is None else json.dumps(valor, ensure_ascii=False, default=float)


def de_json(texto, defecto=None):
    if texto in (None, ""):
        return defecto
    try:
        return json.loads(texto)
    except (TypeError, ValueError):
        return defecto


def contar(c, consulta):
    return int(c.execute(select(func.count()).select_from(consulta.subquery())).scalar() or 0)


__all__ = ["motor", "crear_esquema", "registrar", "ahora", "iso", "asegurar_fecha", "llenar_dimensiones",
           "ID_DIAGNOSTICO", "CLAVE_DIAGNOSTICO", "NOMBRE_DIAGNOSTICO", "ES_TUMOR", "ACCIONES"]
