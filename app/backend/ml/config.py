"""Configuración compartida: rutas, constantes, semillas y versiones."""
import os
import platform
import random
from pathlib import Path

# Raíz del proyecto calculada desde este archivo: app/backend/ml/config.py -> 3 niveles arriba.
RAIZ = Path(__file__).resolve().parents[3]
DATOS = RAIZ / "datos"
RASGOS = DATOS / "rasgos"
MANIFIESTO = DATOS / "manifiesto.csv"
DUPLICADOS = DATOS / "duplicados.csv"
RESULTADOS = RAIZ / "resultados"
MODELOS = RAIZ / "app" / "modelos"

SEMILLA = 42
TAM = 160
CLASES = ["glioma", "meningioma", "notumor", "pituitary"]
TIPOS_TUMOR = ["glioma", "meningioma", "pituitary"]
NOMBRES_ES = {"glioma": "Glioma", "meningioma": "Meningioma",
              "notumor": "Sin tumor", "pituitary": "Tumor hipofisario"}
EXTENSIONES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
SENSIBILIDAD_OBJETIVO = 0.98
N_PLIEGUES = 5
AVISO = "Resultado de apoyo. No sustituye el diagnóstico de un médico especialista."


def fijar_semillas(semilla=SEMILLA):
    """Fija las semillas de Python, NumPy y TensorFlow/Keras."""
    import numpy as np
    os.environ["PYTHONHASHSEED"] = str(semilla)
    random.seed(semilla)
    np.random.seed(semilla)
    try:
        import keras
        keras.utils.set_random_seed(semilla)
    except ImportError:  # permite usar la parte clásica sin TensorFlow
        pass


def versiones():
    """Devuelve un dict con las versiones de las librerías principales, para registrarlas."""
    import numpy
    import sklearn
    v = {"python": platform.python_version(), "numpy": numpy.__version__, "sklearn": sklearn.__version__}
    try:
        import keras
        import tensorflow
        v["tensorflow"] = tensorflow.__version__
        v["keras"] = keras.__version__
    except ImportError:
        v["tensorflow"] = None
        v["keras"] = None
    try:
        import cv2
        import pandas
        v["opencv"] = cv2.__version__
        v["pandas"] = pandas.__version__
    except ImportError:
        pass
    return v
