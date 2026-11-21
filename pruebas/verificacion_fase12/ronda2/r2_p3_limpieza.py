"""Ronda 2 · Punto 3: ¿la limpieza fue excesiva?

Mide, con mi propia correlación (PIL, 8 orientaciones) y con la diferencia a resolución completa,
qué tan parecidas son las imágenes eliminadas a la que se conservó de su grupo, y genera montajes
para revisión visual. No modifica el proyecto.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from r2_comun import ORIENTACIONES, RAIZ, cargar, componentes, orientar

AQUI = Path(__file__).resolve().parent
rng = np.random.default_rng(20261120)
man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
dup = pd.read_csv(RAIZ / "datos" / "duplicados.csv")
rutas, C, O = cargar()
C = np.asarray(C); O = np.asarray(O)
n = len(rutas)
pos = pd.Series(np.arange(n), index=rutas)
clase = np.array([r.split("/")[2] for r in rutas])
en_man = np.isin(rutas, man.ruta)

print("== Qué se eliminó ==")
print(pd.crosstab(dup.clase, dup.accion, margins=True).to_string())
print("Causa de las quitadas por duplicado, por clase:")
q = dup[dup.accion == "quitada_duplicado"]
print(pd.crosstab(q.causa.fillna("(sin causa)"), q.clase, margins=True).to_string())
tam = dup.drop_duplicates("grupo").set_index("grupo").tamano_grupo
print("Grupos de 10 o más imágenes:", int((tam >= 10).sum()), "· imágenes en ellos:", int(tam[tam >= 10].sum()),
      "· clase de esos grupos:", dup[dup.tamano_grupo >= 10].drop_duplicates("grupo").clase.value_counts().to_dict())

# -------------------------------------------------- correlación de cada quitada con la conservada de su grupo
cons = dup[dup.accion == "conservada"].set_index("grupo").ruta
q = q.assign(rep=q.grupo.map(cons))
pi, pr = pos[q.ruta].to_numpy(), pos[q.rep].to_numpy()
q["corr_con_conservada"] = C[pi, pr]
# con la más parecida de su mismo grupo (el eslabón de la cadena)
miembros = dup.groupby("grupo").ruta.apply(lambda s: pos[s].to_numpy())
q["corr_max_en_grupo"] = [C[p, miembros[g]].max() for p, g in zip(pi, q.grupo)]
# con la imagen más parecida que SÍ quedó en el manifiesto (cualquier grupo)
idx_man = np.flatnonzero(en_man)
q["corr_max_con_manifiesto"] = C[np.ix_(pi, idx_man)].max(1)
print("\n== Correlación (mi medida) de cada imagen quitada por duplicado ==")
for col, txt in [("corr_max_en_grupo", "con la más parecida de su grupo (eslabón)"), ("corr_con_conservada", "con la CONSERVADA de su grupo"),
                 ("corr_max_con_manifiesto", "con la más parecida que quedó en el manifiesto")]:
    v = q[col]
    print(f"{txt}: n = {len(v)} · " + " · ".join(f"< {u}: {int((v < u).sum())} ({(v < u).mean():.1%})" for u in [0.98, 0.95, 0.90, 0.80]) + f" · mediana {v.median():.4f}")
print("\nPor clase, quitadas cuya correlación con lo que quedó en el manifiesto es < 0.95 (encadenadas lejos de todo lo conservado):")
print(q.assign(lejos=q.corr_max_con_manifiesto < 0.95).groupby("clase").lejos.agg(["sum", "count", "mean"]).round(3).to_string())
print("Por causa, lo mismo:")
print(q.assign(lejos=q.corr_max_con_manifiesto < 0.95).groupby(q.causa.fillna("(sin causa)")).lejos.agg(["sum", "count", "mean"]).round(3).to_string())

# -------------------------------------------------- diferencia a resolución completa contra la conservada
def gris(r):
    return np.asarray(Image.open(RAIZ / r).convert("L")).astype(np.int16)


def dif_completa(ra, rb):
    """Diferencia absoluta media entre A y B orientada (None si los tamaños no coinciden)."""
    a = gris(ra); b = orientar(gris(rb), int(O[pos[ra], pos[rb]]))
    if a.shape != b.shape:
        return None
    return float(np.abs(a - b).mean())


muestra = q.sample(min(1200, len(q)), random_state=1)
muestra = muestra.assign(dif=[dif_completa(a, b) for a, b in zip(muestra.ruta, muestra.rep)])
m = muestra.dropna(subset=["dif"])
print(f"\n== Diferencia a resolución completa, quitada contra la conservada de su grupo (muestra {len(muestra)}, mismo tamaño {len(m)}) ==")
print("Niveles de gris de diferencia media: " + " · ".join(f"< {u}: {int((m.dif < u).sum())} ({(m.dif < u).mean():.1%})" for u in [1, 2, 3, 5, 8, 12]) + f" · mediana {m.dif.median():.2f}")
print("Por causa (fracción con diferencia media < 3 = recompresión / misma toma):")
print(m.assign(misma=m.dif < 3).groupby(m.causa.fillna("(sin causa)")).misma.agg(["sum", "count", "mean"]).round(3).to_string())
print("Por clase:"); print(m.assign(misma=m.dif < 3).groupby("clase").misma.agg(["sum", "count", "mean"]).round(3).to_string())
print("Por tramo de correlación con la conservada:")
tr = pd.cut(m.corr_con_conservada, [-1, 0.90, 0.95, 0.98, 0.99, 0.995, 1.01])
print(m.assign(misma=m.dif < 3).groupby(tr, observed=True).agg(n=("dif", "size"), dif_mediana=("dif", "median"), frac_misma_toma=("misma", "mean")).round(3).to_string())

# -------------------------------------------------- cuántas "tomas distintas" hay según criterios más estrictos
print("\n== Tomas distintas según el umbral de agrupación (mi correlación, componentes conexas sobre las 7,200) ==")
contr = set(dup.ruta[dup.accion == "quitada_contradictoria"])
no_contr = ~np.isin(rutas, list(contr))
for u in [0.98, 0.985, 0.99, 0.995, 0.999]:
    ii, jj = np.nonzero(np.triu(C > u, 1))
    comp = componentes(n, ii, jj)
    tot = len(np.unique(comp[no_contr]))
    por = {c: len(np.unique(comp[no_contr & (clase == c)])) for c in ["glioma", "meningioma", "notumor", "pituitary"]}
    print(f"   umbral {u}: {tot} grupos (sin los contradictorios) · por clase {por} · grupo más grande {np.bincount(comp).max()}")
print(f"   El manifiesto conserva {len(man)} · por clase {man.clase.value_counts().to_dict()}")
# sin encadenamiento: selección codiciosa (se conserva una imagen si no tiene gemela > u entre las ya conservadas)
for u in [0.98, 0.99]:
    cons_i = []
    marc = np.zeros(n, dtype=bool)
    for i in range(n):
        if not no_contr[i]:
            continue
        if cons_i and C[i, cons_i].max() > u:
            continue
        cons_i.append(i)
    cons_i = np.array(cons_i)
    por = {c: int((clase[cons_i] == c).sum()) for c in ["glioma", "meningioma", "notumor", "pituitary"]}
    print(f"   Sin encadenar (se conserva toda imagen que no tenga gemela > {u} ya conservada): {len(cons_i)} imágenes · por clase {por}")

# -------------------------------------------------- montajes
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def montaje_grupo(g, archivo, k=24):
    sub = dup[dup.grupo == g]
    rep = sub[sub.accion == "conservada"].ruta.iloc[0] if (sub.accion == "conservada").any() else sub.ruta.iloc[0]
    otros = sub[sub.ruta != rep]
    otros = otros.assign(c=C[pos[otros.ruta].to_numpy(), pos[rep]]).sort_values("c")
    # la mitad, las MENOS parecidas a la conservada; la otra mitad al azar
    sel = pd.concat([otros.head(k // 2), otros.iloc[k // 2:].sample(min(k - 1 - k // 2, max(0, len(otros) - k // 2)), random_state=3)])
    fig, axs = plt.subplots(4, 6, figsize=(15, 10.5))
    for ax in axs.ravel():
        ax.axis("off")
    axs.ravel()[0].imshow(Image.open(RAIZ / rep).convert("L"), cmap="gray"); axs.ravel()[0].set_title("CONSERVADA\n" + Path(rep).name, fontsize=7, color="green")
    for ax, r in zip(axs.ravel()[1:], sel.itertuples()):
        ax.imshow(orientar(np.asarray(Image.open(RAIZ / r.ruta).convert("L")), int(O[pos[rep], pos[r.ruta]])), cmap="gray")
        ax.set_title(f"{Path(r.ruta).name}\ncorr con conservada {r.c:.3f}", fontsize=7)
    fig.suptitle(f"Grupo {g} · {len(sub)} imágenes · clase {sub.clase.iloc[0]} (quitadas orientadas hacia la conservada)", fontsize=10)
    fig.tight_layout(); fig.savefig(AQUI / archivo, dpi=75); plt.close(fig)


grandes = dup.drop_duplicates("grupo").sort_values("tamano_grupo", ascending=False)
print("\nGrupos más grandes:"); print(grandes[["grupo", "tamano_grupo", "clase", "contradictorio"]].head(12).to_string(index=False))
gn = grandes[(grandes.clase == "notumor") & ~grandes.contradictorio].head(4)
for k, g in enumerate(gn.grupo):
    montaje_grupo(g, f"r2_grupo_notumor_{k + 1}.png")
go = grandes[(grandes.clase != "notumor") & ~grandes.contradictorio].head(2)
for k, g in enumerate(go.grupo):
    montaje_grupo(g, f"r2_grupo_tumor_{k + 1}.png")


def montaje_pares(tabla, archivo, titulo, ca="ruta_a", cb="ruta_b"):
    tabla = tabla.head(12)
    fig, axs = plt.subplots(4, 6, figsize=(15, 10.8))
    for ax in axs.ravel():
        ax.axis("off")
    for k, r in enumerate(tabla.itertuples()):
        a, b = getattr(r, ca), getattr(r, cb)
        A = np.asarray(Image.open(RAIZ / a).convert("L")); B = orientar(np.asarray(Image.open(RAIZ / b).convert("L")), int(O[pos[a], pos[b]]))
        d = f"{np.abs(A.astype(int) - B.astype(int)).mean():.1f}" if A.shape == B.shape else "tam. distinto"
        x, y = axs.ravel()[2 * k], axs.ravel()[2 * k + 1]
        x.imshow(A, cmap="gray"); x.set_title(f"{a.split('/')[1][:2]}/{Path(a).name}", fontsize=7)
        y.imshow(B, cmap="gray"); y.set_title(f"{b.split('/')[1][:2]}/{Path(b).name} ({ORIENTACIONES[int(O[pos[a], pos[b]])]})\ncorr {C[pos[a], pos[b]]:.4f} · dif media {d}", fontsize=7)
    fig.suptitle(titulo, fontsize=10); fig.tight_layout(); fig.savefig(AQUI / archivo, dpi=75); plt.close(fig)


# pares enlazados por el autor cuya correlación (mía) está en 0.98-0.99, por clase
ii, jj = np.nonzero(np.triu((C > 0.98) & (C <= 0.99), 1))
banda = pd.DataFrame({"ruta_a": rutas[ii], "ruta_b": rutas[jj], "clase": clase[ii], "c": C[ii, jj]})
print(f"\nPares con mi correlación en (0.98, 0.99]: {len(banda)} · por clase {banda.clase.value_counts().to_dict()}")
ii2, jj2 = np.nonzero(np.triu(C > 0.99, 1))
print(f"Pares con mi correlación > 0.99: {len(ii2)}")
for c in ["notumor", "meningioma", "pituitary", "glioma"]:
    s = banda[banda.clase == c]
    if len(s):
        montaje_pares(s.sample(min(12, len(s)), random_state=5), f"r2_pares_098_099_{c}.png", f"Pares enlazados con correlación 0.98-0.99 · {c} (muestra al azar)")
# difs a resolución completa de una muestra de la banda
sb = banda.sample(min(600, len(banda)), random_state=7)
sb = sb.assign(dif=[dif_completa(a, b) for a, b in zip(sb.ruta_a, sb.ruta_b)]).dropna(subset=["dif"])
print(f"Banda 0.98-0.99, diferencia a resolución completa (muestra {len(sb)} con mismo tamaño): " +
      " · ".join(f"< {u}: {(sb.dif < u).mean():.1%}" for u in [1, 2, 3, 5, 8]) + f" · mediana {sb.dif.median():.2f}")
print(sb.assign(misma=sb.dif < 3).groupby("clase").misma.agg(["sum", "count", "mean"]).round(3).to_string())
sel =rng.choice(len(ii2), min(600, len(ii2)), replace=False)
sa = pd.DataFrame({"ruta_a": rutas[ii2[sel]], "ruta_b": rutas[jj2[sel]], "clase": clase[ii2[sel]]})
sa = sa.assign(dif=[dif_completa(a, b) for a, b in zip(sa.ruta_a, sa.ruta_b)]).dropna(subset=["dif"])
print(f"Pares > 0.99, diferencia a resolución completa (muestra {len(sa)}): " + " · ".join(f"< {u}: {(sa.dif < u).mean():.1%}" for u in [1, 2, 3, 5, 8]) + f" · mediana {sa.dif.median():.2f}")

# quitadas por hash perceptual con poca correlación con todo lo conservado
hp = q[q.causa.fillna("").str.startswith("hash perceptual")].sort_values("corr_con_conservada")
print(f"\nQuitadas por 'hash perceptual o huella preparada': {len(hp)} · corr con la conservada < 0.98: {int((hp.corr_con_conservada < 0.98).sum())} · < 0.95: {int((hp.corr_con_conservada < 0.95).sum())} · < 0.90: {int((hp.corr_con_conservada < 0.90).sum())}")
montaje_pares(hp.rename(columns={"ruta": "ruta_a", "rep": "ruta_b"}).head(12), "r2_hash_perceptual_menos_parecidas.png", "Quitadas por hash perceptual: las 12 menos parecidas a la conservada de su grupo")
montaje_pares(hp[hp.corr_con_conservada < 0.95].sample(min(12, int((hp.corr_con_conservada < 0.95).sum())), random_state=2).rename(columns={"ruta": "ruta_a", "rep": "ruta_b"}),
              "r2_hash_perceptual_muestra_bajo_095.png", "Quitadas por hash perceptual con corr < 0.95 con la conservada (muestra al azar)")
lej = q[q.corr_max_con_manifiesto < 0.95]
if len(lej):
    lej = lej.assign(cerca=[rutas[idx_man[C[p, idx_man].argmax()]] for p in pos[lej.ruta].to_numpy()])
    montaje_pares(lej.sample(min(12, len(lej)), random_state=4).rename(columns={"ruta": "ruta_a", "cerca": "ruta_b"}), "r2_quitadas_lejos_de_todo.png",
                  "Quitadas cuya imagen más parecida en el manifiesto tiene corr < 0.95 (muestra al azar; derecha = la más parecida que quedó)")

# pares prueba<->entrenamiento que NO se eliminaron, banda 0.95-0.98
pe = pd.read_csv(AQUI / "r2_pares_prueba_entrenamiento.csv")
b = pe[(pe.correlacion > 0.95) & (pe.correlacion <= 0.98)]
montaje_pares(b.sort_values("correlacion", ascending=False), "r2_prueba_ent_095_098_top.png", "Prueba (izq.) contra entrenamiento (der.) · las 12 más altas de la banda 0.95-0.98", "ruta_prueba", "ruta_entrenamiento")
montaje_pares(b.sample(min(12, len(b)), random_state=9), "r2_prueba_ent_095_098_azar.png", "Prueba (izq.) contra entrenamiento (der.) · muestra al azar de la banda 0.95-0.98", "ruta_prueba", "ruta_entrenamiento")
b = b.assign(dif=[dif_completa(a, c) for a, c in zip(b.ruta_prueba, b.ruta_entrenamiento)])
bb = b.dropna(subset=["dif"])
print(f"\nPrueba<->entrenamiento, banda 0.95-0.98: {len(b)} pares · mismo tamaño {len(bb)} · diferencia media < 3: {int((bb.dif < 3).sum())} · < 5: {int((bb.dif < 5).sum())} · mediana {bb.dif.median():.2f}")
q.to_csv(AQUI / "r2_quitadas_con_correlacion.csv", index=False)
print("Montajes y CSV en", AQUI)
