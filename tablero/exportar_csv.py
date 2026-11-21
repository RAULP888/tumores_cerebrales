"""Exporta a CSV las tablas y vistas del modelo estrella para Power BI (plan B sin Fabric).

Uso (desde la raíz del proyecto):
    .venv\\Scripts\\python.exe tablero\\exportar_csv.py
    .venv\\Scripts\\python.exe tablero\\exportar_csv.py --db otra\\ruta\\tumores.db

- Abre la base SQLite local **solo en modo lectura** (no modifica nada).
- Escribe un archivo por tabla o vista en tablero/csv/, en UTF-8 con BOM (Power BI y Excel
  reconocen así los acentos), separado por comas y con encabezados.
- Las columnas lógicas (0/1 en SQLite) se escriben como TRUE/FALSE para que Power BI las
  detecte como verdadero/falso, igual que los BIT de SQL Server.
- No exporta `usuarios` (tiene el hash de la contraseña) ni `sesiones`. De `dim_paciente` se
  omite `identificador` y de `hecho_prediccion` se omiten las rutas de las imágenes: el tablero
  no muestra identificadores de paciente.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
DB_POR_OMISION = RAIZ / "app" / "almacen" / "tumores.db"
SALIDA = RAIZ / "tablero" / "csv"

# nombre del archivo -> consulta. Solo SELECT con columnas explícitas.
EXPORTAR = {
    # ---- modelo estrella
    "hecho_prediccion": """
        SELECT prediccion_id, paciente_id, fecha_id, usuario_id, modelo_id, diagnostico_predicho_id,
               diagnostico_confirmado_id, origen, probabilidad_tumor, umbral, tipo_probable,
               probabilidad_tipo, de_acuerdo, tiempo_respuesta_ms, creado_en
        FROM hecho_prediccion""",
    "dim_paciente": "SELECT paciente_id, edad, grupo_edad, sexo FROM dim_paciente",
    "dim_fecha": "SELECT fecha_id, fecha, anio, mes, nombre_mes, semana, dia_semana FROM dim_fecha",
    "dim_usuario": "SELECT usuario_id, usuario, rol, activo FROM dim_usuario",
    "dim_modelo": """
        SELECT modelo_id, nombre, tipo, version, estado, umbral, sensibilidad, especificidad, f1, auc,
               origen_metricas, entrenamiento_id, aprobado_en, creado_en FROM vw_modelos""",
    "dim_diagnostico": "SELECT diagnostico_id, clave, nombre, es_tumor FROM dim_diagnostico",
    # ---- vistas de lectura (operación y alternativa plana)
    "vw_predicciones": "SELECT * FROM vw_predicciones",
    "vw_bitacora": "SELECT * FROM vw_bitacora",
    "vw_entrenamientos": "SELECT * FROM vw_entrenamientos",
    "vw_metricas_pliegue": "SELECT * FROM vw_metricas_pliegue",
    "vw_historial_epocas": "SELECT * FROM vw_historial_epocas",
}

COLUMNAS_LOGICAS = {"activo", "es_tumor", "de_acuerdo", "exito", "predicho_tumor", "confirmado_tumor"}
COLUMNAS_ENTERAS = {"edad", "anio", "mes", "semana", "pliegue", "vp", "vn", "fp", "fn", "epoca", "epocas_max",
                    "epoca_actual", "mejor_epoca", "acierto", "falso_negativo", "falso_positivo"}


def a_logico(serie):
    """0/1 -> FALSE/TRUE; los nulos se quedan vacíos."""
    return serie.map(lambda v: "" if pd.isna(v) else ("TRUE" if int(v) == 1 else "FALSE"))


def exportar(ruta_db):
    if not ruta_db.exists():
        print(f"[ERROR] No existe la base {ruta_db}")
        sys.exit(1)
    SALIDA.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(f"file:{ruta_db.resolve().as_posix()}?mode=ro", uri=True)
    try:
        for nombre, consulta in EXPORTAR.items():
            df = pd.read_sql_query(consulta, conexion)
            for col in df.columns:
                if col in COLUMNAS_LOGICAS:
                    df[col] = a_logico(df[col])
                elif col in COLUMNAS_ENTERAS or col.endswith("_id"):
                    # Enteros con nulos: sin esto pandas los escribe como 1.0
                    df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
            destino = SALIDA / f"{nombre}.csv"
            df.to_csv(destino, index=False, encoding="utf-8-sig")
            print(f"  {destino.relative_to(RAIZ)}: {len(df):,} filas, {len(df.columns)} columnas")
    finally:
        conexion.close()
    print("Exportación terminada (la base se abrió solo en modo lectura).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exporta el modelo estrella a CSV para Power BI")
    parser.add_argument("--db", type=Path, default=DB_POR_OMISION, help="ruta del archivo SQLite")
    exportar(parser.parse_args().db)
