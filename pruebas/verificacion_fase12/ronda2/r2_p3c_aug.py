"""Ronda 2 · Archivos con 'aug' en el nombre (aumentos que ya venían en el dataset): ¿su original quedó en la otra partición?"""
from pathlib import Path
import numpy as np, pandas as pd
from PIL import Image
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from r2_comun import RAIZ, ORIENTACIONES, cargar, orientar
AQUI = Path(__file__).resolve().parent
rutas, C, O = cargar(); pos = pd.Series(np.arange(len(rutas)), index=rutas)
man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
es_aug_disco = np.array(["aug" in r for r in rutas])
print("Archivos 'aug' en disco:", int(es_aug_disco.sum()), "· por carpeta:", pd.Series([r.split("/")[1] + "/" + r.split("/")[2] for r in rutas[es_aug_disco]]).value_counts().to_dict())
man["aug"] = man.ruta.str.contains("aug")
print("En el manifiesto:", int(man.aug.sum()), "·", pd.crosstab(man.particion, man.aug).to_dict())
pm = pos[man.ruta].to_numpy(); Cm = np.asarray(C[np.ix_(pm, pm)])
ent = (man.particion == "entrenamiento").to_numpy(); pru = ~ent
ie, ip = np.flatnonzero(ent), np.flatnonzero(pru)
mx, ax = Cm[np.ix_(ip, ie)].max(1), Cm[np.ix_(ip, ie)].argmax(1)
t = pd.DataFrame({"ruta_prueba": man.ruta.to_numpy()[ip], "aug_prueba": man.aug.to_numpy()[ip], "clase": man.clase.to_numpy()[ip],
                  "ruta_ent": man.ruta.to_numpy()[ie][ax], "aug_ent": man.aug.to_numpy()[ie][ax], "correl": mx})
t["algun_aug"] = t.aug_prueba | t.aug_ent
print("\nPares prueba<->entrenamiento (el más parecido) en los que alguna de las dos es 'aug':", int(t.algun_aug.sum()))
for u in [0.95, 0.90, 0.85, 0.80]:
    print(f"   con correlación > {u}: {int((t.algun_aug & (t.correl > u)).sum())}  (prueba aug: {int((t.aug_prueba & (t.correl > u)).sum())} de {int(t.aug_prueba.sum())})")
s = t[t.aug_prueba].sort_values("correl", ascending=False)
fig, axs = plt.subplots(6, 8, figsize=(20, 16))
for ax_ in axs.ravel(): ax_.axis("off")
sel = pd.concat([s.head(12), s.iloc[12:].sample(12, random_state=3)]) if len(s) > 24 else s
for k, r in enumerate(sel.itertuples()):
    o = int(O[pos[r.ruta_prueba], pos[r.ruta_ent]])
    axs.ravel()[2*k].imshow(Image.open(RAIZ / r.ruta_prueba).convert("L"), cmap="gray"); axs.ravel()[2*k].set_title("PRUEBA " + Path(r.ruta_prueba).name, fontsize=7)
    axs.ravel()[2*k+1].imshow(orientar(np.asarray(Image.open(RAIZ / r.ruta_ent).convert("L")), o), cmap="gray")
    axs.ravel()[2*k+1].set_title(f"ENT {Path(r.ruta_ent).name}\n{ORIENTACIONES[o]} · corr {r.correl:.3f}", fontsize=7)
fig.suptitle("Imágenes 'aug' de PRUEBA y su imagen de entrenamiento más parecida (12 más altas + 12 al azar)")
fig.tight_layout(); fig.savefig(AQUI / "r2_aug_prueba.png", dpi=60)
t.to_csv(AQUI / "r2_aug_pares.csv", index=False)
