"""Arquitectura de la red en Keras.

Dos modelos que comparten exactamente la misma cabeza (mismos nombres de capa):

- `construir_cabeza`: recibe los 1,280 rasgos ya extraídos de MobileNetV2. Es rápida de
  entrenar en CPU y es la que se usa en la validación cruzada.
- `construir_completo`: recibe la imagen RGB de 160x160 con valores de 0 a 255, la normaliza
  dentro del modelo, pasa por MobileNetV2 y por la misma cabeza. Es el que usa la aplicación
  y el que permite Grad-CAM y ajuste fino.

Salidas (diccionario):
- "tumor": probabilidad de tumor (sigmoide, 1 valor).
- "tipo": probabilidad de cada tipo de tumor (softmax sobre TIPOS_TUMOR).

Pérdidas:
- "tumor": entropía cruzada binaria ponderada por clase (por el desbalance entre tumor y sin tumor).
- "tipo": entropía cruzada solo sobre los casos de tumor; los casos "sin tumor" llevan la
  etiqueta -1 y su peso es 0.
- Pérdida total = pérdida_tumor + PESO_PERDIDA_TIPO * pérdida_tipo. La pérdida total de
  validación (`val_loss`) es la que vigilan todos los callbacks.
"""
from collections import Counter

import keras
import numpy as np
from keras import layers, ops

from .config import TAM, TIPOS_TUMOR

DIM_RASGOS = 1280
NOMBRE_CAPA_GRADCAM = "out_relu"        # última activación convolucional de MobileNetV2
NOMBRE_CAPA_RASGOS = "promedio_global"  # salida de 1,280 valores
NOMBRE_CAPA_LOGIT = "tumor_logit"       # valor previo a la sigmoide (se usa en Grad-CAM)
CAPAS_CABEZA = ["densa", "tumor_logit", "tipo"]
PESO_PERDIDA_TIPO = 0.5
DROPOUT = 0.3


def _cabeza(x, dropout=DROPOUT):
    x = layers.Dense(256, activation="relu", name="densa")(x)
    x = layers.Dropout(dropout, name="dropout")(x)
    logit = layers.Dense(1, name=NOMBRE_CAPA_LOGIT)(x)
    tumor = layers.Activation("sigmoid", name="tumor")(logit)
    tipo = layers.Dense(len(TIPOS_TUMOR), activation="softmax", name="tipo")(x)
    return {"tumor": tumor, "tipo": tipo}


def construir_cabeza(dim=DIM_RASGOS, dropout=DROPOUT):
    """Modelo Keras sobre rasgos: Dense(256, relu) -> Dropout -> salidas "tumor" y "tipo"."""
    entrada = keras.Input(shape=(dim,), name="rasgos")
    return keras.Model(entrada, _cabeza(entrada, dropout), name="cabeza")


def construir_completo(pesos="imagenet", dropout=DROPOUT, cabeza=None):
    """Modelo de imagen a predicción.

    Entrada: (160, 160, 3) con valores de 0 a 255 (RGB). La normalización de MobileNetV2
    (x / 127.5 - 1) está dentro del modelo. MobileNetV2 queda congelada.
    Si se pasa `cabeza` (un modelo de `construir_cabeza` ya entrenado) se copian sus pesos.
    Es un modelo "plano": la capa de Grad-CAM se obtiene con
    `modelo.get_layer(NOMBRE_CAPA_GRADCAM)`.
    """
    entrada = keras.Input(shape=(TAM, TAM, 3), name="imagen")
    x = layers.Rescaling(1.0 / 127.5, offset=-1.0, name="normalizacion")(entrada)
    base = keras.applications.MobileNetV2(include_top=False, weights=pesos, input_tensor=x,
                                          input_shape=(TAM, TAM, 3))
    for capa in base.layers:
        capa.trainable = False
    x = layers.GlobalAveragePooling2D(name=NOMBRE_CAPA_RASGOS)(base.output)
    modelo = keras.Model(entrada, _cabeza(x, dropout), name="tumores_mobilenetv2")
    modelo.get_layer(NOMBRE_CAPA_GRADCAM)  # falla aquí si el nombre de la capa cambiara
    if cabeza is not None:
        copiar_pesos_cabeza(cabeza, modelo)
    return modelo


def copiar_pesos_cabeza(origen, destino):
    """Copia los pesos de las capas de la cabeza de un modelo a otro (por nombre de capa)."""
    for nombre in CAPAS_CABEZA:
        destino.get_layer(nombre).set_weights(origen.get_layer(nombre).get_weights())
    return destino


def capas_base(modelo_completo):
    """Capas de MobileNetV2 dentro del modelo completo (todo lo anterior al promedio global)."""
    nombres = [c.name for c in modelo_completo.layers]
    fin = nombres.index(NOMBRE_CAPA_RASGOS)
    return [c for c in modelo_completo.layers[:fin] if c.name not in ("imagen", "normalizacion")]


def pesos_clase(y):
    """Pesos de clase balanceados: total / (número de clases * casos de la clase)."""
    c = Counter(int(v) for v in np.asarray(y).ravel())
    total = sum(c.values())
    return {k: total / (len(c) * v) for k, v in c.items()}


def crear_perdida_tumor(peso_sin_tumor=1.0, peso_tumor=1.0):
    """Entropía cruzada binaria ponderada por clase (promedio ponderado del lote)."""
    def perdida_tumor(y_true, y_pred):
        y = ops.reshape(ops.cast(y_true, "float32"), (-1,))
        p = ops.clip(ops.reshape(ops.cast(y_pred, "float32"), (-1,)), 1e-7, 1.0 - 1e-7)
        ce = -(y * ops.log(p) + (1.0 - y) * ops.log(1.0 - p))
        w = y * peso_tumor + (1.0 - y) * peso_sin_tumor
        return ops.sum(ce * w) / ops.maximum(ops.sum(w), 1e-7)
    return perdida_tumor


def perdida_tipo(y_true, y_pred):
    """Entropía cruzada del tipo de tumor; ignora los casos con etiqueta -1 (sin tumor)."""
    y = ops.reshape(ops.cast(y_true, "int32"), (-1,))
    mascara = ops.cast(y >= 0, "float32")
    y = ops.maximum(y, 0)
    ce = keras.losses.sparse_categorical_crossentropy(y, y_pred)
    return ops.sum(ce * mascara) / ops.maximum(ops.sum(mascara), 1.0)


def compilar(modelo, tasa, pesos=None):
    """Compila con Adam, las dos pérdidas y la exactitud de la salida "tumor".

    `pesos` es el dict de `pesos_clase` ({0: peso sin tumor, 1: peso tumor}).
    """
    pesos = pesos or {0: 1.0, 1: 1.0}
    modelo.compile(
        optimizer=keras.optimizers.Adam(tasa),
        loss={"tumor": crear_perdida_tumor(float(pesos.get(0, 1.0)), float(pesos.get(1, 1.0))),
              "tipo": perdida_tipo},
        loss_weights={"tumor": 1.0, "tipo": PESO_PERDIDA_TIPO},
        metrics={"tumor": [keras.metrics.BinaryAccuracy(name="accuracy")]},
    )
    return modelo
