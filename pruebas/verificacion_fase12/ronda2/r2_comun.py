"""Ronda 2 · Cálculo común e independiente del proyecto: miniaturas PIL 64x64 de las 7,200 imágenes y
matriz de correlación máxima sobre las 8 orientaciones (imagen completa y recorte propio).

No importa nada de app.backend.ml. El resultado se guarda en caché FUERA del proyecto.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

RAIZ = Path(r"C:\proyectos\tumores-cerebrales")
CACHE = Path(os.environ.get("R2_CACHE", r"C:\Users\raulp\AppData\Local\Temp\claude\e2221770270e0191\02d9ffa9-eb1c-4c85-8bae-918c19053d32\scratchpad\r2_cache"))
ORIENTACIONES = ["directa", "espejo_h", "espejo_v", "giro_180", "giro_90", "giro_270", "transpuesta", "antitranspuesta"]
OPS = {
    "directa": lambda a: a, "espejo_h": lambda a: a[:, :, ::-1], "espejo_v": lambda a: a[:, ::-1, :],
    "giro_180": lambda a: a[:, ::-1, ::-1], "giro_90": lambda a: np.rot90(a, 1, axes=(1, 2)),
    "giro_270": lambda a: np.rot90(a, 3, axes=(1, 2)), "transpuesta": lambda a: a.transpose(0, 2, 1),
    "antitranspuesta": lambda a: a[:, ::-1, ::-1].transpose(0, 2, 1),
}


def todas_las_rutas():
    return sorted(p.relative_to(RAIZ).as_posix() for c in ["Training", "Testing"] for p in (RAIZ / "datos" / c).rglob("*") if p.is_file())


def recorte_propio(g):
    m = g > 10
    if not m.any():
        return g
    f, c = np.where(m.any(1))[0], np.where(m.any(0))[0]
    return g[f[0]:f[-1] + 1, c[0]:c[-1] + 1]


def _mini(ruta):
    im = Image.open(RAIZ / ruta).convert("L")
    g = np.asarray(im)
    a = np.asarray(im.resize((64, 64), Image.Resampling.BOX), dtype=np.float32)
    b = np.asarray(Image.fromarray(recorte_propio(g)).resize((64, 64), Image.Resampling.BOX), dtype=np.float32)
    return a, b


def norm(A):
    A = np.ascontiguousarray(A).reshape(len(A), -1).astype(np.float32)
    A = A - A.mean(1, keepdims=True)
    return A / np.maximum(np.linalg.norm(A, axis=1, keepdims=True), 1e-12)


def cargar():
    """Devuelve (rutas, C, O): C[i, j] = correlación máxima entre i y j en cualquier orientación y miniatura;
    O[i, j] = índice de la orientación que la da (según la miniatura completa o la recortada, la mayor)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    rutas = np.array(todas_las_rutas())
    fc, fo, fr = CACHE / "C.npy", CACHE / "O.npy", CACHE / "rutas.npy"
    if fc.exists() and fo.exists() and fr.exists() and (np.load(fr) == rutas).all():
        return rutas, np.load(fc, mmap_mode="r"), np.load(fo, mmap_mode="r")
    with ThreadPoolExecutor(12) as ex:
        res = list(ex.map(_mini, rutas))
    n = len(rutas)
    C = np.full((n, n), -1.0, dtype=np.float32)
    O = np.zeros((n, n), dtype=np.uint8)
    for M in (np.stack([r[0] for r in res]), np.stack([r[1] for r in res])):
        base = norm(M)
        for k, nombre in enumerate(ORIENTACIONES):
            c = base @ norm(OPS[nombre](M)).T
            gana = c > C
            C[gana] = c[gana]; O[gana] = k
            del c, gana
    C = np.maximum(C, C.T)   # simétrica (las orientaciones forman un grupo cerrado)
    np.fill_diagonal(C, -1.0)
    np.save(fc, C); np.save(fo, O); np.save(fr, rutas)
    return rutas, C, O


def componentes(n, ii, jj):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    return connected_components(coo_matrix((np.ones(len(ii)), (ii, jj)), shape=(n, n)), directed=False)[1]


def orientar(img, k):
    """Aplica la orientación k (índice de ORIENTACIONES) a una imagen 2D."""
    return OPS[ORIENTACIONES[k]](img[None])[0]
