"""Preprocesamiento único de las imágenes.

Camino único para todo el proyecto (notebooks, aplicación y reentrenamiento):
lectura -> recorte del contorno del cerebro -> 160x160 con INTER_AREA -> RGB de 0 a 255.
La normalización de MobileNetV2 va dentro del modelo, no aquí.
"""
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from .config import TAM


def leer_bytes(b):
    """Decodifica una imagen a partir de sus bytes. Devuelve BGR uint8 (alto, ancho, 3)."""
    arreglo = np.frombuffer(b, dtype=np.uint8)
    img = cv2.imdecode(arreglo, cv2.IMREAD_COLOR) if arreglo.size else None
    if img is None:
        raise ValueError("No se pudo leer la imagen: el archivo no es una imagen válida.")
    return img


def leer_imagen(ruta):
    """Lee una imagen del disco. Devuelve BGR uint8.

    Usa np.fromfile + cv2.imdecode porque cv2.imread falla en Windows con rutas con acentos.
    """
    arreglo = np.fromfile(str(ruta), dtype=np.uint8)
    img = cv2.imdecode(arreglo, cv2.IMREAD_COLOR) if arreglo.size else None
    if img is None:
        raise ValueError(f"No se pudo leer la imagen: {ruta}")
    return img


def recortar_cerebro(img_bgr, margen=0):
    """Recorta el contorno más grande (el cerebro) para quitar el fondo negro sobrante."""
    gris = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gris = cv2.GaussianBlur(gris, (5, 5), 0)
    _, umbral = cv2.threshold(gris, 45, 255, cv2.THRESH_BINARY)
    umbral = cv2.erode(umbral, None, iterations=2)
    umbral = cv2.dilate(umbral, None, iterations=2)
    contornos, _ = cv2.findContours(umbral, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return img_bgr
    c = max(contornos, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(c)
    if w < 20 or h < 20:
        return img_bgr
    y0, y1 = max(0, y - margen), min(img_bgr.shape[0], y + h + margen)
    x0, x1 = max(0, x - margen), min(img_bgr.shape[1], x + w + margen)
    return img_bgr[y0:y1, x0:x1]


def preparar(img_bgr, tam=TAM):
    """Recorte del cerebro + redimensionado con INTER_AREA. Devuelve RGB uint8 (tam, tam, 3)."""
    img = recortar_cerebro(img_bgr)
    img = cv2.resize(img, (tam, tam), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def preparar_ruta(ruta, tam=TAM):
    """Lee y prepara una imagen del disco. Devuelve RGB uint8 (tam, tam, 3)."""
    return preparar(leer_imagen(ruta), tam)


def cargar_lote(rutas, tam=TAM, hilos=8):
    """Lee y prepara muchas imágenes. Devuelve uint8 (n, tam, tam, 3) en el mismo orden de las rutas."""
    rutas = [str(r) for r in rutas]
    if not rutas:
        return np.zeros((0, tam, tam, 3), dtype=np.uint8)
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        imagenes = list(ex.map(lambda r: preparar_ruta(r, tam), rutas))
    return np.stack(imagenes).astype(np.uint8)
