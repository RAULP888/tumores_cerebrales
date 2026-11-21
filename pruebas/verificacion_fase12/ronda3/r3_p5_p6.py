"""Ronda 3 · Puntos 5 y 6: modelo exportado por la ruta de la app (muestra de 150), Grad-CAM y diagnóstico contra el historial.
Solo lee app/modelos/v001 y resultados/."""
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
RAIZ = Path(r"C:\proyectos\tumores-cerebrales")
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
import numpy as np
import pandas as pd

from app.backend.ml import inferencia
from app.backend.ml.diagnostico import diagnosticar
from app.backend.ml.preprocesar import leer_imagen, preparar

RED = "Red Keras (MobileNetV2)"
man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
info = json.loads((RAIZ / "app" / "modelos" / "v001" / "info.json").read_text(encoding="utf-8"))

print("== Punto 6 · Diagnóstico contra historial_epocas.csv ==")
h = pd.read_csv(RAIZ / "resultados" / "historial_epocas.csv")
cfg = info["entrenamiento"]
may = float(man[man.particion == "entrenamiento"].es_tumor.mean())
for etapa, g in h.groupby("etapa", sort=False):
    g = g.reset_index(drop=True)
    i = int(g.perdida_val.to_numpy().argmin()); n = len(g)
    d = info["diagnostico_etapas"][etapa]; emax, pac = cfg[etapa]["epocas_max"], cfg[etapa]["paciencia"]
    vm, vf, em, ef = g.perdida_val[i], g.perdida_val.iloc[-1], g.perdida[i], g.perdida.iloc[-1]
    baja, sub, bre = (g.perdida[0] - g.perdida.min()) / g.perdida[0], (vf - vm) / vm, (vf - ef) / vf
    if baja < 0.05 and g.exactitud_val.max() <= may + 0.01:
        esp = "no aprende"
    elif n - (i + 1) >= 2 and sub > 0.10 and ef < em and bre > 0.30:
        esp = "sobreajuste"
    elif n >= emax and n - (i + 1) < 2:
        esp = "se detuvo antes de converger"
    else:
        esp = "convergió"
    print(f"[{etapa}] {n} épocas de {emax} (paciencia {pac}) · mejor época recalculada {int(g.epoca[i])} (val {vm:.6f}) · info.json {d['mejor_epoca']} (val {d['perdida_val_mejor']:.6f}) · n - mejor = {n - i - 1}")
    print(f"   subida de val tras la mejor {sub:.1%} (regla > 10 %) · brecha final {bre:.1%} (> 30 %) · ent siguió bajando {bool(ef < em)} · etiqueta a mano '{esp}' · info.json '{d['etiqueta']}' · coincide {esp == d['etiqueta']}")
    print(f"   en la mejor época: pérdida ent {em:.4f} / val {vm:.4f} (razón {em / vm:.2f}; advertencia si < 0.25) · exactitud ent {g.exactitud[i]:.4f} / val {g.exactitud_val[i]:.4f} (advertencia si ent >= 0.995 y brecha >= 0.01)")
    print(f"   advertencias en info.json: {len(d.get('advertencias', []))} · mejoro_punto_de_partida {d.get('mejoro_punto_de_partida')} · val inicial {d.get('perdida_val_inicial')}")
    hist = {"loss": g.perdida.tolist(), "val_loss": g.perdida_val.tolist(), "accuracy": g.exactitud.tolist(), "val_accuracy": g.exactitud_val.tolist()}
    if d.get("perdida_val_inicial") is not None:
        hist["val_loss_inicial"] = d["perdida_val_inicial"]
    r = diagnosticar(hist, emax, pac, may)
    print(f"   diagnosticar(historial del CSV) → '{r['etiqueta']}' · mejor época {r['mejor_epoca']} · advertencias {len(r['advertencias'])}")
cv = info["comparacion_validacion"]
print(f"info.json: etapa exportada {info['etapa_exportada']} · mejor_epoca {info['mejor_epoca']} · diagnóstico {info['diagnostico']} · val cabeza {cv['perdida_val_cabeza']:.6f} · val ajuste fino {cv['perdida_val_ajuste_fino']:.6f} · usó ajuste fino {cv['se_uso_ajuste_fino']}")
print("Explicación:", info["explicacion_diagnostico"])
print("Advertencias:", info.get("advertencias_diagnostico"))

print("\n== Punto 5 · Modelo exportado por la ruta de la app (muestra de 150 imágenes de prueba) ==")
pp = pd.read_csv(RAIZ / "resultados" / "predicciones_prueba.csv")
ref = pp[pp.modelo == RED].set_index("ruta")
mp = man[man.particion == "prueba"].reset_index(drop=True)
rng = np.random.default_rng(2026)
# muestra estratificada: todas las "sin tumor" cuentan poco, así que se toman 40 sin tumor y 110 con tumor
idx = np.concatenate([rng.choice(np.flatnonzero(mp.es_tumor.to_numpy() == 0), 40, replace=False), rng.choice(np.flatnonzero(mp.es_tumor.to_numpy() == 1), 110, replace=False)])
modelo, inf = inferencia.cargar_modelo(RAIZ / "app" / "modelos" / "v001")
t0 = time.time()
sal = [inferencia.predecir(modelo, inf, leer_imagen(RAIZ / mp.ruta[i])) for i in idx]
dt = time.time() - t0
prob = np.array([s["probabilidad_tumor"] for s in sal]); hay = np.array([s["hay_tumor"] for s in sal])
r = ref.loc[mp.ruta[idx]]
print(f"{len(idx)} imágenes en {dt:.0f} s ({dt / len(idx):.2f} s por imagen) · umbral usado {sal[0]['umbral']!r} · info.json {info['umbral']!r}")
print(f"Diferencia máxima de probabilidad contra predicciones_prueba.csv: {np.abs(prob - r.probabilidad_tumor.to_numpy()).max():.3e} · decisiones distintas: {int((hay.astype(int) != r.prediccion.to_numpy()).sum())}"
      f" · tipo distinto: {int((np.array([s['tipo_probable'] for s in sal]) != r.tipo_probable.to_numpy()).sum())} · aviso presente: {all(bool(s['aviso']) for s in sal)}")
lote = np.stack([preparar(leer_imagen(RAIZ / mp.ruta[i])) for i in idx]).astype(np.float32)
pl = np.asarray(modelo.predict(lote, batch_size=64, verbose=0)["tumor"]).ravel()
u = float(info["umbral"])
print(f"Lote contra una por una: diferencia máxima {np.abs(pl - prob).max():.3e} · decisiones distintas {int(((pl >= u) != (prob >= u)).sum())} · distancia mínima al umbral en toda la prueba (CSV): {np.abs(ref.probabilidad_tumor.to_numpy() - u).min():.3e}")
y = mp.es_tumor.to_numpy()[idx]
print(f"En la muestra: FN {int(((y == 1) & ~hay).sum())} de {int(y.sum())} tumores · FP {int(((y == 0) & hay).sum())} de {int((y == 0).sum())} sin tumor (el CSV dice FN {int(((r.es_tumor == 1) & (r.prediccion == 0)).sum())}, FP {int(((r.es_tumor == 0) & (r.prediccion == 1)).sum())})")

print("\n== Grad-CAM ==")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, axs = plt.subplots(2, 4, figsize=(11, 5.6))
k = 0
ceros = 0
for es in (1, 0):
    for i in idx[y == es][:2]:
        s = inferencia.predecir(modelo, inf, leer_imagen(RAIZ / mp.ruta[i]), con_gradcam=True)
        gm = s["gradcam"]
        print(f"{'tumor' if es else 'sin tumor'} · {Path(mp.ruta[i]).name} · prob {s['probabilidad_tumor']:.4f} · hay_tumor {s['hay_tumor']} · mapa {gm.shape} min {gm.min():.3f} max {gm.max():.3f} desv {gm.std():.3f} · constante {bool(gm.std() == 0)} · finito {bool(np.isfinite(gm).all())}")
        axs.ravel()[k].imshow(s["imagen_preparada"]); axs.ravel()[k].axis("off"); axs.ravel()[k].set_title(f"real: {'tumor' if es else 'sin tumor'}", fontsize=8)
        axs.ravel()[k + 1].imshow(s["gradcam_superpuesto"]); axs.ravel()[k + 1].axis("off"); axs.ravel()[k + 1].set_title(f"p = {s['probabilidad_tumor']:.3f}", fontsize=8)
        k += 2
fig.tight_layout(); fig.savefig(AQUI / "r3_gradcam.png", dpi=80)
for i in idx[:30]:
    gm = inferencia.predecir(modelo, inf, leer_imagen(RAIZ / mp.ruta[i]), con_gradcam=True)["gradcam"]
    ceros += int(gm.std() == 0 or not np.isfinite(gm).all())
print("Mapas constantes o no finitos en 30 imágenes de la muestra:", ceros)

print("\n== Pesos de MobileNetV2 contra ImageNet ==")
import keras
base = keras.applications.MobileNetV2(include_top=False, weights="imagenet", input_shape=(160, 160, 3))
peor, nc = 0.0, 0
for capa in base.layers:
    w = capa.get_weights()
    if w:
        nc += 1; peor = max(peor, max(float(np.abs(a - b).max()) for a, b in zip(w, modelo.get_layer(capa.name).get_weights())))
print(f"Capas comparadas {nc} · diferencia máxima {peor:.3e}")
with np.load(RAIZ / "datos" / "rasgos" / "rasgos_mobilenet.npz") as dz:
    X, rutas = dz["X"], dz["rutas"]
print("Rasgos en el orden del manifiesto:", bool((rutas == man.ruta.to_numpy()).all()), "· filas", X.shape)
ii = np.sort(rng.choice(len(man), 120, replace=False))
lote2 = np.stack([preparar(leer_imagen(RAIZ / man.ruta[i])) for i in ii]).astype(np.float32)
f = base.predict(keras.applications.mobilenet_v2.preprocess_input(lote2.copy()), batch_size=64, verbose=0).mean(axis=(1, 2))
print(f"Rasgos guardados contra extractor independiente (120 imágenes): diferencia máxima {np.abs(f - X[ii]).max():.3e}")
