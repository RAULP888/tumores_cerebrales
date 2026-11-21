"""Detección de casi duplicados invariante a espejo y giro.

El dataset trae muchas tomas repetidas que no son copias bit a bit: la misma imagen
volteada en espejo, girada o recomprimida en JPEG. Las huellas (SHA-256, hash perceptual)
no las detectan. Aquí cada imagen se reduce a una miniatura de 64x64 en grises y se mide
la correlación de Pearson entre miniaturas, comparando cada imagen con las demás tal
cual y en sus 7 variantes de espejo y giro (las 8 orientaciones del cuadrado).

Dos imágenes se consideran la misma toma si la correlación supera el umbral (0.98).
"""
import cv2
import numpy as np

UMBRAL_CORRELACION = 0.98
TAM_MINIATURA = 64

# Las 8 orientaciones de una miniatura cuadrada (lote con forma n x alto x ancho).
VARIANTES = {
    "directa": lambda a: a,
    "espejo_horizontal": lambda a: a[:, :, ::-1],
    "espejo_vertical": lambda a: a[:, ::-1, :],
    "giro_180": lambda a: a[:, ::-1, ::-1],
    "giro_90": lambda a: np.rot90(a, 1, axes=(1, 2)),
    "giro_270": lambda a: np.rot90(a, 3, axes=(1, 2)),
    "transpuesta": lambda a: a.transpose(0, 2, 1),
    "antitranspuesta": lambda a: a[:, ::-1, ::-1].transpose(0, 2, 1),
}


def miniatura(img, n=TAM_MINIATURA):
    """Miniatura n x n en grises (float32) de una imagen en grises o de 3 canales (BGR o RGB)."""
    img = np.asarray(img)
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)   # para este uso da igual BGR que RGB
    return cv2.resize(img, (n, n), interpolation=cv2.INTER_AREA).astype(np.float32)


def _normalizar(mini):
    m = np.asarray(mini, dtype=np.float32).reshape(len(mini), -1)
    m = m - m.mean(axis=1, keepdims=True)
    return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-6)


def pares_casi_duplicados(mini, umbral=UMBRAL_CORRELACION, variantes=None):
    """Pares (i < j) de un mismo lote de miniaturas cuya correlación supera el umbral.

    Devuelve una lista de tuplas (i, j, variante, correlacion). Si un par supera el umbral
    en varias variantes aparece una vez por variante.
    """
    variantes = list(VARIANTES) if variantes is None else list(variantes)
    mini = np.asarray(mini, dtype=np.float32)
    a = _normalizar(mini)
    pares = []
    for nombre in variantes:
        c = a @ _normalizar(np.ascontiguousarray(VARIANTES[nombre](mini))).T
        ii, jj = np.nonzero(np.triu(c > umbral, k=1))
        pares += [(int(i), int(j), nombre, float(c[i, j])) for i, j in zip(ii, jj)]
        if nombre != "directa":   # c no es simétrica en general: también el triángulo inferior
            ii, jj = np.nonzero(np.tril(c > umbral, k=-1))
            pares += [(int(j), int(i), nombre, float(c[i, j])) for i, j in zip(ii, jj)]
    return pares


def tabla_pares(mini, umbral=UMBRAL_CORRELACION, variantes=None):
    """Pares (i < j) con correlación mayor que el umbral, como dict de arreglos.

    Claves: "i", "j", "variante" y "correlacion". Cada par aparece UNA sola vez, con la
    orientación en la que su correlación es mayor; si empatan, gana la primera de la lista
    (por eso "directa" va primero). Es la forma rápida para umbrales bajos, con muchos pares.
    """
    variantes = list(VARIANTES) if variantes is None else list(variantes)
    mini = np.asarray(mini, dtype=np.float32)
    a = _normalizar(mini)
    n = len(a)
    mejor = np.full((n, n), -1.0, dtype=np.float32)
    cual = np.zeros((n, n), dtype=np.int8)
    for k, nombre in enumerate(variantes):
        c = a @ _normalizar(np.ascontiguousarray(VARIANTES[nombre](mini))).T
        c = np.maximum(c, c.T)   # la correlación del par no depende de cuál de las dos se voltea
        gana = c > mejor
        mejor[gana] = c[gana]
        cual[gana] = k
    ii, jj = np.nonzero(np.triu(mejor > umbral, k=1))
    return {"i": ii.astype(int), "j": jj.astype(int),
            "variante": np.array(variantes, dtype=object)[cual[ii, jj]],
            "correlacion": mejor[ii, jj].astype(float)}


def maxima_correlacion(mini_a, mini_b, variantes=None):
    """Para cada miniatura de A, la mayor correlación con alguna de B en cualquier orientación.

    Devuelve (maxima (n_a,), indice_en_b (n_a,), variante (n_a,) como arreglo de textos).
    """
    variantes = list(VARIANTES) if variantes is None else list(variantes)
    mini_a, mini_b = np.asarray(mini_a, dtype=np.float32), np.asarray(mini_b, dtype=np.float32)
    a = _normalizar(mini_a)
    mejor = np.full(len(a), -1.0, dtype=np.float32)
    cual = np.zeros(len(a), dtype=int)
    var = np.array(["directa"] * len(a), dtype=object)
    if len(mini_b) == 0:
        return mejor, cual, var
    for nombre in variantes:
        c = a @ _normalizar(np.ascontiguousarray(VARIANTES[nombre](mini_b))).T
        m, k = c.max(axis=1), c.argmax(axis=1)
        gana = m > mejor
        mejor[gana], cual[gana], var[gana] = m[gana], k[gana], nombre
    return mejor, cual, var


def contar_gemelas(mini_a, mini_b, umbrales=(0.98, 0.95, 0.90)):
    """Cuántas imágenes de A tienen en B una gemela (cualquier orientación) por encima de cada umbral.

    Devuelve un dict {umbral: cantidad}.
    """
    mejor, _, _ = maxima_correlacion(mini_a, mini_b)
    return {float(u): int((mejor > u).sum()) for u in umbrales}


def agrupar(n, pares):
    """Componentes conexas: une los índices 0..n-1 enlazados por los pares (i, j).

    Devuelve un arreglo con el número de grupo de cada índice (el menor índice del grupo).
    """
    padre = list(range(n))

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for i, j in pares:
        a, b = raiz(int(i)), raiz(int(j))
        if a != b:
            padre[max(a, b)] = min(a, b)
    return np.array([raiz(i) for i in range(n)])
