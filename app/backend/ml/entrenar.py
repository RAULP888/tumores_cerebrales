"""Entrenamiento reutilizable: cabeza, validación cruzada de la cabeza y ajuste fino.

Las funciones no leen ni escriben rutas del proyecto por su cuenta: reciben arreglos y
devuelven el modelo y el historial. Las usan los notebooks y el reentrenamiento del backend
(que las llama en un proceso aparte).

Convenciones
- y_bin: 1 = tumor, 0 = sin tumor.
- y_tipo: índice en TIPOS_TUMOR (0 glioma, 1 meningioma, 2 pituitary) o -1 si no hay tumor.
  Los casos con -1 pesan 0 en la pérdida de la salida "tipo".
- Callbacks: EarlyStopping, ReduceLROnPlateau y ModelCheckpoint vigilan `val_loss`, la
  pérdida TOTAL de validación (tumor ponderada por clase + 0.5 * tipo). Al terminar se
  cargan los pesos de la mejor época (la de menor `val_loss`).
- Historial devuelto: dict con listas por época "loss", "accuracy", "val_loss",
  "val_accuracy" y "learning_rate". "accuracy" es la exactitud de la salida "tumor" con
  umbral 0.5. También trae "cancelado" (bool).
- callback_progreso(etapa, epoca, registros): se llama al final de cada época con
  etapa en {"cabeza", "ajuste_fino"}, la época (desde 1) y un dict con los cinco valores
  de esa época. Si devuelve False, el entrenamiento se cancela al terminar esa época.
"""
import tempfile
from pathlib import Path

import cv2
import keras
import numpy as np
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold, train_test_split

from . import red
from .config import CLASES, N_PLIEGUES, SEMILLA, TIPOS_TUMOR
from .metricas import metricas_binarias

CLAVES_HISTORIAL = ["loss", "accuracy", "val_loss", "val_accuracy", "learning_rate"]


def etiquetas_de_clases(clases):
    """Convierte nombres de clase en (y_bin, y_tipo) según las convenciones del módulo."""
    clases = list(clases)
    y_bin = np.array([0 if c == "notumor" else 1 for c in clases], dtype=np.int32)
    y_tipo = np.array([TIPOS_TUMOR.index(c) if c in TIPOS_TUMOR else -1 for c in clases], dtype=np.int32)
    return y_bin, y_tipo


def _objetivos(y_bin, y_tipo):
    return {"tumor": np.asarray(y_bin, dtype=np.float32).reshape(-1, 1),
            "tipo": np.asarray(y_tipo, dtype=np.int32).reshape(-1, 1)}


class _Progreso(keras.callbacks.Callback):
    """Guarda el historial por época, avisa el progreso y permite cancelar."""

    def __init__(self, etapa, callback_progreso=None):
        super().__init__()
        self.etapa = etapa
        self.callback_progreso = callback_progreso
        self.historial = {k: [] for k in CLAVES_HISTORIAL}
        self.cancelado = False
        self._tasa = None

    def on_epoch_begin(self, epoch, logs=None):
        self._tasa = float(keras.ops.convert_to_numpy(self.model.optimizer.learning_rate))

    def on_epoch_end(self, epoch, logs=None):
        logs = logs or {}

        def valor(*claves):
            for c in claves:
                if c in logs:
                    return float(logs[c])
            return float("nan")

        registros = {
            "loss": valor("loss"),
            "accuracy": valor("tumor_accuracy", "accuracy"),
            "val_loss": valor("val_loss"),
            "val_accuracy": valor("val_tumor_accuracy", "val_accuracy"),
            "learning_rate": self._tasa,
        }
        for k in CLAVES_HISTORIAL:
            self.historial[k].append(registros[k])
        if self.callback_progreso is not None:
            if self.callback_progreso(self.etapa, epoch + 1, dict(registros)) is False:
                self.cancelado = True
                self.model.stop_training = True


def _callbacks(etapa, paciencia, ruta_checkpoint, callback_progreso):
    progreso = _Progreso(etapa, callback_progreso)
    lista = [
        keras.callbacks.EarlyStopping(monitor="val_loss", patience=paciencia, restore_best_weights=True),
        keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.3, patience=max(1, paciencia // 2),
                                          min_lr=1e-7),
        keras.callbacks.ModelCheckpoint(str(ruta_checkpoint), monitor="val_loss", save_best_only=True,
                                        save_weights_only=True),
        progreso,
    ]
    return lista, progreso


def _ruta_checkpoint(ruta_checkpoint, carpeta_temporal):
    if ruta_checkpoint is None:
        return Path(carpeta_temporal) / "mejor.weights.h5"
    ruta = Path(ruta_checkpoint)
    if not ruta.name.endswith(".weights.h5"):
        ruta = ruta.with_name(ruta.name + ".weights.h5")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    return ruta


def entrenar_cabeza(X_tr, y_bin_tr, y_tipo_tr, X_va, y_bin_va, y_tipo_va, epocas_max=60, tasa=1e-3,
                    lote=64, callback_progreso=None, paciencia=8, ruta_checkpoint=None, semilla=SEMILLA,
                    verbose=0):
    """Entrena la cabeza sobre rasgos ya extraídos de MobileNetV2.

    Devuelve (modelo, historial). El modelo queda con los pesos de la mejor época.
    La salida "tumor" usa pesos de clase calculados con y_bin_tr; la pérdida de validación
    usa los mismos pesos para que ambas curvas sean comparables.
    """
    if semilla is not None:
        keras.utils.set_random_seed(int(semilla))
    X_tr = np.asarray(X_tr, dtype=np.float32)
    X_va = np.asarray(X_va, dtype=np.float32)
    modelo = red.construir_cabeza(X_tr.shape[1])
    red.compilar(modelo, tasa, red.pesos_clase(y_bin_tr))
    with tempfile.TemporaryDirectory() as tmp:
        ruta = _ruta_checkpoint(ruta_checkpoint, tmp)
        cbs, progreso = _callbacks("cabeza", paciencia, ruta, callback_progreso)
        modelo.fit(X_tr, _objetivos(y_bin_tr, y_tipo_tr),
                   validation_data=(X_va, _objetivos(y_bin_va, y_tipo_va)),
                   epochs=int(epocas_max), batch_size=int(lote), shuffle=True, callbacks=cbs, verbose=verbose)
        if ruta.exists():
            modelo.load_weights(str(ruta))
    historial = dict(progreso.historial)
    historial["cancelado"] = progreso.cancelado
    return modelo, historial


def predecir_cabeza(modelo, X, lote=512):
    """Predice con la cabeza. Devuelve (prob_tumor (n,), prob_tipo (n, 3))."""
    s = modelo.predict(np.asarray(X, dtype=np.float32), batch_size=lote, verbose=0)
    return np.asarray(s["tumor"]).ravel().astype(float), np.asarray(s["tipo"]).astype(float)


def predecir_completo(modelo, imagenes_rgb, lote=64):
    """Predice con el modelo completo sobre uint8 (n, 160, 160, 3). Devuelve (prob_tumor, prob_tipo)."""
    imagenes_rgb = np.asarray(imagenes_rgb)
    p_tumor, p_tipo = [], []
    for i in range(0, len(imagenes_rgb), 512):
        s = modelo.predict(imagenes_rgb[i:i + 512].astype(np.float32), batch_size=lote, verbose=0)
        p_tumor.append(np.asarray(s["tumor"]).ravel())
        p_tipo.append(np.asarray(s["tipo"]))
    return np.concatenate(p_tumor).astype(float), np.concatenate(p_tipo).astype(float)


def pliegues_estratificados(estratos, n_pliegues=N_PLIEGUES, semilla=SEMILLA, grupos=None):
    """Pliegues estratificados con barajado. Devuelve una lista de (indices_entrenamiento, indices_validacion).

    - Sin `grupos`: StratifiedKFold.
    - Con `grupos` (por ejemplo la columna grupo_similitud del manifiesto): StratifiedGroupKFold,
      que nunca reparte un mismo grupo entre dos pliegues. Así las imágenes muy parecidas
      (la misma toma con otro contraste, cortes casi idénticos) quedan siempre del mismo lado.

    Con los mismos datos y la misma semilla siempre da los mismos pliegues: así los modelos
    clásicos y la red se comparan exactamente sobre las mismas particiones.
    """
    estratos = np.asarray(estratos)
    if grupos is None:
        skf = StratifiedKFold(n_splits=n_pliegues, shuffle=True, random_state=semilla)
        return [(tr, va) for tr, va in skf.split(np.zeros(len(estratos)), estratos)]
    sgkf = StratifiedGroupKFold(n_splits=n_pliegues, shuffle=True, random_state=semilla)
    return [(tr, va) for tr, va in sgkf.split(np.zeros(len(estratos)), estratos, groups=np.asarray(grupos))]


def apartar_validacion(estratos, fraccion=0.15, semilla=SEMILLA, grupos=None):
    """Aparta una validación estratificada. Devuelve (indices_entrenamiento, indices_validacion).

    - Sin `grupos`: train_test_split estratificado con la fracción exacta.
    - Con `grupos`: se toma una de las round(1 / fraccion) partes de StratifiedGroupKFold
      (con fraccion=0.15 es 1 de 7 partes, cerca de 14 %), sin repartir ningún grupo.
    """
    estratos = np.asarray(estratos)
    if grupos is None:
        tr, va = train_test_split(np.arange(len(estratos)), test_size=fraccion, stratify=estratos,
                                  random_state=semilla)
        return np.sort(tr), np.sort(va)
    partes = max(2, int(round(1.0 / fraccion)))
    return pliegues_estratificados(estratos, partes, semilla, grupos)[0]


def kfold_cabeza(X, y_bin, y_tipo, estratos=None, n_pliegues=N_PLIEGUES, fraccion_val=0.15, epocas_max=60,
                 tasa=1e-3, lote=64, paciencia=8, semilla=SEMILLA, umbral=0.5, callback_progreso=None,
                 verbose=0, grupos=None):
    """Validación cruzada estratificada de la cabeza sobre rasgos congelados.

    En cada pliegue, del bloque de entrenamiento se aparta `fraccion_val` para la detención
    temprana; el bloque fuera de pliegue no participa en nada del entrenamiento y solo se
    usa para predecir.

    Si se pasa `grupos` (un identificador por imagen, p. ej. grupo_similitud), tanto los
    pliegues como la validación interna se hacen por grupo: ningún grupo queda repartido.

    Devuelve un dict con:
    - "pliegues": lista de dicts por pliegue (pliegue, umbral, métricas de `metricas_binarias`
      al umbral dado, exactitud_tipo, mejor_epoca, epocas)
    - "prob_oof": probabilidad de tumor fuera de pliegue (n,)
    - "prob_tipo_oof": probabilidades de tipo fuera de pliegue (n, 3)
    - "pliegue_oof": número de pliegue (1..n_pliegues) de cada fila
    - "historiales": lista con el historial de cada pliegue
    - "cancelado": bool
    """
    X = np.asarray(X, dtype=np.float32)
    y_bin = np.asarray(y_bin).astype(int)
    y_tipo = np.asarray(y_tipo).astype(int)
    estratos = np.where(y_tipo >= 0, y_tipo + 1, 0) if estratos is None else np.asarray(estratos)
    prob_oof = np.full(len(X), np.nan)
    prob_tipo_oof = np.full((len(X), len(TIPOS_TUMOR)), np.nan)
    pliegue_oof = np.zeros(len(X), dtype=int)
    filas, historiales, cancelado = [], [], False
    grupos = None if grupos is None else np.asarray(grupos)
    for k, (i_tr, i_va) in enumerate(pliegues_estratificados(estratos, n_pliegues, semilla, grupos), 1):
        rel_ent, rel_det = apartar_validacion(estratos[i_tr], fraccion_val, semilla,
                                              None if grupos is None else grupos[i_tr])
        i_ent, i_det = i_tr[rel_ent], i_tr[rel_det]
        modelo, hist = entrenar_cabeza(
            X[i_ent], y_bin[i_ent], y_tipo[i_ent], X[i_det], y_bin[i_det], y_tipo[i_det],
            epocas_max=epocas_max, tasa=tasa, lote=lote, paciencia=paciencia, semilla=semilla + k,
            callback_progreso=callback_progreso, verbose=verbose)
        p, pt = predecir_cabeza(modelo, X[i_va])
        prob_oof[i_va], prob_tipo_oof[i_va], pliegue_oof[i_va] = p, pt, k
        con_tumor = y_tipo[i_va] >= 0
        fila = {"pliegue": k, "umbral": float(umbral), **metricas_binarias(y_bin[i_va], p, umbral)}
        fila["exactitud_tipo"] = float((pt[con_tumor].argmax(1) == y_tipo[i_va][con_tumor]).mean())
        fila["mejor_epoca"] = int(np.argmin(hist["val_loss"])) + 1
        fila["epocas"] = len(hist["val_loss"])
        filas.append(fila)
        historiales.append(hist)
        if hist.get("cancelado"):
            cancelado = True
            break
    return {"pliegues": filas, "prob_oof": prob_oof, "prob_tipo_oof": prob_tipo_oof,
            "pliegue_oof": pliegue_oof, "historiales": historiales, "cancelado": cancelado}


# ------------------------------------------------------------------ ajuste fino
def aumentar(img, rng):
    """Aumento ligero de una imagen uint8: espejo horizontal, giro, zoom, desplazamiento y brillo leves."""
    alto, ancho = img.shape[:2]
    if rng.random() < 0.5:
        img = img[:, ::-1]
    angulo = rng.uniform(-10, 10)
    escala = rng.uniform(0.92, 1.08)
    m = cv2.getRotationMatrix2D((ancho / 2, alto / 2), angulo, escala)
    m[0, 2] += rng.uniform(-0.06, 0.06) * ancho
    m[1, 2] += rng.uniform(-0.06, 0.06) * alto
    img = cv2.warpAffine(np.ascontiguousarray(img), m, (ancho, alto), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return np.clip(img.astype(np.float32) * rng.uniform(0.9, 1.1), 0, 255)


class _Secuencia(keras.utils.PyDataset):
    """Lotes de imágenes en memoria (uint8) con aumento opcional y barajado por época."""

    def __init__(self, X, y_bin, y_tipo, lote, aumento, semilla):
        super().__init__()
        self.X, self.lote, self.aumento = X, int(lote), aumento
        self.y = _objetivos(y_bin, y_tipo)
        self.rng = np.random.default_rng(semilla)
        self.orden = self.rng.permutation(len(X))

    def __len__(self):
        return int(np.ceil(len(self.X) / self.lote))

    def __getitem__(self, i):
        idx = self.orden[i * self.lote:(i + 1) * self.lote]
        if self.aumento:
            x = np.stack([aumentar(self.X[j], self.rng) for j in idx]).astype(np.float32)
        else:
            x = self.X[idx].astype(np.float32)
        return x, {k: v[idx] for k, v in self.y.items()}

    def on_epoch_end(self):
        self.orden = self.rng.permutation(len(self.X))


def ajuste_fino(modelo_completo, X_tr, y_bin_tr, y_tipo_tr, X_va, y_bin_va, y_tipo_va, capas=30, tasa=1e-5,
                epocas_max=8, lote=32, paciencia=3, aumento=True, callback_progreso=None,
                ruta_checkpoint=None, semilla=SEMILLA, verbose=0):
    """Ajuste fino de las últimas `capas` capas de MobileNetV2 con tasa baja.

    - X_tr y X_va son imágenes ya preparadas, uint8 (n, 160, 160, 3), cargadas en memoria.
    - Las capas BatchNormalization se quedan congeladas (siguen en modo de inferencia).
    - Mismos callbacks que la cabeza, vigilando `val_loss`.

    Devuelve (modelo, historial). El modelo queda con los pesos de la mejor época del
    ajuste fino. El historial trae además "val_loss_inicial" y "val_accuracy_inicial"
    (validación ANTES del ajuste, es decir, de la cabeza sola) y "capas_descongeladas",
    para que quien llama decida si el ajuste mejoró o no.
    """
    if semilla is not None:
        keras.utils.set_random_seed(int(semilla))
    base = red.capas_base(modelo_completo)
    for capa in base:
        capa.trainable = False
    descongeladas = 0
    for capa in base[-int(capas):] if capas else []:
        if not isinstance(capa, keras.layers.BatchNormalization):
            capa.trainable = True
            descongeladas += 1
    red.compilar(modelo_completo, tasa, red.pesos_clase(y_bin_tr))

    X_va_f = np.asarray(X_va).astype(np.float32)
    y_va = _objetivos(y_bin_va, y_tipo_va)
    inicial = modelo_completo.evaluate(X_va_f, y_va, batch_size=64, verbose=0, return_dict=True)
    datos = _Secuencia(np.asarray(X_tr), y_bin_tr, y_tipo_tr, lote, aumento, semilla)
    with tempfile.TemporaryDirectory() as tmp:
        ruta = _ruta_checkpoint(ruta_checkpoint, tmp)
        cbs, progreso = _callbacks("ajuste_fino", paciencia, ruta, callback_progreso)
        modelo_completo.fit(datos, validation_data=(X_va_f, y_va), validation_batch_size=64,
                            epochs=int(epocas_max), callbacks=cbs, verbose=verbose)
        if ruta.exists():
            modelo_completo.load_weights(str(ruta))
    historial = dict(progreso.historial)
    historial["cancelado"] = progreso.cancelado
    historial["val_loss_inicial"] = float(inicial["loss"])
    historial["val_accuracy_inicial"] = float(inicial.get("tumor_accuracy", inicial.get("accuracy", float("nan"))))
    historial["capas_descongeladas"] = descongeladas
    return modelo_completo, historial


def exportar_limpio(modelo_completo, ruta_keras):
    """Guarda el modelo completo sin optimizador ni pérdidas (solo arquitectura y pesos).

    Así `keras.models.load_model(ruta, compile=False)` lo carga sin funciones a la medida.
    """
    limpio = red.construir_completo(pesos=None)
    limpio.set_weights(modelo_completo.get_weights())
    Path(ruta_keras).parent.mkdir(parents=True, exist_ok=True)
    limpio.save(str(ruta_keras))
    return limpio
