"""Pruebas del asistente de consultas (Fase 5) con un cliente SIMULADO, sin red.

Uso: .venv\\Scripts\\python.exe -m pytest pruebas/test_asistente.py -q

El cliente falso se inyecta sustituyendo la dependencia `asistente.obtener_cliente`. Nunca se
llama a la API real ni se lee la clave de ningún archivo: la comprobación de fugas usa una
clave FALSA inyectada en la configuración.
"""
import json
import logging
import sqlite3
from types import SimpleNamespace

import pytest

from entorno_prueba import cargar_base, preparar

preparar()
from fastapi.testclient import TestClient  # noqa: E402

from app.backend import asistente, config  # noqa: E402
from app.backend.main import app  # noqa: E402
from app.backend.tablas import LISTA_BLANCA_ASISTENTE  # noqa: E402

CLAVE_FALSA = "sk-ant-api03-CLAVE-FALSA-SOLO-PRUEBAS-0000000000"

PELIGROSAS = {
    "drop": "DROP TABLE usuarios",
    "update": "UPDATE usuarios SET rol='administrador'",
    "hash": "SELECT hash_password FROM usuarios",
    "dim_paciente": "SELECT * FROM dim_paciente",
    "subconsulta": "SELECT nombre FROM vw_modelos WHERE modelo_id IN (SELECT usuario_id FROM usuarios)",
    "cte": "WITH u AS (SELECT usuario, hash_password FROM usuarios) SELECT * FROM u",
    "dos_sentencias": "SELECT * FROM vw_modelos; DROP TABLE usuarios",
    "comentario": "SELECT * FROM vw_modelos /* ; DROP TABLE usuarios */",
    "comentario_linea": "SELECT * FROM vw_modelos -- ; DELETE FROM bitacora",
    "pragma": "PRAGMA table_info(usuarios)",
    "attach": "ATTACH DATABASE 'otra.db' AS otra",
    "load_extension": "SELECT load_extension('malicioso')",
    "pragma_funcion": "SELECT * FROM pragma_table_info('usuarios')",
    "into": "SELECT * INTO copia FROM vw_modelos",
    "sqlite_master": "SELECT sql FROM sqlite_master",
}


def _respuesta(texto, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=texto)])


def _json_sql(sql, puede=True, motivo=""):
    return _respuesta(json.dumps({"puede_responder": puede, "sql": sql, "explicacion": "Consulta de prueba.",
                                  "motivo": motivo}))


class ClienteFalso:
    """Imita `anthropic.Anthropic().beta.messages.create` y guarda cada llamada."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._crear))

    def _crear(self, **kwargs):
        self.llamadas.append(kwargs)
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(scope="module")
def admin():
    cargar_base()
    cli = TestClient(app)
    r = cli.post("/api/login", json={"usuario": "admin1", "password": "Admin2026!", "rol": "administrador"})
    assert r.status_code == 200, r.text
    yield cli
    app.dependency_overrides.clear()


def _con_cliente(falso):
    app.dependency_overrides[asistente.obtener_cliente] = lambda: falso


def _bitacora(accion):
    with sqlite3.connect(config.DB_RUTA) as c:
        return c.execute("SELECT detalle, exito FROM bitacora WHERE accion = ? ORDER BY evento_id", (accion,)).fetchall()


def test_lista_blanca_sin_datos_sensibles_y_esquema_al_dia(admin):
    with sqlite3.connect(config.DB_RUTA) as c:
        for vista in LISTA_BLANCA_ASISTENTE:
            columnas = [r[1] for r in c.execute(f"PRAGMA table_info({vista})")]
            assert columnas, vista
            assert list(asistente.ESQUEMA[vista][1]) == columnas, f"ESQUEMA desactualizado para {vista}"
            for col in columnas:
                assert not asistente.PATRON_COLUMNA_SENSIBLE.search(col), (vista, col)
    for prohibida in ("usuarios", "sesiones", "dim_paciente", "hecho_prediccion", "bitacora"):
        assert prohibida not in LISTA_BLANCA_ASISTENTE


@pytest.mark.parametrize("caso", sorted(PELIGROSAS))
def test_validador_rechaza(caso):
    with pytest.raises(asistente.Bloqueada):
        asistente.validar_sql(PELIGROSAS[caso])


def test_validador_acepta_y_fuerza_limite():
    sql = asistente.validar_sql("SELECT modelo_version, COUNT(*) AS n FROM vw_predicciones GROUP BY modelo_version "
                                "LIMIT 100000")
    assert sql.endswith(f"LIMIT {config.ASISTENTE_LIMITE_FILAS}")
    assert asistente.validar_sql("SELECT * FROM vw_modelos").endswith(f"LIMIT {config.ASISTENTE_LIMITE_FILAS}")
    assert asistente.validar_sql("SELECT * FROM vw_modelos LIMIT 3").endswith("LIMIT 3")
    union = asistente.validar_sql("SELECT modelo FROM vw_predicciones UNION SELECT nombre FROM vw_modelos")
    assert union.endswith(f"LIMIT {config.ASISTENTE_LIMITE_FILAS}")


def test_validador_tsql_usa_top(monkeypatch):
    monkeypatch.setattr(config, "DB_MODO", "fabric")
    sql = asistente.validar_sql("SELECT TOP 9999 modelo, COUNT(*) AS n FROM dbo.vw_predicciones GROUP BY modelo")
    assert sql.startswith(f"SELECT TOP {config.ASISTENTE_LIMITE_FILAS} ")


def test_solo_lectura():
    with pytest.raises(sqlite3.OperationalError):
        asistente.ejecutar("DELETE FROM bitacora")   # aun sin validar, la conexión es de solo lectura


@pytest.mark.parametrize("caso", ["drop", "update", "hash", "dim_paciente", "subconsulta", "dos_sentencias",
                                  "comentario", "pragma", "attach"])
def test_modelo_devuelve_sql_peligroso_y_se_bloquea(admin, caso):
    antes = len(_bitacora("CONSULTA_IA_BLOQUEADA"))
    falso = ClienteFalso(_json_sql(PELIGROSAS[caso]))
    _con_cliente(falso)
    r = admin.post("/api/admin/asistente", json={"pregunta": "Dame un resumen de los modelos"})
    assert r.status_code == 200
    d = r.json()
    assert d["estado"] == "bloqueada" and d["filas"] == [] and d["columnas"] == []
    assert len(falso.llamadas) == 1          # no se ejecutó ni se redactó nada
    eventos = _bitacora("CONSULTA_IA_BLOQUEADA")
    assert len(eventos) == antes + 1 and eventos[-1][1] == 0


@pytest.mark.parametrize("caso", ["drop", "update", "dos_sentencias", "pragma", "attach"])
def test_sql_escrito_por_el_admin_se_bloquea_sin_llamar_a_claude(admin, caso):
    falso = ClienteFalso()
    _con_cliente(falso)
    d = admin.post("/api/admin/asistente", json={"pregunta": PELIGROSAS[caso]}).json()
    assert d["estado"] == "bloqueada" and falso.llamadas == []


def test_modelo_no_puede_responder(admin):
    falso = ClienteFalso(_json_sql("", puede=False, motivo="Solo puedo hacer consultas de lectura."))
    _con_cliente(falso)
    d = admin.post("/api/admin/asistente", json={"pregunta": "Borra la tabla de usuarios"}).json()
    assert d["estado"] == "bloqueada" and "lectura" in d["respuesta"]
    assert "Borra la tabla" in _bitacora("CONSULTA_IA_BLOQUEADA")[-1][0]


def test_consulta_valida_flujo_completo(admin):
    sql = "SELECT modelo, COUNT(*) AS n FROM vw_predicciones WHERE origen = 'prueba' GROUP BY modelo LIMIT 100000"
    falso = ClienteFalso(_json_sql(sql), _respuesta("Hay 5 modelos con 720 casos de prueba cada uno."))
    _con_cliente(falso)
    d = admin.post("/api/admin/asistente", json={"pregunta": "¿Cuántos casos de prueba tiene cada modelo? PAC-0001"}).json()
    assert d["estado"] == "ok", d
    assert d["sql"].endswith(f"LIMIT {config.ASISTENTE_LIMITE_FILAS}")
    assert d["columnas"] == ["modelo", "n"] and len(d["filas"]) == 5
    assert d["respuesta"].startswith("Hay 5 modelos")
    # Parámetros de la llamada: modelo de la configuración, esfuerzo explícito, salida estructurada.
    primera, segunda = falso.llamadas
    assert primera["model"] == config.ANTHROPIC_MODELO and primera["max_tokens"] == 4000
    assert primera["output_config"]["effort"] == "medium"
    assert primera["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in primera and "tool_choice" not in primera
    assert primera["fallbacks"] == "default" and primera["betas"] == [asistente.BETA_RESPALDO]
    assert all(m["role"] == "user" for m in primera["messages"])      # sin prefill del asistente
    # El identificador escrito en la pregunta no llega a la API ni a la bitácora.
    for llamada in falso.llamadas:
        assert "PAC-0001" not in json.dumps(llamada, ensure_ascii=False, default=str)
    assert "<resultados" in segunda["messages"][0]["content"]
    detalle = _bitacora("CONSULTA_IA")[-1][0]
    assert "PAC-0001" not in detalle and "vw_predicciones" in detalle


def test_rechazo_del_modelo(admin):
    _con_cliente(ClienteFalso(_respuesta("", stop_reason="refusal")))
    d = admin.post("/api/admin/asistente", json={"pregunta": "¿Cuántos estudios hay?"}).json()
    assert d["estado"] == "error" and "negó" in d["respuesta"]


def test_sin_clave_sin_configurar(admin, monkeypatch):
    app.dependency_overrides.pop(asistente.obtener_cliente, None)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    d = admin.post("/api/admin/asistente", json={"pregunta": "¿Cuántos estudios hay?"}).json()
    assert d["estado"] == "sin_configurar" and d["sql"] is None


def test_doctor_recibe_403(admin):
    cli = TestClient(app)
    assert cli.post("/api/login", json={"usuario": "doctor1", "password": "Doctor2026!",
                                        "rol": "doctor"}).status_code == 200
    _con_cliente(ClienteFalso())
    r = cli.post("/api/admin/asistente", json={"pregunta": "¿Cuántos estudios hay?"})
    assert r.status_code == 403
    assert _bitacora("ACCESO_DENEGADO")[-1][0] == "POST /api/admin/asistente"


def test_la_clave_no_se_filtra(admin, monkeypatch, caplog):
    import anthropic
    import httpx2
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", CLAVE_FALSA)
    caplog.set_level(logging.DEBUG)
    peticion = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    errores = [
        RuntimeError(f"fallo interno con la clave {CLAVE_FALSA}"),
        anthropic.APIConnectionError(message=f"sin red {CLAVE_FALSA}", request=peticion),
        anthropic.AuthenticationError(f"clave inválida {CLAVE_FALSA}",
                                      response=httpx2.Response(401, request=peticion), body=None),
    ]
    respuestas = []
    for error in errores:
        _con_cliente(ClienteFalso(error))
        respuestas.append(admin.post("/api/admin/asistente", json={"pregunta": "¿Cuántos estudios hay?"}).text)
    _con_cliente(ClienteFalso(_json_sql("SELECT COUNT(*) AS n FROM vw_modelos"), _respuesta("Hay modelos.")))
    respuestas.append(admin.post("/api/admin/asistente", json={"pregunta": "¿Cuántos modelos hay?"}).text)
    respuestas.append(admin.get("/api/estado").text)
    assert json.loads(respuestas[0])["estado"] == "error"
    assert "conectar" in json.loads(respuestas[1])["respuesta"]
    assert "no es válida" in json.loads(respuestas[2])["respuesta"]
    assert json.loads(respuestas[3])["estado"] == "ok"
    for texto in respuestas:
        assert CLAVE_FALSA not in texto and "sk-ant" not in texto
    assert CLAVE_FALSA not in caplog.text and "sk-ant" not in caplog.text
    with sqlite3.connect(config.DB_RUTA) as c:
        volcado = "\n".join(c.iterdump())
    assert CLAVE_FALSA not in volcado and "sk-ant" not in volcado
    # El cliente real se construiría con la clave falsa sin exponerla en su representación.
    monkeypatch.setattr(asistente, "_cliente", None)
    cliente = asistente.obtener_cliente()
    assert CLAVE_FALSA not in repr(cliente)
    monkeypatch.setattr(asistente, "_cliente", None)
