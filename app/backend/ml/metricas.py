"""Métricas del problema binario (tumor = 1, sin tumor = 0) y pruebas estadísticas."""
import math

import numpy as np


def metricas_binarias(y, prob, umbral=0.5):
    """Métricas con la regla: se predice tumor cuando prob >= umbral.

    Devuelve un dict con vp, vn, fp, fn, sensibilidad, especificidad, precision, f1,
    exactitud y auc (auc es None si en y solo hay una clase).
    """
    y = np.asarray(y).astype(int).ravel()
    prob = np.asarray(prob, dtype=float).ravel()
    pred = (prob >= umbral).astype(int)
    vp = int(((y == 1) & (pred == 1)).sum())
    vn = int(((y == 0) & (pred == 0)).sum())
    fp = int(((y == 0) & (pred == 1)).sum())
    fn = int(((y == 1) & (pred == 0)).sum())
    sens = vp / (vp + fn) if (vp + fn) else 0.0
    espe = vn / (vn + fp) if (vn + fp) else 0.0
    prec = vp / (vp + fp) if (vp + fp) else 0.0
    f1 = 2 * prec * sens / (prec + sens) if (prec + sens) else 0.0
    auc = None
    if len(np.unique(y)) == 2:
        from sklearn.metrics import roc_auc_score
        auc = float(roc_auc_score(y, prob))
    return {"vp": vp, "vn": vn, "fp": fp, "fn": fn,
            "sensibilidad": float(sens), "especificidad": float(espe), "precision": float(prec),
            "f1": float(f1), "exactitud": float((vp + vn) / max(1, len(y))), "auc": auc}


def elegir_umbral(y, prob, sensibilidad_objetivo=0.98):
    """El umbral más alto cuya sensibilidad es >= objetivo (regla: tumor si prob >= umbral), con margen.

    Se ordenan de mayor a menor las probabilidades de los casos de tumor y se toma la que
    ocupa el lugar k = techo(objetivo * número de tumores): hay que detectar al menos esos k.
    El umbral devuelto NO es esa probabilidad exacta sino el punto medio entre ella y la
    siguiente probabilidad más baja de todo el conjunto (de cualquier clase). Así ninguna
    imagen queda justo sobre el umbral: las métricas son las mismas, pero un redondeo de
    punto flotante (por ejemplo, predecir una imagen sola en vez de en lote) no puede cambiar
    la decisión de ese caso. Si no hay ninguna probabilidad más baja, se resta un margen pequeño.
    """
    y = np.asarray(y).astype(int).ravel()
    prob = np.asarray(prob, dtype=float).ravel()
    positivos = np.sort(prob[y == 1])[::-1]
    if len(positivos) == 0:
        raise ValueError("No hay casos de tumor para elegir el umbral.")
    k = int(math.ceil(sensibilidad_objetivo * len(positivos) - 1e-9))
    k = min(max(k, 1), len(positivos))
    limite = float(positivos[k - 1])
    menores = prob[prob < limite]
    if len(menores):
        umbral = (limite + float(menores.max())) / 2.0
    else:
        umbral = limite - min(1e-6, limite / 2.0)
    if not umbral < limite:   # probabilidades tan juntas que el punto medio no cabe entre ellas
        umbral = float(np.nextafter(limite, -np.inf))
    return float(umbral)


def metricas_por_pliegue(y, prob, pliegue, umbral):
    """Lista de dicts (uno por pliegue) con `metricas_binarias` calculadas al umbral dado."""
    y, prob, pliegue = np.asarray(y), np.asarray(prob), np.asarray(pliegue)
    filas = []
    for k in sorted(np.unique(pliegue)):
        m = pliegue == k
        filas.append({"pliegue": int(k), "umbral": float(umbral), **metricas_binarias(y[m], prob[m], umbral)})
    return filas


def wilson(aciertos, n, z=1.96):
    """Intervalo de confianza de Wilson al 95 % para una proporción. Devuelve (inferior, superior)."""
    if n == 0:
        return (0.0, 1.0)
    p = aciertos / n
    centro = (p + z**2 / (2 * n)) / (1 + z**2 / n)
    margen = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def mcnemar(acierta_a, acierta_b):
    """Prueba de McNemar para dos modelos evaluados en las mismas imágenes.

    Devuelve (b, c, p, metodo): b = A acierta y B falla; c = A falla y B acierta.
    Con menos de 25 casos discordantes se usa la prueba binomial exacta.
    """
    from scipy import stats
    acierta_a = np.asarray(acierta_a).astype(bool)
    acierta_b = np.asarray(acierta_b).astype(bool)
    b = int((acierta_a & ~acierta_b).sum())
    c = int((~acierta_a & acierta_b).sum())
    if b + c == 0:
        return b, c, 1.0, "sin casos discordantes"
    if b + c < 25:
        return b, c, float(stats.binomtest(min(b, c), b + c, 0.5).pvalue), "exacta (binomial)"
    est = (abs(b - c) - 1) ** 2 / (b + c)
    return b, c, float(stats.chi2.sf(est, 1)), "ji cuadrada con corrección"
