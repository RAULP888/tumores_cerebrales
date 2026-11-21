"""Comprueba, sin Power BI, los valores que deben dar las medidas DAX de tablero/GUIA_POWER_BI.md.

No hay Power BI Desktop en el equipo de desarrollo, así que el DAX no se puede ejecutar aquí.
Este script calcula cada medida de dos formas independientes sobre la base local:
  1. con SQL (consultas parametrizadas directamente sobre las tablas del modelo estrella), y
  2. con pandas, imitando la lógica de la medida DAX (mismas columnas y mismos filtros),
y verifica que las dos coincidan. Para la prueba, además, compara contra
resultados/prueba_resumen.csv (lo que reportaron los notebooks).

Uso (desde la raíz del proyecto):
    .venv\\Scripts\\python.exe tablero\\comprobar_medidas.py
    .venv\\Scripts\\python.exe tablero\\comprobar_medidas.py --db otra\\ruta\\tumores.db

La base se abre SOLO EN MODO LECTURA. Termina con código 1 si alguna comprobación falla.
"""
import argparse
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
DB_POR_OMISION = RAIZ / "app" / "almacen" / "tumores.db"
PRUEBA_RESUMEN = RAIZ / "resultados" / "prueba_resumen.csv"

fallas = []


def iguales(a, b, tol=1e-9):
    if a is None or b is None or (isinstance(a, float) and math.isnan(a)) or (isinstance(b, float) and math.isnan(b)):
        return (a is None or (isinstance(a, float) and math.isnan(a))) and \
               (b is None or (isinstance(b, float) and math.isnan(b)))
    return abs(float(a) - float(b)) <= tol


def comprobar(nombre, valor_sql, valor_pandas, esperado=None):
    ok = iguales(valor_sql, valor_pandas) and (esperado is None or iguales(valor_sql, esperado, 1e-9))
    if not ok:
        fallas.append(nombre)
    return ok


def fmt(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "(en blanco)"
    if isinstance(v, float) and not float(v).is_integer():
        return f"{v:.4f}"
    return f"{int(v)}"


def dividir(a, b):
    """Equivale a DIVIDE(a, b) de DAX: en blanco si el divisor es 0."""
    return None if not b else a / b


# --------------------------------------------------------------------------- SQL
# Mismas definiciones que las medidas DAX. predicho = dp.es_tumor (relación activa);
# confirmado = dc.es_tumor (relación inactiva activada con USERELATIONSHIP).
SQL_BASE = """
    FROM hecho_prediccion h
    JOIN dim_modelo m ON m.modelo_id = h.modelo_id
    JOIN dim_diagnostico dp ON dp.diagnostico_id = h.diagnostico_predicho_id
    LEFT JOIN dim_diagnostico dc ON dc.diagnostico_id = h.diagnostico_confirmado_id
    WHERE (:origen IS NULL OR h.origen = :origen)
      AND (:modelo_id IS NULL OR h.modelo_id = :modelo_id)
"""
SQL_MEDIDAS = f"""
SELECT COUNT(*)                                                          AS total,
       SUM(CASE WHEN dp.es_tumor = 1 THEN 1 ELSE 0 END)                  AS predichos_tumor,
       SUM(CASE WHEN dp.es_tumor = 1 AND dc.es_tumor = 1 THEN 1 ELSE 0 END) AS vp,
       SUM(CASE WHEN dp.es_tumor = 0 AND dc.es_tumor = 0 THEN 1 ELSE 0 END) AS vn,
       SUM(CASE WHEN dp.es_tumor = 1 AND dc.es_tumor = 0 THEN 1 ELSE 0 END) AS fp,
       SUM(CASE WHEN dp.es_tumor = 0 AND dc.es_tumor = 1 THEN 1 ELSE 0 END) AS fn,
       -- desacuerdo y tiempo: solo origen = 'uso' (KEEPFILTERS en DAX: se intersecta con el filtro actual)
       SUM(CASE WHEN h.origen = 'uso' AND h.de_acuerdo = 0 THEN 1 ELSE 0 END)         AS desacuerdos,
       SUM(CASE WHEN h.origen = 'uso' AND h.de_acuerdo IS NOT NULL THEN 1 ELSE 0 END) AS con_respuesta,
       AVG(CASE WHEN h.origen = 'uso' THEN h.tiempo_respuesta_ms END)                 AS tiempo_prom
{SQL_BASE}
"""


def medidas_sql(con, origen=None, modelo_id=None):
    fila = con.execute(SQL_MEDIDAS, {"origen": origen, "modelo_id": modelo_id}).fetchone()
    total, pred_t, vp, vn, fp, fn, desac, con_resp, tprom = [(0 if v is None and i < 8 else v)
                                                              for i, v in enumerate(fila)]
    return {
        "Total de estudios": total,
        "% con tumor detectado": dividir(pred_t, total),
        "Sensibilidad": dividir(vp, vp + fn),
        "Especificidad": dividir(vn, vn + fp),
        "Falsos negativos": fn,
        "Falsos positivos": fp,
        "Precisión": dividir(vp, vp + fp),
        "Tasa de desacuerdo del doctor": dividir(desac, con_resp),
        "Tiempo promedio de respuesta (ms)": tprom,
        "_vp": vp, "_vn": vn,
    }


# --------------------------------------------------------------------------- pandas (lógica DAX)
def cargar_pandas(con):
    h = pd.read_sql_query("SELECT * FROM hecho_prediccion", con)
    d = pd.read_sql_query("SELECT diagnostico_id, es_tumor FROM dim_diagnostico", con)
    es_tumor = dict(zip(d.diagnostico_id, d.es_tumor.astype(bool)))
    # Columna calculada predicho_tumor = RELATED(dim_diagnostico[es_tumor]) (relación activa)
    h["predicho_tumor"] = h.diagnostico_predicho_id.map(es_tumor)
    # Rol "confirmado": lo que ve la medida al activar la relación inactiva con USERELATIONSHIP
    h["confirmado_tumor"] = h.diagnostico_confirmado_id.map(es_tumor)  # NaN si no está confirmado
    return h


def medidas_pandas(h, origen=None, modelo_id=None):
    f = h
    if origen is not None:
        f = f[f.origen == origen]
    if modelo_id is not None:
        f = f[f.modelo_id == modelo_id]
    conf = f[f.confirmado_tumor.notna()]
    vp = int(((conf.predicho_tumor == True) & (conf.confirmado_tumor == True)).sum())   # noqa: E712
    vn = int(((conf.predicho_tumor == False) & (conf.confirmado_tumor == False)).sum())  # noqa: E712
    fp = int(((conf.predicho_tumor == True) & (conf.confirmado_tumor == False)).sum())   # noqa: E712
    fn = int(((conf.predicho_tumor == False) & (conf.confirmado_tumor == True)).sum())   # noqa: E712
    # En las filas de prueba de_acuerdo = acierto del modelo (lo llena la carga), no es la opinión de
    # un doctor; por eso la medida DAX usa KEEPFILTERS(origen = "uso").
    uso = f[f.origen == "uso"]
    resp = uso[uso.de_acuerdo.notna()]
    tiempos = uso.tiempo_respuesta_ms.dropna()
    return {
        "Total de estudios": len(f),
        "% con tumor detectado": dividir(int(f.predicho_tumor.sum()), len(f)),
        "Sensibilidad": dividir(vp, vp + fn),
        "Especificidad": dividir(vn, vn + fp),
        "Falsos negativos": fn,
        "Falsos positivos": fp,
        "Precisión": dividir(vp, vp + fp),
        "Tasa de desacuerdo del doctor": dividir(int((resp.de_acuerdo == 0).sum()), len(resp)),
        "Tiempo promedio de respuesta (ms)": float(tiempos.mean()) if len(tiempos) else None,
        "_vp": vp, "_vn": vn,
    }


# --------------------------------------------------------------------------- principal
def main(ruta_db):
    if not ruta_db.exists():
        print(f"[ERROR] No existe la base {ruta_db}")
        sys.exit(1)
    con = sqlite3.connect(f"file:{ruta_db.resolve().as_posix()}?mode=ro", uri=True)
    try:
        h = cargar_pandas(con)
        modelos = pd.read_sql_query(
            "SELECT modelo_id, nombre, tipo, version, estado FROM dim_modelo ORDER BY modelo_id", con)
        ultimo = con.execute("SELECT MAX(creado_en) FROM hecho_prediccion").fetchone()[0]
    except Exception:
        con.close()
        raise

    print("Comprobación de las medidas DAX con SQL y pandas (base en modo lectura)")
    print(f"Base: {ruta_db}  ·  corrida: {datetime.now():%Y-%m-%d %H:%M:%S}  ·  "
          f"último registro en hecho_prediccion: {ultimo}")
    print(f"Filas en hecho_prediccion: {len(h):,}  ·  por origen: {h.origen.value_counts().to_dict()}\n")

    # 1) Medidas por modelo con filtro origen = "prueba"
    resumen = pd.read_csv(PRUEBA_RESUMEN, encoding="utf-8")
    esperado_por_nombre = {r.modelo: r for r in resumen.itertuples()}
    medidas_prueba = ["Total de estudios", "% con tumor detectado", "Sensibilidad", "Especificidad",
                      "Falsos negativos", "Falsos positivos", "Precisión", "Tasa de desacuerdo del doctor",
                      "Tiempo promedio de respuesta (ms)"]
    mapa_csv = {"Total de estudios": "n", "Sensibilidad": "sensibilidad", "Especificidad": "especificidad",
                "Falsos negativos": "fn", "Falsos positivos": "fp", "Precisión": "precision"}
    print("=" * 100)
    print('1) Filtro origen = "prueba", un modelo a la vez (segmentación por dim_modelo[nombre])')
    print("=" * 100)
    sens_prod = None
    prod = modelos[(modelos.tipo == "red_keras") & (modelos.estado == "produccion")]
    prod_id = int(prod.modelo_id.iloc[0]) if len(prod) else None
    if prod_id is not None:
        sens_prod = medidas_sql(con, "prueba", prod_id)["Sensibilidad"]
    for m in modelos.itertuples():
        s = medidas_sql(con, "prueba", m.modelo_id)
        p = medidas_pandas(h, "prueba", m.modelo_id)
        ref = esperado_por_nombre.get(m.nombre)
        print(f"\n--- {m.nombre} (modelo_id {m.modelo_id}, versión {m.version}, estado {m.estado})")
        for nombre in medidas_prueba:
            esperado = None
            if ref is not None and nombre in mapa_csv:
                esperado = getattr(ref, mapa_csv[nombre])
            ok = comprobar(f"prueba/{m.nombre}/{nombre}", s[nombre], p[nombre], esperado)
            extra = "" if esperado is None else f"  (prueba_resumen.csv: {fmt(float(esperado))})"
            print(f"  {nombre:<38} SQL={fmt(s[nombre]):>12}  pandas={fmt(p[nombre]):>12}  "
                  f"{'OK' if ok else 'FALLA'}{extra}")
        # Comparación entre versiones: diferencia de sensibilidad contra la red en producción
        dif_s = None if s["Sensibilidad"] is None or sens_prod is None else s["Sensibilidad"] - sens_prod
        dif_p = None if p["Sensibilidad"] is None or sens_prod is None else p["Sensibilidad"] - sens_prod
        ok = comprobar(f"prueba/{m.nombre}/dif", dif_s, dif_p)
        print(f"  {'Dif. sensibilidad vs producción':<38} SQL={fmt(dif_s):>12}  pandas={fmt(dif_p):>12}  "
              f"{'OK' if ok else 'FALLA'}  (en puntos porcentuales: "
              f"{'' if dif_s is None else f'{dif_s * 100:+.2f}'})")

    # 2) Todos los modelos juntos en prueba (sin segmentar): lo que muestra una tarjeta sin filtro de modelo
    print("\n" + "=" * 100)
    print('2) Filtro origen = "prueba" SIN segmentar por modelo (suma los 5 modelos: 5 x 720 filas)')
    print("=" * 100)
    s, p = medidas_sql(con, "prueba"), medidas_pandas(h, "prueba")
    for nombre in medidas_prueba:
        ok = comprobar(f"prueba/todos/{nombre}", s[nombre], p[nombre])
        print(f"  {nombre:<38} SQL={fmt(s[nombre]):>12}  pandas={fmt(p[nombre]):>12}  {'OK' if ok else 'FALLA'}")

    # 3) Uso real
    print("\n" + "=" * 100)
    print('3) Filtro origen = "uso" (estudios reales subidos en la aplicación)')
    print("=" * 100)
    s, p = medidas_sql(con, "uso"), medidas_pandas(h, "uso")
    for nombre in medidas_prueba:
        ok = comprobar(f"uso/{nombre}", s[nombre], p[nombre])
        print(f"  {nombre:<38} SQL={fmt(s[nombre]):>12}  pandas={fmt(p[nombre]):>12}  {'OK' if ok else 'FALLA'}")
    confirmados_uso = int(h[(h.origen == "uso") & h.diagnostico_confirmado_id.notna()].shape[0])
    print(f"  {'(estudios de uso confirmados)':<38} {confirmados_uso}")

    # 4) Uso real contra prueba, sin filtro de origen
    print("\n" + "=" * 100)
    print("4) Estudios de uso real contra prueba (sin filtro de origen)")
    print("=" * 100)
    total_sql = con.execute("SELECT COUNT(*) FROM hecho_prediccion").fetchone()[0]
    uso_sql = con.execute("SELECT COUNT(*) FROM hecho_prediccion WHERE origen = ?", ("uso",)).fetchone()[0]
    pru_sql = con.execute("SELECT COUNT(*) FROM hecho_prediccion WHERE origen = ?", ("prueba",)).fetchone()[0]
    for nombre, a, b in [("Total de estudios (todos)", total_sql, len(h)),
                         ("Estudios de uso", uso_sql, int((h.origen == "uso").sum())),
                         ("Estudios de prueba", pru_sql, int((h.origen == "prueba").sum())),
                         ("% de estudios de uso", dividir(uso_sql, total_sql),
                          dividir(int((h.origen == "uso").sum()), len(h)))]:
        ok = comprobar(f"origen/{nombre}", a, b)
        print(f"  {nombre:<38} SQL={fmt(a):>12}  pandas={fmt(b):>12}  {'OK' if ok else 'FALLA'}")

    # 5) Estudios por diagnóstico confirmado (rol inactivo de dim_diagnostico con USERELATIONSHIP)
    print("\n" + "=" * 100)
    print('5) "Estudios por diagnóstico confirmado", red en producción, origen = "prueba"')
    print("=" * 100)
    filas = con.execute("""
        SELECT dc.clave, COUNT(*) FROM hecho_prediccion h
        JOIN dim_diagnostico dc ON dc.diagnostico_id = h.diagnostico_confirmado_id
        WHERE h.origen = ? AND h.modelo_id = ? GROUP BY dc.clave ORDER BY dc.clave""",
                        ("prueba", prod_id)).fetchall()
    d = pd.read_sql_query("SELECT diagnostico_id, clave FROM dim_diagnostico", con)
    claves = dict(zip(d.diagnostico_id, d.clave))
    sub = h[(h.origen == "prueba") & (h.modelo_id == prod_id)]
    conteo_pd = sub.diagnostico_confirmado_id.map(claves).value_counts().to_dict()
    for clave, n in filas:
        ok = comprobar(f"confirmado/{clave}", n, conteo_pd.get(clave, 0))
        print(f"  {clave:<38} SQL={n:>12}  pandas={conteo_pd.get(clave, 0):>12}  {'OK' if ok else 'FALLA'}")

    # 6) Actividad de usuarios (vw_bitacora)
    print("\n" + "=" * 100)
    print("6) Actividad de usuarios (vw_bitacora, sin filtros)")
    print("=" * 100)
    b = pd.read_sql_query("SELECT * FROM vw_bitacora", con)
    pares = [("Eventos de bitácora", "SELECT COUNT(*) FROM vw_bitacora", len(b)),
             ("Inicios de sesión correctos", "SELECT COUNT(*) FROM vw_bitacora WHERE accion = 'LOGIN_OK'",
              int((b.accion == "LOGIN_OK").sum())),
             ("Inicios de sesión fallidos", "SELECT COUNT(*) FROM vw_bitacora WHERE accion = 'LOGIN_FALLIDO'",
              int((b.accion == "LOGIN_FALLIDO").sum())),
             ("Accesos denegados", "SELECT COUNT(*) FROM vw_bitacora WHERE accion = 'ACCESO_DENEGADO'",
              int((b.accion == "ACCESO_DENEGADO").sum())),
             ("Eventos sin éxito", "SELECT COUNT(*) FROM vw_bitacora WHERE exito = 0", int((b.exito == 0).sum())),
             ("Usuarios activos (dim_usuario)", "SELECT COUNT(*) FROM dim_usuario WHERE activo = 1", None)]
    for nombre, consulta, valor_pd in pares:
        a = con.execute(consulta).fetchone()[0]
        if valor_pd is None:
            u = pd.read_sql_query("SELECT activo FROM dim_usuario", con)
            valor_pd = int((u.activo == 1).sum())
        ok = comprobar(f"bitacora/{nombre}", a, valor_pd)
        print(f"  {nombre:<38} SQL={fmt(a):>12}  pandas={fmt(valor_pd):>12}  {'OK' if ok else 'FALLA'}")
    print("  Eventos por acción:", b.accion.value_counts().sort_index().to_dict())
    con.close()

    print("\n" + ("TODAS LAS COMPROBACIONES COINCIDEN." if not fallas else f"FALLAS: {fallas}"))
    sys.exit(1 if fallas else 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Valores esperados de las medidas DAX")
    parser.add_argument("--db", type=Path, default=DB_POR_OMISION, help="ruta del archivo SQLite")
    main(parser.parse_args().db)
