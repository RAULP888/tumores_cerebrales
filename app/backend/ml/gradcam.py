"""Grad-CAM sobre la salida "tumor": muestra la zona que más influyó en la predicción.

Importante: el mapa indica qué zona de la imagen pesó más en la respuesta del modelo.
No es la ubicación del tumor.
"""
import cv2
import keras
import numpy as np
import tensorflow as tf

from .red import NOMBRE_CAPA_GRADCAM, NOMBRE_CAPA_LOGIT

_MODELOS_GRAD = {}


def _modelo_gradientes(modelo, capa):
    clave = (id(modelo), capa)
    if clave not in _MODELOS_GRAD:
        _MODELOS_GRAD.clear()  # solo se guarda el del modelo en uso
        _MODELOS_GRAD[clave] = keras.Model(
            modelo.inputs, [modelo.get_layer(capa).output, modelo.get_layer(NOMBRE_CAPA_LOGIT).output])
    return _MODELOS_GRAD[clave]


def mapa_gradcam(modelo_completo, img_rgb_uint8, capa=NOMBRE_CAPA_GRADCAM, hacia_tumor=None):
    """Mapa Grad-CAM de la salida "tumor" para una imagen RGB uint8 de 160x160.

    El mapa muestra la zona que más influyó en la respuesta del modelo:
    - hacia_tumor=True: zonas que empujaron la respuesta hacia "tumor".
    - hacia_tumor=False: zonas que la empujaron hacia "sin tumor".
    - hacia_tumor=None (por omisión): se usa el lado hacia el que se inclinó el modelo
      (probabilidad >= 0.5 -> tumor). `inferencia.predecir` pasa la decisión con el umbral.

    Se deriva el valor previo a la sigmoide (así el mapa no se apaga cuando la probabilidad
    está muy cerca de 0 o de 1). Devuelve un arreglo float32 de 0 a 1 con el tamaño de la
    capa convolucional (5x5 en MobileNetV2 a 160 pixeles); `superponer` lo amplía.
    """
    grad = _modelo_gradientes(modelo_completo, capa)
    x = tf.convert_to_tensor(np.asarray(img_rgb_uint8, dtype=np.float32)[None, ...])
    with tf.GradientTape() as cinta:
        conv, logit = grad(x, training=False)
        objetivo = logit[:, 0]
        if hacia_tumor is None:
            hacia_tumor = bool(objetivo[0] >= 0)
        if not hacia_tumor:
            objetivo = -objetivo
    gradientes = cinta.gradient(objetivo, conv)
    pesos = tf.reduce_mean(gradientes, axis=(0, 1, 2))
    mapa = tf.reduce_sum(conv[0] * pesos, axis=-1)
    mapa = tf.maximum(mapa, 0.0)
    mapa = mapa / (tf.reduce_max(mapa) + 1e-8)
    return mapa.numpy().astype(np.float32)


def superponer(img_rgb, mapa, alfa=0.4):
    """Mezcla la imagen RGB con el mapa de calor. Devuelve RGB uint8 del tamaño de la imagen."""
    img_rgb = np.asarray(img_rgb)
    m = cv2.resize(np.asarray(mapa, dtype=np.float32), (img_rgb.shape[1], img_rgb.shape[0]),
                   interpolation=cv2.INTER_CUBIC)
    m = np.clip(m, 0.0, 1.0)
    calor = cv2.applyColorMap(np.uint8(255 * m), cv2.COLORMAP_JET)[..., ::-1]
    return np.clip(img_rgb * (1 - alfa) + calor * alfa, 0, 255).astype(np.uint8)
