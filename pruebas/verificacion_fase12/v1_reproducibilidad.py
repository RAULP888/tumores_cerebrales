"""Punto 1 · Reproducibilidad: compara los resultados de antes y de después de volver a correr los notebooks.

Uso: python v1_reproducibilidad.py <carpeta_copia_previa>   (la copia tiene resultados/, datos/, app_modelos/v001/, notebooks/)
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(r"C:\proyectos\tumores-cerebrales")
ANTES = Path(sys.argv[1])
pares = [(ANTES / "resultados" / f.name, f) for f in sorted((RAIZ / "resultados").glob("*.csv"))]
pares += [(ANTES / "datos" / "manifiesto.csv", RAIZ / "datos" / "manifiesto.csv"), (ANTES / "datos" / "duplicados.csv", RAIZ / "datos" / "duplicados.csv")]
print("== CSV: antes contra después ==")
for a, d in pares:
    if not a.exists():
        print(f"{d.name}: NO existía antes"); continue
    A, D = pd.read_csv(a), pd.read_csv(d)
    if A.shape != D.shape or list(A.columns) != list(D.columns):
        print(f"{d.name}: forma distinta {A.shape} → {D.shape}"); continue
    num = [c for c in A.columns if pd.api.types.is_numeric_dtype(A[c]) and pd.api.types.is_numeric_dtype(D[c])]
    otras = [c for c in A.columns if c not in num]
    texto_igual = all((A[c].fillna("") == D[c].fillna("")).all() for c in otras)
    tiempos = [c for c in num if "segundos" in c]
    num2 = [c for c in num if c not in tiempos]
    dif = {c: float(np.nanmax(np.abs(A[c].to_numpy(float) - D[c].to_numpy(float)))) if len(A) else 0.0 for c in num2}
    peor = max(dif.values()) if dif else 0.0
    cual = max(dif, key=dif.get) if dif else "-"
    bytes_iguales = hashlib.sha256(a.read_bytes()).hexdigest() == hashlib.sha256(d.read_bytes()).hexdigest()
    print(f"{d.name:32s} bytes idénticos: {str(bytes_iguales):5s} · texto igual: {texto_igual} · dif numérica máx (sin columnas de tiempo): {peor:.3e} ({cual})")

print("\n== tabla_comparativa.md ==")
a = (ANTES / "resultados" / "tabla_comparativa.md").read_text(encoding="utf-8"); d = (RAIZ / "resultados" / "tabla_comparativa.md").read_text(encoding="utf-8")
print("Texto idéntico:", a == d)
if a != d:
    for x, z in zip(a.splitlines(), d.splitlines()):
        if x != z:
            print("  ANTES  :", x[:300]); print("  DESPUÉS:", z[:300])

print("\n== tabla_comparativa.csv: diferencia por modelo ==")
A = pd.read_csv(ANTES / "resultados" / "tabla_comparativa.csv").set_index("modelo"); D = pd.read_csv(RAIZ / "resultados" / "tabla_comparativa.csv").set_index("modelo")
num = [c for c in A.columns if pd.api.types.is_numeric_dtype(A[c])]
print((A[num] - D[num]).abs().max(axis=1))

print("\n== predicciones: diferencia máxima de probabilidad por modelo ==")
for f in ["predicciones_prueba.csv", "predicciones_oof.csv"]:
    A = pd.read_csv(ANTES / "resultados" / f); D = pd.read_csv(RAIZ / "resultados" / f)
    j = A.merge(D, on=["ruta", "modelo"], suffixes=("_a", "_d"))
    print(f, "filas:", len(A), len(D), len(j))
    print((j.probabilidad_tumor_a - j.probabilidad_tumor_d).abs().groupby(j.modelo).max().to_string())
    print("   decisiones distintas por modelo:", (j.prediccion_a != j.prediccion_d).groupby(j.modelo).sum().to_dict())

print("\n== info.json del modelo ==")
ia = json.loads((ANTES / "app_modelos" / "v001" / "info.json").read_text(encoding="utf-8")); id_ = json.loads((RAIZ / "app" / "modelos" / "v001" / "info.json").read_text(encoding="utf-8"))


def aplanar(d, p=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from aplanar(v, p + k + ".")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                if isinstance(x, dict):
                    yield from aplanar(x, f"{p}{k}[{i}].")
                else:
                    yield f"{p}{k}[{i}]", x
        else:
            yield p + k, v


fa, fd = dict(aplanar(ia)), dict(aplanar(id_))
distintos = [(k, fa.get(k), fd.get(k)) for k in sorted(set(fa) | set(fd)) if fa.get(k) != fd.get(k)]
print(f"Campos distintos: {len(distintos)} de {len(fa)}")
for k, x, z in distintos:
    print(f"   {k}: {x!r} → {z!r}")

print("\n== Archivos binarios ==")
for rel_a, rel_d in [("app_modelos/v001/modelo.keras", "app/modelos/v001/modelo.keras"), ("app_modelos/v001/validacion.npz", "app/modelos/v001/validacion.npz"),
                     ("datos/rasgos_mobilenet.npz", "datos/rasgos/rasgos_mobilenet.npz"), ("datos/rasgos_basicos.npz", "datos/rasgos/rasgos_basicos.npz")]:
    a, d = ANTES / rel_a, RAIZ / rel_d
    print(f"   {rel_d}: bytes idénticos = {hashlib.sha256(a.read_bytes()).hexdigest() == hashlib.sha256(d.read_bytes()).hexdigest()}")
import os
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import keras
ma = keras.models.load_model(ANTES / "app_modelos" / "v001" / "modelo.keras", compile=False); md = keras.models.load_model(RAIZ / "app" / "modelos" / "v001" / "modelo.keras", compile=False)
print("   Pesos de modelo.keras, diferencia máxima absoluta antes/después:", max(float(np.abs(x - z).max()) for x, z in zip(ma.get_weights(), md.get_weights())))

print("\n== Notebooks: errores y celdas sin ejecutar después de la corrida ==")
for f in sorted((RAIZ / "notebooks").glob("*.ipynb")):
    nb = json.loads(f.read_text(encoding="utf-8"))
    cod = [c for c in nb["cells"] if c["cell_type"] == "code"]
    err = sum(1 for c in cod for o in c.get("outputs", []) if o["output_type"] == "error")
    sin = sum(1 for c in cod if c.get("execution_count") is None)
    orden = [c["execution_count"] for c in cod] == list(range(1, len(cod) + 1))
    na = json.loads((ANTES / "notebooks" / f.name).read_text(encoding="utf-8"))
    fuente_igual = [c["source"] for c in nb["cells"]] == [c["source"] for c in na["cells"]]
    print(f"   {f.name}: celdas de código {len(cod)} · con error {err} · sin ejecutar {sin} · ejecutadas en orden 1..n: {orden} · código fuente idéntico al de antes: {fuente_igual}")
