"""Inferencia con un modelo exportado en app/modelos/vNNN/ (modelo.keras + info.json)."""
import json
from pathlib import Path

import numpy as np

from .config import AVISO, TIPOS_TUMOR
from .preprocesar import preparar


def leer_info(carpeta_version):
    """Lee info.json de una versión. Devuelve un dict."""
    return json.loads((Path(carpeta_version) / "info.json").read_text(encoding="utf-8"))


def cargar_modelo(carpeta_version):
    """Carga una versión exportada. Devuelve (modelo, info).

    `modelo` es el modelo Keras completo (imagen RGB 0-255 de 160x160 -> salidas "tumor" y
    "tipo"); `info` es el contenido de info.json (umbral, capa_gradcam, tipos, métricas...).
    """
    import keras
    carpeta = Path(carpeta_version)
    info = leer_info(carpeta)
    modelo = keras.models.load_model(carpeta / info.get("archivo_modelo", "modelo.keras"), compile=False)
    return modelo, info


def predecir(modelo, info, img_bgr, con_gradcam=False, umbral=None):
    """Predice una imagen BGR (como la entregan `leer_imagen` o `leer_bytes`).

    Devuelve un dict con:
    - probabilidad_tumor (float 0-1)
    - umbral (float) y hay_tumor (bool): hay_tumor = probabilidad_tumor >= umbral
    - tipo_probable (str de TIPOS_TUMOR) y probabilidad_tipo (float): tipo de tumor más
      probable; es un dato secundario que solo tiene sentido cuando hay_tumor es True
    - probabilidades_tipo (dict tipo -> float)
    - aviso (str)
    Si con_gradcam=True agrega:
    - gradcam (float32 0-1, mapa pequeño), imagen_preparada (RGB uint8 160x160) y
      gradcam_superpuesto (RGB uint8 160x160): la "zona que más influyó" en la respuesta
      dada (hacia "tumor" si hay_tumor es True; hacia "sin tumor" si es False).
    """
    umbral = float(info["umbral"] if umbral is None else umbral)
    tipos = info.get("tipos", TIPOS_TUMOR)
    img = preparar(img_bgr, int(info.get("tam", 160)))
    salida = modelo(np.asarray(img, dtype=np.float32)[None, ...], training=False)
    prob = float(np.asarray(salida["tumor"]).ravel()[0])
    p_tipo = np.asarray(salida["tipo"], dtype=float).ravel()
    k = int(p_tipo.argmax())
    resultado = {
        "probabilidad_tumor": prob,
        "umbral": umbral,
        "hay_tumor": bool(prob >= umbral),
        "tipo_probable": tipos[k],
        "probabilidad_tipo": float(p_tipo[k]),
        "probabilidades_tipo": {t: float(p) for t, p in zip(tipos, p_tipo)},
        "aviso": AVISO,
    }
    if con_gradcam:
        from .gradcam import mapa_gradcam, superponer
        mapa = mapa_gradcam(modelo, img, info.get("capa_gradcam", "out_relu"),
                            hacia_tumor=resultado["hay_tumor"])
        resultado["gradcam"] = mapa
        resultado["imagen_preparada"] = img
        resultado["gradcam_superpuesto"] = superponer(img, mapa)
    return resultado
