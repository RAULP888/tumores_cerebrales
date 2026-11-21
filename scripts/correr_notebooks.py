"""Ejecuta los notebooks 01 a 04 en orden y guarda sus salidas dentro de cada notebook.

Uso (desde la raíz del proyecto):
    .venv\\Scripts\\python.exe scripts\\correr_notebooks.py
    .venv\\Scripts\\python.exe scripts\\correr_notebooks.py 03_modelos_ml 04_red_keras   (solo algunos)

Se detiene y termina con código de error si algún notebook falla.
"""
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NOTEBOOKS = ["01_eda", "02_rasgos", "03_modelos_ml", "04_red_keras"]
KERNEL = "tumores"


def correr(nombre):
    ruta = RAIZ / "notebooks" / f"{nombre}.ipynb"
    if not ruta.exists():
        print(f"[ERROR] No existe {ruta}")
        return False
    print(f"\n=== {nombre} ===", flush=True)
    inicio = time.time()
    orden = [sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace",
             f"--ExecutePreprocessor.kernel_name={KERNEL}", "--ExecutePreprocessor.timeout=-1", str(ruta)]
    resultado = subprocess.run(orden, cwd=str(RAIZ / "notebooks"))
    minutos = (time.time() - inicio) / 60
    if resultado.returncode != 0:
        print(f"[ERROR] {nombre} falló después de {minutos:.1f} min (código {resultado.returncode}).", flush=True)
        return False
    print(f"[OK] {nombre} terminó en {minutos:.1f} min.", flush=True)
    return True


def main():
    elegidos = [a.replace(".ipynb", "") for a in sys.argv[1:]] or NOTEBOOKS
    inicio = time.time()
    for nombre in elegidos:
        if not correr(nombre):
            sys.exit(1)
    print(f"\nTodos los notebooks terminaron sin errores en {(time.time() - inicio) / 60:.1f} min.")


if __name__ == "__main__":
    main()
