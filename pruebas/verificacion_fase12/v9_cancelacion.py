"""Punto 9 · Cancelación del entrenamiento: `callback_progreso` devuelve False en la época 2."""
import os
import sys
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
RAIZ = Path(r"C:\proyectos\tumores-cerebrales")
sys.path.insert(0, str(RAIZ))
import numpy as np
import pandas as pd

from app.backend.ml import entrenar

man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
with np.load(RAIZ / "datos" / "rasgos" / "rasgos_mobilenet.npz") as d:
    X = d["X"]
ent = np.where((man.particion == "entrenamiento").to_numpy())[0]   # solo entrenamiento: la prueba no se toca
rng = np.random.default_rng(7)
sub = rng.choice(ent, 600, replace=False)
y, t = entrenar.etiquetas_de_clases(man.clase[sub])
Xs = X[sub]
tr, va = slice(0, 450), slice(450, 600)
print(f"Subconjunto: {len(sub)} imágenes de entrenamiento (450 / 150) · tumores: {int(y.sum())}")

llamadas = []


def cb(etapa, epoca, registros):
    llamadas.append((etapa, epoca, sorted(registros)))
    return False if epoca == 2 else None


modelo, hist = entrenar.entrenar_cabeza(Xs[tr], y[tr], t[tr], Xs[va], y[va], t[va], epocas_max=30, paciencia=8, callback_progreso=cb)
print("Llamadas al callback:", [(e, n) for e, n, _ in llamadas])
print("Claves de registros:", llamadas[0][2])
print("Épocas en el historial:", len(hist["loss"]), "· cancelado:", hist["cancelado"])
print("Se detuvo en la época 2:", len(hist["loss"]) == 2 and len(llamadas) == 2, "· marca cancelado:", hist["cancelado"] is True)
p, _ = entrenar.predecir_cabeza(modelo, Xs[va])
print("El modelo devuelto predice (probabilidades finitas):", bool(np.isfinite(p).all()), "· val_loss por época:", [round(v, 4) for v in hist["val_loss"]])

# Control: sin cancelar, corre más de 2 épocas y cancelado = False
llamadas2 = []
_, hist2 = entrenar.entrenar_cabeza(Xs[tr], y[tr], t[tr], Xs[va], y[va], t[va], epocas_max=5, paciencia=8,
                                    callback_progreso=lambda e, n, r: llamadas2.append(n))
print("Control sin cancelar: épocas", len(hist2["loss"]), "· cancelado:", hist2["cancelado"])

# Devolver True o None no debe cancelar; solo False
_, hist3 = entrenar.entrenar_cabeza(Xs[tr], y[tr], t[tr], Xs[va], y[va], t[va], epocas_max=3, paciencia=8,
                                    callback_progreso=lambda e, n, r: True)
print("Control devolviendo True: épocas", len(hist3["loss"]), "· cancelado:", hist3["cancelado"])

# kfold_cabeza también debe detenerse y marcar cancelado
n_llam = []
def cb2(etapa, epoca, registros):
    n_llam.append(epoca)
    return epoca < 2
cv = entrenar.kfold_cabeza(Xs, y, t, n_pliegues=3, epocas_max=20, paciencia=5, callback_progreso=cb2)
print("kfold_cabeza cancelado en la época 2 del primer pliegue: cancelado =", cv["cancelado"], "· pliegues hechos:", len(cv["pliegues"]),
      "· llamadas:", n_llam, "· predicciones OOF sin llenar (NaN):", int(np.isnan(cv["prob_oof"]).sum()), "de", len(Xs))
