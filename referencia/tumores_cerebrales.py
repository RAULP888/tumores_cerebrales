"""
Proyecto #11 · Clasificación de tumores cerebrales en resonancia magnética
Mapa de Proyectos ML · Diplomado IA Generativa, BI y Ciencia de Datos

Dataset: Brain Tumor MRI Dataset (Kaggle, Masoud Nickparvar)
  7,023 imágenes · 4 clases: glioma, meningioma, notumor, pituitary
  Estructura esperada:
    datos/
      Training/glioma, Training/meningioma, Training/notumor, Training/pituitary
      Testing/glioma,  Testing/meningioma,  Testing/notumor,  Testing/pituitary

Descarga (requiere cuenta de Kaggle y kaggle.json en ~/.kaggle):
  pip install kaggle
  kaggle datasets download -d masoudnickparvar/brain-tumor-mri-dataset -p datos --unzip

Instalación:
  pip install tensorflow opencv-python-headless pillow scikit-learn matplotlib pandas

Uso:
  python tumores_cerebrales.py --datos datos --modelo efficientnet --epocas 12 --epocas-ajuste 8
  python tumores_cerebrales.py --datos datos --modelo resnet50
  python tumores_cerebrales.py --datos datos --modelo cnn          (línea base desde cero)

Qué hace, paso a paso:
  1. Inventario del dataset (conteo por clase y partición, tamaños de imagen).
  2. Detección de duplicados con hash perceptual, dentro y entre Training y Testing.
  3. Preprocesamiento: recorte del contorno del cerebro con OpenCV y redimensionado.
  4. Partición estratificada de validación (15 % de Training).
  5. Entrenamiento en dos fases: cabeza nueva con base congelada y luego ajuste fino.
  6. Evaluación en Testing: exactitud, F1 macro, reporte por clase, matriz de confusión, AUC por clase.
  7. Grad-CAM: mapas de calor que muestran en qué zona se fijó el modelo.
  8. Exportación para Power BI (CSV por caso) y para el dashboard (resultados.json).
  9. Borrador de reporte por caso, siempre marcado como "requiere validación médica".

Aviso: proyecto académico. El modelo no es un dispositivo médico ni sustituye el diagnóstico de un especialista.
"""
import argparse
import hashlib
import json
import os
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image
from sklearn.metrics import (accuracy_score, classification_report, confusion_matrix,
                             f1_score, roc_auc_score)
from sklearn.model_selection import train_test_split

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

CLASES = ["glioma", "meningioma", "notumor", "pituitary"]
NOMBRES_ES = {"glioma": "Glioma", "meningioma": "Meningioma", "notumor": "Sin tumor", "pituitary": "Tumor hipofisario"}
EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
SEMILLA = 42


def fijar_semillas(s=SEMILLA):
    random.seed(s)
    np.random.seed(s)
    tf.random.set_seed(s)


# ---------------------------------------------------------------- 1. Inventario
def listar(datos: Path):
    filas = []
    for particion in ["Training", "Testing"]:
        for clase in CLASES:
            carpeta = datos / particion / clase
            if not carpeta.is_dir():
                raise FileNotFoundError(f"No existe la carpeta {carpeta}. Revisa la estructura del dataset.")
            for f in sorted(carpeta.iterdir()):
                if f.suffix.lower() in EXT:
                    filas.append({"ruta": str(f), "particion": particion, "clase": clase})
    return pd.DataFrame(filas)


def inventario(df: pd.DataFrame):
    tam = []
    for ruta in df.ruta:
        with Image.open(ruta) as im:
            tam.append(im.size)
    df = df.assign(ancho=[t[0] for t in tam], alto=[t[1] for t in tam])
    conteo = df.groupby(["particion", "clase"]).size().unstack(fill_value=0)
    print("\n[1] Inventario por partición y clase")
    print(conteo.to_string())
    print(f"Total de imágenes: {len(df):,}")
    print(f"Tamaños distintos: {df[['ancho', 'alto']].drop_duplicates().shape[0]} · "
          f"más común: {Counter(tam).most_common(1)[0][0]}")
    return df, conteo


# ---------------------------------------------------------------- 2. Duplicados
def hash_promedio(ruta, n=16):
    with Image.open(ruta) as im:
        g = np.asarray(im.convert("L").resize((n, n), Image.Resampling.BILINEAR), dtype=np.float32)
    bits = (g > g.mean()).flatten()
    return hashlib.md5(np.packbits(bits).tobytes()).hexdigest()


def duplicados(df: pd.DataFrame):
    df = df.assign(hash=[hash_promedio(r) for r in df.ruta])
    grupos = df.groupby("hash")
    entre, conflicto, dentro = set(), set(), 0
    for h, g in grupos:
        if len(g) < 2:
            continue
        if g.particion.nunique() > 1:
            entre.add(h)
        if g.clase.nunique() > 1:
            conflicto.add(h)
        dentro += len(g) - 1
    res = {
        "grupos_duplicados": int(sum(1 for _, g in grupos if len(g) > 1)),
        "imagenes_repetidas": int(dentro),
        "test_con_copia_en_train": int(df[(df.particion == "Testing") & df.hash.isin(entre)].shape[0]),
        "hashes_con_etiquetas_distintas": int(len(conflicto)),
    }
    print("\n[2] Duplicados (hash perceptual de 16x16)")
    for k, v in res.items():
        print(f"  {k}: {v}")
    return df, res, entre


# ---------------------------------------------------------------- 3. Preprocesamiento
def recortar_cerebro(img_bgr, margen=0):
    """Recorta el contorno más grande (el cerebro) para quitar el fondo negro sobrante."""
    gris = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gris = cv2.GaussianBlur(gris, (5, 5), 0)
    _, umbral = cv2.threshold(gris, 45, 255, cv2.THRESH_BINARY)
    umbral = cv2.erode(umbral, None, iterations=2)
    umbral = cv2.dilate(umbral, None, iterations=2)
    contornos, _ = cv2.findContours(umbral, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return img_bgr
    c = max(contornos, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(c)
    if w < 20 or h < 20:
        return img_bgr
    y0, y1 = max(0, y - margen), min(img_bgr.shape[0], y + h + margen)
    x0, x1 = max(0, x - margen), min(img_bgr.shape[1], x + w + margen)
    return img_bgr[y0:y1, x0:x1]


def preprocesar(df: pd.DataFrame, destino: Path, tam: int):
    destino.mkdir(parents=True, exist_ok=True)
    nuevas = []
    for fila in df.itertuples():
        salida = destino / fila.particion / fila.clase / (Path(fila.ruta).stem + ".png")
        if not salida.exists():
            salida.parent.mkdir(parents=True, exist_ok=True)
            # np.fromfile + imdecode: funciona con rutas con acentos en Windows (cv2.imread no)
            img = cv2.imdecode(np.fromfile(fila.ruta, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                nuevas.append(None)
                continue
            img = recortar_cerebro(img)
            img = cv2.resize(img, (tam, tam), interpolation=cv2.INTER_AREA)
            cv2.imencode(".png", img)[1].tofile(str(salida))
        nuevas.append(str(salida))
    df = df.assign(procesada=nuevas).dropna(subset=["procesada"])
    print(f"\n[3] Preprocesadas {len(df):,} imágenes a {tam}x{tam} en {destino}")
    return df


# ---------------------------------------------------------------- 4-5. Datos y modelo
def preparar_fn(modelo):
    if modelo == "resnet50":
        return keras.applications.resnet50.preprocess_input
    return lambda x: x  # EfficientNet incluye su propio reescalado; la CNN usa una capa Rescaling


def crear_dataset(rutas, etiquetas, tam, lote, modelo, entrenamiento):
    prep = preparar_fn(modelo)
    aumento = keras.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(0.05),
        layers.RandomZoom(0.10),
        layers.RandomContrast(0.10),
    ], name="aumento")

    def cargar(ruta, y):
        img = tf.io.decode_png(tf.io.read_file(ruta), channels=3)
        img = tf.image.resize(img, (tam, tam))
        return tf.cast(img, tf.float32), y

    ds = tf.data.Dataset.from_tensor_slices((tf.constant(list(rutas), dtype=tf.string),
                                             tf.constant(list(etiquetas), dtype=tf.int32)))
    if entrenamiento:
        ds = ds.shuffle(len(rutas), seed=SEMILLA)
    ds = ds.map(cargar, num_parallel_calls=tf.data.AUTOTUNE)
    if entrenamiento:
        ds = ds.map(lambda x, y: (aumento(x, training=True), y), num_parallel_calls=tf.data.AUTOTUNE)
    ds = ds.map(lambda x, y: (prep(x), y), num_parallel_calls=tf.data.AUTOTUNE)
    return ds.batch(lote).prefetch(tf.data.AUTOTUNE)


def construir_modelo(modelo, tam, pesos):
    entrada = keras.Input(shape=(tam, tam, 3), name="imagen")
    w = None if pesos == "none" else "imagenet"
    if modelo == "efficientnet":
        base = keras.applications.EfficientNetB0(include_top=False, weights=w, input_tensor=entrada)
        capa_cam = "top_activation"
    elif modelo == "resnet50":
        base = keras.applications.ResNet50(include_top=False, weights=w, input_tensor=entrada)
        capa_cam = "conv5_block3_out"
    else:
        base = None
        x = layers.Rescaling(1.0 / 255)(entrada)
        for i, f in enumerate([32, 64, 128, 256]):
            x = layers.Conv2D(f, 3, padding="same", activation="relu")(x)
            x = layers.BatchNormalization()(x)
            x = layers.Conv2D(f, 3, padding="same", activation="relu", name=f"conv_{i}" if i < 3 else "conv_final")(x)
            x = layers.MaxPooling2D()(x)
        capa_cam = "conv_final"
        salida = x
    if base is not None:
        for capa in base.layers:
            capa.trainable = False
        salida = base.output
    x = layers.GlobalAveragePooling2D(name="gap")(salida)
    x = layers.Dropout(0.3)(x)
    x = layers.Dense(256, activation="relu")(x)
    x = layers.Dropout(0.3)(x)
    out = layers.Dense(len(CLASES), activation="softmax", name="probabilidades")(x)
    return keras.Model(entrada, out, name=f"tumores_{modelo}"), base, capa_cam


def pesos_clase(y):
    c = Counter(y)
    total = len(y)
    return {k: total / (len(c) * v) for k, v in c.items()}


def entrenar(model, base, ds_tr, ds_va, y_tr, epocas, epocas_ajuste, capas_ajuste, salida: Path):
    cb = [
        keras.callbacks.EarlyStopping(monitor="val_loss", patience=4, restore_best_weights=True),
        keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.3, patience=2, min_lr=1e-7),
        keras.callbacks.ModelCheckpoint(str(salida / "mejor_modelo.keras"), monitor="val_loss", save_best_only=True),
    ]
    cw = pesos_clase(y_tr)
    model.compile(optimizer=keras.optimizers.Adam(1e-3), loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    print("\n[5a] Fase 1: entrenando la cabeza")
    h1 = model.fit(ds_tr, validation_data=ds_va, epochs=epocas, class_weight=cw, callbacks=cb, verbose=2)
    hist = {k: list(map(float, v)) for k, v in h1.history.items()}

    if base is not None and epocas_ajuste > 0:
        print(f"\n[5b] Fase 2: ajuste fino de las últimas {capas_ajuste} capas de la base")
        for capa in base.layers[-capas_ajuste:]:
            if not isinstance(capa, layers.BatchNormalization):
                capa.trainable = True
        model.compile(optimizer=keras.optimizers.Adam(1e-5), loss="sparse_categorical_crossentropy", metrics=["accuracy"])
        h2 = model.fit(ds_tr, validation_data=ds_va, epochs=epocas_ajuste, class_weight=cw, callbacks=cb, verbose=2)
        for k, v in h2.history.items():
            hist.setdefault(k, []).extend(map(float, v))
    return hist


# ---------------------------------------------------------------- 6. Evaluación
def evaluar(model, ds_te, y_te, salida: Path):
    prob = model.predict(ds_te, verbose=0)
    pred = prob.argmax(1)
    acc = accuracy_score(y_te, pred)
    f1 = f1_score(y_te, pred, average="macro")
    try:
        auc = roc_auc_score(np.eye(len(CLASES))[y_te], prob, average=None)
    except ValueError:
        auc = np.full(len(CLASES), np.nan)
    rep = classification_report(y_te, pred, labels=list(range(len(CLASES))), target_names=CLASES, output_dict=True, zero_division=0)
    cm = confusion_matrix(y_te, pred, labels=list(range(len(CLASES))))
    print("\n[6] Evaluación en Testing")
    print(f"  Exactitud: {acc:.4f} · F1 macro: {f1:.4f}")
    print(classification_report(y_te, pred, labels=list(range(len(CLASES))), target_names=CLASES, zero_division=0))

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(CLASES)), [NOMBRES_ES[c] for c in CLASES], rotation=30, ha="right")
    ax.set_yticks(range(len(CLASES)), [NOMBRES_ES[c] for c in CLASES])
    for i in range(len(CLASES)):
        for j in range(len(CLASES)):
            ax.text(j, i, cm[i, j], ha="center", va="center", color="white" if cm[i, j] > cm.max() / 2 else "black")
    ax.set_xlabel("Predicción")
    ax.set_ylabel("Clase real")
    ax.set_title(f"Matriz de confusión · exactitud {acc:.3f}")
    fig.tight_layout()
    fig.savefig(salida / "matriz_confusion.png", dpi=150)
    plt.close(fig)

    metricas = {
        "exactitud": round(float(acc), 4),
        "f1_macro": round(float(f1), 4),
        "por_clase": {c: {"precision": round(rep[c]["precision"], 4), "recall": round(rep[c]["recall"], 4),
                          "f1": round(rep[c]["f1-score"], 4), "soporte": int(rep[c]["support"]),
                          "auc": None if np.isnan(auc[i]) else round(float(auc[i]), 4)}
                      for i, c in enumerate(CLASES)},
        "matriz_confusion": cm.tolist(),
    }
    return prob, pred, metricas


def graficar_historial(hist, salida: Path):
    fig, axs = plt.subplots(1, 2, figsize=(10, 4))
    for k, ax in zip(["loss", "accuracy"], axs):
        ax.plot(hist.get(k, []), label="entrenamiento")
        ax.plot(hist.get("val_" + k, []), label="validación")
        ax.set_title("Pérdida" if k == "loss" else "Exactitud")
        ax.set_xlabel("Época")
        ax.legend()
    fig.tight_layout()
    fig.savefig(salida / "historial.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- 7. Grad-CAM
def grad_cam(model, capa, img_prep, clase=None):
    grad_model = keras.Model(model.inputs, [model.get_layer(capa).output, model.output])
    x = tf.convert_to_tensor(img_prep[None, ...], dtype=tf.float32)
    with tf.GradientTape() as tape:
        conv, pred = grad_model(x, training=False)
        if clase is None:
            clase = int(tf.argmax(pred[0]))
        objetivo = pred[:, clase]
    grads = tape.gradient(objetivo, conv)
    pesos = tf.reduce_mean(grads, axis=(0, 1, 2))
    mapa = tf.reduce_sum(conv[0] * pesos, axis=-1)
    mapa = tf.maximum(mapa, 0) / (tf.reduce_max(mapa) + 1e-8)
    return mapa.numpy(), clase


def superponer(img_rgb, mapa, alfa=0.4):
    m = cv2.resize(mapa, (img_rgb.shape[1], img_rgb.shape[0]))
    calor = cv2.applyColorMap(np.uint8(255 * m), cv2.COLORMAP_JET)[..., ::-1]
    return np.clip(img_rgb * (1 - alfa) + calor * alfa, 0, 255).astype(np.uint8)


def galeria_gradcam(model, capa, df_te, prob, modelo, tam, salida: Path, por_clase=3):
    prep = preparar_fn(modelo)
    fig, axs = plt.subplots(len(CLASES), por_clase, figsize=(3 * por_clase, 3 * len(CLASES)))
    axs = np.atleast_2d(axs)
    for i, c in enumerate(CLASES):
        sub = df_te[df_te.clase == c].head(por_clase)
        for j in range(por_clase):
            ax = axs[i, j]
            ax.axis("off")
            if j >= len(sub):
                continue
            fila = sub.iloc[j]
            img = np.asarray(Image.open(fila.procesada).convert("RGB").resize((tam, tam)), dtype=np.float32)
            mapa, k = grad_cam(model, capa, np.asarray(prep(img.copy())))
            ax.imshow(superponer(img, mapa))
            ax.set_title(f"Real: {NOMBRES_ES[c]}\nPred: {NOMBRES_ES[CLASES[k]]} ({prob[fila.name, k]:.0%})", fontsize=8)
    fig.suptitle("Grad-CAM · zonas que más influyeron en la predicción", fontsize=11)
    fig.tight_layout()
    fig.savefig(salida / "gradcam.png", dpi=150)
    plt.close(fig)
    print(f"\n[7] Galería Grad-CAM guardada en {salida / 'gradcam.png'}")


# ---------------------------------------------------------------- 8-9. Exportación y reporte
def borrador_reporte(clase_pred, confianza, umbral_revision):
    nombre = NOMBRES_ES[CLASES[clase_pred]]
    if confianza < umbral_revision:
        texto = (f"Hallazgo incierto: el modelo no alcanza la confianza mínima ({confianza:.0%}). "
                 "Se recomienda lectura prioritaria por un radiólogo.")
    elif CLASES[clase_pred] == "notumor":
        texto = f"El modelo no identifica patrones compatibles con tumor (confianza {confianza:.0%})."
    else:
        texto = (f"El modelo identifica patrones compatibles con {nombre.lower()} (confianza {confianza:.0%}). "
                 "Revisar la zona resaltada en el mapa Grad-CAM.")
    return texto + " REQUIERE VALIDACIÓN MÉDICA. Herramienta de apoyo, no diagnóstico."


def exportar(df_te, prob, pred, y_te, metricas, inventario_conteo, dup, hist, args, salida: Path):
    conf = prob.max(1)
    casos = pd.DataFrame({
        "archivo": [Path(r).name for r in df_te.ruta],
        "clase_real": [CLASES[i] for i in y_te],
        "prediccion": [CLASES[i] for i in pred],
        "confianza": conf.round(4),
        "correcto": (pred == np.asarray(y_te)),
        "requiere_revision": conf < args.umbral_revision,
        **{f"p_{c}": prob[:, i].round(4) for i, c in enumerate(CLASES)},
        "borrador_reporte": [borrador_reporte(p, c, args.umbral_revision) for p, c in zip(pred, conf)],
    })
    casos.to_csv(salida / "casos_powerbi.csv", index=False, encoding="utf-8-sig")
    resultados = {
        "modelo": args.modelo,
        "tamano_imagen": args.img,
        "inventario": {p: {c: int(inventario_conteo.loc[p, c]) for c in CLASES} for p in inventario_conteo.index},
        "duplicados": dup,
        "metricas": metricas,
        "casos_en_revision": int(casos.requiere_revision.sum()),
        "umbral_revision": args.umbral_revision,
        "epocas_entrenadas": len(hist.get("loss", [])),
        "historial": hist,
    }
    (salida / "resultados.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[8] Exportado: {salida / 'casos_powerbi.csv'} y {salida / 'resultados.json'}")
    print(f"    Casos que requieren revisión (confianza < {args.umbral_revision:.0%}): {int(casos.requiere_revision.sum())}")


# ---------------------------------------------------------------- Principal
def main():
    ap = argparse.ArgumentParser(description="Clasificación de tumores cerebrales en MRI")
    ap.add_argument("--datos", required=True, help="Carpeta con Training/ y Testing/")
    ap.add_argument("--salida", default="resultados_tumores")
    ap.add_argument("--modelo", choices=["efficientnet", "resnet50", "cnn"], default="efficientnet")
    ap.add_argument("--pesos", choices=["imagenet", "none"], default="imagenet", help="none solo para pruebas")
    ap.add_argument("--img", type=int, default=224)
    ap.add_argument("--lote", type=int, default=32)
    ap.add_argument("--epocas", type=int, default=12)
    ap.add_argument("--epocas-ajuste", type=int, default=8)
    ap.add_argument("--capas-ajuste", type=int, default=40)
    ap.add_argument("--umbral-revision", type=float, default=0.80)
    ap.add_argument("--quitar-duplicados", action="store_true", help="Quita de Testing las imágenes que también están en Training")
    ap.add_argument("--gradcam-por-clase", type=int, default=3)
    args = ap.parse_args()

    fijar_semillas()
    inicio = time.time()
    datos, salida = Path(args.datos), Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    df = listar(datos)
    df, conteo = inventario(df)
    df, dup, hashes_entre = duplicados(df)
    if args.quitar_duplicados:
        antes = len(df)
        df = df[~((df.particion == "Testing") & df.hash.isin(hashes_entre))]
        print(f"  Se quitaron {antes - len(df)} imágenes de Testing con copia en Training")

    df = preprocesar(df, salida / "procesadas", args.img)
    mapa = {c: i for i, c in enumerate(CLASES)}
    df["y"] = df.clase.map(mapa)

    entren = df[df.particion == "Training"]
    tr, va = train_test_split(entren, test_size=0.15, stratify=entren.y, random_state=SEMILLA)
    te = df[df.particion == "Testing"].reset_index(drop=True)
    for nombre, parte in [("entrenamiento", tr), ("validación", va), ("prueba", te)]:
        if parte.empty:
            raise SystemExit(f"La partición de {nombre} quedó vacía. Revisa la carpeta de datos o la opción --quitar-duplicados.")
    print(f"\n[4] Partición: entrenamiento {len(tr):,} · validación {len(va):,} · prueba {len(te):,}")

    ds_tr = crear_dataset(tr.procesada, tr.y, args.img, args.lote, args.modelo, True)
    ds_va = crear_dataset(va.procesada, va.y, args.img, args.lote, args.modelo, False)
    ds_te = crear_dataset(te.procesada, te.y, args.img, args.lote, args.modelo, False)

    model, base, capa_cam = construir_modelo(args.modelo, args.img, args.pesos)
    print(f"\n[5] Modelo {model.name}: {model.count_params():,} parámetros")
    hist = entrenar(model, base, ds_tr, ds_va, tr.y.tolist(), args.epocas, args.epocas_ajuste, args.capas_ajuste, salida)
    graficar_historial(hist, salida)
    model.save(salida / "modelo_final.keras")

    prob, pred, metricas = evaluar(model, ds_te, te.y.to_numpy(), salida)
    galeria_gradcam(model, capa_cam, te, prob, args.modelo, args.img, salida, args.gradcam_por_clase)
    exportar(te, prob, pred, te.y.to_numpy(), metricas, conteo, dup, hist, args, salida)
    print(f"\nListo en {(time.time() - inicio) / 60:.1f} min. Resultados en {salida.resolve()}")


if __name__ == "__main__":
    main()
