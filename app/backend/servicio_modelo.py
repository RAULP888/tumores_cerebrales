"""Modelo de producción en memoria.

Se carga una vez al arrancar y se recarga al aprobar o revertir. Un candado evita que
TensorFlow corra predicciones en paralelo (y que se cambie el modelo a mitad de una predicción).
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import catalogo, db

log = logging.getLogger("tumores.modelo")


class ServicioModelo:
    """Todo el trabajo de TensorFlow (carga, calentamiento y predicción) corre en UN solo hilo
    dedicado: así nunca hay predicciones en paralelo y TensorFlow no vuelve a calentarse en cada
    hilo del servidor (eso hacía lentas las primeras predicciones)."""

    def __init__(self):
        self._hilo_tf = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tensorflow")
        self.candado = threading.RLock()
        self.modelo = None
        self.info = None
        self.modelo_id = None
        self.version = None
        self.nombre = None
        self.umbral = None
        self.error = None

    @property
    def cargado(self):
        return self.modelo is not None

    def cargar_produccion(self):
        """Carga la red con estado 'produccion' de dim_modelo. Devuelve True si quedó cargada."""
        return self._hilo_tf.submit(self._cargar_produccion).result()

    def _cargar_produccion(self):
        from .ml.inferencia import cargar_modelo, predecir
        with db.motor().connect() as c:
            fila = catalogo.modelo_produccion(c)
        if fila is None:
            with self.candado:
                self.modelo, self.info, self.modelo_id, self.version = None, None, None, None
                self.error = "No hay un modelo en producción registrado."
            return False
        carpeta = catalogo.carpeta(fila["version"])
        try:
            modelo, info = cargar_modelo(carpeta)
            # Calentamiento: la primera llamada construye los grafos (incluido el de Grad-CAM).
            prueba = np.random.default_rng(0).integers(0, 255, (256, 256, 3), dtype=np.uint8)
            for _ in range(3):
                predecir(modelo, info, prueba, con_gradcam=True)
        except Exception as e:  # noqa: BLE001 - se informa en /api/estado
            log.exception("No se pudo cargar el modelo %s", fila["version"])
            with self.candado:
                self.modelo = None
                self.error = f"No se pudo cargar el modelo {fila['version']}: {type(e).__name__}"
            return False
        with self.candado:
            self.modelo, self.info = modelo, info
            self.modelo_id, self.version = int(fila["modelo_id"]), fila["version"]
            self.nombre = fila["nombre"]
            self.umbral = float(fila["umbral"] if fila["umbral"] is not None else info.get("umbral", 0.5))
            self.error = None
        log.info("Modelo en producción: %s (umbral %.4f)", self.version, self.umbral)
        return True

    def fijar_umbral(self, valor):
        with self.candado:
            self.umbral = float(valor)

    def predecir(self, img_bgr):
        """Predicción con Grad-CAM. Devuelve (resultado, modelo_id, version)."""
        return self._hilo_tf.submit(self._predecir, img_bgr).result()

    def _predecir(self, img_bgr):
        from .ml.inferencia import predecir
        with self.candado:
            if self.modelo is None:
                raise RuntimeError("El modelo no está cargado.")
            r = predecir(self.modelo, self.info, img_bgr, con_gradcam=True, umbral=self.umbral)
            return r, self.modelo_id, self.version

    def estado(self):
        return {"cargado": self.cargado, "version": self.version, "nombre": self.nombre,
                "umbral": self.umbral}


servicio = ServicioModelo()
