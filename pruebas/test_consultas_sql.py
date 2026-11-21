"""Ejecuta cada consulta de sql/03_consultas.sql contra una base cargada y compara con pandas.

Uso: .venv\\Scripts\\python.exe -m pytest pruebas/test_consultas_sql.py -q
"""
import re
import sqlite3

import pandas as pd
import pytest
import sqlglot

from entorno_prueba import RAIZ, cargar_base, preparar

preparar()
from app.backend import config  # noqa: E402
from app.backend.tablas import VISTAS  # noqa: E402

ARCHIVO = RAIZ / "sql" / "03_consultas.sql"
NOMBRE_RED = "Red Keras (MobileNetV2)"


def leer_consultas():
    """{numero: (titulo, sql)} a partir de las marcas '-- @consulta N: título'."""
    texto = ARCHIVO.read_text(encoding="utf-8")
    partes = re.split(r"^-- @consulta (\d+): (.*)$", texto, flags=re.M)
    consultas = {}
    for i in range(1, len(partes), 3):
        numero, titulo, cuerpo = int(partes[i]), partes[i + 1].strip(), partes[i + 2]
        lineas = [ln for ln in cuerpo.splitlines() if not ln.strip().startswith("--")]
        sql = "\n".join(lineas).strip()
        assert sql.endswith(";"), f"La consulta {numero} debe terminar en ';'"
        consultas[numero] = (titulo, sql.rstrip(";").strip())
    return consultas


CONSULTAS = leer_consultas()


@pytest.fixture(scope="module")
def base():
    cargar_base()
    with sqlite3.connect(config.DB_RUTA) as c:
        yield c


def consulta_df(base, numero):
    return pd.read_sql_query(CONSULTAS[numero][1], base)


def test_hay_al_menos_8_consultas():
    assert len(CONSULTAS) >= 8
    assert sorted(CONSULTAS) == list(range(1, len(CONSULTAS) + 1))


@pytest.mark.parametrize("numero", sorted(CONSULTAS))
def test_consulta_corre_en_sqlite_y_es_tsql_valido(base, numero):
    titulo, sql = CONSULTAS[numero]
    df = pd.read_sql_query(sql, base)
    assert len(df.columns) > 0, titulo
    assert "identificador" not in [c.lower() for c in df.columns]
    # Debe ser analizable como T-SQL (mismo texto para Fabric).
    sqlglot.parse_one(sql, read="tsql")
    for palabra in ("LIMIT", "STRFTIME", "DATEPART", "TOP "):
        assert palabra not in sql.upper(), f"La consulta {numero} usa {palabra}, que no es portable"


def test_comparacion_5_modelos_igual_a_resumen_de_prueba(base):
    df = consulta_df(base, 7).set_index("modelo")
    resumen = pd.read_csv(RAIZ / "resultados" / "prueba_resumen.csv").set_index("modelo")
    assert len(df) == 5 and set(df.index) == set(resumen.index)
    for modelo, r in resumen.iterrows():
        fila = df.loc[modelo]
        for k in ("vp", "vn", "fp", "fn", "n"):
            assert int(fila[k]) == int(r[k]), (modelo, k)
        assert abs(fila["sensibilidad"] - round(r["sensibilidad"], 4)) < 1e-9, modelo
        assert abs(fila["especificidad"] - round(r["especificidad"], 4)) < 1e-9, modelo
    red = df.loc[NOMBRE_RED]
    # Valores de resultados/prueba_resumen.csv al cierre de la Fase 5 (0.9675 y 21 falsos negativos).
    assert int(red["fn"]) == int(resumen.loc[NOMBRE_RED, "fn"])
    assert abs(red["sensibilidad"] - round(resumen.loc[NOMBRE_RED, "sensibilidad"], 4)) < 1e-9


def test_sensibilidad_por_version_igual_a_pandas(base):
    df = consulta_df(base, 1)
    prueba = df[df["origen"] == "prueba"].set_index("modelo")
    pred = pd.read_csv(RAIZ / "resultados" / "predicciones_prueba.csv")
    for modelo, g in pred.groupby("modelo"):
        vp = int(((g.es_tumor == 1) & (g.prediccion == 1)).sum())
        fn = int(((g.es_tumor == 1) & (g.prediccion == 0)).sum())
        assert int(prueba.loc[modelo, "vp"]) == vp and int(prueba.loc[modelo, "fn"]) == fn, modelo
        assert abs(prueba.loc[modelo, "sensibilidad"] - round(vp / (vp + fn), 4)) < 1e-9, modelo


def test_falsos_negativos_igual_a_pandas(base):
    df = consulta_df(base, 5)
    pred = pd.read_csv(RAIZ / "resultados" / "predicciones_prueba.csv")
    red = pred[pred.modelo == NOMBRE_RED]
    esperado = int(((red.es_tumor == 1) & (red.prediccion == 0)).sum())
    obtenido = int(df[(df.modelo == NOMBRE_RED) & (df.origen == "prueba")]["falsos_negativos"].sum())
    assert obtenido == esperado


def test_vistas_sincronizadas_con_tsql():
    tsql = (RAIZ / "sql" / "01_crear_tablas.sql").read_text(encoding="utf-8")
    for nombre in VISTAS:
        assert f"CREATE OR ALTER VIEW dbo.{nombre} AS" in tsql, f"Falta la vista {nombre} en 01_crear_tablas.sql"
