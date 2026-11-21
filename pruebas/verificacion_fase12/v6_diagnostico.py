"""Punto 6 · Mejor época y diagnóstico coherentes con el historial; `diagnosticar` con 4 historiales sintéticos."""
import json
import sys
from pathlib import Path

RAIZ = Path(r"C:\proyectos\tumores-cerebrales")
sys.path.insert(0, str(RAIZ))
import numpy as np
import pandas as pd

from app.backend.ml.diagnostico import diagnosticar

h = pd.read_csv(RAIZ / "resultados" / "historial_epocas.csv")
info = json.loads((RAIZ / "app" / "modelos" / "v001" / "info.json").read_text(encoding="utf-8"))
cfg = info["entrenamiento"]
print("== Mejor época recalculada desde historial_epocas.csv ==")
for etapa, g in h.groupby("etapa", sort=False):
    g = g.reset_index(drop=True)
    i = int(g.perdida_val.to_numpy().argmin())
    d = info["diagnostico_etapas"][etapa]
    n, emax, pac = len(g), cfg[etapa]["epocas_max"], cfg[etapa]["paciencia"]
    val_mejor, val_final = g.perdida_val[i], g.perdida_val.iloc[-1]
    ent_mejor, ent_final = g.perdida[i], g.perdida.iloc[-1]
    baja = (g.perdida[0] - g.perdida.min()) / g.perdida[0]
    subida = (val_final - val_mejor) / val_mejor
    brecha = (val_final - ent_final) / val_final
    print(f"\n[{etapa}] épocas corridas {n} de {emax} (paciencia {pac}) · épocas consecutivas 1..n: {bool((g.epoca.to_numpy() == np.arange(1, n + 1)).all())}")
    print(f"   mejor época recalculada = {int(g.epoca[i])} (val {val_mejor:.6f}) · info.json = {d['mejor_epoca']} (val {d['perdida_val_mejor']:.6f})")
    print(f"   épocas corridas info.json = {d['epocas_corridas']} · n - mejor = {n - (i + 1)} (¿igual a la paciencia? {n - (i + 1) == pac})")
    print(f"   baja de la pérdida de entrenamiento = {baja:.1%} · mejor exactitud val = {g.exactitud_val.max():.4f}")
    print(f"   subida de val tras la mejor = {subida:.1%} (regla sobreajuste: > 10 %) · brecha final (val - ent)/val = {brecha:.1%} (regla: > 30 %) · "
          f"entrenamiento siguió bajando: {bool(ent_final < ent_mejor)}")
    # etiqueta según las reglas del docstring, aplicada a mano
    mayoritaria = 0.8413
    if baja < 0.05 and g.exactitud_val.max() <= mayoritaria + 0.01:
        esperada = "no aprende"
    elif n - (i + 1) >= 2 and subida > 0.10 and ent_final < ent_mejor and brecha > 0.30:
        esperada = "sobreajuste"
    elif n >= emax and n - (i + 1) < 2:
        esperada = "se detuvo antes de converger"
    else:
        esperada = "convergió"
    print(f"   etiqueta según las reglas del docstring (aplicadas a mano) = '{esperada}' · info.json = '{d['etiqueta']}' · coincide: {esperada == d['etiqueta']}")
    # tasa de aprendizaje: reducciones
    cambios = g.epoca[g.tasa_aprendizaje.diff().fillna(0) != 0].tolist()
    print(f"   la tasa de aprendizaje cambia en las épocas: {cambios} · valores: {sorted(g.tasa_aprendizaje.unique(), reverse=True)}")
print(f"\ninfo.json mejor_epoca (modelo exportado, etapa {info['etapa_exportada']}) = {info['mejor_epoca']} · diagnóstico = {info['diagnostico']}")
cv = info["comparacion_validacion"]
print(f"Comparación: val cabeza {cv['perdida_val_cabeza']:.6f} · val ajuste fino {cv['perdida_val_ajuste_fino']:.6f} · se usó ajuste fino: {cv['se_uso_ajuste_fino']}"
      f" · coherente (ajuste < cabeza): {(cv['perdida_val_ajuste_fino'] < cv['perdida_val_cabeza']) == cv['se_uso_ajuste_fino']}")
hc = h[h.etapa == "cabeza"]; ha = h[h.etapa == "ajuste_fino"]
print(f"   mínimo val de la cabeza en el historial: {hc.perdida_val.min():.6f} · mínimo val del ajuste fino en el historial: {ha.perdida_val.min():.6f}")

print("\n== `diagnosticar` con historiales sintéticos propios ==")
ep = np.arange(1, 21)
casos = {
    # baja suave y se aplana; la detención temprana actúa (20 de 60), mejor época 14
    "convergió": dict(h={"loss": list(0.6 * np.exp(-ep / 4) + 0.10), "val_loss": list(np.concatenate([np.linspace(0.62, 0.150, 14), np.linspace(0.151, 0.156, 6)])),
                         "val_accuracy": list(np.linspace(0.85, 0.96, 20))}, emax=60, pac=6),
    # se agotan las 20 épocas y la validación sigue bajando (mejor = última)
    "se detuvo antes de converger": dict(h={"loss": list(np.linspace(0.7, 0.30, 20)), "val_loss": list(np.linspace(0.72, 0.33, 20)),
                                            "val_accuracy": list(np.linspace(0.80, 0.93, 20))}, emax=20, pac=6),
    # la validación toca fondo en la época 6 y luego sube mucho mientras el entrenamiento sigue bajando
    "sobreajuste": dict(h={"loss": list(np.linspace(0.6, 0.02, 20)), "val_loss": list(np.concatenate([np.linspace(0.6, 0.30, 6), np.linspace(0.33, 0.70, 14)])),
                           "val_accuracy": list(np.concatenate([np.linspace(0.85, 0.93, 6), np.linspace(0.93, 0.90, 14)]))}, emax=60, pac=14),
    # la pérdida casi no se mueve y la exactitud se queda en la clase mayoritaria
    "no aprende": dict(h={"loss": list(0.693 - 0.0005 * ep), "val_loss": list(0.693 + 0.0002 * np.sin(ep)),
                          "val_accuracy": [0.84] * 20}, emax=20, pac=6),
}
todo_ok = True
for esperada, c in casos.items():
    r = diagnosticar(c["h"], c["emax"], c["pac"], 0.84)
    ok = r["etiqueta"] == esperada
    todo_ok &= ok
    print(f"   esperado '{esperada}' → obtenido '{r['etiqueta']}' (mejor época {r['mejor_epoca']}) · {'OK' if ok else 'DISTINTO'}")
    print("      ", r["explicacion"])
# casos límite adicionales
print("   Casos límite:")
r = diagnosticar({"loss": [], "val_loss": []}, 10, 3)
print(f"      historial vacío → '{r['etiqueta']}'")
r = diagnosticar({"loss": [0.5, 0.2, 0.1, 0.05, 0.02, 0.01], "val_loss": [0.5, 0.45, 0.6, 0.9, 1.3, 1.8], "val_accuracy": [0.9] * 6}, 6, 3, 0.84)
print(f"      sobreajuste claro agotando las épocas (6 de 6, mejor = 2) → '{r['etiqueta']}'")
r = diagnosticar({"loss": [0.137, 0.119, 0.091, 0.083], "val_loss": [0.2524, 0.3141, 0.2682, 0.2713], "val_accuracy": [0.979, 0.979, 0.981, 0.982]}, 8, 3, 0.84)
print(f"      el ajuste fino real (mejor época 1, empeoró respecto a la cabeza 0.2042) → '{r['etiqueta']}'")
r = diagnosticar({"loss": [float('nan')] * 5, "val_loss": [float('nan')] * 5, "val_accuracy": [0.84] * 5}, 5, 3, 0.84)
print(f"      pérdidas NaN → '{r['etiqueta']}' (mejor época {r['mejor_epoca']})")
r = diagnosticar({"loss": [0.60, 0.45], "val_loss": [0.53, 0.43], "val_accuracy": [0.90, 0.93]}, 30, 8, 0.84)
print(f"      entrenamiento CANCELADO en la época 2 de 30 (validación todavía bajando) → '{r['etiqueta']}' · detencion_temprana={r['detencion_temprana']}")
print("        explicación devuelta:", r["explicacion"])
print("Los 4 sintéticos principales clasificados como se esperaba:", todo_ok)
