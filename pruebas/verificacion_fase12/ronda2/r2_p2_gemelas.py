"""Ronda 2 · Punto 2: gemelas con medida independiente, copias exactas, integridad y división."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from sklearn.model_selection import StratifiedKFold, train_test_split

from r2_comun import RAIZ, cargar

AQUI = Path(__file__).resolve().parent
man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
dup = pd.read_csv(RAIZ / "datos" / "duplicados.csv")
rutas, C, O = cargar()
pos = pd.Series(np.arange(len(rutas)), index=rutas)
print(f"Manifiesto: {len(man)} · duplicados.csv: {len(dup)} · archivos en disco: {len(rutas)}")

print("\n== Integridad del manifiesto ==")
print("Rutas repetidas:", int(man.ruta.duplicated().sum()), "· inexistentes:", int((~man.ruta.isin(rutas)).sum()))
partes = man.ruta.str.split("/", expand=True)
print("carpeta_origen != carpeta real:", int((partes[1] != man.carpeta_origen).sum()), "· clase != carpeta real:", int((partes[2] != man.clase).sum()),
      "· es_tumor incoherente:", int(((man.clase != "notumor").astype(int) != man.es_tumor).sum()))
print("Particiones:", man.particion.value_counts().to_dict(), "· es_tumor por partición:", pd.crosstab(man.particion, man.es_tumor).to_dict("index"))
t = pd.crosstab(man.clase, man.particion); t["frac_prueba"] = (t.prueba / t.sum(axis=1)).round(5)
print(t); print(f"Fracción de prueba global: {(man.particion == 'prueba').mean():.5f}")
_, ip = train_test_split(np.arange(len(man)), test_size=0.20, stratify=man.clase, random_state=42)
mia = np.full(len(man), "entrenamiento", dtype=object); mia[ip] = "prueba"
print("Filas cuya partición difiere de train_test_split(0.2, stratify=clase, random_state=42):", int((mia != man.particion.to_numpy()).sum()))
print("Columna grupo: valores repetidos en el manifiesto:", int(man.grupo.duplicated().sum()),
      "· grupos presentes en las dos particiones:", int((man.groupby("grupo").particion.nunique() > 1).sum()))
quit_ = set(dup.ruta[dup.accion != "conservada"]); en_man = set(man.ruta)
print(f"En manifiesto {len(en_man)} + quitadas {len(quit_)} = {len(en_man) + len(quit_)} · traslape {len(en_man & quit_)} · en disco sin clasificar {len(set(rutas) - en_man - quit_)}")
print("Acciones en duplicados.csv:", dup.accion.value_counts().to_dict())
cons = dup[dup.accion == "conservada"]
print("Conservadas de duplicados.csv que NO están en el manifiesto:", int((~cons.ruta.isin(en_man)).sum()),
      "· grupos no contradictorios con más de una conservada:", int((cons.groupby("grupo").size() > 1).sum()))

print("\n== Copias exactas entre particiones (recalculado desde los archivos) ==")


def huellas(r):
    b = (RAIZ / r).read_bytes()
    rgb = np.asarray(Image.open(BytesIO(b)).convert("RGB"))
    return hashlib.sha256(b).hexdigest(), hashlib.sha256(str(rgb.shape).encode() + rgb.tobytes()).hexdigest()


with ThreadPoolExecutor(12) as ex:
    hh = list(ex.map(huellas, man.ruta))
ent = (man.particion == "entrenamiento").to_numpy(); pru = ~ent
for k, nombre in enumerate(["SHA-256 de bytes", "SHA-256 de pixeles (PIL, RGB)"]):
    v = pd.Series([h[k] for h in hh])
    print(f"{nombre}: compartidos entre particiones = {len(set(v[ent]) & set(v[pru]))} · repetidos en todo el manifiesto = {int(v.duplicated().sum())}")

print("\n== Gemelas con mi medida (miniaturas PIL 64x64, imagen completa y recorte propio, 8 orientaciones) ==")
pm = pos[man.ruta].to_numpy()
Cm = np.asarray(C[np.ix_(pm, pm)])
ie, ipr = np.flatnonzero(ent), np.flatnonzero(pru)
me = man[ent].reset_index(drop=True)
UMB = [0.98, 0.95, 0.90]


def fila(nombre, m):
    print(f"{nombre}: n = {len(m)} · " + " · ".join(f"> {u}: {int((m > u).sum())} ({(m > u).mean():.1%})" for u in UMB) + f" · máxima {m.max():.4f}")
    return {"frontera": nombre, "n": len(m), **{f"mayor_{u}": int((m > u).sum()) for u in UMB}, "maxima": float(m.max())}


filas = [fila("prueba <-> entrenamiento", Cm[np.ix_(ipr, ie)].max(1))]
itr, iva = train_test_split(np.arange(len(me)), test_size=0.15, stratify=me.clase, random_state=42)
filas.append(fila("validación apartada (15 %) <-> su entrenamiento", Cm[np.ix_(ie[iva], ie[itr])].max(1)))
pl = np.zeros(len(me), dtype=int)
for k, (_, iv) in enumerate(StratifiedKFold(5, shuffle=True, random_state=42).split(np.zeros(len(me)), me.clase), 1):
    pl[iv] = k
Ce = Cm[np.ix_(ie, ie)].copy(); Ce[pl[:, None] == pl[None, :]] = -1
filas.append(fila("entre pliegues (cada imagen contra los otros 4)", Ce.max(1)))
filas.append(fila("dentro de todo el manifiesto (cualquier otra imagen)", Cm.max(1)))
pd.DataFrame(filas).to_csv(AQUI / "r2_gemelas_fronteras.csv", index=False)
rep = pd.read_csv(RAIZ / "resultados" / "eda_fuga_gemelas.csv")
print("\nLo que reporta el autor (resultados/eda_fuga_gemelas.csv):"); print(rep.to_string(index=False))

# Pares prueba<->entrenamiento por encima de 0.98 con mi medida (si los hay) y la banda 0.95-0.98
mx, ax = Cm[np.ix_(ipr, ie)].max(1), Cm[np.ix_(ipr, ie)].argmax(1)
pares = pd.DataFrame({"ruta_prueba": man.ruta.to_numpy()[ipr], "clase_prueba": man.clase.to_numpy()[ipr],
                      "ruta_entrenamiento": man.ruta.to_numpy()[ie][ax], "clase_entrenamiento": man.clase.to_numpy()[ie][ax], "correlacion": mx})
pares.sort_values("correlacion", ascending=False).to_csv(AQUI / "r2_pares_prueba_entrenamiento.csv", index=False)
print(f"\nPares prueba<->entrenamiento > 0.98 con mi medida: {int((mx > 0.98).sum())}")
print(pares[pares.correlacion > 0.98].sort_values("correlacion", ascending=False).head(15).to_string(index=False))
b = pares[(pares.correlacion > 0.95) & (pares.correlacion <= 0.98)]
print(f"Banda 0.95-0.98: {len(b)} imágenes de prueba · por clase {b.clase_prueba.value_counts().to_dict()} · con clase distinta en su par: {int((b.clase_prueba != b.clase_entrenamiento).sum())}")
b9 = pares[(pares.correlacion > 0.90) & (pares.correlacion <= 0.95)]
print(f"Banda 0.90-0.95: {len(b9)} · con clase distinta en su par: {int((b9.clase_prueba != b9.clase_entrenamiento).sum())}")
