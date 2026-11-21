"""Punto 2 · Verificación independiente de duplicados y de la división entrenamiento/prueba.

No usa las columnas de hash del manifiesto como evidencia: todo se recalcula desde los archivos.
Solo lee el proyecto; escribe únicamente en esta carpeta (montajes PNG y un CSV de pares).
"""
import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from scipy.fft import dctn

RAIZ = Path(r"C:\proyectos\tumores-cerebrales")
AQUI = Path(__file__).resolve().parent
man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
dup = pd.read_csv(RAIZ / "datos" / "duplicados.csv")
print(f"Manifiesto: {len(man)} filas · duplicados.csv: {len(dup)} filas")

# ---------------------------------------------------------------- estructura
print("\n== Estructura del manifiesto ==")
print("Rutas repetidas:", int(man.ruta.duplicated().sum()))
existe = np.array([(RAIZ / r).is_file() for r in man.ruta])
print("Rutas que no existen:", int((~existe).sum()))
partes = man.ruta.str.split("/", expand=True)
print("Prefijo distinto de 'datos':", int((partes[0] != "datos").sum()))
print("carpeta_origen != carpeta real:", int((partes[1] != man.carpeta_origen).sum()))
print("clase != carpeta real:", int((partes[2] != man.clase).sum()))
print("es_tumor incoherente con clase:", int(((man.clase != "notumor").astype(int) != man.es_tumor).sum()))
print("Valores de particion:", man.particion.value_counts().to_dict())
tabla = pd.crosstab(man.clase, man.particion)
tabla["frac_prueba"] = tabla.prueba / tabla.sum(axis=1)
print(tabla)
print(f"Fracción de prueba global: {(man.particion == 'prueba').mean():.5f}")
# ¿Se reproduce la división con train_test_split(semilla 42, estratificada por clase)?
from sklearn.model_selection import train_test_split
_, i_pru = train_test_split(np.arange(len(man)), test_size=0.20, stratify=man.clase, random_state=42)
mia = np.full(len(man), "entrenamiento", dtype=object); mia[i_pru] = "prueba"
print("Filas cuya partición difiere de train_test_split(test_size=0.2, stratify=clase, random_state=42):",
      int((mia != man.particion.to_numpy()).sum()))

# Todos los archivos del dataset están en el manifiesto o figuran como quitados
todos = sorted(p.relative_to(RAIZ).as_posix() for c in ["Training", "Testing"] for p in (RAIZ / "datos" / c).rglob("*") if p.is_file())
quitadas = set(dup.ruta[dup.accion != "conservada"])
en_man = set(man.ruta)
print(f"\nArchivos en disco: {len(todos)} · en manifiesto: {len(en_man)} · quitados según duplicados.csv: {len(quitadas)}")
print("En manifiesto y a la vez quitados:", len(en_man & quitadas))
print("En disco pero ni en manifiesto ni quitados:", len(set(todos) - en_man - quitadas))
print("En manifiesto pero no en disco:", len(en_man - set(todos)))


# ---------------------------------------------------------------- huellas propias
def recorte_propio(g):
    """Caja del contenido (pixeles > 10) sobre la imagen en grises; recorte propio, distinto al del proyecto."""
    m = g > 10
    if not m.any():
        return g
    f, c = np.where(m.any(1))[0], np.where(m.any(0))[0]
    return g[f[0]:f[-1] + 1, c[0]:c[-1] + 1]


def phash(g_img, n=32, k=8):
    """Hash perceptual por DCT (pHash clásico): 64 bits."""
    a = np.asarray(g_img.resize((n, n), Image.Resampling.LANCZOS), dtype=np.float64)
    d = dctn(a, norm="ortho")[:k, :k]
    med = np.median(d.ravel()[1:])
    return np.packbits((d > med).ravel())


def mini(g_img, n=32):
    a = np.asarray(g_img.resize((n, n), Image.Resampling.BOX), dtype=np.float64).ravel()
    a = a - a.mean()
    s = np.linalg.norm(a)
    return a / s if s > 0 else a


def analizar(ruta):
    b = (RAIZ / ruta).read_bytes()
    sha_arch = hashlib.sha256(b).hexdigest()
    from io import BytesIO
    im = Image.open(BytesIO(b))
    rgb = np.asarray(im.convert("RGB"))
    sha_pix = hashlib.sha256(str(rgb.shape).encode() + rgb.tobytes()).hexdigest()
    gris = im.convert("L")
    g = np.asarray(gris)
    rec = Image.fromarray(recorte_propio(g))
    return sha_arch, sha_pix, phash(gris), phash(rec), mini(gris), mini(rec)


with ThreadPoolExecutor(12) as ex:
    res = list(ex.map(analizar, man.ruta))
sha_arch = np.array([r[0] for r in res]); sha_pix = np.array([r[1] for r in res])
ph = np.stack([r[2] for r in res]); ph_rec = np.stack([r[3] for r in res])
mi = np.stack([r[4] for r in res]); mi_rec = np.stack([r[5] for r in res])
ent = (man.particion == "entrenamiento").to_numpy(); pru = ~ent
print(f"\n== Huellas recalculadas desde los archivos ({len(man)} imágenes; {ent.sum()} entrenamiento, {pru.sum()} prueba) ==")


def cruces(valores, nombre):
    v = pd.Series(valores)
    comp = set(v[ent]) & set(v[pru])
    n_pru = int(v[pru].isin(comp).sum())
    print(f"{nombre}: valores compartidos entre particiones = {len(comp)} (imágenes de prueba afectadas: {n_pru}) · "
          f"valores repetidos en todo el manifiesto = {int(v.duplicated().sum())}")
    return comp


cruces(sha_arch, "(a) SHA-256 de los bytes del archivo")
cruces(sha_pix, "(b) SHA-256 de los pixeles decodificados (PIL, RGB)")
cruces([x.tobytes().hex() for x in ph], "(c1) pHash-DCT 64 bits, imagen completa")
cruces([x.tobytes().hex() for x in ph_rec], "(c2) pHash-DCT 64 bits, recorte propio")

# Distancia de Hamming entre prueba y entrenamiento
POP = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def hamming_min(A, B):
    mins, args = [], []
    for a in A:
        d = POP[np.bitwise_xor(B, a)].sum(1)
        mins.append(d.min()); args.append(d.argmin())
    return np.array(mins), np.array(args)


for nombre, H in [("imagen completa", ph), ("recorte propio", ph_rec)]:
    dmin, _ = hamming_min(H[pru], H[ent])
    print(f"pHash {nombre}: imágenes de prueba con distancia de Hamming mínima a entrenamiento "
          + " · ".join(f"<= {t}: {int((dmin <= t).sum())}" for t in [0, 2, 4, 6, 8]))

# Comprobación de que las columnas del manifiesto dicen la verdad (reproduciendo la receta del autor)
import cv2
def sha_autor(ruta):
    img = cv2.imdecode(np.fromfile(str(RAIZ / ruta), dtype=np.uint8), cv2.IMREAD_COLOR)
    return hashlib.sha256(str(img.shape).encode() + img.tobytes()).hexdigest()
with ThreadPoolExecutor(12) as ex:
    sha_a = np.array(list(ex.map(sha_autor, man.ruta)))
print("\nColumna sha256 del manifiesto distinta de la recalculada con la receta del autor:", int((sha_a != man.sha256.to_numpy()).sum()))
imgs = np.load(RAIZ / "datos" / "rasgos" / "imagenes_160.npy", mmap_mode="r")
sha_prep = np.array([hashlib.sha256(np.ascontiguousarray(imgs[i]).tobytes()).hexdigest() for i in range(len(man))])
print("imagenes_160.npy: filas cuyo SHA-256 difiere de sha256_preparada del manifiesto:", int((sha_prep != man.sha256_preparada.to_numpy()).sum()))
cruces(sha_prep, "SHA-256 de la imagen preparada guardada (imagenes_160.npy)")

# ---------------------------------------------------------------- casi idénticas
print("\n== Imágenes de prueba casi idénticas a alguna de entrenamiento ==")
UMBRALES = [0.90, 0.95, 0.97, 0.98, 0.99, 0.995, 0.999]


def maxcorr(M):
    te, tr = M[pru], M[ent]
    c = te @ tr.T
    # también contra el espejo horizontal
    n = int(np.sqrt(M.shape[1]))
    tr_esp = tr.reshape(-1, n, n)[:, :, ::-1].reshape(len(tr), -1)
    c2 = te @ tr_esp.T
    return c.max(1), c.argmax(1), c2.max(1), c2.argmax(1)


resultados = {}
for nombre, M in [("miniatura 32x32 imagen completa", mi), ("miniatura 32x32 recorte propio", mi_rec)]:
    m1, a1, m2, a2 = maxcorr(M)
    resultados[nombre] = (m1, a1, m2, a2)
    print(f"Correlación de pixeles, {nombre} (mediana del máximo {np.median(m1):.3f}):")
    print("   directa : " + " · ".join(f"> {u}: {int((m1 > u).sum())}" for u in UMBRALES))
    print("   espejo  : " + " · ".join(f"> {u}: {int((m2 > u).sum())}" for u in UMBRALES))
m_full, a_full = resultados["miniatura 32x32 imagen completa"][:2]
m_rec, a_rec = resultados["miniatura 32x32 recorte propio"][:2]
m_any = np.maximum.reduce([m_full, m_rec, resultados["miniatura 32x32 imagen completa"][2], resultados["miniatura 32x32 recorte propio"][2]])
print("Cualquiera de las cuatro variantes: " + " · ".join(f"> {u}: {int((m_any > u).sum())}" for u in UMBRALES))

# Similitud coseno de los rasgos MobileNetV2 guardados (para comparar con la cifra del autor)
with np.load(RAIZ / "datos" / "rasgos" / "rasgos_mobilenet.npz") as d:
    X = d["X"]; assert (d["rutas"] == man.ruta.to_numpy()).all()
Xn = X / np.linalg.norm(X, axis=1, keepdims=True)
cs = Xn[pru] @ Xn[ent].T
cmax, carg = cs.max(1), cs.argmax(1)
print("Similitud coseno de rasgos MobileNetV2 (máximo contra entrenamiento): "
      + " · ".join(f"> {u}: {int((cmax > u).sum())}" for u in [0.95, 0.98, 0.99, 0.995, 0.999]))
print(f"Prueba con correlación de pixeles (recorte) > 0.98 Y coseno > 0.98: {int(((m_rec > 0.98) & (cmax > 0.98)).sum())}")
print(f"Prueba con correlación de pixeles (cualquiera) > 0.98 O coseno > 0.98: {int(((m_any > 0.98) | (cmax > 0.98)).sum())}")

man_pru, man_ent = man[pru].reset_index(drop=True), man[ent].reset_index(drop=True)
pares = pd.DataFrame({"ruta_prueba": man_pru.ruta, "clase_prueba": man_pru.clase,
                      "corr_completa": m_full, "par_completa": man_ent.ruta[a_full].to_numpy(),
                      "corr_recorte": m_rec, "par_recorte": man_ent.ruta[a_rec].to_numpy(),
                      "clase_par_recorte": man_ent.clase[a_rec].to_numpy(),
                      "coseno_mobilenet": cmax, "par_coseno": man_ent.ruta[carg].to_numpy()})
pares.sort_values("corr_recorte", ascending=False).to_csv(AQUI / "pares_casi_identicos.csv", index=False, encoding="utf-8")
alto = pares[pares.corr_recorte > 0.98]
print(f"Pares con correlación (recorte) > 0.98: {len(alto)} · con clase distinta entre prueba y su par: {int((alto.clase_prueba != alto.clase_par_recorte).sum())}")
print("Por clase de la imagen de prueba (corr recorte > 0.98):", alto.clase_prueba.value_counts().to_dict())

# Montajes para revisión visual
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def montaje(filas, archivo, titulo):
    filas = filas.head(12)
    if not len(filas):
        return
    fig, axs = plt.subplots(4, 6, figsize=(15, 10.5))
    for ax in axs.ravel():
        ax.axis("off")
    for k, r in enumerate(filas.itertuples()):
        a, b = axs.ravel()[2 * k], axs.ravel()[2 * k + 1]
        a.imshow(Image.open(RAIZ / r.ruta_prueba).convert("L"), cmap="gray"); a.set_title("PRUEBA " + Path(r.ruta_prueba).name, fontsize=7)
        b.imshow(Image.open(RAIZ / r.par_recorte).convert("L"), cmap="gray"); b.set_title(f"ENT {Path(r.par_recorte).name}\ncorr {r.corr_recorte:.4f} cos {r.coseno_mobilenet:.3f}", fontsize=7)
    fig.suptitle(titulo); fig.tight_layout(); fig.savefig(AQUI / archivo, dpi=80); plt.close(fig)


orden = pares.sort_values("corr_recorte", ascending=False)
montaje(orden, "pares_top.png", "Pares prueba/entrenamiento con mayor correlación (recorte propio)")
montaje(orden[orden.corr_recorte < 0.99], "pares_bajo_099.png", "Pares justo por debajo de 0.99")
montaje(orden[orden.corr_recorte < 0.98], "pares_bajo_098.png", "Pares justo por debajo de 0.98")
montaje(orden[orden.corr_recorte < 0.95], "pares_bajo_095.png", "Pares justo por debajo de 0.95")
print("Montajes guardados en", AQUI)
