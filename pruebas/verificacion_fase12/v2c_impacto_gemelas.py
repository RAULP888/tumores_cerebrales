"""Punto 2 (impacto) · Gemelas directas y en espejo: cuántas hay, en qué particiones y cuánto inflan las métricas.

Relación "gemela": correlación > 0.98 entre miniaturas 64x64 en grises, comparando la imagen con la otra
tal cual, en espejo horizontal, en espejo vertical o girada 180°. Se forman grupos (componentes conexas).
No modifica nada del proyecto: solo mide.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from sklearn.base import clone
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

RAIZ = Path(r"C:\proyectos\tumores-cerebrales")
AQUI = Path(__file__).resolve().parent
UMBRAL = 0.98
man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
ent = (man.particion == "entrenamiento").to_numpy(); pru = ~ent
n = len(man)


def mini(ruta):
    return np.asarray(Image.open(RAIZ / ruta).convert("L").resize((64, 64), Image.Resampling.BOX), dtype=np.float32)


with ThreadPoolExecutor(12) as ex:
    M = np.stack(list(ex.map(mini, man.ruta)))


def norm(A):
    A = A.reshape(len(A), -1).astype(np.float32)
    A = A - A.mean(1, keepdims=True)
    return A / np.maximum(np.linalg.norm(A, axis=1, keepdims=True), 1e-12)


base = norm(M)
variantes = {"directa": M, "espejo_horizontal": M[:, :, ::-1], "espejo_vertical": M[:, ::-1, :], "giro_180": M[:, ::-1, ::-1]}
pares = {}
for k, V in variantes.items():
    C = base @ norm(V).T
    np.fill_diagonal(C, -1)          # una imagen no es gemela de sí misma (ni de su propio espejo)
    pares[k] = C > UMBRAL
    del C
cualquiera = np.logical_or.reduce(list(pares.values()))
cualquiera |= cualquiera.T

print(f"== Gemelas (correlación 64x64 > {UMBRAL}) ==")
print("Imágenes de PRUEBA con al menos una gemela en ENTRENAMIENTO:")
for k, P in pares.items():
    P = P | P.T
    print(f"   {k:18s}: {int(P[np.ix_(pru, ent)].any(1).sum())} de {int(pru.sum())}")
solo_esp = (pares["espejo_horizontal"] | pares["espejo_horizontal"].T)[np.ix_(pru, ent)].any(1) & ~(pares["directa"] | pares["directa"].T)[np.ix_(pru, ent)].any(1)
con_gemela = cualquiera[np.ix_(pru, ent)].any(1)
print(f"   cualquiera        : {int(con_gemela.sum())} de {int(pru.sum())} ({con_gemela.mean():.1%})")
print(f"   solo por espejo horizontal (sin gemela directa): {int(solo_esp.sum())}")
mp = man[pru].reset_index(drop=True)
print("   por clase:", pd.crosstab(mp.clase, pd.Series(con_gemela, name="con_gemela_en_entrenamiento")).to_dict("index"))

# clases de las gemelas
i, j = np.where(np.triu(cualquiera))
print(f"Pares gemelos en todo el manifiesto: {len(i)} · con clase distinta: {int((man.clase.to_numpy()[i] != man.clase.to_numpy()[j]).sum())} · "
      f"con etiqueta tumor/sin tumor distinta: {int((man.es_tumor.to_numpy()[i] != man.es_tumor.to_numpy()[j]).sum())}")
_, grupo = connected_components(coo_matrix((np.ones(len(i)), (i, j)), shape=(n, n)), directed=False)
tam = np.bincount(grupo)
print(f"Grupos de gemelas: {len(tam)} grupos para {n} imágenes · imágenes en grupos de 2 o más: {int((tam[grupo] > 1).sum())} · grupo más grande: {tam.max()}")
cruza = pd.Series(man.particion.to_numpy()).groupby(grupo).nunique() > 1
print(f"Grupos repartidos entre entrenamiento y prueba: {int(cruza.sum())}")

# dentro del entrenamiento: gemelas en pliegues distintos
me = man[ent].reset_index(drop=True)
pl = np.zeros(len(me), dtype=int)
for k, (_, iv) in enumerate(StratifiedKFold(5, shuffle=True, random_state=42).split(np.zeros(len(me)), me.clase), 1):
    pl[iv] = k
Ce = cualquiera[np.ix_(ent, ent)]
otro_pliegue = (Ce & (pl[:, None] != pl[None, :])).any(1)
print(f"Imágenes de ENTRENAMIENTO con una gemela en OTRO pliegue de la validación cruzada: {int(otro_pliegue.sum())} de {len(me)} ({otro_pliegue.mean():.1%})")
# validación apartada del modelo final (15 %)
from sklearn.model_selection import train_test_split
itr, iva = train_test_split(np.arange(len(me)), test_size=0.15, stratify=me.clase, random_state=42)
val_gem = Ce[np.ix_(iva, itr)].any(1)
print(f"Imágenes de la VALIDACIÓN apartada (umbral y detención temprana) con gemela en su entrenamiento: {int(val_gem.sum())} de {len(iva)} ({val_gem.mean():.1%})")

# ---------------------------------------------------------- impacto en las métricas reportadas
print("\n== Métricas de prueba reportadas, separando imágenes con y sin gemela en entrenamiento ==")
pp = pd.read_csv(RAIZ / "resultados" / "predicciones_prueba.csv")
marca = pd.Series(con_gemela, index=mp.ruta)
filas = []
for m, a in pp.groupby("modelo", sort=False):
    a = a.set_index("ruta").loc[mp.ruta]
    for nombre, sel in [("con gemela", marca.to_numpy()), ("sin gemela", ~marca.to_numpy())]:
        y, pr_, p = a.es_tumor.to_numpy()[sel], a.prediccion.to_numpy()[sel], a.probabilidad_tumor.to_numpy()[sel]
        vp, fn = int(((y == 1) & (pr_ == 1)).sum()), int(((y == 1) & (pr_ == 0)).sum())
        vn, fp = int(((y == 0) & (pr_ == 0)).sum()), int(((y == 0) & (pr_ == 1)).sum())
        filas.append({"modelo": m, "subconjunto": nombre, "n": int(sel.sum()), "tumores": vp + fn, "sin_tumor": vn + fp, "fn": fn, "fp": fp,
                      "sensibilidad": vp / (vp + fn), "especificidad": vn / (vn + fp), "auc": roc_auc_score(y, p)})
pd.set_option("display.width", 250)
print(pd.DataFrame(filas).round(4).to_string(index=False))

# ---------------------------------------------------------- estimación con división por grupos
print("\n== Misma receta de modelos, validación cruzada por GRUPOS de gemelas contra la estratificada simple (todas las imágenes del manifiesto) ==")
with np.load(RAIZ / "datos" / "rasgos" / "rasgos_mobilenet.npz") as d:
    Xm = d["X"]
with np.load(RAIZ / "datos" / "rasgos" / "rasgos_basicos.npz") as d:
    Xb = d["X"]
y = man.es_tumor.to_numpy()
modelos = {
    "Logística (rasgos básicos)": (Xb, LogisticRegression(max_iter=5000, class_weight="balanced", random_state=42)),
    "Logística (MobileNetV2)": (Xm, LogisticRegression(max_iter=5000, class_weight="balanced", random_state=42)),
    "SVM RBF (MobileNetV2)": (Xm, SVC(kernel="rbf", C=10, gamma="scale", class_weight="balanced", probability=True, random_state=42)),
}
divisiones = {"estratificada simple (como el proyecto)": list(StratifiedKFold(5, shuffle=True, random_state=42).split(Xm, man.clase)),
              "por grupos de gemelas": list(StratifiedGroupKFold(5, shuffle=True, random_state=42).split(Xm, man.clase, grupo))}
for nombre, (X, est) in modelos.items():
    for dn, div in divisiones.items():
        p = np.full(n, np.nan)
        for a, b in div:
            p[b] = clone(Pipeline([("e", StandardScaler()), ("m", est)])).fit(X[a], y[a]).predict_proba(X[b])[:, 1]
        pos = np.sort(p[y == 1])[::-1]
        u = pos[int(np.ceil(0.98 * len(pos))) - 1]
        esp = (p[y == 0] < u).mean()
        # sensibilidad honesta: umbral elegido en 4 pliegues y aplicado al quinto
        sens, espe = [], []
        for a, b in div:
            pa = np.sort(p[a][y[a] == 1])[::-1]; ua = pa[int(np.ceil(0.98 * len(pa))) - 1]
            sens.append((p[b][y[b] == 1] >= ua).mean()); espe.append((p[b][y[b] == 0] < ua).mean())
        print(f"   {nombre:28s} · {dn:40s}: AUC OOF {roc_auc_score(y, p):.4f} · especificidad con sensibilidad 0.98 = {esp:.4f} · errores a ese umbral: FN {int((p[y == 1] < u).sum())}, FP {int((p[y == 0] >= u).sum())}")
pd.DataFrame({"ruta": man.ruta, "particion": man.particion, "grupo_gemelas": grupo, "tamano_grupo": tam[grupo]}).to_csv(AQUI / "grupos_gemelas.csv", index=False)
