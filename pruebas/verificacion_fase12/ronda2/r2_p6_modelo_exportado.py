"""Ronda 2 · Punto 6 (y parte del 5) · El modelo exportado es el evaluado; pesos de MobileNetV2 = ImageNet; rasgos guardados reproducibles.

Carga app/modelos/v001 con app.backend.ml.inferencia y predice TODAS las imágenes de prueba (y las de
validación) desde el archivo, por `predecir`. Solo lee el proyecto.
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
RAIZ = Path(r"C:\proyectos\tumores-cerebrales")
sys.path.insert(0, str(RAIZ))

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, roc_auc_score
from sklearn.model_selection import train_test_split

from app.backend.ml import inferencia
from app.backend.ml.preprocesar import leer_imagen

AQUI = Path(__file__).resolve().parent
RED = "Red Keras (MobileNetV2)"
man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
man_pru = man[man.particion == "prueba"].reset_index(drop=True)
man_ent = man[man.particion == "entrenamiento"].reset_index(drop=True)
pp = pd.read_csv(RAIZ / "resultados" / "predicciones_prueba.csv")
ref = pp[pp.modelo == RED].set_index("ruta").loc[man_pru.ruta]

modelo, info = inferencia.cargar_modelo(RAIZ / "app" / "modelos" / "v001")
print("Modelo cargado:", modelo.name, "· capas:", len(modelo.layers), "· umbral info.json:", info["umbral"])

# ---------------- prueba completa por la ruta de la app
t0 = time.time()
prob, hay, tipo, ptipo = [], [], [], []
for r in man_pru.ruta:
    s = inferencia.predecir(modelo, info, leer_imagen(RAIZ / r))
    prob.append(s["probabilidad_tumor"]); hay.append(s["hay_tumor"]); tipo.append(s["tipo_probable"]); ptipo.append(s["probabilidad_tipo"])
prob, hay = np.array(prob), np.array(hay)
print(f"\n== Prueba: {len(prob)} imágenes por inferencia.predecir en {time.time() - t0:.0f} s ==")
d = np.abs(prob - ref.probabilidad_tumor.to_numpy())
print(f"Diferencia máxima de probabilidad_tumor contra predicciones_prueba.csv: {d.max():.3e} (media {d.mean():.3e})")
print("Decisiones distintas (hay_tumor contra columna prediccion):", int((hay.astype(int) != ref.prediccion.to_numpy()).sum()))
print("tipo_probable distinto:", int((np.array(tipo) != ref.tipo_probable.to_numpy()).sum()),
      f"· diferencia máxima de probabilidad_tipo: {np.abs(np.array(ptipo) - ref.probabilidad_tipo.to_numpy()).max():.3e}")
y = man_pru.es_tumor.to_numpy()
vn, fp, fn, vp = confusion_matrix(y, hay.astype(int), labels=[0, 1]).ravel()
mias = {"vp": vp, "vn": vn, "fp": fp, "fn": fn, "sensibilidad": vp / (vp + fn), "especificidad": vn / (vn + fp),
        "precision": vp / (vp + fp), "f1": 2 * vp / (2 * vp + fp + fn), "auc": roc_auc_score(y, prob),
        "exactitud": (vp + vn) / len(y)}
mp = info["metricas_prueba"]
print("Métricas por la ruta de la app contra info.json:")
peor = 0.0
for k, v in mias.items():
    peor = max(peor, abs(float(v) - float(mp[k])))
    print(f"   {k:14s} app = {float(v):.6f} · info.json = {float(mp[k]):.6f} · dif = {abs(float(v) - float(mp[k])):.2e}")
tum = y == 1
ex_tipo = float((np.array(tipo)[tum] == man_pru.clase.to_numpy()[tum]).mean())
print(f"   exactitud_tipo app = {ex_tipo:.6f} · info.json = {mp['exactitud_tipo']:.6f}")
print(f"Diferencia máxima de métricas: {peor:.2e}")

# ---------------- lote contra imagen por imagen (prueba)
print("\n== Prueba: lote (model.predict sobre imágenes preparadas) contra imagen por imagen (ruta de la app) ==")
from app.backend.ml.preprocesar import preparar
lote = np.stack([preparar(leer_imagen(RAIZ / r)) for r in man_pru.ruta]).astype(np.float32)
p_lote = np.asarray(modelo.predict(lote, batch_size=64, verbose=0)["tumor"]).ravel().astype(float)
u = float(info["umbral"])
print(f"Diferencia máxima lote contra una por una: {np.abs(p_lote - prob).max():.3e} · decisiones distintas: {int(((p_lote >= u) != (prob >= u)).sum())}")
print(f"Distancia mínima de una probabilidad de prueba al umbral: {np.abs(prob - u).min():.3e} · imágenes de prueba a menos de 1e-4 del umbral: {int((np.abs(prob - u) < 1e-4).sum())}")

# ---------------- validación apartada, independiente de validacion.npz
print("\n== Validación apartada recalculada desde los archivos (independiente de validacion.npz) ==")
_, iv = train_test_split(np.arange(len(man_ent)), test_size=0.15, stratify=man_ent.clase, random_state=42)
pv = np.array([inferencia.predecir(modelo, info, leer_imagen(RAIZ / r))["probabilidad_tumor"] for r in man_ent.ruta[iv]])
yv = man_ent.es_tumor.to_numpy()[iv]
with np.load(RAIZ / "app" / "modelos" / "v001" / "validacion.npz") as dz:
    print(f"Diferencia máxima contra prob_val de validacion.npz: {np.abs(pv - dz['prob_val']).max():.3e} · etiquetas distintas: {int((yv != dz['y_val']).sum())}")
    dec_npz = dz["prob_val"] >= u
print(f"Decisiones distintas imagen por imagen contra lote (npz) en validación: {int(((pv >= u) != dec_npz).sum())}")
pos = pv[yv == 1]; neg = pv[yv == 0]
mvj = info["metricas_validacion"]
print(f"Validación al umbral exportado, por la ruta de la app: sensibilidad {(pos >= u).mean():.6f} ({int((pos >= u).sum())}/{len(pos)}) · especificidad {(neg < u).mean():.6f} ({int((neg < u).sum())}/{len(neg)})"
      f" · info.json: sensibilidad {mvj['sensibilidad']:.6f}, especificidad {mvj['especificidad']:.6f}, FN {mvj['fn']}, FP {mvj['fp']}")

# ---------------- Grad-CAM
print("\n== Grad-CAM ==")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, axs = plt.subplots(2, 2, figsize=(6, 6))
for fila, (nombre, es) in zip(axs, [("con tumor", 1), ("sin tumor", 0)]):
    r = man_pru.ruta[man_pru.es_tumor == es].iloc[0]
    s = inferencia.predecir(modelo, info, leer_imagen(RAIZ / r), con_gradcam=True)
    g = s["gradcam"]
    print(f"{nombre}: {r} · prob {s['probabilidad_tumor']:.4f} · hay_tumor {s['hay_tumor']} · mapa {g.shape} {g.dtype} "
          f"min {g.min():.4f} max {g.max():.4f} desv {g.std():.4f} · valores distintos {len(np.unique(g))} · finito {bool(np.isfinite(g).all())} "
          f"· superpuesto {s['gradcam_superpuesto'].shape} {s['gradcam_superpuesto'].dtype}")
    print(f"   constante: {bool(g.std() == 0)} · en rango [0, 1]: {bool(g.min() >= 0 and g.max() <= 1)}")
    fila[0].imshow(s["imagen_preparada"]); fila[0].set_title(nombre, fontsize=8); fila[0].axis("off")
    fila[1].imshow(s["gradcam_superpuesto"]); fila[1].set_title(f"p={s['probabilidad_tumor']:.3f}", fontsize=8); fila[1].axis("off")
fig.tight_layout(); fig.savefig(AQUI / "gradcam_verificacion.png", dpi=90)
# ¿cuántos mapas salen constantes (todo cero) en una muestra de prueba?
rng = np.random.default_rng(0)
ceros = 0
muestra = rng.choice(len(man_pru), 60, replace=False)
for i in muestra:
    g = inferencia.predecir(modelo, info, leer_imagen(RAIZ / man_pru.ruta[i]), con_gradcam=True)["gradcam"]
    ceros += int(g.std() == 0 or not np.isfinite(g).all())
print(f"Mapas constantes o no finitos en una muestra de {len(muestra)} imágenes de prueba: {ceros}")

# ---------------- pesos de MobileNetV2: ¿son los de ImageNet sin tocar?
print("\n== Pesos de MobileNetV2 en modelo.keras contra ImageNet ==")
import keras
base = keras.applications.MobileNetV2(include_top=False, weights="imagenet", input_shape=(160, 160, 3))
peor_w, n_capas = 0.0, 0
for capa in base.layers:
    w = capa.get_weights()
    if not w:
        continue
    w2 = modelo.get_layer(capa.name).get_weights()
    n_capas += 1
    peor_w = max(peor_w, max(float(np.abs(a - b).max()) for a, b in zip(w, w2)))
print(f"Capas con pesos comparadas: {n_capas} · diferencia máxima absoluta contra ImageNet: {peor_w:.3e}")

# ---------------- rasgos guardados: ¿se reproducen con un extractor independiente?
print("\n== Rasgos guardados contra un extractor independiente (keras.applications + preprocess_input) ==")
with np.load(RAIZ / "datos" / "rasgos" / "rasgos_mobilenet.npz") as dz:
    X, rutas = dz["X"], dz["rutas"]
print("Orden de rasgos == manifiesto:", bool((rutas == man.ruta.to_numpy()).all()))
from app.backend.ml.preprocesar import preparar
idx = np.sort(rng.choice(len(man), 400, replace=False))
lote = np.stack([preparar(leer_imagen(RAIZ / man.ruta[i])) for i in idx]).astype(np.float32)
x = keras.applications.mobilenet_v2.preprocess_input(lote.copy())
f = base.predict(x, batch_size=64, verbose=0).mean(axis=(1, 2))
print(f"Muestra de {len(idx)} imágenes (ambas particiones): diferencia máxima absoluta = {np.abs(f - X[idx]).max():.3e} · "
      f"relativa a la norma media = {np.abs(f - X[idx]).max() / np.abs(X[idx]).mean():.3e}")
imgs = np.load(RAIZ / "datos" / "rasgos" / "imagenes_160.npy", mmap_mode="r")
print("imagenes_160.npy == preparar(archivo) en la muestra:", bool((np.asarray(imgs[idx]) == lote.astype(np.uint8)).all()))
