"""Prueba de punta a punta contra la SQL database de Microsoft Fabric.

Uso (con el usuario presente: la primera vez se abre el navegador para iniciar sesión con
Microsoft Entra ID; después se reutiliza la sesión guardada en app/almacen/fabric_auth.json):

    .venv\\Scripts\\python.exe scripts/probar_fabric.py

Fuerza DB_MODO=fabric solo para este proceso (no cambia .env). Necesita FABRIC_SERVIDOR y
FABRIC_BASE en .env. Pasos, en orden:
  1. Conectar e imprimir la base, el usuario y el número de tablas.
  2. Crear el esquema (ejecuta sql/01_crear_tablas.sql por lotes; se puede repetir).
  3. Cargar los datos (sql/02_cargar_datos.py) y los usuarios de demostración.
  4. Contar filas por tabla y vista.
  5. Correr 3 consultas de sql/03_consultas.sql en T-SQL.
  6. Pasar una consulta por el validador del asistente (TOP) y ejecutarla en la conexión de solo lectura.
Se detiene en el primer paso que falle e indica cuál fue.
"""
import os
import re
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
os.environ["DB_MODO"] = "fabric"

from app.backend import asistente, carga, config, db  # noqa: E402
from app.backend.tablas import VISTAS, metadata  # noqa: E402

CONSULTAS_A_PROBAR = (1, 7, 9)


def paso(numero, titulo):
    print(f"\n=== Paso {numero}: {titulo} ===", flush=True)
    return time.perf_counter()


def consultas_del_archivo():
    texto = (RAIZ / "sql" / "03_consultas.sql").read_text(encoding="utf-8")
    partes = re.split(r"^-- @consulta (\d+): (.*)$", texto, flags=re.M)
    salida = {}
    for i in range(1, len(partes), 3):
        cuerpo = "\n".join(ln for ln in partes[i + 2].splitlines() if not ln.strip().startswith("--"))
        salida[int(partes[i])] = (partes[i + 1].strip(), cuerpo.strip().rstrip(";"))
    return salida


def imprimir(cursor, maximo=8):
    columnas = [d[0] for d in cursor.description]
    filas = cursor.fetchmany(maximo)
    print("  " + " | ".join(columnas))
    for f in filas:
        print("  " + " | ".join("" if v is None else str(v) for v in f))


def main():
    assert config.DB_MODO == "fabric"
    print(f"Servidor: {config.FABRIC_SERVIDOR or '(falta FABRIC_SERVIDOR)'} | base: {config.FABRIC_BASE or '(falta FABRIC_BASE)'}")
    m = db.motor()

    t = paso(1, "conectar")
    crudo = m.raw_connection()
    try:
        cur = crudo.cursor()
        cur.execute("SELECT DB_NAME(), SUSER_SNAME(), (SELECT COUNT(*) FROM sys.tables), @@VERSION")
        base, usuario, tablas, version = cur.fetchone()
        print(f"  base: {base} | usuario: {usuario} | tablas: {tablas}")
        print(f"  {str(version).splitlines()[0]}")
    finally:
        crudo.close()
    print(f"  ({time.perf_counter() - t:.1f} s)")

    t = paso(2, "crear el esquema (sql/01_crear_tablas.sql)")
    lotes = db.crear_esquema()
    print(f"  {lotes} lotes ejecutados ({time.perf_counter() - t:.1f} s)")

    t = paso(3, "cargar los datos y los usuarios de demostración")
    resumen = carga.cargar_todo()
    for k, v in resumen.items():
        print(f"  {k}: {v}")
    import runpy
    creados, restablecidos = runpy.run_path(str(RAIZ / "scripts" / "crear_usuarios_demo.py"))["crear"]()
    print(f"  usuarios creados: {creados or 'ninguno'} | restablecidos: {restablecidos or 'ninguno'}")
    print(f"  ({time.perf_counter() - t:.1f} s)")

    t = paso(4, "filas por tabla y vista")
    crudo = m.raw_connection()
    try:
        cur = crudo.cursor()
        for nombre in [tb.name for tb in metadata.sorted_tables] + list(VISTAS):
            cur.execute(f"SELECT COUNT(*) FROM dbo.{nombre}")   # nombres fijos del esquema, no del usuario
            print(f"  {nombre:24s} {cur.fetchone()[0]:>8}")
    finally:
        crudo.close()
    print(f"  ({time.perf_counter() - t:.1f} s)")

    t = paso(5, "consultas de sql/03_consultas.sql en T-SQL")
    consultas = consultas_del_archivo()
    crudo = m.raw_connection()
    try:
        cur = crudo.cursor()
        for n in CONSULTAS_A_PROBAR:
            titulo, sql = consultas[n]
            print(f"\n  -- Consulta {n}: {titulo}")
            cur.execute(sql)
            imprimir(cur)
    finally:
        crudo.close()
    print(f"  ({time.perf_counter() - t:.1f} s)")

    t = paso(6, "asistente: validador (TOP) y conexión de solo lectura")
    sql = asistente.validar_sql("SELECT modelo, COUNT(*) AS n FROM vw_predicciones GROUP BY modelo")
    print("  SQL validado:", sql)
    columnas, filas = asistente.ejecutar(sql)
    print("  ", columnas)
    for f in filas:
        print("  ", f)
    print(f"  ({time.perf_counter() - t:.1f} s)")
    print("\nTodo terminó sin errores.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"\n[ERROR] {type(e).__name__}: {str(e)[:500]}")
        sys.exit(1)
