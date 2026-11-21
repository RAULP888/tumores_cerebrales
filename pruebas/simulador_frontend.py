"""Servidor simulado para probar el frontend sin el modelo real.

Cumple el contrato de la API de CLAUDE.md con respuestas fijas o generadas en memoria.
Los números que devuelve son DE DEMOSTRACIÓN: no son métricas ni resultados del modelo.
Sirve solo para revisar pantallas, flujos y manejo de errores del frontend.

Uso:
    .venv\\Scripts\\python.exe -m uvicorn pruebas.simulador_frontend:app --port 8011

Credenciales simuladas: doctor1 / Doctor2026!  ·  admin1 / Admin2026!
"""
from __future__ import annotations

import io
import math
import secrets
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Cookie, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, Response as RespuestaCruda
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFilter
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

RAIZ = Path(__file__).resolve().parents[1]
FRONTEND = RAIZ / "app" / "frontend"

app = FastAPI(title="Simulador del frontend")
candado = threading.Lock()

ACCIONES = ["LOGIN_OK", "LOGIN_FALLIDO", "LOGOUT", "ACCESO_DENEGADO", "ESTUDIO_CREADO", "ESTUDIO_CONFIRMADO",
            "ENTRENAMIENTO_INICIADO", "ENTRENAMIENTO_TERMINADO", "ENTRENAMIENTO_CANCELADO", "ENTRENAMIENTO_ERROR",
            "MODELO_APROBADO", "MODELO_REVERTIDO", "UMBRAL_ACTUALIZADO", "USUARIO_CREADO", "USUARIO_ACTUALIZADO",
            "CONSULTA_IA", "CONSULTA_IA_BLOQUEADA", "CARGA_DATOS"]
NOMBRES = {"glioma": "Glioma", "meningioma": "Meningioma", "pituitary": "Tumor hipofisario"}
ES_TUMOR = {"sin_tumor": False, "tumor": True, "glioma": True, "meningioma": True, "pituitary": True}
AVISO = "Resultado de apoyo. No sustituye el diagnóstico de un médico especialista."


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


ESTADO = {
    "usuarios": [
        {"usuario_id": 1, "usuario": "doctor1", "password": "Doctor2026!", "rol": "doctor", "activo": True, "creado_en": "2026-11-18T09:00:00"},
        {"usuario_id": 2, "usuario": "doctor2", "password": "Doctor2026!", "rol": "doctor", "activo": True, "creado_en": "2026-11-18T09:05:00"},
        {"usuario_id": 3, "usuario": "admin1", "password": "Admin2026!", "rol": "administrador", "activo": True, "creado_en": "2026-11-18T09:10:00"},
    ],
    "sesiones": {},
    "media": {},
    "estudios": [],
    "bitacora": [],
    "modelos": [
        {"modelo_id": 1, "version": "base-rl", "nombre": "Regresión logística (rasgos básicos)", "tipo": "clasico", "estado": "referencia",
         "umbral": 0.5, "sensibilidad": 0.861, "especificidad": 0.702, "f1": 0.874, "auc": 0.861, "creado_en": "2026-11-19T10:00:00", "entrenamiento_id": None},
        {"modelo_id": 2, "version": "v001", "nombre": "MobileNetV2 + cabeza densa", "tipo": "red_keras", "estado": "produccion",
         "umbral": 0.37, "sensibilidad": 0.982, "especificidad": 0.951, "f1": 0.978, "auc": 0.995, "creado_en": "2026-11-20T16:30:00", "entrenamiento_id": None},
    ],
    "entrenamientos": [],
    "umbral": 0.37,
}


def registrar(accion, detalle, usuario=None, exito=True, ip="127.0.0.1"):
    ESTADO["bitacora"].append({
        "evento_id": len(ESTADO["bitacora"]) + 1, "fecha_hora": ahora(),
        "usuario": usuario["usuario"] if usuario else None, "rol": usuario["rol"] if usuario else None,
        "accion": accion, "detalle": detalle, "ip": ip, "exito": exito})


for i in range(37):  # bitácora inicial para probar la paginación
    registrar(ACCIONES[i % 6], f"Evento simulado {i + 1}", ESTADO["usuarios"][i % 3], exito=(i % 7 != 3))


@app.exception_handler(StarletteHTTPException)
async def _http(_request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def error(mensaje, codigo=400):
    raise HTTPException(status_code=codigo, detail=mensaje)


def usuario_actual(ts_sesion: str | None):
    if not ts_sesion or ts_sesion not in ESTADO["sesiones"]:
        error("Inicie sesión para continuar.", 401)
    uid = ESTADO["sesiones"][ts_sesion]
    return next(u for u in ESTADO["usuarios"] if u["usuario_id"] == uid)


def admin_actual(ts_sesion):
    u = usuario_actual(ts_sesion)
    if u["rol"] != "administrador":
        registrar("ACCESO_DENEGADO", "Ruta de administrador", u, exito=False)
        error("Esta sección es solo para administradores.", 403)
    return u


def publico(u):
    return {"usuario_id": u["usuario_id"], "usuario": u["usuario"], "rol": u["rol"]}


def produccion():
    return next((m for m in ESTADO["modelos"] if m["estado"] == "produccion"), None)


# ------------------------------------------------------------------ público
@app.get("/api/estado")
def estado():
    p = produccion()
    return {"modelo": {"cargado": p is not None, "version": p and p["version"], "nombre": p and p["nombre"], "umbral": ESTADO["umbral"]},
            "base_datos": "local", "asistente_configurado": True, "powerbi_url": "", "aviso": AVISO}


class Login(BaseModel):
    usuario: str
    password: str
    rol: str


@app.post("/api/login")
def login(datos: Login, response: Response):
    u = next((x for x in ESTADO["usuarios"] if x["usuario"] == datos.usuario), None)
    if u is None or u["password"] != datos.password or not u["activo"]:
        registrar("LOGIN_FALLIDO", f"Usuario {datos.usuario}", None, exito=False)
        error("Usuario o contraseña incorrectos.", 401)
    if u["rol"] != datos.rol:
        registrar("LOGIN_FALLIDO", "Rol elegido distinto", u, exito=False)
        error("Su usuario no tiene el rol elegido. Elija el rol que le corresponde.", 403)
    token = secrets.token_urlsafe(24)
    ESTADO["sesiones"][token] = u["usuario_id"]
    response.set_cookie("ts_sesion", token, httponly=True, samesite="lax")
    registrar("LOGIN_OK", "Inicio de sesión", u)
    return publico(u)


@app.post("/api/logout")
def logout(response: Response, ts_sesion: str | None = Cookie(default=None)):
    if ts_sesion in ESTADO["sesiones"]:
        u = usuario_actual(ts_sesion)
        registrar("LOGOUT", "Cierre de sesión", u)
        ESTADO["sesiones"].pop(ts_sesion, None)
    response.delete_cookie("ts_sesion")
    return {"ok": True}


@app.get("/api/yo")
def yo(ts_sesion: str | None = Cookie(default=None)):
    return publico(usuario_actual(ts_sesion))


# ------------------------------------------------------------------ estudios
def mapa_simulado(imagen: Image.Image, semilla: int) -> Image.Image:
    base = imagen.convert("RGB").resize((256, 256))
    capa = Image.new("L", base.size, 0)
    d = ImageDraw.Draw(capa)
    cx, cy = 90 + (semilla * 37) % 90, 80 + (semilla * 53) % 100
    d.ellipse([cx - 45, cy - 40, cx + 45, cy + 40], fill=255)
    capa = capa.filter(ImageFilter.GaussianBlur(22))
    calor = Image.new("RGB", base.size, (255, 80, 0))
    return Image.composite(Image.blend(base, calor, 0.55), base, capa)


def guardar_png(imagen: Image.Image) -> str:
    nombre = secrets.token_hex(8) + ".png"
    buf = io.BytesIO()
    imagen.save(buf, format="PNG")
    ESTADO["media"][nombre] = buf.getvalue()
    return nombre


@app.get("/media/{nombre}")
def media(nombre: str, ts_sesion: str | None = Cookie(default=None)):
    usuario_actual(ts_sesion)
    if nombre not in ESTADO["media"]:
        error("No se encontró la imagen.", 404)
    return RespuestaCruda(ESTADO["media"][nombre], media_type="image/png")


@app.post("/api/estudios")
async def crear_estudio(identificador: str = Form(""), edad: str = Form(""), sexo: str = Form(""),
                        fecha_estudio: str = Form(""), archivos: list[UploadFile] = File(default=[]),
                        ts_sesion: str | None = Cookie(default=None)):
    u = usuario_actual(ts_sesion)
    import re
    if not re.match(r"^[A-Z]{2,5}-\d{1,6}$", identificador):
        error("El identificador debe tener el formato PAC-0001.")
    if not archivos:
        error("Sube al menos una imagen.")
    if len(archivos) > 8:
        error("Puedes subir como máximo 8 imágenes por estudio.")
    time.sleep(0.6)
    resultados = []
    p = produccion()
    for i, archivo in enumerate(archivos):
        datos = await archivo.read()
        try:
            img = Image.open(io.BytesIO(datos))
            img.load()
        except Exception:  # noqa: BLE001
            resultados.append({"archivo": archivo.filename, "error": "No se pudo leer la imagen: está dañada o no es válida."})
            continue
        semilla = len(ESTADO["estudios"]) + i
        prob = [0.94, 0.08, 0.71, 0.22][semilla % 4]
        hay = prob >= ESTADO["umbral"]
        tipo = ["meningioma", None, "glioma", None][semilla % 4] if hay else None
        n_img = guardar_png(img.convert("RGB").resize((256, 256)))
        n_cam = guardar_png(mapa_simulado(img, semilla))
        pid = len(ESTADO["estudios"]) + 1
        estudio = {
            "prediccion_id": pid, "creado_en": ahora(), "identificador": identificador, "edad": int(edad), "sexo": sexo,
            "fecha_estudio": fecha_estudio, "hay_tumor": hay, "etiqueta": "Se detecta posible tumor" if hay else "No se detecta tumor",
            "probabilidad_tumor": prob, "confianza": prob if hay else 1 - prob, "tipo_probable": tipo,
            "tipo_nombre": NOMBRES.get(tipo) if tipo else None, "probabilidad_tipo": 0.85 if tipo else None,
            "modelo_version": p["version"], "de_acuerdo": None, "diagnostico_confirmado": None,
            "imagen_url": f"/media/{n_img}", "gradcam_url": f"/media/{n_cam}", "doctor": u["usuario"],
            "usuario_id": u["usuario_id"], "umbral": ESTADO["umbral"], "tiempo_respuesta_ms": 412.5 + 30 * i,
        }
        ESTADO["estudios"].append(estudio)
        registrar("ESTUDIO_CREADO", f"Predicción {pid}", u)
        resultados.append({k: estudio[k] for k in ("prediccion_id", "hay_tumor", "etiqueta", "probabilidad_tumor", "confianza", "umbral",
                                                   "tipo_probable", "tipo_nombre", "probabilidad_tipo", "imagen_url", "gradcam_url",
                                                   "modelo_version", "tiempo_respuesta_ms")} | {"archivo": archivo.filename, "aviso": AVISO})
    return {"resultados": resultados}


class Confirmacion(BaseModel):
    de_acuerdo: bool
    diagnostico_real: str


def a_publico(e):
    return {k: v for k, v in e.items() if k not in ("usuario_id", "umbral", "tiempo_respuesta_ms", "tipo_probable", "probabilidad_tipo")}


@app.post("/api/estudios/{pid}/confirmacion")
def confirmar(pid: int, datos: Confirmacion, ts_sesion: str | None = Cookie(default=None)):
    u = usuario_actual(ts_sesion)
    e = next((x for x in ESTADO["estudios"] if x["prediccion_id"] == pid), None)
    if e is None:
        error("No existe ese estudio.", 404)
    if u["rol"] != "administrador" and e["usuario_id"] != u["usuario_id"]:
        error("Solo puedes confirmar tus propios estudios.", 403)
    if datos.diagnostico_real not in ES_TUMOR:
        error("diagnostico_real no es válido.")
    if datos.de_acuerdo and ES_TUMOR[datos.diagnostico_real] != e["hay_tumor"]:
        error("Marcaste 'de acuerdo' pero el diagnóstico real contradice el resultado del sistema.")
    e["de_acuerdo"] = datos.de_acuerdo
    e["diagnostico_confirmado"] = datos.diagnostico_real
    registrar("ESTUDIO_CONFIRMADO", f"Predicción {pid}", u)
    return a_publico(e)


@app.get("/api/estudios")
def listar_estudios(desde: str = "", hasta: str = "", resultado: str = "", confirmacion: str = "", identificador: str = "",
                    limite: int = 100, ts_sesion: str | None = Cookie(default=None)):
    u = usuario_actual(ts_sesion)
    lista = [e for e in ESTADO["estudios"] if u["rol"] == "administrador" or e["usuario_id"] == u["usuario_id"]]
    if resultado:
        lista = [e for e in lista if e["hay_tumor"] == (resultado == "tumor")]
    if confirmacion == "pendiente":
        lista = [e for e in lista if e["de_acuerdo"] is None]
    elif confirmacion == "de_acuerdo":
        lista = [e for e in lista if e["de_acuerdo"] is True]
    elif confirmacion == "desacuerdo":
        lista = [e for e in lista if e["de_acuerdo"] is False]
    if identificador:
        lista = [e for e in lista if identificador.upper() in e["identificador"]]
    if desde:
        lista = [e for e in lista if e["creado_en"][:10] >= desde]
    if hasta:
        lista = [e for e in lista if e["creado_en"][:10] <= hasta]
    return {"estudios": [a_publico(e) for e in reversed(lista)][:limite]}


# ------------------------------------------------------------------ administrador
@app.get("/api/admin/resumen")
def resumen(ts_sesion: str | None = Cookie(default=None)):
    admin_actual(ts_sesion)
    es = ESTADO["estudios"]
    con = sum(e["hay_tumor"] for e in es)
    p = produccion()
    return {"estudios": len(es), "estudios_hoy": sum(e["creado_en"][:10] == date.today().isoformat() for e in es),
            "con_tumor": con, "pct_tumor": round(100 * con / len(es), 1) if es else 0.0,
            "confirmados": sum(e["de_acuerdo"] is not None for e in es),
            "desacuerdos": sum(e["de_acuerdo"] is False for e in es),
            "falsos_negativos": sum(e["de_acuerdo"] is False and not e["hay_tumor"] for e in es),
            "falsos_positivos": sum(e["de_acuerdo"] is False and e["hay_tumor"] for e in es),
            "tiempo_promedio_ms": round(sum(e["tiempo_respuesta_ms"] for e in es) / len(es), 1) if es else None,
            "modelo_produccion": p and {"modelo_id": p["modelo_id"], "version": p["version"], "nombre": p["nombre"], "umbral": ESTADO["umbral"]}}


class Parametros(BaseModel):
    epocas_max: int
    tasa: float
    lote: int
    kfold: bool
    ajuste_fino: bool


DURACION_POR_EPOCA = 0.25  # segundos simulados


def historial_simulado(epocas, kfold, ajuste_fino):
    etapas = []
    if kfold:
        etapas += [(f"pliegue_{k}", min(epocas, 12)) for k in range(1, 6)]
    etapas.append(("cabeza", min(epocas, 14)))
    if ajuste_fino:
        etapas.append(("ajuste_fino", min(epocas, 8)))
    filas = []
    for etapa, n in etapas:
        desplazamiento = 0.0 if etapa != "ajuste_fino" else -0.08
        for ep in range(1, n + 1):
            perdida = 0.55 * math.exp(-ep / 4) + 0.08 + desplazamiento * 0.3
            perdida_val = 0.5 * math.exp(-ep / 3.5) + 0.12 + 0.004 * max(0, ep - 9) ** 2 + desplazamiento * 0.2
            filas.append({"etapa": etapa, "epoca": ep, "perdida": round(perdida, 4), "perdida_val": round(perdida_val, 4),
                          "exactitud": round(min(0.995, 0.78 + 0.2 * (1 - math.exp(-ep / 3))), 4),
                          "exactitud_val": round(min(0.985, 0.76 + 0.19 * (1 - math.exp(-ep / 3)) - 0.002 * max(0, ep - 9)), 4),
                          "tasa_aprendizaje": 0.001 if etapa != "ajuste_fino" else 1e-5})
    return filas


def avanzar(ent):
    """Calcula el avance del entrenamiento simulado según el tiempo transcurrido."""
    if ent["estado"] in ("terminado", "cancelado", "error"):
        return
    total = len(ent["_historial"])
    transcurrido = time.time() - ent["_inicio"]
    hechas = min(total, int(transcurrido / DURACION_POR_EPOCA))
    ent["historial"] = ent["_historial"][:hechas]
    if ent.get("_cancelar"):
        ent["estado"] = "cancelado"
        ent["mensaje"] = "Entrenamiento cancelado por el administrador."
        ent["diagnostico"] = "cancelado"
        ent["explicacion"] = f"El entrenamiento se canceló tras {hechas} épocas. No se puede decir si convergió."
        ent["terminado_en"] = ahora()
        return
    if hechas == 0:
        ent["estado"] = "en_cola" if transcurrido < 0.5 else "corriendo"
        ent["mensaje"] = "Preparando los datos de entrenamiento…"
        return
    actual = ent["historial"][-1]
    ent["estado"] = "corriendo"
    ent["etapa"] = actual["etapa"]
    ent["epoca_actual"] = actual["epoca"]
    ent["progreso"] = round(hechas / total, 3)
    ent["mensaje"] = f"Entrenando {actual['etapa'].replace('_', ' ')}: época {actual['epoca']}."
    if hechas >= total:
        ultima = [h for h in ent["historial"] if h["etapa"] == actual["etapa"]]
        mejor = min(ultima, key=lambda h: h["perdida_val"])["epoca"]
        version = f"v{len(ESTADO['modelos']):03d}"
        ent.update({"estado": "terminado", "progreso": 1.0, "mensaje": "Entrenamiento terminado. Nueva versión candidata.",
                    "mejor_epoca": mejor, "diagnostico": "convergió",
                    "explicacion": f"(Simulado) La pérdida de validación llegó a su mínimo en la época {mejor} y la detención temprana actuó.",
                    "advertencias": ["(Simulado) Señales de memorización leves: la exactitud de entrenamiento supera a la de validación."],
                    "metricas": {"sensibilidad": 0.981, "especificidad": 0.947, "precision": 0.982, "f1": 0.981, "auc": 0.994, "umbral": 0.35},
                    "matriz_confusion": [[267, 15], [16, 832]], "version": version, "terminado_en": ahora(),
                    "metricas_pliegue": [{"pliegue": k, "sensibilidad": 0.975 + k * 0.002, "especificidad": 0.94 + k * 0.004, "precision": 0.98,
                                          "f1": 0.978, "auc": 0.993, "vp": 678 + k, "vn": 225 - k, "fp": 13, "fn": 17 - k} for k in range(1, 6)]
                    if ent["_kfold"] else []})
        ESTADO["modelos"].append({"modelo_id": len(ESTADO["modelos"]) + 1, "version": version, "nombre": "MobileNetV2 + cabeza densa (reentrenado)",
                                  "tipo": "red_keras", "estado": "candidato", "umbral": 0.35, "sensibilidad": 0.981, "especificidad": 0.947,
                                  "f1": 0.981, "auc": 0.994, "creado_en": ahora(), "entrenamiento_id": ent["entrenamiento_id"]})


def publico_entrenamiento(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


@app.post("/api/admin/entrenamientos")
def iniciar_entrenamiento(datos: Parametros, ts_sesion: str | None = Cookie(default=None)):
    u = admin_actual(ts_sesion)
    with candado:
        for e in ESTADO["entrenamientos"]:
            avanzar(e)
            if e["estado"] in ("en_cola", "corriendo"):
                error("Ya hay un entrenamiento en curso. Espere a que termine o cancélelo.", 409)
        if not 1 <= datos.epocas_max <= 100:
            error("Las épocas máximas deben estar entre 1 y 100.")
        eid = len(ESTADO["entrenamientos"]) + 1
        ESTADO["entrenamientos"].append({
            "entrenamiento_id": eid, "estado": "en_cola", "etapa": None, "epoca_actual": 0, "epocas_max": datos.epocas_max,
            "progreso": 0.0, "mensaje": "En cola", "historial": [], "metricas_pliegue": [], "mejor_epoca": None, "diagnostico": None,
            "explicacion": None, "advertencias": [], "metricas": None, "matriz_confusion": None, "curvas_url": None, "version": None,
            "iniciado_en": ahora(), "terminado_en": None,
            "_inicio": time.time(), "_historial": historial_simulado(datos.epocas_max, datos.kfold, datos.ajuste_fino), "_kfold": datos.kfold})
        registrar("ENTRENAMIENTO_INICIADO", f"Entrenamiento {eid}", u)
    return {"entrenamiento_id": eid}


@app.get("/api/admin/entrenamientos")
def listar_entrenamientos(ts_sesion: str | None = Cookie(default=None)):
    admin_actual(ts_sesion)
    for e in ESTADO["entrenamientos"]:
        avanzar(e)
    return {"entrenamientos": [{k: e[k] for k in ("entrenamiento_id", "estado", "iniciado_en", "terminado_en", "version", "diagnostico")}
                               for e in reversed(ESTADO["entrenamientos"])]}


@app.get("/api/admin/entrenamientos/{eid}")
def detalle_entrenamiento(eid: int, ts_sesion: str | None = Cookie(default=None)):
    admin_actual(ts_sesion)
    e = next((x for x in ESTADO["entrenamientos"] if x["entrenamiento_id"] == eid), None)
    if e is None:
        error("No existe ese entrenamiento.", 404)
    avanzar(e)
    return publico_entrenamiento(e)


@app.post("/api/admin/entrenamientos/{eid}/cancelar")
def cancelar(eid: int, ts_sesion: str | None = Cookie(default=None)):
    u = admin_actual(ts_sesion)
    e = next((x for x in ESTADO["entrenamientos"] if x["entrenamiento_id"] == eid), None)
    if e is None:
        error("No existe ese entrenamiento.", 404)
    if e["estado"] not in ("en_cola", "corriendo"):
        error(f"El entrenamiento ya está en estado '{e['estado']}'.", 409)
    e["_cancelar"] = True
    registrar("ENTRENAMIENTO_CANCELADO", f"Entrenamiento {eid}", u)
    return {"ok": True}


@app.get("/api/admin/modelos")
def modelos(ts_sesion: str | None = Cookie(default=None)):
    admin_actual(ts_sesion)
    return {"modelos": ESTADO["modelos"]}


@app.post("/api/admin/modelos/{mid}/aprobar")
def aprobar(mid: int, ts_sesion: str | None = Cookie(default=None)):
    u = admin_actual(ts_sesion)
    m = next((x for x in ESTADO["modelos"] if x["modelo_id"] == mid), None)
    if m is None or m["estado"] != "candidato":
        error("Solo se puede aprobar un modelo candidato.", 409)
    p = produccion()
    if p:
        p["estado"] = "retirado"
    m["estado"] = "produccion"
    ESTADO["umbral"] = m["umbral"]
    registrar("MODELO_APROBADO", m["version"], u)
    return {"ok": True, "version": m["version"], "modelo_id": mid}


@app.post("/api/admin/modelos/revertir")
def revertir(ts_sesion: str | None = Cookie(default=None)):
    u = admin_actual(ts_sesion)
    retirados = [m for m in ESTADO["modelos"] if m["estado"] == "retirado"]
    if not retirados:
        error("No hay una versión anterior a la cual regresar.", 409)
    p = produccion()
    if p:
        p["estado"] = "retirado"
    anterior = retirados[-1]
    anterior["estado"] = "produccion"
    ESTADO["umbral"] = anterior["umbral"]
    registrar("MODELO_REVERTIDO", anterior["version"], u)
    return {"ok": True, "version": anterior["version"], "modelo_id": anterior["modelo_id"]}


def metricas_umbral(valor):
    # Curva de demostración: 1,130 casos de validación (848 con tumor, 282 sin tumor).
    fn = round(848 * (valor ** 3) * 0.35)
    fp = round(282 * ((1 - valor) ** 3) * 0.45)
    vp, vn = 848 - fn, 282 - fp
    return {"valor": round(valor, 2), "actual": ESTADO["umbral"], "n": 1130, "origen": "validación (simulada)",
            "vp": vp, "vn": vn, "fp": fp, "fn": fn, "sensibilidad": vp / 848, "especificidad": vn / 282}


@app.get("/api/admin/umbral")
def ver_umbral(valor: float, ts_sesion: str | None = Cookie(default=None)):
    admin_actual(ts_sesion)
    if not 0.01 <= valor <= 0.99:
        error("El umbral debe estar entre 0.01 y 0.99.")
    return metricas_umbral(valor)


class Umbral(BaseModel):
    valor: float


@app.put("/api/admin/umbral")
def guardar_umbral(datos: Umbral, ts_sesion: str | None = Cookie(default=None)):
    u = admin_actual(ts_sesion)
    if not 0.01 <= datos.valor <= 0.99:
        error("El umbral debe estar entre 0.01 y 0.99.")
    anterior = ESTADO["umbral"]
    ESTADO["umbral"] = round(datos.valor, 2)
    produccion()["umbral"] = ESTADO["umbral"]
    registrar("UMBRAL_ACTUALIZADO", f"{anterior} → {ESTADO['umbral']}", u)
    return {"ok": True, "valor": ESTADO["umbral"], "anterior": anterior, "version": produccion()["version"]}


def usuario_publico(u):
    return {k: u[k] for k in ("usuario_id", "usuario", "rol", "activo", "creado_en")}


@app.get("/api/admin/usuarios")
def usuarios(ts_sesion: str | None = Cookie(default=None)):
    admin_actual(ts_sesion)
    return {"usuarios": [usuario_publico(u) for u in ESTADO["usuarios"]]}


class NuevoUsuario(BaseModel):
    usuario: str
    password: str
    rol: str


@app.post("/api/admin/usuarios")
def crear_usuario(datos: NuevoUsuario, ts_sesion: str | None = Cookie(default=None)):
    u = admin_actual(ts_sesion)
    if any(x["usuario"] == datos.usuario for x in ESTADO["usuarios"]):
        error("Ya existe un usuario con ese nombre.", 409)
    if datos.rol not in ("doctor", "administrador"):
        error("El rol no es válido.")
    nuevo = {"usuario_id": len(ESTADO["usuarios"]) + 1, "usuario": datos.usuario, "password": datos.password, "rol": datos.rol,
             "activo": True, "creado_en": ahora()}
    ESTADO["usuarios"].append(nuevo)
    registrar("USUARIO_CREADO", datos.usuario, u)
    return usuario_publico(nuevo)


class CambioUsuario(BaseModel):
    activo: bool | None = None
    password: str | None = None
    rol: str | None = None


@app.put("/api/admin/usuarios/{uid}")
def cambiar_usuario(uid: int, datos: CambioUsuario, ts_sesion: str | None = Cookie(default=None)):
    u = admin_actual(ts_sesion)
    x = next((v for v in ESTADO["usuarios"] if v["usuario_id"] == uid), None)
    if x is None:
        error("No existe ese usuario.", 404)
    if datos.activo is False and uid == u["usuario_id"]:
        error("No puede desactivar su propia cuenta.")
    for campo in ("activo", "password", "rol"):
        if getattr(datos, campo) is not None:
            x[campo] = getattr(datos, campo)
    registrar("USUARIO_ACTUALIZADO", x["usuario"], u)
    return usuario_publico(x)


@app.get("/api/admin/bitacora")
def bitacora(usuario: str = "", accion: str = "", exito: str = "", desde: str = "", hasta: str = "", pagina: int = 1,
             ts_sesion: str | None = Cookie(default=None)):
    admin_actual(ts_sesion)
    lista = list(reversed(ESTADO["bitacora"]))
    if usuario:
        lista = [e for e in lista if e["usuario"] and usuario.lower() in e["usuario"].lower()]
    if accion:
        lista = [e for e in lista if e["accion"] == accion]
    if exito in ("si", "no"):
        lista = [e for e in lista if e["exito"] == (exito == "si")]
    if desde:
        lista = [e for e in lista if e["fecha_hora"][:10] >= desde]
    if hasta:
        lista = [e for e in lista if e["fecha_hora"][:10] <= hasta]
    por_pagina = 25
    paginas = max(1, math.ceil(len(lista) / por_pagina))
    pagina = max(1, min(pagina, paginas))
    return {"total": len(lista), "pagina": pagina, "paginas": paginas,
            "eventos": lista[(pagina - 1) * por_pagina: pagina * por_pagina], "acciones": ACCIONES}


class Pregunta(BaseModel):
    pregunta: str


@app.post("/api/admin/asistente")
def asistente(datos: Pregunta, ts_sesion: str | None = Cookie(default=None)):
    u = admin_actual(ts_sesion)
    texto = datos.pregunta.lower()
    if any(p in texto for p in ("borra", "elimina", "delete", "drop", "update", "actualiza")):
        registrar("CONSULTA_IA_BLOQUEADA", datos.pregunta[:80], u, exito=False)
        return {"estado": "bloqueada", "respuesta": "La solicitud pedía modificar datos y se rechazó.",
                "sql": "DELETE FROM hecho_prediccion", "columnas": [], "filas": []}
    registrar("CONSULTA_IA", datos.pregunta[:80], u)
    return {"estado": "ok",
            "respuesta": "(Simulado) Esta semana doctor1 registró 3 estudios con posible tumor y doctor2 registró 1.",
            "sql": "SELECT u.usuario AS doctor, COUNT(*) AS estudios_con_tumor\nFROM hecho_prediccion h\n"
                   "JOIN dim_usuario u ON u.usuario_id = h.usuario_id\nJOIN dim_fecha f ON f.fecha_id = h.fecha_id\n"
                   "WHERE h.origen = 'uso' AND h.diagnostico_predicho_id = 2 AND f.fecha >= :inicio_semana\n"
                   "GROUP BY u.usuario\nORDER BY estudios_con_tumor DESC",
            "columnas": ["doctor", "estudios_con_tumor"], "filas": [["doctor1", 3], ["doctor2", 1], ["<b>no-html</b>", 0]]}


app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
