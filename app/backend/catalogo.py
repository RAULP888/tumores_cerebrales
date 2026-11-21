"""Catálogo de modelos (dim_modelo) y versiones exportadas en app/modelos/vNNN/."""
import json
import re
from pathlib import Path

from sqlalchemy import insert, select, update

from . import config, db
from .tablas import dim_modelo

PATRON_VERSION = re.compile(r"^v(\d{3,})$")


def leer_info(version):
    ruta = config.MODELOS / version / "info.json"
    return json.loads(ruta.read_text(encoding="utf-8"))


def versiones_en_disco():
    """Versiones vNNN que tienen modelo.keras e info.json, ordenadas."""
    if not config.MODELOS.exists():
        return []
    salida = []
    for carpeta in config.MODELOS.iterdir():
        if carpeta.is_dir() and PATRON_VERSION.match(carpeta.name) and (carpeta / "info.json").exists():
            salida.append(carpeta.name)
    return sorted(salida, key=lambda v: int(v[1:]))


def siguiente_version(c):
    """Siguiente vNNN libre (considera disco y base)."""
    numeros = [int(v[1:]) for v in versiones_en_disco()]
    for (v,) in c.execute(select(dim_modelo.c.version).where(dim_modelo.c.tipo == "red_keras")):
        m = PATRON_VERSION.match(str(v))
        if m:
            numeros.append(int(m.group(1)))
    return f"v{(max(numeros) + 1) if numeros else 1:03d}"


def metricas_resumen(info):
    """(sensibilidad, especificidad, f1, auc, origen) de un info.json de red: validación apartada si hay."""
    for clave, origen in (("metricas_validacion", "validacion"), ("metricas_umbral", "validacion"),
                          ("metricas_prueba", "prueba")):
        m = info.get(clave)
        if isinstance(m, dict) and m.get("sensibilidad") is not None:
            return m.get("sensibilidad"), m.get("especificidad"), m.get("f1"), m.get("auc"), origen
    return None, None, None, None, None


def registrar_red(c, version, estado, entrenamiento_id=None, conservar_estado=True):
    """Inserta o actualiza una versión de la red en dim_modelo. Devuelve modelo_id.

    Si ya existe y conservar_estado=True, no cambia su estado (ni lo que haya decidido el
    administrador), solo refresca nombre y métricas; el umbral solo se llena si estaba vacío.
    """
    info = leer_info(version)
    sens, espe, f1, auc, origen = metricas_resumen(info)
    fila = c.execute(select(dim_modelo).where(dim_modelo.c.tipo == "red_keras",
                                              dim_modelo.c.version == version)).mappings().first()
    datos = {"nombre": info.get("nombre", "Red Keras (MobileNetV2)"), "sensibilidad": sens, "especificidad": espe,
             "f1": f1, "auc": auc, "origen_metricas": origen}
    if fila is None:
        datos.update({"tipo": "red_keras", "version": version, "estado": estado,
                      "umbral": float(info.get("umbral", 0.5)), "entrenamiento_id": entrenamiento_id,
                      "creado_en": db.ahora(), "aprobado_en": db.ahora() if estado == "produccion" else None})
        return int(c.execute(insert(dim_modelo).values(**datos)).inserted_primary_key[0])
    if not conservar_estado:
        datos["estado"] = estado
    if fila["umbral"] is None:
        datos["umbral"] = float(info.get("umbral", 0.5))
    if entrenamiento_id is not None:
        datos["entrenamiento_id"] = entrenamiento_id
    c.execute(update(dim_modelo).where(dim_modelo.c.modelo_id == fila["modelo_id"]).values(**datos))
    return int(fila["modelo_id"])


def modelo_produccion(c):
    """Fila (dict) de la red en producción, o None."""
    return c.execute(select(dim_modelo).where(dim_modelo.c.tipo == "red_keras", dim_modelo.c.estado == "produccion")
                     .order_by(dim_modelo.c.modelo_id.desc())).mappings().first()


def asegurar_produccion():
    """Si no hay red en producción, registra la versión más antigua en disco (v001) como producción."""
    with db.motor().begin() as c:
        if modelo_produccion(c) is not None:
            return
        versiones = versiones_en_disco()
        if not versiones:
            return
        version = versiones[0]
        existente = c.execute(select(dim_modelo.c.modelo_id).where(
            dim_modelo.c.tipo == "red_keras", dim_modelo.c.version == version)).first()
        if existente is None:
            registrar_red(c, version, "produccion")
        else:
            c.execute(update(dim_modelo).where(dim_modelo.c.modelo_id == existente[0])
                      .values(estado="produccion", aprobado_en=db.ahora()))


def carpeta(version):
    return Path(config.MODELOS) / version
