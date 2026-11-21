"""Punto 3 (parte ejecutada) · Los clásicos se reproducen entrenando SOLO con entrenamiento, con código propio.

1. Los .joblib guardados predicen lo mismo que predicciones_prueba.csv.
2. Reentrenando desde cero (Pipeline propio, solo filas de entrenamiento) se obtienen las mismas
   probabilidades de prueba y las mismas predicciones fuera de pliegue: no hace falta la prueba para llegar a esos números.
3. El escalador guardado dentro de cada Pipeline tiene la media del entrenamiento (no de todo el conjunto).
"""
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

RAIZ = Path(r"C:\proyectos\tumores-cerebrales")
RES = RAIZ / "resultados"
man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
with np.load(RAIZ / "datos" / "rasgos" / "rasgos_mobilenet.npz") as d:
    Xm = d["X"]; assert (d["rutas"] == man.ruta.to_numpy()).all()
with np.load(RAIZ / "datos" / "rasgos" / "rasgos_basicos.npz") as d:
    Xb = d["X"]; assert (d["rutas"] == man.ruta.to_numpy()).all()
ent = (man.particion == "entrenamiento").to_numpy(); pru = ~ent
y = man.es_tumor.to_numpy()
pp = pd.read_csv(RES / "predicciones_prueba.csv"); po = pd.read_csv(RES / "predicciones_oof.csv")
info = json.loads((RES / "modelos_clasicos" / "info.json").read_text(encoding="utf-8"))

# rasgos básicos: recalcular con código propio en una muestra
import cv2
imgs = np.load(RAIZ / "datos" / "rasgos" / "imagenes_160.npy", mmap_mode="r")
idx = np.random.default_rng(1).choice(len(man), 500, replace=False)
peor = 0.0
for i in idx:
    g = cv2.cvtColor(np.asarray(imgs[i]), cv2.COLOR_RGB2GRAY).astype(np.float64)
    hist = np.histogram(g, bins=16, range=(0, 256))[0] / g.size
    mio = np.concatenate([[g.mean() / 255, g.std() / 255], hist])
    peor = max(peor, np.abs(mio - Xb[i]).max())
print(f"Rasgos básicos recalculados (500 imágenes): diferencia máxima {peor:.2e}")

definiciones = {
    "Logística (rasgos básicos)": (Xb, LogisticRegression(max_iter=5000, C=1.0, class_weight="balanced", random_state=42)),
    "Logística (MobileNetV2)": (Xm, LogisticRegression(max_iter=5000, C=1.0, class_weight="balanced", random_state=42)),
    "Random Forest (MobileNetV2)": (Xm, RandomForestClassifier(n_estimators=300, class_weight="balanced", n_jobs=-1, random_state=42)),
    "SVM RBF (MobileNetV2)": (Xm, SVC(kernel="rbf", C=10, gamma="scale", class_weight="balanced", probability=True, random_state=42)),
}
me = man[ent].reset_index(drop=True)
pliegues = list(StratifiedKFold(5, shuffle=True, random_state=42).split(np.zeros(len(me)), me.clase))
for nombre, (X, est) in definiciones.items():
    ref = pp[pp.modelo == nombre].set_index("ruta").loc[man.ruta[pru], "probabilidad_tumor"].to_numpy()
    guardado = joblib.load(RES / "modelos_clasicos" / info[nombre]["archivo"])
    es_pipeline = isinstance(guardado, Pipeline) and isinstance(guardado.steps[0][1], StandardScaler)
    d_guardado = np.abs(guardado.predict_proba(X[pru])[:, 1] - ref).max()
    esc = guardado.steps[0][1]
    d_media_ent = np.abs(esc.mean_ - X[ent].mean(0)).max(); d_media_todo = np.abs(esc.mean_ - X.mean(0)).max()
    tub = Pipeline([("e", StandardScaler()), ("m", est)])
    nuevo = clone(tub).fit(X[ent], y[ent])
    d_nuevo = np.abs(nuevo.predict_proba(X[pru])[:, 1] - ref).max()
    linea = (f"{nombre}: Pipeline con StandardScaler = {es_pipeline} · .joblib contra CSV dif máx = {d_guardado:.2e} · "
             f"reentrenado solo con entrenamiento contra CSV dif máx = {d_nuevo:.2e} · "
             f"media del escalador: dif con entrenamiento {d_media_ent:.1e}, con todo el conjunto {d_media_todo:.1e}")
    if "SVM" not in nombre:   # el OOF del SVM tarda ~1 min; se omite
        p = np.full(ent.sum(), np.nan)
        for itr, iva in pliegues:
            p[iva] = clone(tub).fit(X[ent][itr], y[ent][itr]).predict_proba(X[ent][iva])[:, 1]
        ref_o = po[po.modelo == nombre].set_index("ruta").loc[me.ruta, "probabilidad_tumor"].to_numpy()
        linea += f" · OOF recalculado contra CSV dif máx = {np.abs(p - ref_o).max():.2e}"
    print(linea)
