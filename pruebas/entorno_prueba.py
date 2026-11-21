"""Entorno temporal compartido por las pruebas (base SQLite, imágenes y modelos en una carpeta temporal).

Si otra prueba ya importó la configuración (p. ej. test_api.py en la misma corrida de pytest),
se reutiliza su entorno temporal. La clave de la API se deja SIEMPRE vacía: las pruebas nunca
llaman a la API real ni leen la clave del archivo .env.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def preparar():
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    if "app.backend.config" in sys.modules:
        return
    tmp = Path(tempfile.mkdtemp(prefix="ts_pruebas_"))
    os.environ["TS_DB_RUTA"] = str(tmp / "prueba.db")
    os.environ["TS_MEDIA_DIR"] = str(tmp / "media")
    os.environ["TS_MODELOS_DIR"] = str(tmp / "modelos")
    os.environ["TS_REGISTROS_DIR"] = str(tmp / "registros")
    os.environ["DB_MODO"] = "local"
    os.environ["ANTHROPIC_API_KEY"] = ""
    destino = tmp / "modelos" / "v001"
    destino.mkdir(parents=True)
    for archivo in (RAIZ / "app" / "modelos" / "v001").iterdir():
        if archivo.suffix in (".keras", ".json", ".npz") or archivo.name.startswith("curvas"):
            shutil.copy2(archivo, destino / archivo.name)


def cargar_base():
    """Esquema, carga inicial y usuarios de demostración (idempotente)."""
    import runpy
    from app.backend import carga
    carga.cargar_todo()
    runpy.run_path(str(RAIZ / "scripts" / "crear_usuarios_demo.py"))["crear"]()
