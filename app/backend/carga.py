"""Carga inicial de datos (la usa sql/02_cargar_datos.py y las pruebas).

Idempotente: se puede correr varias veces sin duplicar filas.
- dim_diagnostico (5 claves) y dim_fecha (2025-01-01 a 2027-12-31).
- dim_modelo: los 4 modelos clásicos (estado 'referencia') y la red v001 ('produccion' si no hay
  otra en producción; si ya existe se conserva su estado).
- hecho_prediccion con origen='prueba': resultados de prueba de los 5 modelos
  (resultados/predicciones_prueba.csv). Se borran y se vuelven a cargar las filas 'prueba'.
- entrenamientos, historial_epocas y metricas_pliegue de la corrida original de v001
  (resultados/historial_epocas.csv, resultados/cv_pliegues.csv e info.json).
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, insert, select, update

from . import catalogo, config, db
from .tablas import dim_modelo, entrenamientos, hecho_prediccion, historial_epocas, metricas_pliegue

NOMBRE_RED_CSV = "Red Keras (MobileNetV2)"
MARCA_ORIGINAL = "Corrida original del notebook 04 (carga inicial)"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _entero(v):
    f = _num(v)
    return None if f is None else int(round(f))


def _fecha_info(info):
    try:
        return datetime.fromisoformat(str(info.get("fecha"))).replace(microsecond=0)
    except (TypeError, ValueError):
        return db.ahora()


def _clasicos():
    """{nombre: {"archivo", "umbral"}} de resultados/modelos_clasicos/info.json (tolerante)."""
    ruta = config.RESULTADOS / "modelos_clasicos" / "info.json"
    if not ruta.exists():
        return {}
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return {k: v for k, v in datos.items() if isinstance(v, dict)}


def cargar_modelos(c, version_red="v001"):
    """Registra los clásicos y la red. Devuelve {nombre_en_csv: modelo_id}."""
    ids = {}
    resumen = {}
    ruta_resumen = config.RESULTADOS / "prueba_resumen.csv"
    if ruta_resumen.exists():
        for _, r in pd.read_csv(ruta_resumen).iterrows():
            resumen[str(r["modelo"])] = r
    info_red = catalogo.leer_info(version_red)
    creado = _fecha_info(info_red)
    for nombre, datos in _clasicos().items():
        version = Path(str(datos.get("archivo", nombre))).stem
        r = resumen.get(nombre)
        valores = {"nombre": nombre, "umbral": _num(datos.get("umbral")),
                   "sensibilidad": None if r is None else _num(r.get("sensibilidad")),
                   "especificidad": None if r is None else _num(r.get("especificidad")),
                   "f1": None if r is None else _num(r.get("f1")),
                   "auc": None if r is None else _num(r.get("auc")),
                   "origen_metricas": "prueba"}
        fila = c.execute(select(dim_modelo.c.modelo_id).where(dim_modelo.c.tipo == "clasico",
                                                              dim_modelo.c.version == version)).first()
        if fila is None:
            mid = c.execute(insert(dim_modelo).values(tipo="clasico", version=version, estado="referencia",
                                                      creado_en=creado, **valores)).inserted_primary_key[0]
        else:
            mid = fila[0]
            c.execute(update(dim_modelo).where(dim_modelo.c.modelo_id == mid).values(**valores))
        ids[nombre] = int(mid)
    hay_produccion = catalogo.modelo_produccion(c) is not None
    estado = "retirado" if hay_produccion else "produccion"
    mid = catalogo.registrar_red(c, version_red, estado)
    # La carga refleja el info.json vigente: el umbral de v001 se refresca desde el archivo.
    c.execute(update(dim_modelo).where(dim_modelo.c.modelo_id == mid)
              .values(umbral=float(info_red.get("umbral", 0.5)), creado_en=creado))
    ids[info_red.get("nombre", NOMBRE_RED_CSV)] = mid
    ids[NOMBRE_RED_CSV] = mid
    return ids


def cargar_prueba(c, ids, fecha_carga):
    """Predicciones de prueba de los 5 modelos en hecho_prediccion (origen='prueba')."""
    ruta = config.RESULTADOS / "predicciones_prueba.csv"
    if not ruta.exists():
        return 0
    p = pd.read_csv(ruta)
    c.execute(delete(hecho_prediccion).where(hecho_prediccion.c.origen == "prueba"))
    fid = db.asegurar_fecha(c, fecha_carga.date())
    filas = []
    for r in p.itertuples(index=False):
        mid = ids.get(str(r.modelo))
        if mid is None:
            continue
        pred = int(r.prediccion)
        clase = str(r.clase)
        real = "sin_tumor" if clase == "notumor" else (clase if clase in db.ID_DIAGNOSTICO else "tumor")
        tipo = getattr(r, "tipo_probable", None)
        tipo = tipo if (pred == 1 and isinstance(tipo, str) and tipo) else None
        filas.append({
            "paciente_id": None, "fecha_id": fid, "usuario_id": None, "modelo_id": mid,
            "diagnostico_predicho_id": db.ID_DIAGNOSTICO["tumor" if pred == 1 else "sin_tumor"],
            "diagnostico_confirmado_id": db.ID_DIAGNOSTICO[real], "origen": "prueba",
            "probabilidad_tumor": float(r.probabilidad_tumor), "umbral": float(r.umbral),
            "tipo_probable": tipo, "probabilidad_tipo": _num(getattr(r, "probabilidad_tipo", None)) if tipo else None,
            "de_acuerdo": bool(pred == int(r.es_tumor)), "tiempo_respuesta_ms": None,
            "archivo_imagen": str(r.ruta), "archivo_gradcam": None, "creado_en": fecha_carga,
        })
    for i in range(0, len(filas), 1000):
        c.execute(insert(hecho_prediccion), filas[i:i + 1000])
    return len(filas)


def cargar_corrida_original(c, ids, version_red="v001"):
    """Entrenamiento original de v001 con su historial y sus métricas por pliegue."""
    info = catalogo.leer_info(version_red)
    mid = ids[NOMBRE_RED_CSV]
    fila_modelo = c.execute(select(dim_modelo.c.entrenamiento_id).where(dim_modelo.c.modelo_id == mid)).first()
    eid = fila_modelo[0] if fila_modelo else None
    ent = info.get("entrenamiento", {}) or {}
    cabeza = ent.get("cabeza", {}) or {}
    etapa_exp = info.get("etapa_exportada", "cabeza")
    diag_etapa = (info.get("diagnostico_etapas", {}) or {}).get(etapa_exp, {}) or {}
    mv = info.get("metricas_validacion", {}) or {}
    matriz = [[mv.get("vn"), mv.get("fp")], [mv.get("fn"), mv.get("vp")]] if mv else None
    fecha = _fecha_info(info)
    valores = {
        "modelo_id": mid, "estado": "terminado",
        "parametros": db.a_json({"epocas_max": cabeza.get("epocas_max"), "tasa": cabeza.get("tasa"),
                                 "lote": cabeza.get("lote"), "kfold": True,
                                 "ajuste_fino": "ajuste_fino" in ent, "origen": "notebook"}),
        "etapa": "terminado", "epoca_actual": cabeza.get("epocas_corridas"), "epocas_max": cabeza.get("epocas_max"),
        "progreso": 1.0, "mensaje": MARCA_ORIGINAL, "mejor_epoca": info.get("mejor_epoca"),
        "diagnostico": info.get("diagnostico"), "explicacion": info.get("explicacion_diagnostico"),
        "advertencias": db.a_json(info.get("advertencias_diagnostico", diag_etapa.get("advertencias", [])) or []),
        "metricas": db.a_json({"origen": "validacion", **mv} if mv else None),
        "matriz_confusion": db.a_json(matriz), "curvas": f"curvas_{etapa_exp}.png",
        "iniciado_en": fecha, "terminado_en": fecha, "solicitado_por": None,
    }
    existe = eid is not None and c.execute(select(entrenamientos.c.entrenamiento_id).where(
        entrenamientos.c.entrenamiento_id == eid)).first() is not None
    if existe:
        c.execute(update(entrenamientos).where(entrenamientos.c.entrenamiento_id == eid).values(**valores))
    else:
        eid = int(c.execute(insert(entrenamientos).values(**valores)).inserted_primary_key[0])
        c.execute(update(dim_modelo).where(dim_modelo.c.modelo_id == mid).values(entrenamiento_id=eid))
    c.execute(delete(historial_epocas).where(historial_epocas.c.entrenamiento_id == eid))
    ruta_h = config.RESULTADOS / "historial_epocas.csv"
    n_hist = 0
    if ruta_h.exists():
        h = pd.read_csv(ruta_h)
        filas = [{"entrenamiento_id": eid, "etapa": str(r.etapa), "epoca": int(r.epoca), "perdida": _num(r.perdida),
                  "exactitud": _num(r.exactitud), "perdida_val": _num(r.perdida_val),
                  "exactitud_val": _num(r.exactitud_val), "tasa_aprendizaje": _num(r.tasa_aprendizaje)}
                 for r in h.itertuples(index=False)]
        if filas:
            c.execute(insert(historial_epocas), filas)
        n_hist = len(filas)
    # Métricas por pliegue de los 5 modelos (la red se liga al entrenamiento original).
    todos = list(set(ids.values()))
    c.execute(delete(metricas_pliegue).where(metricas_pliegue.c.modelo_id.in_(todos),
                                             (metricas_pliegue.c.entrenamiento_id == eid)
                                             | metricas_pliegue.c.entrenamiento_id.is_(None)))
    ruta_cv = config.RESULTADOS / "cv_pliegues.csv"
    n_cv = 0
    if ruta_cv.exists():
        cv = pd.read_csv(ruta_cv)
        filas = []
        for r in cv.to_dict("records"):
            m = ids.get(str(r.get("modelo")))
            if m is None:
                continue
            filas.append({"entrenamiento_id": eid if m == mid else None, "modelo_id": m,
                          "pliegue": int(r["pliegue"]), "sensibilidad": _num(r.get("sensibilidad")),
                          "especificidad": _num(r.get("especificidad")), "precision": _num(r.get("precision")),
                          "f1": _num(r.get("f1")), "auc": _num(r.get("auc")), "vp": _entero(r.get("vp")),
                          "vn": _entero(r.get("vn")), "fp": _entero(r.get("fp")), "fn": _entero(r.get("fn"))})
        if filas:
            c.execute(insert(metricas_pliegue), filas)
        n_cv = len(filas)
    return eid, n_hist, n_cv


def cargar_todo(version_red="v001"):
    """Corre toda la carga. Devuelve un resumen con los conteos."""
    config.asegurar_carpetas()
    db.crear_esquema()
    dims = db.llenar_dimensiones()
    with db.motor().begin() as c:
        ids = cargar_modelos(c, version_red)
        fecha = _fecha_info(catalogo.leer_info(version_red))
        n_prueba = cargar_prueba(c, ids, fecha)
        eid, n_hist, n_cv = cargar_corrida_original(c, ids, version_red)
    resumen = {**dims, "modelos": len(set(ids.values())), "predicciones_prueba": n_prueba,
               "entrenamiento_original": eid, "historial_epocas": n_hist, "metricas_pliegue": n_cv}
    db.registrar("CARGA_DATOS", "Carga inicial: " + ", ".join(f"{k}={v}" for k, v in resumen.items()))
    return resumen
