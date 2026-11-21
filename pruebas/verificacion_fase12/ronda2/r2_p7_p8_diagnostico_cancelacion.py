"""Ronda 2 · Puntos 7 y 8: diagnóstico contra el historial, sintéticos y cancelación real de extremo a extremo."""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
RAIZ = Path(r"C:\proyectos\tumores-cerebrales")
sys.path.insert(0, str(RAIZ))
import numpy as np
import pandas as pd

from app.backend.ml.diagnostico import diagnosticar

h = pd.read_csv(RAIZ / "resultados" / "historial_epocas.csv")
info = json.loads((RAIZ / "app" / "modelos" / "v001" / "info.json").read_text(encoding="utf-8"))
cfg = info["entrenamiento"]
man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
mayoritaria = float(man[man.particion == "entrenamiento"].es_tumor.mean())
print(f"== Punto 7 · Mejor época y etiqueta recalculadas desde historial_epocas.csv (clase mayoritaria {mayoritaria:.4f}) ==")
for etapa, g in h.groupby("etapa", sort=False):
    g = g.reset_index(drop=True)
    i = int(g.perdida_val.to_numpy().argmin())
    d = info["diagnostico_etapas"][etapa]
    n, emax, pac = len(g), cfg[etapa]["epocas_max"], cfg[etapa]["paciencia"]
    val_mejor, val_final, ent_mejor, ent_final = g.perdida_val[i], g.perdida_val.iloc[-1], g.perdida[i], g.perdida.iloc[-1]
    baja = (g.perdida[0] - g.perdida.min()) / g.perdida[0]
    subida = (val_final - val_mejor) / val_mejor
    brecha = (val_final - ent_final) / val_final
    if baja < 0.05 and g.exactitud_val.max() <= mayoritaria + 0.01:
        esperada = "no aprende"
    elif n - (i + 1) >= 2 and subida > 0.10 and ent_final < ent_mejor and brecha > 0.30:
        esperada = "sobreajuste"
    elif n >= emax and n - (i + 1) < 2:
        esperada = "se detuvo antes de converger"
    else:
        esperada = "convergió"
    print(f"\n[{etapa}] {n} épocas de {emax} (paciencia {pac}) · n - mejor = {n - (i + 1)}")
    print(f"   mejor época recalculada = {int(g.epoca[i])} (val {val_mejor:.6f}) · info.json = {d['mejor_epoca']} (val {d['perdida_val_mejor']:.6f}) · épocas corridas info.json = {d['epocas_corridas']}")
    print(f"   subida de val tras la mejor = {subida:.1%} (regla > 10 %) · brecha final = {brecha:.1%} (regla > 30 %) · entrenamiento siguió bajando = {bool(ent_final < ent_mejor)} · épocas después = {n - (i + 1)} (regla >= 2)")
    print(f"   etiqueta por las reglas (a mano) = '{esperada}' · info.json = '{d['etiqueta']}' · coincide: {esperada == d['etiqueta']}")
    print(f"   en la mejor época: pérdida ent {ent_mejor:.4f} / val {val_mejor:.4f} (razón {ent_mejor / val_mejor:.2f}; advertencia si < 0.25) · exactitud ent {g.exactitud[i]:.4f} / val {g.exactitud_val[i]:.4f}")
    print(f"   advertencias en info.json: {len(d.get('advertencias', []))} · mejoro_punto_de_partida = {d.get('mejoro_punto_de_partida')} · perdida_val_inicial = {d.get('perdida_val_inicial')} · cancelado = {d.get('cancelado')}")
    print(f"   tasa de aprendizaje cambia en las épocas {g.epoca[g.tasa_aprendizaje.diff().fillna(0) != 0].tolist()}")
cv = info["comparacion_validacion"]
print(f"\ninfo.json: etapa exportada = {info['etapa_exportada']} · mejor_epoca = {info['mejor_epoca']} · diagnóstico = {info['diagnostico']}")
print(f"Comparación: val cabeza {cv['perdida_val_cabeza']:.6f} · val ajuste fino {cv['perdida_val_ajuste_fino']:.6f} · se usó ajuste fino = {cv['se_uso_ajuste_fino']} · "
      f"mínimo val de la cabeza en el historial {h[h.etapa == 'cabeza'].perdida_val.min():.6f} · del ajuste fino {h[h.etapa == 'ajuste_fino'].perdida_val.min():.6f}")
print("Explicación guardada:", info["explicacion_diagnostico"])

print("\n== Punto 7 · `diagnosticar` con historiales sintéticos propios ==")
ep = np.arange(1, 21)
casos = [
    ("convergió", dict(loss=list(np.linspace(0.6, 0.12, 20)), val_loss=list(np.concatenate([np.linspace(0.62, 0.150, 14), np.linspace(0.151, 0.156, 6)])),
                       accuracy=list(np.linspace(0.85, 0.955, 20)), val_accuracy=list(np.linspace(0.85, 0.95, 20))), 60, 6, {}),
    ("se detuvo antes de converger", dict(loss=list(np.linspace(0.7, 0.30, 20)), val_loss=list(np.linspace(0.72, 0.33, 20)),
                                          accuracy=list(np.linspace(0.8, 0.93, 20)), val_accuracy=list(np.linspace(0.80, 0.93, 20))), 20, 6, {}),
    ("sobreajuste", dict(loss=list(np.linspace(0.6, 0.02, 20)), val_loss=list(np.concatenate([np.linspace(0.6, 0.30, 6), np.linspace(0.33, 0.70, 14)])),
                         accuracy=list(np.linspace(0.85, 1.0, 20)), val_accuracy=list(np.concatenate([np.linspace(0.85, 0.93, 6), np.linspace(0.93, 0.90, 14)]))), 60, 14, {}),
    ("no aprende", dict(loss=list(0.693 - 0.0005 * ep), val_loss=list(0.693 + 0.0002 * np.sin(ep)), accuracy=[0.90] * 20, val_accuracy=[0.907] * 20), 20, 6, {}),
    ("cancelado", dict(loss=[0.60, 0.45], val_loss=[0.53, 0.43], accuracy=[0.90, 0.93], val_accuracy=[0.90, 0.93], cancelado=True), 30, 8, {}),
    ("cancelado", dict(loss=[0.60, 0.45], val_loss=[0.53, 0.43], accuracy=[0.90, 0.93], val_accuracy=[0.90, 0.93]), 30, 8, {"cancelado": True}),
    ("cancelado", dict(loss=[], val_loss=[], cancelado=True), 30, 8, {}),
]
ok_todos = True
for esperada, hist, emax, pac, extra in casos:
    r = diagnosticar(hist, emax, pac, mayoritaria, **extra)
    ok = r["etiqueta"] == esperada; ok_todos &= ok
    print(f"   esperado '{esperada}' → '{r['etiqueta']}' · mejor época {r['mejor_epoca']} · detencion_temprana {r['detencion_temprana']} · cancelado {r['cancelado']} · advertencias {len(r['advertencias'])} · {'OK' if ok else 'DISTINTO'}")
    print("      ", r["explicacion"][:330])
# no mejora el punto de partida (como un ajuste fino que empeora)
r = diagnosticar(dict(loss=[0.137, 0.119, 0.091, 0.083], val_loss=[0.2524, 0.3141, 0.2682, 0.2713], accuracy=[0.987, 0.984, 0.991, 0.993],
                      val_accuracy=[0.979, 0.979, 0.981, 0.982], val_loss_inicial=0.2042), 8, 3, mayoritaria)
ok = r["mejoro_punto_de_partida"] is False and len(r["advertencias"]) >= 1 and "no mejoró" in r["explicacion"]; ok_todos &= ok
print(f"   no mejora el punto de partida (val inicial 0.2042, mejor 0.2524) → etiqueta '{r['etiqueta']}' · mejoro_punto_de_partida {r['mejoro_punto_de_partida']} · advertencias {len(r['advertencias'])} · {'OK' if ok else 'DISTINTO'}")
print("      ", r["explicacion"][:400])
r = diagnosticar(dict(loss=[0.137, 0.119, 0.091, 0.083], val_loss=[0.19, 0.185, 0.186, 0.187], accuracy=[0.95] * 4, val_accuracy=[0.95] * 4, val_loss_inicial=0.2042), 8, 3, mayoritaria)
ok = r["mejoro_punto_de_partida"] is True; ok_todos &= ok
print(f"   sí mejora el punto de partida → mejoro_punto_de_partida {r['mejoro_punto_de_partida']} · advertencias {len(r['advertencias'])} · {'OK' if ok else 'DISTINTO'}")
# memorización: el caso real de la ronda anterior (cabeza: ent 0.013 contra val 0.204, exactitud 0.9998 contra 0.982)
r = diagnosticar(dict(loss=[0.5, 0.1, 0.013, 0.012, 0.011], val_loss=[0.30, 0.22, 0.204, 0.208, 0.209], accuracy=[0.94, 0.99, 0.9998, 1.0, 1.0],
                      val_accuracy=[0.97, 0.98, 0.982, 0.985, 0.985]), 60, 2, mayoritaria)
ok = r["etiqueta"] == "convergió" and len(r["advertencias"]) == 1; ok_todos &= ok
print(f"   memorización sin subida de validación → '{r['etiqueta']}' · advertencias {len(r['advertencias'])} · {'OK' if ok else 'DISTINTO'}")
print("      ", r["explicacion"][:420])
r = diagnosticar(dict(loss=[float("nan")] * 4, val_loss=[float("nan")] * 4, accuracy=[0.9] * 4, val_accuracy=[0.907] * 4), 10, 3, mayoritaria)
print(f"   (límite) pérdidas NaN → '{r['etiqueta']}' · mejor época {r['mejor_epoca']}")
print("Todos los sintéticos como se esperaba:", ok_todos)

print("\n== Punto 8 · Cancelación real de extremo a extremo ==")
from app.backend.ml import entrenar
with np.load(RAIZ / "datos" / "rasgos" / "rasgos_mobilenet.npz") as d:
    X = d["X"]; assert (d["rutas"] == man.ruta.to_numpy()).all()
ent = np.flatnonzero((man.particion == "entrenamiento").to_numpy())
sub = np.random.default_rng(7).choice(ent, 600, replace=False)
y, t = entrenar.etiquetas_de_clases(man.clase[sub])
Xs = X[sub]; tr, va = slice(0, 450), slice(450, 600)
llamadas = []
modelo, hist = entrenar.entrenar_cabeza(Xs[tr], y[tr], t[tr], Xs[va], y[va], t[va], epocas_max=30, paciencia=8,
                                        callback_progreso=lambda e, n, r: (llamadas.append(n), False if n == 2 else None)[1])
print(f"Llamadas al callback: {llamadas} · épocas en el historial: {len(hist['loss'])} · hist['cancelado'] = {hist['cancelado']} · val_loss {[round(v, 4) for v in hist['val_loss']]}")
p, _ = entrenar.predecir_cabeza(modelo, Xs[va])
print("El modelo devuelto predice valores finitos:", bool(np.isfinite(p).all()))
r = diagnosticar(hist, 30, 8, float(y[tr].mean()))
print(f"diagnosticar(historial real cancelado) → etiqueta '{r['etiqueta']}' · cancelado {r['cancelado']} · detencion_temprana {r['detencion_temprana']} · mejor época {r['mejor_epoca']}")
print("   ", r["explicacion"])
print("PASA punto 8:", len(hist["loss"]) == 2 and hist["cancelado"] is True and r["etiqueta"] == "cancelado" and r["detencion_temprana"] is False)
_, hist2 = entrenar.entrenar_cabeza(Xs[tr], y[tr], t[tr], Xs[va], y[va], t[va], epocas_max=4, paciencia=8, callback_progreso=lambda e, n, r: None)
r2 = diagnosticar(hist2, 4, 8, float(y[tr].mean()))
print(f"Control sin cancelar (4 épocas de 4): cancelado = {hist2['cancelado']} · etiqueta '{r2['etiqueta']}'")
cvk = entrenar.kfold_cabeza(Xs, y, t, n_pliegues=3, epocas_max=20, paciencia=5, callback_progreso=lambda e, n, r: n < 2)
rk = diagnosticar(cvk["historiales"][0], 20, 5, float(y.mean()))
print(f"kfold_cabeza cancelado: cancelado = {cvk['cancelado']} · pliegues hechos {len(cvk['pliegues'])} · diagnóstico del pliegue interrumpido '{rk['etiqueta']}'")
