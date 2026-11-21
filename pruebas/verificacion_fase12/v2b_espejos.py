"""Punto 2 (ampliación) · ¿Hay copias en espejo / giradas entre entrenamiento y prueba?

Comprobación exacta a resolución completa: SHA-256 de los pixeles decodificados (PIL, grises) de cada
imagen y de sus variantes (espejo horizontal, espejo vertical, giro de 180°). Si la variante de una imagen
de prueba coincide con el original de una de entrenamiento, es la misma toma volteada.
Además, comprobación tolerante (compresión JPEG distinta) con miniaturas de 64x64.
"""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

RAIZ = Path(r"C:\proyectos\tumores-cerebrales")
AQUI = Path(__file__).resolve().parent
man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
ent = (man.particion == "entrenamiento").to_numpy(); pru = ~ent
VARIANTES = {"original": lambda g: g, "espejo_horizontal": lambda g: g[:, ::-1], "espejo_vertical": lambda g: g[::-1, :],
             "giro_180": lambda g: g[::-1, ::-1]}


def h(g):
    g = np.ascontiguousarray(g)
    return hashlib.sha256(str(g.shape).encode() + g.tobytes()).hexdigest()


def analizar(ruta):
    im = Image.open(RAIZ / ruta).convert("L")
    g = np.asarray(im)
    m = np.asarray(im.resize((64, 64), Image.Resampling.BOX), dtype=np.float32)
    return {k: h(f(g)) for k, f in VARIANTES.items()}, m


with ThreadPoolExecutor(12) as ex:
    res = list(ex.map(analizar, man.ruta))
hashes = pd.DataFrame([r[0] for r in res])
mini = np.stack([r[1] for r in res])

print("== Coincidencia EXACTA de pixeles (resolución completa) entre particiones ==")
orig_ent = set(hashes.original[ent]); orig_todo = hashes.original
for k in VARIANTES:
    en_pru = hashes.loc[pru, k].isin(orig_ent)
    # dentro de todo el manifiesto: imagen cuya variante es el original de OTRA imagen
    mapa = pd.Series(np.arange(len(man)), index=orig_todo.to_numpy())
    mapa = mapa[~mapa.index.duplicated()]
    j = mapa.reindex(hashes[k].to_numpy()).to_numpy()
    otra = ~np.isnan(j) & (j != np.arange(len(man)))
    print(f"   {k:18s}: imágenes de prueba cuya variante es idéntica a una imagen de entrenamiento = {int(en_pru.sum())} · "
          f"pares en todo el manifiesto (variante == original de otra imagen) = {int(otra.sum())}")

print("\n== Coincidencia tolerante (miniatura 64x64, correlación) entre prueba y entrenamiento ==")


def norm(M):
    M = M.reshape(len(M), -1).astype(np.float64)
    M = M - M.mean(1, keepdims=True)
    return M / np.maximum(np.linalg.norm(M, axis=1, keepdims=True), 1e-12)


te = norm(mini[pru])
filas = {}
for k, f in {"original": lambda a: a, "espejo_horizontal": lambda a: a[:, :, ::-1], "espejo_vertical": lambda a: a[:, ::-1, :],
             "giro_180": lambda a: a[:, ::-1, ::-1]}.items():
    tr = norm(f(mini[ent]))
    c = te @ tr.T
    filas[k] = (c.max(1), c.argmax(1))
    print(f"   {k:18s}: " + " · ".join(f"> {u}: {int((c.max(1) > u).sum())}" for u in [0.95, 0.98, 0.99, 0.995, 0.999]))

# Autosimetría: una imagen casi simétrica se parece a su propio espejo; eso NO es una copia.
propia = (norm(mini) * norm(mini[:, :, ::-1])).sum(1)
print(f"\nCorrelación de cada imagen con SU PROPIO espejo horizontal (64x64): mediana {np.median(propia):.3f} · > 0.95: {int((propia > 0.95).sum())} · > 0.99: {int((propia > 0.99).sum())} de {len(man)}")
mo, ao = filas["original"]; mh, ah = filas["espejo_horizontal"]
ganancia = mh - mo
print(f"Prueba donde el espejo de una imagen de entrenamiento se parece > 0.99 y la versión directa de CUALQUIER entrenamiento queda < 0.95: {int(((mh > 0.99) & (mo < 0.95)).sum())}")
print(f"Prueba con espejo > 0.99: {int((mh > 0.99).sum())} · de ellas, el par en espejo y el par directo son la misma imagen de entrenamiento: {int(((mh > 0.99) & (ah == ao)).sum())}")

man_pru, man_ent = man[pru].reset_index(drop=True), man[ent].reset_index(drop=True)
t = pd.DataFrame({"ruta_prueba": man_pru.ruta, "clase_prueba": man_pru.clase, "corr_directa": mo, "par_directo": man_ent.ruta[ao].to_numpy(),
                  "corr_espejo": mh, "par_espejo": man_ent.ruta[ah].to_numpy(), "clase_par_espejo": man_ent.clase[ah].to_numpy(),
                  "autosimetria_prueba": propia[pru]})
t.to_csv(AQUI / "pares_espejo.csv", index=False, encoding="utf-8")
sel = t[(t.corr_espejo > 0.99)]
print("Por clase (espejo > 0.99):", sel.clase_prueba.value_counts().to_dict(), "· clase distinta en el par:", int((sel.clase_prueba != sel.clase_par_espejo).sum()))

# Diferencia a resolución completa de los pares en espejo más fuertes
print("\nDiferencia a resolución completa de pares en espejo (prueba contra espejo de entrenamiento):")
difs = []
for r in sel.sort_values("corr_espejo", ascending=False).itertuples():
    a = np.asarray(Image.open(RAIZ / r.ruta_prueba).convert("L")).astype(np.int16)
    b = np.asarray(Image.open(RAIZ / r.par_espejo).convert("L")).astype(np.int16)[:, ::-1]
    if a.shape == b.shape:
        difs.append((np.abs(a - b).mean(), np.abs(a - b).max(), (a == b).mean()))
difs = np.array(difs)
if len(difs):
    print(f"   pares con el mismo tamaño: {len(difs)} de {len(sel)} · idénticos pixel a pixel: {int((difs[:, 1] == 0).sum())} · "
          f"diferencia absoluta media < 1 nivel de gris: {int((difs[:, 0] < 1).sum())} · < 3: {int((difs[:, 0] < 3).sum())} · mediana de la diferencia media: {np.median(difs[:, 0]):.2f}")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
for nombre, filtro in [("espejo_top", sel.sort_values("corr_espejo", ascending=False)),
                       ("espejo_no_simetricas", sel[sel.autosimetria_prueba < 0.90].sort_values("corr_espejo", ascending=False)),
                       ("espejo_sin_par_directo", t[(t.corr_espejo > 0.99) & (t.corr_directa < 0.95)].sort_values("corr_espejo", ascending=False))]:
    f12 = filtro.head(12)
    if not len(f12):
        print(f"(sin pares para {nombre})"); continue
    fig, axs = plt.subplots(4, 6, figsize=(15, 10.5))
    for ax in axs.ravel():
        ax.axis("off")
    for k, r in enumerate(f12.itertuples()):
        a, b = axs.ravel()[2 * k], axs.ravel()[2 * k + 1]
        a.imshow(Image.open(RAIZ / r.ruta_prueba).convert("L"), cmap="gray"); a.set_title(f"PRUEBA {Path(r.ruta_prueba).name}\nautosim {r.autosimetria_prueba:.2f}", fontsize=7)
        b.imshow(Image.open(RAIZ / r.par_espejo).convert("L"), cmap="gray"); b.set_title(f"ENT (sin voltear) {Path(r.par_espejo).name}\nespejo {r.corr_espejo:.4f} directa {r.corr_directa:.3f}", fontsize=7)
    fig.suptitle(nombre); fig.tight_layout(); fig.savefig(AQUI / f"pares_{nombre}.png", dpi=80); plt.close(fig)
    print(f"Montaje pares_{nombre}.png: {len(f12)} pares (de {len(filtro)})")
