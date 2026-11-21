"""Reentrenamiento en un proceso aparte.

Uso (lo lanza el servidor): python -m app.backend.reentrenar --id N

Datos que usa (el conjunto de PRUEBA nunca entra):
- Rasgos guardados de MobileNetV2 (datos/rasgos/rasgos_mobilenet.npz) de las filas del
  manifiesto cuya partición NO es "prueba".
- Predicciones de uso confirmadas por doctores (hecho_prediccion con origen='uso' y
  diagnostico_confirmado_id): se leen sus imágenes preparadas guardadas en app/almacen/media y
  se extraen sus rasgos. Se EXCLUYEN las que son gemelas (correlación > 0.95 en cualquier
  orientación) de alguna imagen de prueba, para que la prueba no se filtre por esa vía.

Pasos: (opcional) K-fold de la cabeza -> cabeza con validación apartada -> (opcional) ajuste
fino, quedándose con la etapa de menor val_loss -> diagnóstico, curvas, umbral (objetivo 0.98)
y métricas EN VALIDACIÓN -> exporta app/modelos/vNNN/ y lo registra como candidato.
Cada época se escribe en historial_epocas y el avance en entrenamientos. Si el estado pasa a
'cancelado', se detiene al terminar la época en curso.
"""
import argparse
import json
import shutil
import sys
import time
import traceback

import numpy as np

from . import catalogo, config, db
from .tablas import dim_diagnostico, entrenamientos, hecho_prediccion, historial_epocas, metricas_pliegue
from sqlalchemy import insert, select, update

UMBRAL_GEMELA_PRUEBA = 0.95
FRACCION_VAL = 0.15
EPOCAS_AJUSTE_FINO = 8
PACIENCIA_AJUSTE_FINO = 3


class Cancelado(Exception):
    pass


def _limpio(v):
    if v is None:
        return None
    v = float(v)
    return None if v != v else v


class Avance:
    """Escribe el avance y el historial en la base, y revisa si se pidió cancelar."""

    def __init__(self, eid, total_unidades):
        self.eid = eid
        self.total = max(1, total_unidades)
        self.hechas = 0
        self.cancelado = False
        self.pliegue = 0
        self.en_kfold = False
        self.epocas_etapa = 0

    def estado_actual(self, c):
        return c.execute(select(entrenamientos.c.estado).where(entrenamientos.c.entrenamiento_id == self.eid)).scalar()

    def poner(self, etapa=None, mensaje=None, progreso=None, epoca=None, **extra):
        valores = dict(extra)
        if etapa is not None:
            valores["etapa"] = etapa
        if mensaje is not None:
            valores["mensaje"] = mensaje[:500]
        if progreso is not None:
            valores["progreso"] = float(min(1.0, progreso))
        if epoca is not None:
            valores["epoca_actual"] = int(epoca)
        with db.motor().begin() as c:
            estado = self.estado_actual(c)
            if estado == "cancelado":
                self.cancelado = True
                valores.pop("estado", None)
            c.execute(update(entrenamientos).where(entrenamientos.c.entrenamiento_id == self.eid).values(**valores))
        if self.cancelado:
            raise Cancelado()

    def cerrar_etapa(self, unidades_hasta):
        self.hechas = max(self.hechas, unidades_hasta)

    def callback(self, etapa_fija=None, epocas_max=0):
        """Devuelve la función callback_progreso(etapa, epoca, registros) para ml.entrenar."""
        def cb(etapa, epoca, registros):
            if etapa_fija == "pliegue":
                if epoca == 1:
                    self.pliegue += 1
                nombre = f"pliegue_{self.pliegue}"
                texto = f"Validación cruzada: pliegue {self.pliegue} de 5, época {epoca}"
            else:
                nombre = etapa
                texto = ("Cabeza" if etapa == "cabeza" else "Ajuste fino") + f": época {epoca} de {epocas_max}"
            self.hechas += 1
            fila = {"entrenamiento_id": self.eid, "etapa": nombre, "epoca": int(epoca),
                    "perdida": _limpio(registros.get("loss")), "exactitud": _limpio(registros.get("accuracy")),
                    "perdida_val": _limpio(registros.get("val_loss")),
                    "exactitud_val": _limpio(registros.get("val_accuracy")),
                    "tasa_aprendizaje": _limpio(registros.get("learning_rate"))}
            with db.motor().begin() as c:
                c.execute(insert(historial_epocas), [fila])
                estado = self.estado_actual(c)
                c.execute(update(entrenamientos).where(entrenamientos.c.entrenamiento_id == self.eid).values(
                    etapa=nombre, epoca_actual=int(epoca), progreso=float(min(0.99, self.hechas / self.total)),
                    mensaje=texto))
            if estado == "cancelado":
                self.cancelado = True
                return False
            return True
        return cb


# ------------------------------------------------------------------ datos
def _leer_png_rgb(ruta, tam):
    import cv2
    arr = np.fromfile(str(ruta), dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR) if arr.size else None
    if img is None:
        return None
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    if img.shape[:2] != (tam, tam):
        img = cv2.resize(img, (tam, tam), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(img)


def datos_manifiesto():
    """Rasgos y etiquetas de las filas que NO son de prueba. Devuelve dict."""
    import pandas as pd
    from .ml.config import MANIFIESTO, RASGOS
    man = pd.read_csv(MANIFIESTO)
    z = np.load(RASGOS / "rasgos_mobilenet.npz", allow_pickle=False)
    X_todo = np.asarray(z["X"], dtype=np.float32)
    rutas_npz = [str(r) for r in z["rutas"]] if "rutas" in z.files else list(man["ruta"].astype(str))
    posicion = {r: i for i, r in enumerate(rutas_npz)}
    faltan = [r for r in man["ruta"].astype(str) if r not in posicion]
    if faltan:
        raise RuntimeError(f"Los rasgos guardados no corresponden al manifiesto ({len(faltan)} rutas sin rasgos).")
    orden = np.array([posicion[r] for r in man["ruta"].astype(str)])
    es_prueba = man["particion"].astype(str).str.lower().eq("prueba").to_numpy()
    sel = np.where(~es_prueba)[0]
    grupos = None
    if "grupo_similitud" in man.columns:
        grupos = np.array([f"m{g}" for g in man["grupo_similitud"].astype(str).to_numpy()[sel]], dtype=object)
    return {"man": man, "sel": sel, "prueba": np.where(es_prueba)[0], "X": X_todo[orden[sel]],
            "clases": man["clase"].astype(str).to_numpy()[sel], "rutas": man["ruta"].astype(str).to_numpy()[sel],
            "grupos": grupos}


def imagenes_preparadas(man, indices):
    """Imágenes preparadas (uint8 n x 160 x 160 x 3) de filas del manifiesto, del caché si corresponde."""
    from .ml.config import RAIZ, RASGOS, TAM
    from .ml.preprocesar import cargar_lote
    ruta = RASGOS / "imagenes_160.npy"
    if ruta.exists():
        cache = np.load(ruta, mmap_mode="r")
        if cache.shape[0] == len(man) and cache.shape[1:] == (TAM, TAM, 3):
            return np.asarray(cache[np.asarray(indices)], dtype=np.uint8)
    return cargar_lote([RAIZ / r for r in man["ruta"].astype(str).to_numpy()[np.asarray(indices)]])


def confirmadas(man, indices_prueba, avance):
    """Imágenes de uso confirmadas por doctores, sin las gemelas de prueba."""
    from .ml.config import TAM, TIPOS_TUMOR
    from .ml.duplicados import maxima_correlacion, miniatura
    with db.motor().connect() as c:
        filas = c.execute(select(hecho_prediccion.c.prediccion_id, hecho_prediccion.c.archivo_imagen,
                                 dim_diagnostico.c.clave)
                          .select_from(hecho_prediccion.join(
                              dim_diagnostico,
                              dim_diagnostico.c.diagnostico_id == hecho_prediccion.c.diagnostico_confirmado_id))
                          .where(hecho_prediccion.c.origen == "uso",
                                 hecho_prediccion.c.diagnostico_confirmado_id.is_not(None))
                          .order_by(hecho_prediccion.c.prediccion_id)).all()
    imgs, y_bin, y_tipo, ids = [], [], [], []
    for pid, archivo, clave in filas:
        if not archivo:
            continue
        img = _leer_png_rgb(config.MEDIA / archivo, TAM)
        if img is None:
            continue
        imgs.append(img)
        ids.append(int(pid))
        y_bin.append(0 if clave == "sin_tumor" else 1)
        y_tipo.append(TIPOS_TUMOR.index(clave) if clave in TIPOS_TUMOR else -1)
    resumen = {"confirmadas_encontradas": len(imgs), "confirmadas_excluidas_por_prueba": 0, "confirmadas_usadas": 0}
    if not imgs:
        return None, resumen
    avance.poner(mensaje=f"Revisando {len(imgs)} imágenes confirmadas contra el conjunto de prueba")
    imgs = np.stack(imgs)
    mini_conf = np.stack([miniatura(im) for im in imgs])
    prueba = imagenes_preparadas(man, indices_prueba)
    mini_prueba = np.stack([miniatura(im) for im in prueba])
    corr, _, _ = maxima_correlacion(mini_conf, mini_prueba)
    quedan = corr <= UMBRAL_GEMELA_PRUEBA
    resumen["confirmadas_excluidas_por_prueba"] = int((~quedan).sum())
    resumen["confirmadas_usadas"] = int(quedan.sum())
    if not quedan.any():
        return None, resumen
    return {"imgs": imgs[quedan], "y_bin": np.array(y_bin)[quedan], "y_tipo": np.array(y_tipo)[quedan],
            "ids": np.array(ids)[quedan]}, resumen


def _estratos(y_bin, y_tipo):
    e = np.where(y_bin == 0, 0, np.where(y_tipo >= 0, y_tipo + 1, 4))
    for k in np.unique(e):
        if (e == k).sum() < 10:
            e[e == k] = 0 if k == 0 else 1
    return e


def apartar(estratos, grupos):
    """Índices (entrenamiento, validación) con FRACCION_VAL apartado; por grupo si hay grupos."""
    from sklearn.model_selection import StratifiedGroupKFold, train_test_split
    from .ml import entrenar
    from .ml.config import SEMILLA
    funcion = getattr(entrenar, "apartar_validacion", None)
    if funcion is not None:
        try:
            ent, det = funcion(estratos, FRACCION_VAL, SEMILLA, grupos)
            return np.asarray(ent), np.asarray(det)
        except TypeError:
            pass
    n = len(estratos)
    if grupos is None:
        ent, det = train_test_split(np.arange(n), test_size=FRACCION_VAL, stratify=estratos, random_state=SEMILLA)
        return np.sort(ent), np.sort(det)
    sgkf = StratifiedGroupKFold(n_splits=int(round(1 / FRACCION_VAL)), shuffle=True, random_state=SEMILLA)
    ent, det = next(sgkf.split(np.zeros(n), estratos, grupos))
    return ent, det


# ------------------------------------------------------------------ proceso principal
def ejecutar(eid):
    with db.motor().connect() as c:
        fila = c.execute(select(entrenamientos).where(entrenamientos.c.entrenamiento_id == eid)).mappings().first()
    if fila is None:
        raise RuntimeError(f"No existe el entrenamiento {eid}.")
    p = db.de_json(fila["parametros"], {}) or {}
    epocas_max = int(p.get("epocas_max", 60))
    tasa, lote = float(p.get("tasa", 1e-3)), int(p.get("lote", 64))
    usar_kfold, usar_af = bool(p.get("kfold")), bool(p.get("ajuste_fino"))
    paciencia = int(p.get("paciencia") or 8)
    ep_af = min(EPOCAS_AJUSTE_FINO, epocas_max)
    total = (5 * epocas_max if usar_kfold else 0) + epocas_max + (ep_af if usar_af else 0)
    avance = Avance(eid, total)
    inicio = time.time()
    avance.poner(etapa="preparando", mensaje="Cargando TensorFlow y los rasgos guardados", progreso=0.0,
                 estado="corriendo", epoca=0)

    from .ml import entrenar, red
    from .ml.config import CLASES, SEMILLA, TIPOS_TUMOR, fijar_semillas, versiones
    from .ml.diagnostico import diagnosticar, graficar_curvas
    from .ml.metricas import elegir_umbral, metricas_binarias, metricas_por_pliegue
    from .ml.rasgos import rasgos_mobilenet
    fijar_semillas(SEMILLA)

    d = datos_manifiesto()
    X = d["X"]
    y_bin, y_tipo = entrenar.etiquetas_de_clases(d["clases"])
    rutas = list(d["rutas"])
    grupos = d["grupos"]
    conf, resumen_conf = confirmadas(d["man"], d["prueba"], avance)
    n_manifiesto = len(X)
    if conf is not None:
        avance.poner(mensaje=f"Extrayendo rasgos de {len(conf['imgs'])} imágenes confirmadas")
        X = np.concatenate([X, rasgos_mobilenet(conf["imgs"])])
        y_bin = np.concatenate([y_bin, conf["y_bin"]]).astype(np.int32)
        y_tipo = np.concatenate([y_tipo, conf["y_tipo"]]).astype(np.int32)
        rutas += [f"confirmada:{i}" for i in conf["ids"]]
        if grupos is not None:
            grupos = np.concatenate([grupos, np.array([f"c{i}" for i in conf["ids"]], dtype=object)])
    estratos = _estratos(y_bin, y_tipo)
    rutas = np.array(rutas)

    # --- K-fold (opcional)
    resultado_cv = None
    if usar_kfold:
        avance.poner(etapa="pliegue_1", mensaje="Validación cruzada de la cabeza (5 pliegues)")
        kw = {"grupos": grupos} if grupos is not None else {}
        resultado_cv = entrenar.kfold_cabeza(X, y_bin, y_tipo, estratos=estratos, epocas_max=epocas_max, tasa=tasa,
                                             lote=lote, paciencia=paciencia,
                                             callback_progreso=avance.callback("pliegue", epocas_max), **kw)
        if avance.cancelado or resultado_cv.get("cancelado"):
            raise Cancelado()
        avance.cerrar_etapa(5 * epocas_max)

    # --- Cabeza con validación apartada
    ent, det = apartar(estratos, grupos)
    avance.poner(etapa="cabeza", mensaje="Entrenando la cabeza", epoca=0)
    cabeza, hist_cabeza = entrenar.entrenar_cabeza(
        X[ent], y_bin[ent], y_tipo[ent], X[det], y_bin[det], y_tipo[det], epocas_max=epocas_max, tasa=tasa, lote=lote,
        paciencia=paciencia, callback_progreso=avance.callback(None, epocas_max))
    if avance.cancelado or hist_cabeza.get("cancelado"):
        raise Cancelado()
    avance.cerrar_etapa((5 * epocas_max if usar_kfold else 0) + epocas_max)
    proporcion = float(max(y_bin[ent].mean(), 1 - y_bin[ent].mean()))
    diag_cabeza = diagnosticar(hist_cabeza, epocas_max, paciencia, proporcion_mayoritaria=proporcion)

    # --- Ajuste fino (opcional)
    hist_af, diag_af, etapa_final, completo, img_det = None, None, "cabeza", None, None
    if usar_af:
        avance.poner(etapa="ajuste_fino", mensaje="Preparando imágenes para el ajuste fino", epoca=0)
        es_man = lambda idx: idx[idx < n_manifiesto]  # noqa: E731
        es_conf = lambda idx: idx[idx >= n_manifiesto] - n_manifiesto  # noqa: E731

        def imgs(idx):
            partes = [imagenes_preparadas(d["man"], d["sel"][es_man(idx)])]
            if conf is not None and len(es_conf(idx)):
                partes.append(conf["imgs"][es_conf(idx)])
            return np.concatenate(partes)
        orden_ent = np.concatenate([es_man(ent), es_conf(ent) + n_manifiesto])
        orden_det = np.concatenate([es_man(det), es_conf(det) + n_manifiesto])
        img_ent, img_det = imgs(ent), imgs(det)
        ent, det = orden_ent, orden_det   # mismo orden que las imágenes
        completo = red.construir_completo(cabeza=cabeza)
        completo, hist_af = entrenar.ajuste_fino(
            completo, img_ent, y_bin[ent], y_tipo[ent], img_det, y_bin[det], y_tipo[det], tasa=1e-5,
            epocas_max=ep_af, lote=32, paciencia=PACIENCIA_AJUSTE_FINO,
            callback_progreso=avance.callback(None, ep_af))
        if avance.cancelado or hist_af.get("cancelado"):
            raise Cancelado()
        diag_af = diagnosticar(hist_af, ep_af, PACIENCIA_AJUSTE_FINO, proporcion_mayoritaria=proporcion)
        mejor_af = float(np.nanmin(hist_af["val_loss"])) if hist_af["val_loss"] else float("inf")
        if mejor_af < float(hist_af.get("val_loss_inicial", float("inf"))):
            etapa_final = "ajuste_fino"
        del img_ent

    # --- Modelo final, umbral y métricas en validación
    avance.poner(etapa="evaluando", mensaje="Eligiendo el umbral y calculando métricas en validación",
                 progreso=0.95)
    if etapa_final == "ajuste_fino":
        prob_val, tipo_val = entrenar.predecir_completo(completo, img_det)
    else:
        completo = red.construir_completo(cabeza=cabeza)
        prob_val, tipo_val = entrenar.predecir_cabeza(cabeza, X[det])
    y_val = y_bin[det]
    if resultado_cv is not None and etapa_final == "cabeza":
        y_umbral, prob_umbral = y_bin, resultado_cv["prob_oof"]
        origen_umbral = (f"predicciones fuera de pliegue de la validación cruzada de la cabeza ({len(y_bin)} "
                         "imágenes sin prueba)")
        rutas_umbral = rutas
    else:
        y_umbral, prob_umbral = y_val, prob_val
        origen_umbral = f"validación apartada ({len(y_val)} imágenes sin prueba)"
        rutas_umbral = rutas[det]
    umbral = elegir_umbral(y_umbral, prob_umbral, config.SENSIBILIDAD_OBJETIVO)
    m_umbral = {"n": int(len(y_umbral)), "umbral": umbral, **metricas_binarias(y_umbral, prob_umbral, umbral)}
    m_val = {"n": int(len(y_val)), "umbral": umbral, **metricas_binarias(y_val, prob_val, umbral)}
    con_tumor = y_tipo[det] >= 0
    if con_tumor.any():
        m_val["exactitud_tipo"] = float((tipo_val[con_tumor].argmax(1) == y_tipo[det][con_tumor]).mean())
    matriz = [[m_val["vn"], m_val["fp"]], [m_val["fn"], m_val["vp"]]]
    pliegues = []
    if resultado_cv is not None:
        pliegues = metricas_por_pliegue(y_bin, resultado_cv["prob_oof"], resultado_cv["pliegue_oof"], umbral)

    diag_final = diag_af if etapa_final == "ajuste_fino" else diag_cabeza
    if usar_af and etapa_final == "cabeza":
        diag_final = dict(diag_cabeza)
        diag_final["advertencias"] = list(diag_cabeza.get("advertencias", [])) + [
            "El ajuste fino no mejoró la pérdida de validación; se exporta la cabeza sola."]

    # --- Exportar
    with db.motor().connect() as c:
        version = catalogo.siguiente_version(c)
    carpeta = catalogo.carpeta(version)
    carpeta.mkdir(parents=True, exist_ok=False)
    try:
        avance.poner(etapa="exportando", mensaje=f"Exportando la versión {version}", progreso=0.97)
        entrenar.exportar_limpio(completo, carpeta / "modelo.keras")
        graficar_curvas(hist_cabeza, diag_cabeza["mejor_epoca"], carpeta / "curvas_cabeza.png",
                        titulo=f"{version} - cabeza")
        if hist_af is not None:
            graficar_curvas(hist_af, diag_af["mejor_epoca"], carpeta / "curvas_ajuste_fino.png",
                            titulo=f"{version} - ajuste fino")
        np.savez(carpeta / "validacion.npz", y=np.asarray(y_umbral, dtype=np.int32),
                 prob=np.asarray(prob_umbral, dtype=np.float64), rutas=np.asarray(rutas_umbral, dtype=str),
                 origen=np.array(origen_umbral), y_val=np.asarray(y_val, dtype=np.int32),
                 prob_val=np.asarray(prob_val, dtype=np.float64), rutas_val=np.asarray(rutas[det], dtype=str))
        cv_info = None
        if resultado_cv is not None:
            cv_info = {"nota": "K-fold sobre la cabeza con rasgos congelados (reentrenamiento)", "pliegues": len(pliegues),
                       "umbral": umbral, "por_pliegue": pliegues}
            for k in ("sensibilidad", "especificidad", "precision", "f1", "auc", "exactitud"):
                valores = [f[k] for f in pliegues if f.get(k) is not None]
                if valores:
                    cv_info[f"{k}_media"] = float(np.mean(valores))
                    cv_info[f"{k}_std"] = float(np.std(valores))
        info = {
            "version": version, "nombre": "Red Keras (MobileNetV2)", "tipo": "red_keras",
            "fecha": db.ahora().isoformat(), "archivo_modelo": "modelo.keras", "etapa_exportada": etapa_final,
            "descripcion": ("Reentrenamiento: MobileNetV2 congelada + cabeza densa" if etapa_final == "cabeza"
                            else "Reentrenamiento: MobileNetV2 con ajuste fino de las últimas capas"),
            "entrada": "Imagen RGB uint8 de 160x160 con valores de 0 a 255 (recorte del cerebro + INTER_AREA); "
                       "la normalización está dentro del modelo",
            "umbral": umbral, "sensibilidad_objetivo": config.SENSIBILIDAD_OBJETIVO, "origen_umbral": origen_umbral,
            "metricas_umbral": m_umbral, "capa_gradcam": red.NOMBRE_CAPA_GRADCAM, "tam": 160, "clases": CLASES,
            "tipos": TIPOS_TUMOR, "metricas_cv": cv_info, "metricas_validacion": m_val,
            "metricas_prueba": None,
            "nota_prueba": "Modelo candidato: se evaluó en validación, no en el conjunto de prueba.",
            "mejor_epoca": diag_final["mejor_epoca"], "diagnostico": diag_final["etiqueta"],
            "explicacion_diagnostico": diag_final["explicacion"],
            "advertencias_diagnostico": diag_final.get("advertencias", []),
            "diagnostico_etapas": {"cabeza": diag_cabeza, **({"ajuste_fino": diag_af} if diag_af else {})},
            "comparacion_validacion": {
                "perdida_val_cabeza": diag_cabeza.get("perdida_val_mejor"),
                "perdida_val_ajuste_fino": None if diag_af is None else diag_af.get("perdida_val_mejor"),
                "se_uso_ajuste_fino": etapa_final == "ajuste_fino"},
            "entrenamiento": {
                "entrenamiento_id": eid, "n_entrenamiento": int(len(ent)), "n_validacion": int(len(det)),
                "n_rasgos_guardados": int(n_manifiesto), **resumen_conf,
                "pesos_clase": {str(k): v for k, v in red.pesos_clase(y_bin[ent]).items()},
                "cabeza": {"epocas_max": epocas_max, "paciencia": paciencia, "tasa": tasa, "lote": lote,
                           "epocas_corridas": len(hist_cabeza["val_loss"])},
                "ajuste_fino": None if hist_af is None else {
                    "epocas_max": ep_af, "paciencia": PACIENCIA_AJUSTE_FINO, "tasa": 1e-5, "lote": 32, "capas": 30,
                    "capas_descongeladas": hist_af.get("capas_descongeladas"),
                    "epocas_corridas": len(hist_af["val_loss"])},
                "kfold": usar_kfold, "grupos_similitud": grupos is not None,
                "segundos": round(time.time() - inicio, 1)},
            "versiones": versiones(), "semilla": SEMILLA, "aviso": config.AVISO,
        }
        (carpeta / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2, default=float),
                                           encoding="utf-8")
        # Comprobación: el modelo exportado carga y hace Grad-CAM.
        from .ml.inferencia import cargar_modelo, predecir
        mod, inf = cargar_modelo(carpeta)
        muestra = np.zeros((160, 160, 3), dtype=np.uint8) if img_det is None else img_det[0]
        predecir(mod, inf, muestra[..., ::-1], con_gradcam=True)
    except BaseException:
        shutil.rmtree(carpeta, ignore_errors=True)
        raise

    curvas = "curvas_ajuste_fino.png" if etapa_final == "ajuste_fino" else "curvas_cabeza.png"
    metricas = {"origen": "validacion", **m_val, "origen_umbral": origen_umbral,
                "n_entrenamiento": int(len(ent)), "n_validacion": int(len(det)), **resumen_conf,
                "etapa_exportada": etapa_final}
    with db.motor().begin() as c:
        if c.execute(select(entrenamientos.c.estado).where(entrenamientos.c.entrenamiento_id == eid)).scalar() == "cancelado":
            raise Cancelado()
        modelo_id = catalogo.registrar_red(c, version, "candidato", entrenamiento_id=eid, conservar_estado=False)
        c.execute(update(entrenamientos).where(entrenamientos.c.entrenamiento_id == eid).values(
            modelo_id=modelo_id, estado="terminado", etapa="terminado", progreso=1.0,
            mensaje=f"Terminado: candidato {version} (umbral {umbral:.4f})", mejor_epoca=diag_final["mejor_epoca"],
            diagnostico=diag_final["etiqueta"], explicacion=diag_final["explicacion"],
            advertencias=db.a_json(diag_final.get("advertencias", [])), metricas=db.a_json(metricas),
            matriz_confusion=db.a_json(matriz), curvas=curvas, terminado_en=db.ahora()))
        if pliegues:
            c.execute(insert(metricas_pliegue), [
                {"entrenamiento_id": eid, "modelo_id": modelo_id, "pliegue": f["pliegue"],
                 "sensibilidad": f["sensibilidad"], "especificidad": f["especificidad"], "precision": f["precision"],
                 "f1": f["f1"], "auc": f["auc"], "vp": f["vp"], "vn": f["vn"], "fp": f["fp"], "fn": f["fn"]}
                for f in pliegues])
        quien, ip = db.solicitante_entrenamiento(c, eid)
        db.registrar("ENTRENAMIENTO_TERMINADO", f"Entrenamiento {eid}: candidato {version}, diagnóstico "
                     f"'{diag_final['etiqueta']}', sensibilidad val {m_val['sensibilidad']:.3f}", quien, ip, conexion=c)
    return version


def _terminar_cancelado(eid):
    with db.motor().begin() as c:
        c.execute(update(entrenamientos).where(entrenamientos.c.entrenamiento_id == eid).values(
            estado="cancelado", etapa="cancelado", diagnostico="cancelado",
            explicacion="El entrenamiento se canceló antes de terminar; no se generó un modelo candidato.",
            mensaje="Cancelado por el administrador", terminado_en=db.ahora()))
        ep = c.execute(select(entrenamientos.c.epoca_actual, entrenamientos.c.etapa)
                       .where(entrenamientos.c.entrenamiento_id == eid)).first()
        quien, ip = db.solicitante_entrenamiento(c, eid)
        db.registrar("ENTRENAMIENTO_CANCELADO", f"Entrenamiento {eid}: se detuvo (época {ep[0] if ep else '-'})",
                     quien, ip, conexion=c)


def _terminar_error(eid, e):
    texto = f"{type(e).__name__}: {str(e)[:300]}"
    with db.motor().begin() as c:
        c.execute(update(entrenamientos).where(entrenamientos.c.entrenamiento_id == eid).values(
            estado="error", etapa="error", mensaje=f"Error: {texto}"[:500], terminado_en=db.ahora()))
        quien, ip = db.solicitante_entrenamiento(c, eid)
        db.registrar("ENTRENAMIENTO_ERROR", f"Entrenamiento {eid}: {texto}", quien, ip, exito=False, conexion=c)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reentrenamiento de la red (proceso aparte)")
    parser.add_argument("--id", type=int, required=True)
    args = parser.parse_args(argv)
    eid = args.id
    try:
        version = ejecutar(eid)
        print(f"Entrenamiento {eid} terminado: {version}", flush=True)
        return 0
    except Cancelado:
        _terminar_cancelado(eid)
        print(f"Entrenamiento {eid} cancelado", flush=True)
        return 0
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        _terminar_error(eid, e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
