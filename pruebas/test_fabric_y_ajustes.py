"""Pruebas sin red de la preparación para Fabric y de los ajustes pedidos por el Verificador.

Uso: .venv\\Scripts\\python.exe -m pytest pruebas/test_fabric_y_ajustes.py -q

No se conecta a Fabric (iniciar sesión abre el navegador): se comprueba que el script T-SQL se
divide bien en lotes, que la cadena ODBC no lleva credenciales, que las consultas del backend
compiladas para SQL Server no usan `IS 1` y que el motor Fabric se arma con `creator`.
"""
import re
import sqlite3

import pytest
from sqlalchemy.dialects import mssql

from entorno_prueba import RAIZ, cargar_base, preparar

preparar()
from fastapi.testclient import TestClient  # noqa: E402

from app.backend import config, db, fabric  # noqa: E402
from app.backend.main import app  # noqa: E402
from app.backend.tablas import VISTAS, metadata  # noqa: E402


# ------------------------------------------------------------------ Fabric (sin red)
def test_script_tsql_en_lotes():
    lotes = fabric.lotes_tsql((RAIZ / "sql" / "01_crear_tablas.sql").read_text(encoding="utf-8"))
    vistas = [lote for lote in lotes if "CREATE OR ALTER VIEW" in lote]
    assert len(vistas) == len(VISTAS)
    for lote in vistas:
        # CREATE VIEW debe ser la primera sentencia de su lote (solo puede haber comentarios antes).
        sin_comentarios = re.sub(r"--[^\n]*", "", re.sub(r"/\*.*?\*/", "", lote, flags=re.S))
        assert sin_comentarios.lstrip().startswith("CREATE OR ALTER VIEW"), lote[:80]
    texto = "\n".join(lotes)
    for tabla in metadata.sorted_tables:
        assert f"dbo.{tabla.name}" in texto, tabla.name
    assert "DATETIME2(0)" in texto and "CHECK (" in texto
    assert not any(lote.strip().upper() == "GO" for lote in lotes)


def test_cadena_odbc_sin_credenciales(monkeypatch):
    monkeypatch.setattr(config, "FABRIC_SERVIDOR", "ejemplo.database.fabric.microsoft.com")
    monkeypatch.setattr(config, "FABRIC_BASE", "base_de_prueba")
    normal, lectura = fabric.cadena_odbc(), fabric.cadena_odbc(solo_lectura=True)
    for cadena in (normal, lectura):
        assert "Driver={ODBC Driver 18 for SQL Server}" in cadena
        assert "Server=ejemplo.database.fabric.microsoft.com,1433" in cadena
        assert "Encrypt=yes" in cadena and "TrustServerCertificate=no" in cadena
        for prohibido in ("Authentication", "UID=", "PWD=", "Password"):
            assert prohibido not in cadena
    assert "ApplicationIntent=ReadOnly" in lectura and "ApplicationIntent" not in normal
    monkeypatch.setattr(config, "FABRIC_SERVIDOR", "otro.servidor,1444")
    assert "Server=otro.servidor,1444;" in fabric.cadena_odbc()


def test_motor_fabric_usa_creator_sin_conectar(monkeypatch):
    llamadas = []
    monkeypatch.setattr(fabric, "conectar", lambda solo_lectura=False: llamadas.append(solo_lectura))
    m = db._motor_fabric()
    assert m.dialect.name == "mssql" and str(m.url) == "mssql+pyodbc://"
    assert llamadas == []          # crear el motor no abre conexión ni navegador
    m.dispose()


def test_token_se_reutiliza_y_renueva(monkeypatch):
    import time
    from types import SimpleNamespace
    pedidos = []

    class CredencialFalsa:
        def get_token(self, alcance):
            pedidos.append(alcance)
            return SimpleNamespace(token="token-falso", expires_on=time.time() + (60 if len(pedidos) == 1 else 3600))

    monkeypatch.setattr(fabric, "credencial", lambda: CredencialFalsa())
    monkeypatch.setattr(fabric, "_token", None)
    a = fabric.token_bytes()          # primer token: vence en 60 s (menos que el margen)
    fabric.token_bytes()              # se renueva
    fabric.token_bytes()              # ya no: dura una hora
    assert pedidos == [fabric.ALCANCE, fabric.ALCANCE]
    assert a[4:] == "token-falso".encode("utf-16-le")
    monkeypatch.setattr(fabric, "_token", None)


def test_consultas_del_backend_validas_para_sql_server():
    """Ninguna consulta del backend debe compilar a `IS 1`/`IS 0` (SQL Server lo rechaza)."""
    import inspect
    from app.backend import seguridad
    from app.backend.rutas import admin, estudios
    for modulo in (seguridad, admin, estudios):
        assert ".is_(True" not in inspect.getsource(modulo) and ".is_(False" not in inspect.getsource(modulo)
    from sqlalchemy import select
    from app.backend.tablas import usuarios
    sql = str(select(usuarios.c.usuario).where(usuarios.c.activo == True).compile(dialect=mssql.dialect()))  # noqa: E712
    assert " IS " not in sql.replace("IS NULL", "").replace("IS NOT NULL", "")


# ------------------------------------------------------------------ ajustes del Verificador
@pytest.fixture(scope="module")
def admin():
    cargar_base()
    cli = TestClient(app)
    assert cli.post("/api/login", json={"usuario": "admin1", "password": "Admin2026!",
                                        "rol": "administrador"}).status_code == 200
    return cli


def _ultimo(accion):
    with sqlite3.connect(config.DB_RUTA) as c:
        return c.execute("SELECT usuario, detalle, ip, exito FROM bitacora WHERE accion = ? ORDER BY evento_id DESC",
                         (accion,)).fetchone()


def test_docs_desactivadas(admin):
    for ruta in ("/api/docs", "/api/openapi.json", "/api/redoc"):
        assert admin.get(ruta).status_code == 404, ruta


def test_cambios_de_usuario_rechazados_quedan_en_bitacora(admin):
    yo = admin.get("/api/yo").json()
    r = admin.put(f"/api/admin/usuarios/{yo['usuario_id']}", json={"activo": False})
    assert r.status_code == 409
    usuario, detalle, ip, exito = _ultimo("USUARIO_ACTUALIZADO")
    assert usuario == "admin1" and exito == 0 and ip and "a ti mismo" in detalle
    r = admin.put(f"/api/admin/usuarios/{yo['usuario_id']}", json={"password": "corta"})
    assert r.status_code == 422
    usuario, detalle, _, exito = _ultimo("USUARIO_ACTUALIZADO")
    assert exito == 0 and "8 y 72" in detalle and "corta" not in detalle
    r = admin.post("/api/admin/usuarios", json={"usuario": "doctor1", "password": "Doctor2026!", "rol": "doctor"})
    assert r.status_code == 409
    usuario, detalle, _, exito = _ultimo("USUARIO_CREADO")
    assert exito == 0 and "Ya existe" in detalle
    r = admin.post("/api/admin/usuarios", json={"usuario": "x", "password": "Doctor2026!", "rol": "doctor"})
    assert r.status_code == 422 and _ultimo("USUARIO_CREADO")[3] == 0
