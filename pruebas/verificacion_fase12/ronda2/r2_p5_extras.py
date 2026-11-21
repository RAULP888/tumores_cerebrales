"""Ronda 2 · Comprobaciones sueltas: firma del caché, `elegir_umbral` con margen, impacto de las casi gemelas
que quedaron (banda 0.90-0.98) en las métricas de prueba, y montaje de la banda 0.95-0.98 para notumor y meningioma."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(r"C:\proyectos\tumores-cerebrales")
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ)); sys.path.insert(0, str(AQUI))
from app.backend.ml import rasgos
from app.backend.ml.metricas import elegir_umbral

man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
print("== Firma del caché de rasgos ==")
f0 = rasgos.firma_cache(man)
with np.load(RAIZ / "datos" / "rasgos" / "rasgos_mobilenet.npz") as d:
    f_mob = str(d["firma"])
with np.load(RAIZ / "datos" / "rasgos" / "rasgos_basicos.npz") as d:
    f_bas = str(d["firma"])
f_img = (RAIZ / "datos" / "rasgos" / "imagenes_160.firma.txt").read_text(encoding="utf-8").strip()
print("Firma actual == la guardada en rasgos_mobilenet / rasgos_basicos / imagenes_160:", f0 == f_mob, f0 == f_bas, f0 == f_img)
m2 = man.copy(); m2.loc[0, "sha256"] = "0" * 64
m3 = man.iloc[::-1].reset_index(drop=True)
m4 = man.iloc[:-1]
print("Cambia si cambia un sha256:", rasgos.firma_cache(m2) != f0, "· si cambia el orden:", rasgos.firma_cache(m3) != f0, "· si falta una fila:", rasgos.firma_cache(m4) != f0)
print("Entra en la firma el código de: preprocesar.py, rasgos.py, red.py (leído del módulo). NO entra: versión de keras/opencv ni los pesos de ImageNet.")

print("\n== elegir_umbral con margen ==")
rng = np.random.default_rng(0)
peor_margen, fallos = 1.0, 0
for _ in range(300):
    n = int(rng.integers(30, 400))
    y = (rng.random(n) < 0.8).astype(int)
    if y.sum() < 5:
        continue
    p = np.round(np.clip(rng.normal(0.5 + 0.25 * y, 0.25), 0, 1), int(rng.integers(2, 8)))
    u = elegir_umbral(y, p, 0.98)
    pos = p[y == 1]
    bruto = next(t for t in np.unique(p)[::-1] if (pos >= t).mean() >= 0.98)
    ok = (pos >= u).mean() >= 0.98 and ((p >= u) == (p >= bruto)).all() and not (p == u).any()
    fallos += int(not ok)
    peor_margen = min(peor_margen, np.abs(p - u).min())
print(f"300 casos aleatorios: fallos = {fallos} (mismas decisiones que el umbral 'más alto con sens >= 0.98' y ninguna probabilidad exactamente sobre el umbral) · margen mínimo observado {peor_margen:.2e}")
print("Caso límite, todas las probabilidades iguales:", elegir_umbral([1, 1, 0], [0.5, 0.5, 0.5]), "· un solo tumor:", elegir_umbral([1, 0], [0.9, 0.2]))

print("\n== Métricas de prueba separando las imágenes con casi gemela en entrenamiento (mi medida) ==")
pe = pd.read_csv(AQUI / "r2_pares_prueba_entrenamiento.csv").set_index("ruta_prueba")
pp = pd.read_csv(RAIZ / "resultados" / "predicciones_prueba.csv")
filas = []
for m, a in pp.groupby("modelo", sort=False):
    a = a.set_index("ruta"); c = pe.loc[a.index, "correlacion"].to_numpy()
    for nombre, sel in [("corr > 0.95", c > 0.95), ("0.90 < corr <= 0.95", (c > 0.90) & (c <= 0.95)), ("corr <= 0.90", c <= 0.90)]:
        y, pr = a.es_tumor.to_numpy()[sel], a.prediccion.to_numpy()[sel]
        vp, fn = int(((y == 1) & (pr == 1)).sum()), int(((y == 1) & (pr == 0)).sum())
        vn, fp = int(((y == 0) & (pr == 0)).sum()), int(((y == 0) & (pr == 1)).sum())
        filas.append({"modelo": m, "subconjunto": nombre, "n": int(sel.sum()), "tumores": vp + fn, "sin_tumor": vn + fp, "fn": fn, "fp": fp,
                      "sensibilidad": round(vp / max(1, vp + fn), 4), "especificidad": round(vn / max(1, vn + fp), 4)})
pd.set_option("display.width", 220)
print(pd.DataFrame(filas).to_string(index=False))

# Montaje: toda la banda 0.95-0.98 de notumor y meningioma (prueba contra entrenamiento)
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from r2_comun import ORIENTACIONES, cargar, orientar
rutas, C, O = cargar()
pos = pd.Series(np.arange(len(rutas)), index=rutas)
b = pe.reset_index()
b = b[(b.correlacion > 0.95) & (b.correlacion <= 0.98)]
for clases, archivo in [(["notumor", "meningioma"], "r2_prueba_ent_095_098_notumor_meningioma.png"), (["glioma"], "r2_prueba_ent_095_098_glioma.png")]:
    s = b[b.clase_prueba.isin(clases)].sort_values("correlacion", ascending=False).head(24)
    fig, axs = plt.subplots(6, 8, figsize=(20, 16))
    for ax in axs.ravel():
        ax.axis("off")
    for k, r in enumerate(s.itertuples()):
        o = int(O[pos[r.ruta_prueba], pos[r.ruta_entrenamiento]])
        axs.ravel()[2 * k].imshow(Image.open(RAIZ / r.ruta_prueba).convert("L"), cmap="gray"); axs.ravel()[2 * k].set_title("PRUEBA " + Path(r.ruta_prueba).name, fontsize=7)
        axs.ravel()[2 * k + 1].imshow(orientar(np.asarray(Image.open(RAIZ / r.ruta_entrenamiento).convert("L")), o), cmap="gray")
        axs.ravel()[2 * k + 1].set_title(f"ENT {Path(r.ruta_entrenamiento).name}\n{ORIENTACIONES[o]} · corr {r.correlacion:.3f}", fontsize=7)
    fig.tight_layout(); fig.savefig(AQUI / archivo, dpi=60); plt.close(fig)
    print("Montaje", archivo, "con", len(s), "pares de", int(b.clase_prueba.isin(clases).sum()))
