"""Extracción de rasgos.

- Rasgos de MobileNetV2 congelada (ImageNet, 160x160, promedio global -> 1,280 valores).
  El extractor es el mismo grafo del modelo completo cortado en el promedio global, así
  que la normalización de MobileNetV2 se aplica dentro y los rasgos guardados son los que
  vería la cabeza dentro del modelo de la aplicación.
- Rasgos básicos (18): brillo medio, contraste (desviación estándar) e histograma de
  grises normalizado de 16 barras. Son la base de la solución más simple.
"""
import hashlib
from pathlib import Path

import cv2
import numpy as np

from .config import TAM

N_BARRAS = 16
NOMBRES_BASICOS = ["brillo", "contraste"] + [f"hist_{i:02d}" for i in range(N_BARRAS)]

_EXTRACTOR = None


def firma_cache(manifiesto):
    """Firma (SHA-256) que identifica un caché de rasgos o de imágenes preparadas.

    Cambia si cambia el manifiesto (rutas, orden o contenido de las imágenes según su
    columna sha256), el tamaño TAM o el código de preprocesar.py, rasgos.py o red.py.
    Un caché guardado con otra firma ya no corresponde y debe recalcularse.
    """
    h = hashlib.sha256()
    h.update(f"TAM={TAM}\n".encode())
    for ruta, sha in zip(manifiesto["ruta"].astype(str), manifiesto["sha256"].astype(str)):
        h.update(f"{ruta}|{sha}\n".encode())
    aqui = Path(__file__).resolve().parent
    for nombre in ["preprocesar.py", "rasgos.py", "red.py"]:
        h.update((aqui / nombre).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def extractor_mobilenet():
    """Modelo Keras congelado: imagen RGB 0-255 (160x160) -> 1,280 rasgos. Se crea una sola vez."""
    global _EXTRACTOR
    if _EXTRACTOR is None:
        import keras
        from .red import NOMBRE_CAPA_RASGOS, construir_completo
        completo = construir_completo()
        _EXTRACTOR = keras.Model(completo.input, completo.get_layer(NOMBRE_CAPA_RASGOS).output,
                                 name="extractor_mobilenetv2")
        _EXTRACTOR.trainable = False
    return _EXTRACTOR


def rasgos_mobilenet(imagenes_rgb, lote=64):
    """Rasgos de MobileNetV2 de un arreglo uint8 (n, 160, 160, 3). Devuelve float32 (n, 1280)."""
    modelo = extractor_mobilenet()
    imagenes_rgb = np.asarray(imagenes_rgb)
    if imagenes_rgb.ndim == 3:
        imagenes_rgb = imagenes_rgb[None, ...]
    salida = []
    for i in range(0, len(imagenes_rgb), 512):
        bloque = imagenes_rgb[i:i + 512].astype(np.float32)
        salida.append(modelo.predict(bloque, batch_size=lote, verbose=0))
    return np.concatenate(salida).astype(np.float32)


def rasgos_basicos(img_rgb):
    """Rasgos básicos de una imagen RGB uint8 ya preparada. Devuelve float32 (18,).

    brillo = media de grises / 255; contraste = desviación estándar de grises / 255;
    histograma de 16 barras (0 a 255) normalizado para que sume 1.
    """
    gris = cv2.cvtColor(np.asarray(img_rgb, dtype=np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    hist, _ = np.histogram(gris, bins=N_BARRAS, range=(0, 256))
    hist = hist.astype(np.float32) / max(1, gris.size)
    return np.concatenate([[gris.mean() / 255.0, gris.std() / 255.0], hist]).astype(np.float32)


def rasgos_basicos_lote(imagenes_rgb):
    """Rasgos básicos de un arreglo uint8 (n, 160, 160, 3). Devuelve float32 (n, 18)."""
    return np.stack([rasgos_basicos(im) for im in imagenes_rgb]).astype(np.float32)
