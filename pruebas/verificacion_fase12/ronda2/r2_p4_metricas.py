"""Ronda 2 · Punto 4 · Recalcula las métricas desde las predicciones guardadas, con código propio (numpy/sklearn/scipy).

Uso: python v4_metricas.py [carpeta_resultados] [carpeta_modelo]
Por omisión usa resultados/ y app/modelos/v001 del proyecto. No importa nada de app.backend.ml.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score

RAIZ = Path(r"C:\proyectos\tumores-cerebrales")
RES = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "resultados"
MOD = Path(sys.argv[2]) if len(sys.argv) > 2 else RAIZ / "app" / "modelos" / "v001"
TOL = 1e-4
RED = "Red Keras (MobileNetV2)"
fallas = []
dif_max = 0.0


def comparar(nombre, mio, reportado, tol=TOL):
    global dif_max
    d = abs(float(mio) - float(reportado))
    dif_max = max(dif_max, d)
    if not d <= tol:
        fallas.append(f"{nombre}: recalculado {mio!r} · reportado {reportado!r} · diferencia {d:.3g}")


def metricas(y, p, u):
    pred = (p >= u).astype(int)
    vn, fp, fn, vp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {"vp": int(vp), "vn": int(vn), "fp": int(fp), "fn": int(fn),
            "sensibilidad": recall_score(y, pred), "especificidad": vn / (vn + fp),
            "precision": precision_score(y, pred), "f1": f1_score(y, pred), "auc": roc_auc_score(y, p),
            "exactitud": (vp + vn) / len(y)}


def umbral_mas_alto(y, p, objetivo=0.98):
    """Fuerza bruta: de todos los valores de probabilidad, el más alto t con sensibilidad(p >= t) >= objetivo."""
    pos = p[y == 1]
    mejor = None
    for t in np.unique(p)[::-1]:
        if (pos >= t).mean() >= objetivo:
            mejor = t
            break
    return mejor


def wilson(k, n, z=stats.norm.ppf(0.975)):
    from statsmodels.stats.proportion import proportion_confint  # si no está, se usa la fórmula
    return proportion_confint(k, n, alpha=0.05, method="wilson")


def wilson_formula(k, n, z=1.959963984540054):
    ph = k / n
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    m = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return c - m, c + m


pp = pd.read_csv(RES / "predicciones_prueba.csv")
po = pd.read_csv(RES / "predicciones_oof.csv")
pr = pd.read_csv(RES / "prueba_resumen.csv").set_index("modelo")
cr = pd.read_csv(RES / "cv_resumen.csv").set_index("modelo")
cp = pd.read_csv(RES / "cv_pliegues.csv")
tc = pd.read_csv(RES / "tabla_comparativa.csv").set_index("modelo")
info = json.loads((MOD / "info.json").read_text(encoding="utf-8"))
man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
modelos = list(pp.modelo.unique())
print("Modelos en predicciones_prueba:", modelos)
print("Modelos en predicciones_oof:", list(po.modelo.unique()))

# ---- integridad de los archivos de predicciones
man_pru = man[man.particion == "prueba"]; man_ent = man[man.particion == "entrenamiento"]
for m in modelos:
    a = pp[pp.modelo == m]; b = po[po.modelo == m]
    if set(a.ruta) != set(man_pru.ruta) or len(a) != len(man_pru):
        fallas.append(f"{m}: las rutas de predicciones_prueba no son exactamente las de prueba del manifiesto")
    if set(b.ruta) != set(man_ent.ruta) or len(b) != len(man_ent):
        fallas.append(f"{m}: las rutas de predicciones_oof no son exactamente las de entrenamiento del manifiesto")
    for t, nombre in [(a, "prueba"), (b, "oof")]:
        y_man = man.set_index("ruta").loc[t.ruta, "es_tumor"].to_numpy()
        if (y_man != t.es_tumor.to_numpy()).any():
            fallas.append(f"{m}: es_tumor de predicciones_{nombre} no coincide con el manifiesto")
        if ((t.probabilidad_tumor >= t.umbral).astype(int) != t.prediccion).any():
            fallas.append(f"{m}: columna prediccion de {nombre} no coincide con prob >= umbral")
        if t.umbral.nunique() != 1:
            fallas.append(f"{m}: más de un umbral en {nombre}")
print("Rutas de prueba que aparecen también en predicciones_oof:", len(set(pp.ruta) & set(po.ruta)))
# mismos pliegues para todos los modelos
piv = po.pivot(index="ruta", columns="modelo", values="pliegue")
print("Imágenes con pliegue distinto entre modelos:", int((piv.nunique(axis=1) > 1).sum()))
# los pliegues son los de StratifiedKFold(5, shuffle, 42) por clase
from sklearn.model_selection import StratifiedKFold
me = man_ent.reset_index(drop=True)
mis = np.zeros(len(me), dtype=int)
for k, (_, iv) in enumerate(StratifiedKFold(5, shuffle=True, random_state=42).split(np.zeros(len(me)), me.clase), 1):
    mis[iv] = k
print("Imágenes cuyo pliegue difiere de StratifiedKFold(5, shuffle=True, random_state=42) por clase:",
      int((piv.loc[me.ruta].iloc[:, 0].to_numpy() != mis).sum()))

# ---- PRUEBA
print("\n== PRUEBA: recalculado desde predicciones_prueba.csv ==")
filas = []
for m in modelos:
    a = pp[pp.modelo == m]
    y, p, u = a.es_tumor.to_numpy(), a.probabilidad_tumor.to_numpy(), float(a.umbral.iloc[0])
    r = metricas(y, p, u)
    filas.append({"modelo": m, "umbral": u, **r})
    comparar(f"prueba_resumen umbral [{m}]", u, pr.loc[m, "umbral"], 1e-9)
    for k, v in r.items():
        comparar(f"prueba_resumen {k} [{m}]", v, pr.loc[m, k])
        if k != "exactitud" or "prueba_exactitud" in tc.columns:
            comparar(f"tabla_comparativa prueba_{k} [{m}]", v, tc.loc[m, f"prueba_{k}"])
    for nombre, (k_, n_) in {"sensibilidad": (r["vp"], r["vp"] + r["fn"]), "especificidad": (r["vn"], r["vn"] + r["fp"])}.items():
        li, ls = wilson_formula(k_, n_)
        comparar(f"Wilson {nombre} inf [{m}]", li, pr.loc[m, f"{nombre}_ic95_inferior"])
        comparar(f"Wilson {nombre} sup [{m}]", ls, pr.loc[m, f"{nombre}_ic95_superior"])
        comparar(f"tabla Wilson {nombre} inf [{m}]", li, tc.loc[m, f"prueba_{nombre}_ic95_inferior"])
        comparar(f"tabla Wilson {nombre} sup [{m}]", ls, tc.loc[m, f"prueba_{nombre}_ic95_superior"])
    comparar(f"tabla umbral_prueba [{m}]", u, tc.loc[m, "umbral_prueba"], 1e-9)
mias_prueba = pd.DataFrame(filas).set_index("modelo")
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
print(mias_prueba.round(6))
for k in ["vp", "vn", "fp", "fn", "sensibilidad", "especificidad", "precision", "f1", "auc", "exactitud"]:
    comparar(f"info.json metricas_prueba {k}", mias_prueba.loc[RED, k], info["metricas_prueba"][k])
comparar("info.json metricas_prueba umbral", mias_prueba.loc[RED, "umbral"], info["metricas_prueba"]["umbral"], 1e-9)
comparar("info.json umbral", mias_prueba.loc[RED, "umbral"], info["umbral"], 1e-9)
# exactitud del tipo
a = pp[(pp.modelo == RED) & (pp.es_tumor == 1)]
comparar("info.json exactitud_tipo", (a.tipo_probable == a.clase).mean(), info["metricas_prueba"]["exactitud_tipo"])

# ---- VALIDACIÓN CRUZADA
print("\n== CV: recalculado desde predicciones_oof.csv (media y desviación ddof=1 entre pliegues) ==")
filas = []
for m in modelos:
    b = po[po.modelo == m]
    y, p, u, pl = b.es_tumor.to_numpy(), b.probabilidad_tumor.to_numpy(), float(b.umbral.iloc[0]), b.pliegue.to_numpy()
    por = pd.DataFrame([{"pliegue": k, **metricas(y[pl == k], p[pl == k], u)} for k in sorted(np.unique(pl))])
    rep = cp[cp.modelo == m].set_index("pliegue")
    if len(por) != 5:
        fallas.append(f"{m}: {len(por)} pliegues en lugar de 5")
    for r in por.itertuples():
        for k in ["vp", "vn", "fp", "fn", "sensibilidad", "especificidad", "precision", "f1", "auc", "exactitud"]:
            comparar(f"cv_pliegues {k} [{m}, pliegue {r.pliegue}]", getattr(r, k), rep.loc[r.pliegue, k])
    fila = {"modelo": m, "umbral": u}
    for k in ["sensibilidad", "especificidad", "precision", "f1", "auc", "exactitud"]:
        fila[f"{k}_media"], fila[f"{k}_std"] = por[k].mean(), por[k].std(ddof=1)
        comparar(f"cv_resumen {k}_media [{m}]", fila[f"{k}_media"], cr.loc[m, f"{k}_media"])
        comparar(f"cv_resumen {k}_std [{m}]", fila[f"{k}_std"], cr.loc[m, f"{k}_std"])
        if k != "exactitud":
            comparar(f"tabla cv_{k}_media [{m}]", fila[f"{k}_media"], tc.loc[m, f"cv_{k}_media"])
            comparar(f"tabla cv_{k}_std [{m}]", fila[f"{k}_std"], tc.loc[m, f"cv_{k}_std"])
        if m == RED:
            comparar(f"info.json metricas_cv {k}_media", fila[f"{k}_media"], info["metricas_cv"][f"{k}_media"])
            comparar(f"info.json metricas_cv {k}_std", fila[f"{k}_std"], info["metricas_cv"][f"{k}_std"])
    tot = metricas(y, p, u)
    for k, kk in [("sensibilidad", "sensibilidad_oof"), ("especificidad", "especificidad_oof"), ("auc", "auc_oof"), ("vp", "vp"), ("vn", "vn"), ("fp", "fp"), ("fn", "fn")]:
        comparar(f"cv_resumen {kk} [{m}]", tot[k], cr.loc[m, kk])
    comparar(f"cv_resumen umbral [{m}]", u, cr.loc[m, "umbral"], 1e-9)
    comparar(f"tabla umbral_cv [{m}]", u, tc.loc[m, "umbral_cv"], 1e-9)
    # umbral: el más alto con sensibilidad >= 0.98 en las predicciones fuera de pliegue
    mio = umbral_mas_alto(y, p)
    sens_en_u = (p[y == 1] >= u).mean()
    siguiente = np.unique(p[p > u])
    sens_sig = (p[y == 1] >= siguiente[0]).mean() if len(siguiente) else float("nan")
    fila.update({"umbral_fuerza_bruta": mio, "sens_oof_en_umbral": sens_en_u, "sens_oof_en_siguiente_valor": sens_sig})
    arriba = p[p >= u].min(); abajo = p[p < u].max()
    fila.update({"prob_inmediata_superior": arriba, "prob_inmediata_inferior": abajo, "punto_medio": (arriba + abajo) / 2})
    comparar(f"el valor inmediato superior al umbral CV es el más alto con sens >= 0.98 [{m}]", mio, arriba, 1e-12)
    comparar(f"el umbral CV es el punto medio entre los dos valores vecinos [{m}]", (arriba + abajo) / 2, u, 1e-9)
    if m == RED:
        comparar("info.json metricas_cv umbral", u, info["metricas_cv"]["umbral"], 1e-9)
        for d in info["metricas_cv"]["por_pliegue"]:
            r = por.set_index("pliegue").loc[d["pliegue"]]
            for k in ["vp", "vn", "fp", "fn", "sensibilidad", "especificidad", "precision", "f1", "auc", "exactitud"]:
                comparar(f"info.json por_pliegue {k} [{d['pliegue']}]", r[k], d[k])
    # el umbral de prueba debe ser el mismo de CV (también en la red, si se exportó la cabeza)
    comparar(f"umbral prueba == umbral CV [{m}]", u, mias_prueba.loc[m, "umbral"], 1e-9)
    filas.append(fila)
mias_cv = pd.DataFrame(filas).set_index("modelo")
print(mias_cv.round(6).T)

# ---- tabla_comparativa.md contra lo recalculado (valores con 4 decimales)
print("\n== tabla_comparativa.md ==")
md = (RES / "tabla_comparativa.md").read_text(encoding="utf-8")
n_md = 0
for linea in md.splitlines():
    c = [x.strip() for x in linea.strip().strip("|").split("|")]
    if c and c[0] in modelos:
        m = c[0]
        esperado = []
        for k in ["sensibilidad", "especificidad", "precision", "f1", "auc"]:
            esperado.append(f"{mias_cv.loc[m, k + '_media']:.4f} ± {mias_cv.loc[m, k + '_std']:.4f}")
        esperado.append(f"{mias_prueba.loc[m, 'umbral']:.4f}")
        r = mias_prueba.loc[m]
        s = wilson_formula(r.vp, r.vp + r.fn); e = wilson_formula(r.vn, r.vn + r.fp)
        esperado.append(f"{r.sensibilidad:.4f} ({s[0]:.3f} a {s[1]:.3f})")
        esperado.append(f"{r.especificidad:.4f} ({e[0]:.3f} a {e[1]:.3f})")
        esperado += [f"{r.precision:.4f}", f"{r.f1:.4f}", f"{r.auc:.4f}", str(int(r.fn)), str(int(r.fp))]
        n_md += 1
        for j, (x, z) in enumerate(zip(c[1:], esperado)):
            if x != z:
                fallas.append(f"tabla_comparativa.md [{m}] columna {j + 1}: dice '{x}', recalculado '{z}'")
print("Filas de modelos revisadas en el .md:", n_md)
u_cv_md = re.search(r"umbral de CV de la cabeza fue ([0-9]+.[0-9]+)", md)
if u_cv_md:
    comparar("md: umbral de CV de la cabeza", float(u_cv_md.group(1)), mias_cv.loc[RED, "umbral"], 5e-5)

# ---- umbral de la red exportada
print("\n== Umbral de la red exportada (validacion.npz) ==")
print("origen_umbral en info.json:", info["origen_umbral"], "· etapa exportada:", info["etapa_exportada"])
with np.load(MOD / "validacion.npz", allow_pickle=False) as d:
    yu, pu, rutas_u = d["y"].astype(int), d["prob"], d["rutas"]
    yv, pv, rutas_v = d["y_val"].astype(int), d["prob_val"], d["rutas_val"]
red_oof = po[po.modelo == RED].set_index("ruta").loc[me.ruta]
print("npz y/prob: n =", len(yu), "· mismas rutas y orden que el entrenamiento del manifiesto:", bool((rutas_u == me.ruta.to_numpy()).all()),
      "· dif máx contra predicciones_oof.csv de la red:", float(np.abs(red_oof.probabilidad_tumor.to_numpy() - pu).max()),
      "· etiquetas distintas:", int((red_oof.es_tumor.to_numpy() != yu).sum()))
lim = umbral_mas_alto(yu, pu)
arriba, abajo = pu[pu >= info["umbral"]].min(), pu[pu < info["umbral"]].max()
print(f"Más alto con sens >= 0.98 en esos datos = {lim!r} · vecino inferior = {abajo!r} · punto medio = {(lim + abajo) / 2!r} · info.json umbral = {info['umbral']!r}")
comparar("valor inmediato superior al umbral exportado == más alto con sens >= 0.98 (OOF)", lim, arriba, 1e-12)
comparar("umbral exportado == punto medio", (lim + abajo) / 2, info["umbral"], 1e-9)
print(f"Margen del umbral a cada vecino: {arriba - info['umbral']:.3e} arriba, {info['umbral'] - abajo:.3e} abajo")
mu = metricas(yu, pu, info["umbral"])
for k, v in mu.items():
    comparar(f"info.json metricas_umbral {k}", v, info["metricas_umbral"][k])
mv = metricas(yv, pv, info["umbral"])
for k, v in mv.items():
    comparar(f"info.json metricas_validacion {k}", v, info["metricas_validacion"][k])
print("Métricas en la validación apartada al umbral exportado (recalculadas):", {k: round(float(v), 6) for k, v in mv.items()})
print("Rutas de validación que son de prueba:", int(pd.Series(rutas_v).isin(man_pru.ruta).sum()), "· de y/prob que son de prueba:", int(pd.Series(rutas_u).isin(man_pru.ruta).sum()))
from sklearn.model_selection import train_test_split
_, iv = train_test_split(np.arange(len(me)), test_size=0.15, stratify=me.clase, random_state=42)
print("rutas_val es exactamente la división 15 % esperada:", bool((me.ruta.to_numpy()[iv] == rutas_v).all()))
# ¿Qué habría pasado con la regla anterior (umbral de la validación apartada)? Informativo.
lim_v = umbral_mas_alto(yv, pv)
a = pp[pp.modelo == RED]
yt, pt = a.es_tumor.to_numpy(), a.probabilidad_tumor.to_numpy()
for nombre, uu in [("regla actual (fuera de pliegue)", info["umbral"]), ("regla anterior (validación apartada)", lim_v), ("0.5", 0.5)]:
    r = metricas(yt, pt, uu)
    print(f"   Prueba de la red con {nombre}, umbral {uu:.4f}: sensibilidad {r['sensibilidad']:.4f} · especificidad {r['especificidad']:.4f} · FN {r['fn']} · FP {r['fp']}")

# ---- McNemar
print("\n== McNemar red contra cada clásico (recalculado) ==")
mc = pd.read_csv(RES / "mcnemar.csv").set_index("modelo_b")
ac = pp.assign(ok=(pp.prediccion == pp.es_tumor)).pivot(index="ruta", columns="modelo", values="ok")
mejor = cr.drop(index=RED).sort_values(["especificidad_oof", "auc_oof"], ascending=False).index[0]
info_cl = json.loads((RES / "modelos_clasicos" / "info.json").read_text(encoding="utf-8"))
print("Mejor clásico por CV (recalculado: mayor especificidad OOF, desempate AUC):", mejor, "· declarado:", info_cl["_mejor_por_validacion_cruzada"],
      "· marcado en mcnemar.csv:", list(mc.index[mc.es_mejor_clasico_cv]))
if mejor != info_cl["_mejor_por_validacion_cruzada"] or list(mc.index[mc.es_mejor_clasico_cv]) != [mejor]:
    fallas.append("El mejor clásico declarado no coincide con el recalculado")
for otro in [m for m in modelos if m != RED]:
    b = int((ac[RED] & ~ac[otro]).sum()); c = int((~ac[RED] & ac[otro]).sum())
    p_exacta = stats.binomtest(min(b, c), b + c, 0.5).pvalue if b + c else 1.0
    p_ji = stats.chi2.sf((abs(b - c) - 1) ** 2 / (b + c), 1) if b + c else 1.0
    p_mio = p_exacta if b + c < 25 else p_ji
    print(f"  {otro}: b={b} c={c} · p exacta={p_exacta:.6g} · p ji con corrección={p_ji:.6g} · reportado p={mc.loc[otro, 'p_valor']:.6g} ({mc.loc[otro, 'metodo']})")
    comparar(f"McNemar b [{otro}]", b, mc.loc[otro, "a_acierta_b_falla"], 0)
    comparar(f"McNemar c [{otro}]", c, mc.loc[otro, "a_falla_b_acierta"], 0)
    comparar(f"McNemar p [{otro}]", p_mio, mc.loc[otro, "p_valor"])
try:
    from statsmodels.stats.contingency_tables import mcnemar as mc_sm
    t = pd.crosstab(ac[RED], ac[mejor]).reindex(index=[True, False], columns=[True, False], fill_value=0).to_numpy()
    print(f"  statsmodels (exacta) red contra {mejor}: p = {mc_sm(t, exact=True).pvalue:.6g}")
except ImportError:
    print("  (statsmodels no está instalado; se usó scipy)")
# McNemar solo sobre los casos con tumor (sensibilidad), informativo
tum = pp[pp.modelo == RED].set_index("ruta").es_tumor == 1
b = int((ac[RED] & ~ac[mejor])[tum].sum()); c = int((~ac[RED] & ac[mejor])[tum].sum())
print(f"  Informativo, solo imágenes con tumor (sensibilidad) red contra {mejor}: b={b} c={c} p exacta={stats.binomtest(min(b, c), b + c, 0.5).pvalue:.4g}")

print(f"\nDiferencia máxima entre recalculado y reportado en todas las comparaciones: {dif_max:.3g}")
print(f"FALLAS ({len(fallas)}):")
for f in fallas:
    print("  -", f)
