"""Carga inicial de la base (idempotente).

Uso: .venv\\Scripts\\python.exe sql/02_cargar_datos.py

Crea el esquema si falta y carga dim_diagnostico, dim_fecha, dim_modelo (4 clásicos como
'referencia' y la red v001), los resultados de PRUEBA de los 5 modelos en hecho_prediccion
(origen='prueba') y la corrida original de v001 (entrenamientos, historial_epocas y
metricas_pliegue). Se puede correr varias veces sin duplicar. Usa DB_MODO del archivo .env.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.backend import config  # noqa: E402
from app.backend.carga import cargar_todo  # noqa: E402


def main():
    print(f"Base: {config.DB_MODO}" + (f" ({config.DB_RUTA})" if config.DB_MODO == "local" else ""))
    resumen = cargar_todo()
    for clave, valor in resumen.items():
        print(f"  {clave}: {valor}")
    print("Carga terminada.")


if __name__ == "__main__":
    main()
