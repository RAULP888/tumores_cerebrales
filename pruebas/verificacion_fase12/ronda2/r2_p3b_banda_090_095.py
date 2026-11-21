"""Ronda 2 · Montaje de una muestra al azar de pares prueba<->entrenamiento con correlación 0.90-0.95."""
from pathlib import Path
import numpy as np, pandas as pd
from PIL import Image
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from r2_comun import RAIZ, ORIENTACIONES, cargar, orientar
AQUI = Path(__file__).resolve().parent
rutas, C, O = cargar(); pos = pd.Series(np.arange(len(rutas)), index=rutas)
b = pd.read_csv(AQUI / "r2_pares_prueba_entrenamiento.csv")
b = b[(b.correlacion > 0.90) & (b.correlacion <= 0.95)]
print("Banda 0.90-0.95 por clase:", b.clase_prueba.value_counts().to_dict())
s = b.sample(24, random_state=11)
fig, axs = plt.subplots(6, 8, figsize=(20, 16))
for ax in axs.ravel(): ax.axis("off")
for k, r in enumerate(s.itertuples()):
    o = int(O[pos[r.ruta_prueba], pos[r.ruta_entrenamiento]])
    axs.ravel()[2*k].imshow(Image.open(RAIZ / r.ruta_prueba).convert("L"), cmap="gray"); axs.ravel()[2*k].set_title("PRUEBA " + Path(r.ruta_prueba).name, fontsize=7)
    axs.ravel()[2*k+1].imshow(orientar(np.asarray(Image.open(RAIZ / r.ruta_entrenamiento).convert("L")), o), cmap="gray")
    axs.ravel()[2*k+1].set_title(f"ENT {Path(r.ruta_entrenamiento).name}\n{ORIENTACIONES[o]} · corr {r.correlacion:.3f}", fontsize=7)
fig.tight_layout(); fig.savefig(AQUI / "r2_prueba_ent_090_095_azar.png", dpi=60)
