"""Ronda 3 · Puntos 1 y 2: fuga con medida independiente, manifiesto, grupos, pliegues y recuperadas.

Solo lee el proyecto. Reutiliza la matriz de correlación independiente de la ronda 2 (PIL 64x64, imagen
completa y recorte propio, 8 orientaciones, sobre los 7,200 archivos), guardada fuera del proyecto.
"""
import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from sklearn.model_selection import StratifiedGroupKFold

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "ronda2"))
from r2_comun import ORIENTACIONES, RAIZ, cargar, orientar

man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
dup = pd.read_csv(RAIZ / "datos" / "duplicados.csv")
rutas, C, O = cargar()
C = np.asarray(C)
pos = pd.Series(np.arange(len(rutas)), index=rutas)

print("== Punto 2 · Integridad ==")
print(f"Manifiesto {len(man)} · duplicados.csv {len(dup)} · en disco {len(rutas)} · suma {len(man) + len(dup)} · traslape {len(set(man.ruta) & set(dup.ruta))} · "
      f"en disco sin clasificar {len(set(rutas) - set(man.ruta) - set(dup.ruta))} · rutas repetidas {int(man.ruta.duplicated().sum())} / {int(dup.ruta.duplicated().sum())}")
p = man.ruta.str.split("/", expand=True)
print("carpeta_origen != carpeta:", int((p[1] != man.carpeta_origen).sum()), "· clase != carpeta:", int((p[2] != man.clase).sum()),
      "· es_tumor incoherente:", int(((man.clase != "notumor").astype(int) != man.es_tumor).sum()), "· 'aug' en el manifiesto:", int(man.ruta.str.contains("aug").sum()))
print("duplicados.csv por causa:", dup.causa.value_counts().to_dict(), "· acciones:", dup.accion.value_counts().to_dict())
print("  'aug' en disco:", int(pd.Series(rutas).str.contains("aug").sum()), "· 'aug' en duplicados con causa aumento:", int((dup.ruta.str.contains("aug") & (dup.causa == "aumento_del_dataset")).sum()))
ref = dup[dup.causa.isin(["copia_exacta", "casi_identica", "espejo_o_giro"])]
print("  referencias de las copias que NO están en el manifiesto:", int((~ref.ruta_referencia.isin(man.ruta)).sum()), "de", len(ref),
      "· con clase distinta a su referencia:", int((ref.clase != ref.clase_referencia).sum()))
mia = C[pos[ref.ruta].to_numpy(), pos[ref.ruta_referencia].to_numpy()]
print(f"  correlación (mi medida) de cada copia eliminada con su referencia conservada: < 0.98: {int((mia < 0.98).sum())} · < 0.97: {int((mia < 0.97).sum())} · < 0.95: {int((mia < 0.95).sum())} · mínima {mia.min():.4f}")
print(pd.crosstab(man.clase, man.particion, margins=True).to_string())
print("es_tumor por partición:", pd.crosstab(man.particion, man.es_tumor).to_dict("index"), f"· fracción de prueba {(man.particion == 'prueba').mean():.4f}")

print("\n== Punto 2 · Grupos y pliegues ==")
g = man.groupby("grupo_similitud")
print(f"Grupos de similitud: {g.ngroups} · mayor: {int(g.size().max())} · grupos en dos particiones: {int((g.particion.nunique() > 1).sum())} · grupos en dos pliegues: {int((g.pliegue.nunique() > 1).sum())}"
      f" · grupos con más de una clase: {int((g.clase.nunique() > 1).sum())} · que mezclan tumor/sin tumor: {int((g.es_tumor.nunique() > 1).sum())}")
print("pliegue por partición:", pd.crosstab(man.particion, man.pliegue).to_dict("index"))
sg = StratifiedGroupKFold(5, shuffle=True, random_state=42)
_, ip = list(sg.split(np.zeros(len(man)), man.clase, man.grupo_similitud))[0]
esp = np.full(len(man), "entrenamiento", dtype=object); esp[ip] = "prueba"
print("Filas cuya partición difiere del primer pliegue de StratifiedGroupKFold(5, shuffle, 42) por clase y grupo:", int((esp != man.particion.to_numpy()).sum()))
ent = (man.particion == "entrenamiento").to_numpy(); pru = ~ent
me = man[ent].reset_index(drop=True)
mis = np.zeros(len(me), dtype=int)
for k, (_, iv) in enumerate(StratifiedGroupKFold(5, shuffle=True, random_state=42).split(np.zeros(len(me)), me.clase, me.grupo_similitud), 1):
    mis[iv] = k
print("Filas de entrenamiento cuyo pliegue difiere del recalculado:", int((mis != me.pliegue.to_numpy()).sum()))
oof = pd.read_csv(RAIZ / "resultados" / "predicciones_oof.csv")
piv = oof.pivot(index="ruta", columns="modelo", values="pliegue")
print("Modelos en predicciones_oof:", piv.shape[1], "· imágenes con pliegue distinto entre modelos:", int((piv.nunique(axis=1) > 1).sum()),
      "· distinto del manifiesto:", int((piv.loc[me.ruta].to_numpy() != me.pliegue.to_numpy()[:, None]).any(1).sum()))
# validación apartada por grupos: primera de 7 partes
itr, iva = list(StratifiedGroupKFold(7, shuffle=True, random_state=42).split(np.zeros(len(me)), me.clase, me.grupo_similitud))[0]
with np.load(RAIZ / "app" / "modelos" / "v001" / "validacion.npz", allow_pickle=False) as d:
    rv = d["rutas_val"]
print(f"Validación apartada recalculada (1 de 7 partes por grupos): {len(iva)} · rutas_val del npz: {len(rv)} · mismo conjunto: {set(rv) == set(me.ruta.to_numpy()[iva])}"
      f" · grupos compartidos entre validación y su entrenamiento: {len(set(me.grupo_similitud[iva]) & set(me.grupo_similitud[itr]))} · rutas_val en prueba: {int(np.isin(rv, man.ruta[pru]).sum())}")

print("\n== Copias exactas entre particiones ==")
def huellas(r):
    b = (RAIZ / r).read_bytes()
    rgb = np.asarray(Image.open(BytesIO(b)).convert("RGB"))
    return hashlib.sha256(b).hexdigest(), hashlib.sha256(str(rgb.shape).encode() + rgb.tobytes()).hexdigest()
with ThreadPoolExecutor(12) as ex:
    hh = list(ex.map(huellas, man.ruta))
for k, nombre in enumerate(["SHA-256 de bytes", "SHA-256 de pixeles"]):
    v = pd.Series([h[k] for h in hh])
    print(f"{nombre}: compartidos entre particiones {len(set(v[ent]) & set(v[pru]))} · repetidos en el manifiesto {int(v.duplicated().sum())}")

print("\n== Punto 1 · Fuga con mi medida ==")
pm = pos[man.ruta].to_numpy(); Cm = C[np.ix_(pm, pm)]
ie, ipr = np.flatnonzero(ent), np.flatnonzero(pru)
UMB = [0.98, 0.95, 0.90]
def fila(nombre, m):
    print(f"{nombre}: n = {len(m)} · " + " · ".join(f"> {u}: {int((m > u).sum())} ({(m > u).mean():.1%})" for u in UMB) + f" · máxima {m.max():.4f}")
mx, ax = Cm[np.ix_(ipr, ie)].max(1), Cm[np.ix_(ipr, ie)].argmax(1)
fila("prueba <-> entrenamiento", mx)
fila("validación apartada <-> su entrenamiento", Cm[np.ix_(ie[iva], ie[itr])].max(1))
Ce = Cm[np.ix_(ie, ie)].copy(); pl = me.pliegue.to_numpy(); Ce[pl[:, None] == pl[None, :]] = -1
fila("entre pliegues (cada imagen contra los otros 4)", Ce.max(1))
print("Lo que reporta el autor:"); print(pd.read_csv(RAIZ / "resultados" / "eda_fuga_gemelas.csv").to_string(index=False))
pares = pd.DataFrame({"ruta_prueba": man.ruta.to_numpy()[ipr], "clase_prueba": man.clase.to_numpy()[ipr], "ruta_entrenamiento": man.ruta.to_numpy()[ie][ax],
                      "clase_entrenamiento": man.clase.to_numpy()[ie][ax], "correlacion": mx}).sort_values("correlacion", ascending=False)
pares.to_csv(AQUI / "r3_pares_prueba_entrenamiento.csv", index=False)
print("\nPares prueba<->entrenamiento > 0.95 con mi medida (frontera de remuestreo):")
print(pares[pares.correlacion > 0.95].to_string(index=False))
b = pares[(pares.correlacion > 0.90) & (pares.correlacion <= 0.95)]
print(f"Banda 0.90-0.95: {len(b)} ({len(b) / len(pares):.1%}) · por clase {b.clase_prueba.value_counts().to_dict()} · clase distinta en el par: {int((b.clase_prueba != b.clase_entrenamiento).sum())}")
st = pares[pares.clase_prueba == "notumor"]
print(f"'Sin tumor' de prueba: {len(st)} · con par > 0.95: {int((st.correlacion > 0.95).sum())} · en 0.90-0.95: {int(((st.correlacion > 0.90) & (st.correlacion <= 0.95)).sum())}")
dentro = Cm.max(1)
print(f"Dentro del manifiesto, imágenes con otra > 0.98: {int((dentro > 0.98).sum())} · pares > 0.95 con grupo_similitud distinto: "
      f"{int(np.triu((Cm > 0.95) & (man.grupo_similitud.to_numpy()[:, None] != man.grupo_similitud.to_numpy()[None, :]), 1).sum())}")

print("\n== Punto 1 · Lo que falló en la ronda 2 ==")
r2 = pd.read_csv(AQUI.parent / "ronda2" / "r2_pares_prueba_entrenamiento.csv")
r2 = r2[(r2.correlacion > 0.95) & (r2.correlacion <= 0.98)]
part = man.set_index("ruta").particion; grp = man.set_index("ruta").grupo_similitud
def estado(a, b):
    ea, eb = part.get(a, "quitada"), part.get(b, "quitada")
    if ea == "quitada" or eb == "quitada":
        return "al menos una quitada"
    return "mismo lado" if ea == eb else "SIGUE CRUZANDO"
r2["estado"] = [estado(a, b) for a, b in zip(r2.ruta_prueba, r2.ruta_entrenamiento)]
r2["mismo_grupo"] = [(a in grp.index and b in grp.index and grp[a] == grp[b]) for a, b in zip(r2.ruta_prueba, r2.ruta_entrenamiento)]
print("Los 69 pares prueba<->entrenamiento de la banda 0.95-0.98 de la ronda 2, hoy:"); print(pd.crosstab(r2.clase_prueba, r2.estado, margins=True).to_string())
print("De los que siguen ambos en el manifiesto, en el mismo grupo_similitud:", int(r2.mismo_grupo.sum()), "de", int((r2.estado != "al menos una quitada").sum()))
print(r2[r2.estado == "SIGUE CRUZANDO"].to_string(index=False))
for a, b2 in [("datos/Training/notumor/Tr-no_1312.jpg", "datos/Training/notumor/Tr-no_120.jpg"), ("datos/Training/meningioma/Tr-me_584.jpg", "datos/Training/glioma/Tr-gl_502.jpg")]:
    print(f"   {Path(a).name}: {part.get(a, 'quitada')} (grupo {grp.get(a, '-')}) · {Path(b2).name}: {part.get(b2, "quitada")} (grupo {grp.get(b2, "-")}) · mi correlación {C[pos[a], pos[b2]]:.4f}")

print("\n== Punto 2 · Las recuperadas ==")
viejo = pd.read_csv(Path(sys.argv[1])) if len(sys.argv) > 1 else None
if viejo is not None:
    nuevas = man[~man.ruta.isin(viejo.ruta)]
    perdidas = viejo[~viejo.ruta.isin(man.ruta)]
    print(f"En el manifiesto actual y no en el de la ronda 2: {len(nuevas)} · por clase {nuevas.clase.value_counts().to_dict()} · por partición {nuevas.particion.value_counts().to_dict()}")
    print(f"En el de la ronda 2 y ya no: {len(perdidas)} · de ellas 'aug': {int(perdidas.ruta.str.contains('aug').sum())} · no 'aug' por clase {perdidas[~perdidas.ruta.str.contains('aug')].clase.value_counts().to_dict()}")
    resto = np.flatnonzero(~man.ruta.isin(nuevas.ruta).to_numpy())
    pn = np.flatnonzero(man.ruta.isin(nuevas.ruta).to_numpy())
    cmax, carg = Cm[np.ix_(pn, np.arange(len(man)))].max(1), Cm[np.ix_(pn, np.arange(len(man)))].argmax(1)
    rec = pd.DataFrame({"ruta": man.ruta.to_numpy()[pn], "clase": man.clase.to_numpy()[pn], "particion": man.particion.to_numpy()[pn], "mas_parecida": man.ruta.to_numpy()[carg],
                        "particion_par": man.particion.to_numpy()[carg], "correlacion": cmax, "mismo_grupo": man.grupo_similitud.to_numpy()[pn] == man.grupo_similitud.to_numpy()[carg]})
    print("Correlación de cada recuperada con la imagen más parecida del manifiesto: " + " · ".join(f"> {u}: {int((rec.correlacion > u).sum())}" for u in [0.98, 0.97, 0.95, 0.90]) + f" · mediana {rec.correlacion.median():.3f}")
    print("Recuperadas con par > 0.95 que quedó en la OTRA partición:", int(((rec.correlacion > 0.95) & (rec.particion != rec.particion_par)).sum()))
    rec.sort_values("correlacion", ascending=False).to_csv(AQUI / "r3_recuperadas.csv", index=False)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
def montaje(tabla, ca, cb, archivo, titulo, n=20):
    tabla = tabla.head(n)
    fig, axs = plt.subplots(5, 8, figsize=(20, 13.5))
    for a_ in axs.ravel():
        a_.axis("off")
    for k, r in enumerate(tabla.itertuples()):
        a, b_ = getattr(r, ca), getattr(r, cb)
        o = int(O[pos[a], pos[b_]])
        axs.ravel()[2 * k].imshow(Image.open(RAIZ / a).convert("L"), cmap="gray"); axs.ravel()[2 * k].set_title(Path(a).name, fontsize=7)
        axs.ravel()[2 * k + 1].imshow(orientar(np.asarray(Image.open(RAIZ / b_).convert("L")), o), cmap="gray")
        axs.ravel()[2 * k + 1].set_title(f"{Path(b_).name}\n{ORIENTACIONES[o]} · corr {C[pos[a], pos[b_]]:.3f}", fontsize=7)
    fig.suptitle(titulo); fig.tight_layout(); fig.savefig(AQUI / archivo, dpi=60); plt.close(fig)
montaje(b.sample(20, random_state=21), "ruta_prueba", "ruta_entrenamiento", "r3_banda_090_095_azar.png", "Prueba (izq.) contra entrenamiento (der.) · 20 pares al azar de la banda 0.90-0.95")
montaje(b, "ruta_prueba", "ruta_entrenamiento", "r3_banda_090_095_top.png", "Prueba (izq.) contra entrenamiento (der.) · los 20 más altos por debajo de 0.95")
stb = st[(st.correlacion > 0.88)]
montaje(stb, "ruta_prueba", "ruta_entrenamiento", "r3_sin_tumor_prueba_top.png", "'Sin tumor' de prueba y su par de entrenamiento más parecido (los 20 más altos)")
if viejo is not None:
    montaje(rec.sort_values("correlacion", ascending=False), "ruta", "mas_parecida", "r3_recuperadas_top.png", "Recuperadas (izq.) y la imagen más parecida del manifiesto (der.) · las 20 más altas")
    montaje(rec.sample(20, random_state=5), "ruta", "mas_parecida", "r3_recuperadas_azar.png", "Recuperadas (izq.) y la imagen más parecida del manifiesto (der.) · 20 al azar")
print("Montajes en", AQUI)
# copias eliminadas cuya correlación (mi medida) con su referencia es baja
baja = ref.assign(mia=mia).sort_values("mia")
print("\nCopias eliminadas con mi correlación < 0.95 contra su referencia, por causa:", baja[baja.mia < 0.95].causa.value_counts().to_dict(), "· por clase:", baja[baja.mia < 0.95].clase.value_counts().to_dict())
print("   correlación que reporta el autor para ellas: mínima", round(float(baja[baja.mia < 0.95].correlacion.min()), 4))
montaje(baja, "ruta", "ruta_referencia", "r3_quitadas_baja_correlacion_top.png", "Eliminadas (izq.) y su referencia conservada (der.) · las 20 con MENOR correlación según mi medida")
montaje(baja[baja.mia < 0.95].sample(20, random_state=8), "ruta", "ruta_referencia", "r3_quitadas_baja_correlacion_azar.png", "Eliminadas (izq.) y su referencia (der.) · 20 al azar con mi correlación < 0.95")
