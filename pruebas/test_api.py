"""Pruebas de la API (Fases 3 y 4).

Uso: .venv\\Scripts\\python.exe -m pytest pruebas/test_api.py -q

Usan una base SQLite, una carpeta de imágenes y una carpeta de modelos TEMPORALES (variables
TS_DB_RUTA, TS_MEDIA_DIR y TS_MODELOS_DIR), con una copia de app/modelos/v001. Las imágenes
son reales, de la partición de prueba del manifiesto. Incluyen dos reentrenamientos reales en
un proceso aparte (uno corto que termina y otro que se cancela).
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="ts_pruebas_"))
os.environ["TS_DB_RUTA"] = str(TMP / "prueba.db")
os.environ["TS_MEDIA_DIR"] = str(TMP / "media")
os.environ["TS_MODELOS_DIR"] = str(TMP / "modelos")
os.environ["TS_REGISTROS_DIR"] = str(TMP / "registros")
os.environ["DB_MODO"] = "local"
os.environ["ANTHROPIC_API_KEY"] = ""
(TMP / "modelos" / "v001").mkdir(parents=True)
for archivo in (RAIZ / "app" / "modelos" / "v001").iterdir():
    if archivo.suffix in (".keras", ".json", ".npz") or archivo.name.startswith("curvas"):
        shutil.copy2(archivo, TMP / "modelos" / "v001" / archivo.name)
sys.path.insert(0, str(RAIZ))

from fastapi.testclient import TestClient  # noqa: E402

from app.backend import carga, config  # noqa: E402
from app.backend.main import app  # noqa: E402

assert config.DB_RUTA == TMP / "prueba.db"

RUTAS_ADMIN = [
    ("get", "/api/admin/resumen", None), ("post", "/api/admin/entrenamientos", {"epocas_max": 1, "tasa": 0.001,
                                                                               "lote": 64, "kfold": False,
                                                                               "ajuste_fino": False}),
    ("get", "/api/admin/entrenamientos", None), ("get", "/api/admin/entrenamientos/1", None),
    ("get", "/api/admin/entrenamientos/1/curvas", None), ("post", "/api/admin/entrenamientos/1/cancelar", None),
    ("get", "/api/admin/modelos", None), ("post", "/api/admin/modelos/1/aprobar", None),
    ("post", "/api/admin/modelos/revertir", None), ("get", "/api/admin/umbral?valor=0.5", None),
    ("put", "/api/admin/umbral", {"valor": 0.5}), ("get", "/api/admin/usuarios", None),
    ("post", "/api/admin/usuarios", {"usuario": "intruso", "password": "Intruso2026!", "rol": "administrador"}),
    ("put", "/api/admin/usuarios/1", {"activo": False}), ("get", "/api/admin/bitacora", None),
    ("post", "/api/admin/asistente", {"pregunta": "¿cuántos estudios hay?"}),
]
CAMPOS_RESULTADO = {"prediccion_id", "archivo", "hay_tumor", "etiqueta", "probabilidad_tumor", "confianza", "umbral",
                    "tipo_probable", "tipo_nombre", "probabilidad_tipo", "imagen_url", "gradcam_url", "modelo_version",
                    "tiempo_respuesta_ms", "aviso"}
CAMPOS_ESTUDIO = {"prediccion_id", "creado_en", "identificador", "edad", "sexo", "fecha_estudio", "hay_tumor",
                  "etiqueta", "probabilidad_tumor", "confianza", "tipo_nombre", "modelo_version", "de_acuerdo",
                  "diagnostico_confirmado", "imagen_url", "gradcam_url", "doctor"}
ESTADO = {}


def _sql(consulta, parametros=()):
    with sqlite3.connect(TMP / "prueba.db") as c:
        return c.execute(consulta, parametros).fetchall()


def _imagenes_prueba():
    """(ruta_tumor, ruta_sin_tumor, esperado) de la partición de prueba."""
    man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
    prueba = set(man.loc[man["particion"] == "prueba", "ruta"])
    pred = pd.read_csv(RAIZ / "resultados" / "predicciones_prueba.csv")
    red = pred[pred["modelo"].str.contains("Red Keras") & pred["ruta"].isin(prueba)]
    if len(red):
        t = red[red["es_tumor"] == 1].sort_values("probabilidad_tumor", ascending=False).iloc[0]["ruta"]
        s = red[red["es_tumor"] == 0].sort_values("probabilidad_tumor").iloc[0]["ruta"]
        return RAIZ / t, RAIZ / s, True
    t = man[(man["particion"] == "prueba") & (man["es_tumor"] == 1)].iloc[0]["ruta"]
    s = man[(man["particion"] == "prueba") & (man["es_tumor"] == 0)].iloc[0]["ruta"]
    return RAIZ / t, RAIZ / s, False


def _cliente():
    """Cliente adicional (comparte la app ya arrancada; no vuelve a cargar el modelo)."""
    return TestClient(app)


def _login(cli, usuario, password, rol):
    r = cli.post("/api/login", json={"usuario": usuario, "password": password, "rol": rol})
    assert r.status_code == 200, r.text
    return r.json()


def _esperar(cli, eid, estados, segundos=600, condicion=None):
    fin = time.time() + segundos
    while time.time() < fin:
        d = cli.get(f"/api/admin/entrenamientos/{eid}").json()
        if d["estado"] in estados and (condicion is None or condicion(d)):
            return d
        time.sleep(1.0)
    raise AssertionError(f"El entrenamiento {eid} no llegó a {estados}: {d}")


@pytest.fixture(scope="module")
def cliente():
    carga.cargar_todo()
    import runpy
    runpy.run_path(str(RAIZ / "scripts" / "crear_usuarios_demo.py"))["crear"]()
    with TestClient(app) as cli:
        yield cli


@pytest.fixture(scope="module")
def admin(cliente):
    cli = _cliente()
    _login(cli, "admin1", "Admin2026!", "administrador")
    return cli


# ------------------------------------------------------------------ público y sesión
def test_estado(cliente):
    r = cliente.get("/api/estado").json()
    assert r["modelo"]["cargado"] is True and r["modelo"]["version"] == "v001"
    assert r["base_datos"] == "local" and r["asistente_configurado"] is False
    assert r["aviso"] == "Resultado de apoyo. No sustituye el diagnóstico de un médico especialista."
    assert set(r) == {"modelo", "base_datos", "asistente_configurado", "powerbi_url", "aviso"}


def test_login_ok_fallido_y_rol_equivocado():
    cli = _cliente()
    assert cli.get("/api/yo").status_code == 401
    r = cli.post("/api/login", json={"usuario": "doctor1", "password": "mala", "rol": "doctor"})
    assert r.status_code == 401 and isinstance(r.json()["detail"], str)
    r = cli.post("/api/login", json={"usuario": "doctor1", "password": "Doctor2026!", "rol": "administrador"})
    assert r.status_code == 403
    assert config.COOKIE_SESION not in cli.cookies
    datos = _login(cli, "doctor1", "Doctor2026!", "doctor")
    assert set(datos) == {"usuario_id", "usuario", "rol"} and datos["rol"] == "doctor"
    assert cli.get("/api/yo").json()["usuario"] == "doctor1"
    acciones = [a for (a,) in _sql("SELECT accion FROM bitacora WHERE usuario = ? ORDER BY evento_id", ("doctor1",))]
    assert acciones[-3:] == ["LOGIN_FALLIDO", "LOGIN_FALLIDO", "LOGIN_OK"]
    assert _sql("SELECT COUNT(*) FROM bitacora WHERE accion='LOGIN_OK' AND ip IS NOT NULL")[0][0] >= 1
    # La sesión se guarda como hash, nunca el token en claro.
    token = cli.cookies.get(config.COOKIE_SESION)
    assert _sql("SELECT COUNT(*) FROM sesiones WHERE token_hash = ?", (token,))[0][0] == 0
    assert cli.post("/api/logout").json() == {"ok": True}
    assert cli.get("/api/yo").status_code == 401


def test_doctor_recibe_403_en_admin(cliente):
    cli = _cliente()
    _login(cli, "doctor1", "Doctor2026!", "doctor")
    antes = _sql("SELECT COUNT(*) FROM bitacora WHERE accion='ACCESO_DENEGADO' AND usuario='doctor1'")[0][0]
    for metodo, ruta, cuerpo in RUTAS_ADMIN:
        r = getattr(cli, metodo)(ruta, json=cuerpo) if cuerpo is not None else getattr(cli, metodo)(ruta)
        assert r.status_code == 403, (metodo, ruta, r.status_code, r.text)
    despues = _sql("SELECT COUNT(*) FROM bitacora WHERE accion='ACCESO_DENEGADO' AND usuario='doctor1'")[0][0]
    assert despues - antes == len(RUTAS_ADMIN)
    assert _sql("SELECT COUNT(*) FROM entrenamientos WHERE estado <> 'terminado'")[0][0] == 0
    sin_sesion = _cliente()
    assert sin_sesion.get("/api/admin/resumen").status_code == 401


# ------------------------------------------------------------------ flujo del doctor
def test_flujo_completo(cliente):
    cli = _cliente()
    yo = _login(cli, "doctor1", "Doctor2026!", "doctor")
    con_tumor, sin_tumor, conocido = _imagenes_prueba()
    archivos = [("archivos", ("con_tumor.jpg", con_tumor.read_bytes(), "image/jpeg")),
                ("archivos", ("sin_tumor.jpg", sin_tumor.read_bytes(), "image/jpeg")),
                ("archivos", ("notas.png", b"esto no es una imagen", "image/png"))]
    hoy = date.today().isoformat()
    r = cli.post("/api/estudios", data={"identificador": "PAC-0001", "edad": "54", "sexo": "F", "fecha_estudio": hoy},
                 files=archivos)
    assert r.status_code == 200, r.text
    res = r.json()["resultados"]
    assert len(res) == 3
    a, b, malo = res
    assert set(malo) == {"archivo", "error"} and malo["archivo"] == "notas.png"
    for x in (a, b):
        assert set(x) == CAMPOS_RESULTADO, set(x) ^ CAMPOS_RESULTADO
        assert x["aviso"] == config.AVISO and x["modelo_version"] == "v001"
        conf = x["probabilidad_tumor"] if x["hay_tumor"] else 1 - x["probabilidad_tumor"]
        assert abs(x["confianza"] - conf) < 1e-9
        assert x["etiqueta"] == ("Se detecta posible tumor" if x["hay_tumor"] else "No se detecta tumor")
        assert x["imagen_url"].startswith("/media/") and x["gradcam_url"].startswith("/media/")
        assert x["tiempo_respuesta_ms"] > 0
        if not x["hay_tumor"]:
            assert x["tipo_probable"] is None and x["tipo_nombre"] is None and x["probabilidad_tipo"] is None
    if conocido:
        assert a["hay_tumor"] is True and b["hay_tumor"] is False
        assert a["tipo_probable"] in ("glioma", "meningioma", "pituitary") and a["tipo_nombre"]
    ESTADO.update({"a": a, "b": b, "doctor1": cli, "imagen_tumor": con_tumor})

    # Fila en hecho_prediccion, recuperada con una consulta SQL parametrizada.
    filas = _sql("SELECT h.prediccion_id, h.origen, h.usuario_id, p.identificador, h.probabilidad_tumor, "
                 "h.tiempo_respuesta_ms, h.fecha_id FROM hecho_prediccion h "
                 "JOIN dim_paciente p ON p.paciente_id = h.paciente_id WHERE h.prediccion_id = ? AND p.identificador = ?",
                 (a["prediccion_id"], "PAC-0001"))
    assert len(filas) == 1
    pid, origen, uid, ident, prob, ms, fid = filas[0]
    assert origen == "uso" and uid == yo["usuario_id"] and abs(prob - a["probabilidad_tumor"]) < 1e-9
    assert fid == int(hoy.replace("-", ""))
    assert _sql("SELECT COUNT(*) FROM bitacora WHERE accion='ESTUDIO_CREADO'")[0][0] == 2

    # Confirmación: de acuerdo con la primera y en desacuerdo con la segunda.
    r = cli.post(f"/api/estudios/{a['prediccion_id']}/confirmacion",
                 json={"de_acuerdo": True, "diagnostico_real": a["tipo_probable"] or "tumor"} if a["hay_tumor"]
                 else {"de_acuerdo": True, "diagnostico_real": "sin_tumor"})
    assert r.status_code == 200, r.text
    est = r.json()
    assert set(est) == CAMPOS_ESTUDIO and est["de_acuerdo"] is True and est["diagnostico_confirmado"]
    real_b = "glioma" if not b["hay_tumor"] else "sin_tumor"
    r = cli.post(f"/api/estudios/{b['prediccion_id']}/confirmacion", json={"de_acuerdo": False,
                                                                          "diagnostico_real": real_b})
    assert r.status_code == 200 and r.json()["de_acuerdo"] is False
    assert cli.post(f"/api/estudios/{b['prediccion_id']}/confirmacion",
                    json={"de_acuerdo": True, "diagnostico_real": "inventado"}).status_code == 422

    # Historial filtrado.
    todos = cli.get("/api/estudios").json()["estudios"]
    assert len(todos) == 2 and all(set(e) == CAMPOS_ESTUDIO for e in todos)
    assert all(e["doctor"] == "doctor1" and e["identificador"] == "PAC-0001" for e in todos)
    acuerdo = cli.get("/api/estudios", params={"confirmacion": "de_acuerdo"}).json()["estudios"]
    assert [e["prediccion_id"] for e in acuerdo] == [a["prediccion_id"]]
    desac = cli.get("/api/estudios", params={"confirmacion": "desacuerdo", "identificador": "PAC-0001",
                                             "desde": hoy, "hasta": hoy}).json()["estudios"]
    assert [e["prediccion_id"] for e in desac] == [b["prediccion_id"]]
    assert cli.get("/api/estudios", params={"confirmacion": "pendiente"}).json()["estudios"] == []
    if conocido:
        tumor = cli.get("/api/estudios", params={"resultado": "tumor"}).json()["estudios"]
        assert [e["prediccion_id"] for e in tumor] == [a["prediccion_id"]]

    # Otro doctor no ve ni confirma estudios ajenos.
    otro = _cliente()
    _login(otro, "doctor2", "Doctor2026!", "doctor")
    ESTADO["doctor2"] = otro
    assert otro.get("/api/estudios").json()["estudios"] == []
    assert otro.post(f"/api/estudios/{a['prediccion_id']}/confirmacion",
                     json={"de_acuerdo": False, "diagnostico_real": "sin_tumor"}).status_code == 403


def test_archivo_no_imagen_e_identificador(cliente):
    cli = ESTADO["doctor1"]
    hoy = date.today().isoformat()
    r = cli.post("/api/estudios", data={"identificador": "PAC-0002", "edad": "30", "sexo": "M", "fecha_estudio": hoy},
                 files=[("archivos", ("radiografia.jpg", b"%PDF-1.4 no soy imagen", "image/jpeg"))])
    assert r.status_code == 200
    res = r.json()["resultados"]
    assert len(res) == 1 and set(res[0]) == {"archivo", "error"}
    for ident in ("Juan Pérez", "juan perez", "PACIENTE-1", "PAC0001", ""):
        r = cli.post("/api/estudios", data={"identificador": ident, "edad": "30", "sexo": "M", "fecha_estudio": hoy},
                     files=[("archivos", ("a.jpg", ESTADO["imagen_tumor"].read_bytes(), "image/jpeg"))])
        assert r.status_code == 422 and isinstance(r.json()["detail"], str), ident
    r = cli.post("/api/estudios", data={"identificador": "PAC-3", "edad": "130", "sexo": "M", "fecha_estudio": hoy},
                 files=[("archivos", ("a.jpg", ESTADO["imagen_tumor"].read_bytes(), "image/jpeg"))])
    assert r.status_code == 422


def test_media(cliente):
    url = ESTADO["a"]["gradcam_url"]
    assert _cliente().get(url).status_code == 401
    assert ESTADO["doctor2"].get(url).status_code == 403
    r = ESTADO["doctor1"].get(url)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert ESTADO["doctor1"].get("/media/..%2F..%2Fprueba.db").status_code == 404
    assert ESTADO["doctor1"].get("/media/no_existe.png").status_code == 404


def test_estaticos_no_pisan_api(cliente):
    assert cliente.get("/api/no-existe").status_code == 404
    assert cliente.get("/api/estado").status_code == 200


# ------------------------------------------------------------------ administrador
def test_resumen_usuarios_y_bitacora(admin):
    r = admin.get("/api/admin/resumen").json()
    assert r["estudios"] == 2 and r["confirmados"] == 2 and r["desacuerdos"] == 1
    assert r["modelo_produccion"]["version"] == "v001" and r["tiempo_promedio_ms"] > 0
    r = admin.post("/api/admin/usuarios", json={"usuario": "doctor3", "password": "Doctor2026!", "rol": "doctor"})
    assert r.status_code == 200 and "hash_password" not in r.json()
    uid = r.json()["usuario_id"]
    assert admin.post("/api/admin/usuarios", json={"usuario": "doctor3", "password": "Doctor2026!",
                                                   "rol": "doctor"}).status_code == 409
    assert admin.put(f"/api/admin/usuarios/{uid}", json={"activo": False}).json()["activo"] is False
    nuevo = _cliente()
    assert nuevo.post("/api/login", json={"usuario": "doctor3", "password": "Doctor2026!",
                                          "rol": "doctor"}).status_code == 401
    usuarios = admin.get("/api/admin/usuarios").json()["usuarios"]
    assert {u["usuario"] for u in usuarios} >= {"doctor1", "doctor2", "admin1", "doctor3"}
    assert all("hash_password" not in u for u in usuarios)
    b = admin.get("/api/admin/bitacora", params={"accion": "ACCESO_DENEGADO", "exito": "no"}).json()
    assert b["total"] >= len(RUTAS_ADMIN) and all(e["accion"] == "ACCESO_DENEGADO" for e in b["eventos"])
    assert "CARGA_DATOS" in b["acciones"] and b["pagina"] == 1
    r = admin.post("/api/admin/asistente", json={"pregunta": "¿Cuántos estudios hay?"}).json()
    assert r["estado"] == "sin_configurar"
    modelos = admin.get("/api/admin/modelos").json()["modelos"]
    assert sum(m["estado"] == "produccion" for m in modelos) == 1
    assert sum(m["estado"] == "referencia" for m in modelos) >= 1


def test_umbral(admin):
    r = admin.get("/api/admin/umbral", params={"valor": 0.5})
    assert r.status_code == 200, r.text
    u = r.json()
    assert {"valor", "actual", "n", "origen", "vp", "vn", "fp", "fn", "sensibilidad", "especificidad"} <= set(u)
    assert u["vp"] + u["vn"] + u["fp"] + u["fn"] == u["n"] > 0 and u["valor"] == 0.5
    anterior = u["actual"]
    assert admin.put("/api/admin/umbral", json={"valor": 1.5}).status_code == 422
    assert admin.put("/api/admin/umbral", json={"valor": 0.5}).status_code == 200
    assert admin.get("/api/estado").json()["modelo"]["umbral"] == 0.5
    r = ESTADO["doctor1"].post("/api/estudios", data={"identificador": "PAC-0001", "edad": "54", "sexo": "F",
                                                      "fecha_estudio": date.today().isoformat()},
                               files=[("archivos", ("x.jpg", ESTADO["imagen_tumor"].read_bytes(), "image/jpeg"))])
    assert r.json()["resultados"][0]["umbral"] == 0.5
    detalle = _sql("SELECT detalle FROM bitacora WHERE accion='UMBRAL_ACTUALIZADO' ORDER BY evento_id DESC")[0][0]
    assert f"{anterior:.4f}" in detalle and "0.5000" in detalle
    assert admin.put("/api/admin/umbral", json={"valor": anterior}).status_code == 200


def test_reentrenamiento_corto_aprobar_y_revertir(admin):
    r = admin.post("/api/admin/entrenamientos", json={"epocas_max": 2, "tasa": 0.001, "lote": 64, "kfold": False,
                                                      "ajuste_fino": False})
    assert r.status_code == 200, r.text
    eid = r.json()["entrenamiento_id"]
    d = _esperar(admin, eid, ("terminado", "error", "cancelado"))
    assert d["estado"] == "terminado", d["mensaje"]
    assert d["progreso"] == 1.0 and d["version"] and d["version"] != "v001"
    cabeza = [h for h in d["historial"] if h["etapa"] == "cabeza"]
    assert [h["epoca"] for h in cabeza] == [1, 2] and all(h["perdida_val"] is not None for h in cabeza)
    assert d["diagnostico"] and d["explicacion"] and d["mejor_epoca"] in (1, 2)
    assert isinstance(d["advertencias"], list)
    m = d["metricas"]
    assert m["origen"] == "validacion" and 0 <= m["sensibilidad"] <= 1
    # Las 2 imágenes confirmadas son de la partición de prueba: ninguna puede entrar al reentrenamiento.
    assert m["confirmadas_usadas"] == 0 and m["confirmadas_excluidas_por_prueba"] == 2
    (vn, fp), (fn, vp) = d["matriz_confusion"]
    assert vn + fp + fn + vp == m["n"] == m["n_validacion"]
    assert admin.get(d["curvas_url"]).headers["content-type"] == "image/png"
    carpeta = TMP / "modelos" / d["version"]
    assert {"modelo.keras", "info.json", "validacion.npz", "curvas_cabeza.png"} <= {p.name for p in carpeta.iterdir()}
    assert _sql("SELECT COUNT(*) FROM historial_epocas WHERE entrenamiento_id = ?", (eid,))[0][0] == 2
    assert _sql("SELECT COUNT(*) FROM bitacora WHERE accion='ENTRENAMIENTO_TERMINADO'")[0][0] == 1
    # El proceso de fondo firma el evento con el usuario que lo pidió y su IP.
    usuario, rol, ip = _sql("SELECT usuario, rol, ip FROM bitacora WHERE accion='ENTRENAMIENTO_TERMINADO'")[0]
    assert usuario == "admin1" and rol == "administrador" and ip
    lista =admin.get("/api/admin/entrenamientos").json()["entrenamientos"]
    assert lista[0]["entrenamiento_id"] == eid and lista[0]["version"] == d["version"]
    modelos = {x["version"]: x for x in admin.get("/api/admin/modelos").json()["modelos"] if x["tipo"] == "red_keras"}
    cand = modelos[d["version"]]
    assert cand["estado"] == "candidato" and cand["entrenamiento_id"] == eid

    # Aprobar: el candidato pasa a producción y v001 a retirado; se recarga el modelo.
    r = admin.post(f"/api/admin/modelos/{cand['modelo_id']}/aprobar")
    assert r.status_code == 200, r.text
    assert admin.get("/api/estado").json()["modelo"]["version"] == d["version"]
    modelos = {x["version"]: x["estado"] for x in admin.get("/api/admin/modelos").json()["modelos"]}
    assert modelos[d["version"]] == "produccion" and modelos["v001"] == "retirado"
    r = ESTADO["doctor1"].post("/api/estudios", data={"identificador": "PAC-0004", "edad": "40", "sexo": "Otro",
                                                      "fecha_estudio": date.today().isoformat()},
                               files=[("archivos", ("x.jpg", ESTADO["imagen_tumor"].read_bytes(), "image/jpeg"))])
    assert r.json()["resultados"][0]["modelo_version"] == d["version"]
    assert admin.post(f"/api/admin/modelos/{cand['modelo_id']}/aprobar").status_code == 409

    # Revertir: regresa a v001.
    r = admin.post("/api/admin/modelos/revertir")
    assert r.status_code == 200, r.text
    assert admin.get("/api/estado").json()["modelo"]["version"] == "v001"
    modelos = {x["version"]: x["estado"] for x in admin.get("/api/admin/modelos").json()["modelos"]}
    assert modelos["v001"] == "produccion" and modelos[d["version"]] == "retirado"
    acciones = {a for (a,) in _sql("SELECT accion FROM bitacora")}
    assert {"ENTRENAMIENTO_INICIADO", "MODELO_APROBADO", "MODELO_REVERTIDO"} <= acciones


def test_reentrenamiento_cancelado(admin):
    r = admin.post("/api/admin/entrenamientos", json={"epocas_max": 300, "tasa": 0.001, "lote": 64, "kfold": False,
                                                      "ajuste_fino": False, "paciencia": 300})
    assert r.status_code == 200, r.text
    eid = r.json()["entrenamiento_id"]
    _esperar(admin, eid, ("corriendo",), condicion=lambda d: (d["epoca_actual"] or 0) >= 1)
    assert admin.post("/api/admin/entrenamientos", json={"epocas_max": 2, "tasa": 0.001, "lote": 64,
                                                         "kfold": False, "ajuste_fino": False}).status_code == 409
    assert admin.post(f"/api/admin/entrenamientos/{eid}/cancelar").json() == {"ok": True}
    d = _esperar(admin, eid, ("cancelado",), condicion=lambda d: d["etapa"] == "cancelado")
    assert d["version"] is None and len(d["historial"]) < 300
    assert _sql("SELECT terminado_en IS NOT NULL FROM entrenamientos WHERE entrenamiento_id = ?", (eid,))[0][0] == 1
    assert _sql("SELECT COUNT(*) FROM bitacora WHERE accion='ENTRENAMIENTO_CANCELADO'")[0][0] >= 2
    filas = _sql("SELECT usuario, ip FROM bitacora WHERE accion='ENTRENAMIENTO_CANCELADO' AND detalle LIKE ?",
                 (f"Entrenamiento {eid}: se detuvo%",))
    assert len(filas) == 1 and filas[0][0] == "admin1" and filas[0][1]
    assert admin.post(f"/api/admin/entrenamientos/{eid}/cancelar").status_code == 409


def test_logout_admin(admin):
    assert admin.post("/api/logout").json() == {"ok": True}
    assert admin.get("/api/admin/resumen").status_code == 401
