"""Rutas del Administrador (/api/admin/*). Un doctor recibe 403 y queda ACCESO_DENEGADO."""
import math
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import aliased

from .. import asistente as ia
from .. import catalogo, config, db, gestor_entrenamiento, seguridad
from ..servicio_modelo import servicio
from ..tablas import (bitacora, dim_diagnostico, dim_modelo, entrenamientos, hecho_prediccion, historial_epocas,
                      metricas_pliegue, usuarios)

router = APIRouter(prefix="/api/admin", dependencies=[Depends(seguridad.requiere_admin)])
POR_PAGINA = 50


def _error(mensaje, codigo=422):
    raise HTTPException(status_code=codigo, detail=mensaje)


def _f(v):
    if v is None:
        return None
    v = float(v)
    return None if math.isnan(v) else v


# ------------------------------------------------------------------ resumen
@router.get("/resumen")
def resumen():
    dp = aliased(dim_diagnostico)
    dc = aliased(dim_diagnostico)
    base = (select(hecho_prediccion.c.prediccion_id, hecho_prediccion.c.creado_en, hecho_prediccion.c.de_acuerdo,
                   hecho_prediccion.c.tiempo_respuesta_ms, hecho_prediccion.c.diagnostico_confirmado_id,
                   dp.c.es_tumor.label("pred"), dc.c.es_tumor.label("real"))
            .select_from(hecho_prediccion.join(dp, dp.c.diagnostico_id == hecho_prediccion.c.diagnostico_predicho_id)
                         .outerjoin(dc, dc.c.diagnostico_id == hecho_prediccion.c.diagnostico_confirmado_id))
            .where(hecho_prediccion.c.origen == "uso")).subquery()
    hoy = datetime.combine(date.today(), datetime.min.time())
    with db.motor().connect() as c:
        def n(*cond):
            return int(c.execute(select(func.count()).select_from(base).where(*cond)).scalar() or 0)
        estudios = n()
        con_tumor = n(base.c.pred == (True))
        r = {
            "estudios": estudios,
            "estudios_hoy": n(base.c.creado_en >= hoy),
            "con_tumor": con_tumor,
            "pct_tumor": round(100.0 * con_tumor / estudios, 1) if estudios else 0.0,
            "confirmados": n(base.c.diagnostico_confirmado_id.is_not(None)),
            "desacuerdos": n(base.c.de_acuerdo == (False)),
            "falsos_negativos": n(base.c.pred == (False), base.c.real == (True)),
            "falsos_positivos": n(base.c.pred == (True), base.c.real == (False)),
        }
        prom = c.execute(select(func.avg(base.c.tiempo_respuesta_ms))).scalar()
        r["tiempo_promedio_ms"] = round(float(prom), 1) if prom is not None else None
        prod = catalogo.modelo_produccion(c)
    r["modelo_produccion"] = None if prod is None else {"modelo_id": prod["modelo_id"], "version": prod["version"],
                                                        "nombre": prod["nombre"], "umbral": prod["umbral"]}
    return r


# ------------------------------------------------------------------ entrenamientos
class SolicitudEntrenamiento(BaseModel):
    epocas_max: int = 60
    tasa: float = 1e-3
    lote: int = 64
    kfold: bool = False
    ajuste_fino: bool = False
    paciencia: Optional[int] = None


@router.post("/entrenamientos")
def iniciar_entrenamiento(datos: SolicitudEntrenamiento, request: Request, usuario=Depends(seguridad.requiere_admin)):
    if not 1 <= datos.epocas_max <= 300:
        _error("epocas_max debe estar entre 1 y 300.")
    if not 1e-6 <= datos.tasa <= 0.1:
        _error("tasa debe estar entre 0.000001 y 0.1.")
    if not 8 <= datos.lote <= 512:
        _error("lote debe estar entre 8 y 512.")
    if datos.paciencia is not None and not 1 <= datos.paciencia <= 300:
        _error("paciencia debe estar entre 1 y 300.")
    parametros = datos.model_dump()
    if parametros["paciencia"] is None:
        parametros["paciencia"] = 8
    with db.motor().begin() as c:
        if gestor_entrenamiento.hay_activo(c):
            _error("Ya hay un entrenamiento en curso. Espera a que termine o cancélalo.", 409)
        eid = int(c.execute(insert(entrenamientos).values(
            # La IP de quien lo pide se guarda para que el proceso de fondo firme sus eventos en la bitácora.
            estado="en_cola", parametros=db.a_json({**parametros, "ip_solicitud": seguridad.ip_de(request)}),
            etapa="en_cola", epoca_actual=0,
            epocas_max=datos.epocas_max, progreso=0.0, mensaje="En cola", iniciado_en=db.ahora(),
            solicitado_por=usuario["usuario_id"])).inserted_primary_key[0])
    try:
        gestor_entrenamiento.lanzar(eid)
    except Exception as e:  # noqa: BLE001
        with db.motor().begin() as c:
            c.execute(update(entrenamientos).where(entrenamientos.c.entrenamiento_id == eid).values(
                estado="error", terminado_en=db.ahora(), mensaje=f"No se pudo lanzar el proceso: {type(e).__name__}"))
        db.registrar("ENTRENAMIENTO_ERROR", f"Entrenamiento {eid}: no se pudo lanzar", usuario,
                     seguridad.ip_de(request), exito=False)
        _error("No se pudo iniciar el entrenamiento.", 500)
    db.registrar("ENTRENAMIENTO_INICIADO", f"Entrenamiento {eid}: " + db.a_json(parametros), usuario,
                 seguridad.ip_de(request))
    return {"entrenamiento_id": eid}


@router.get("/entrenamientos")
def listar_entrenamientos():
    with db.motor().connect() as c:
        filas = c.execute(select(entrenamientos.c.entrenamiento_id, entrenamientos.c.estado,
                                 entrenamientos.c.iniciado_en, entrenamientos.c.terminado_en,
                                 entrenamientos.c.diagnostico, dim_modelo.c.version)
                          .select_from(entrenamientos.outerjoin(dim_modelo,
                                                                dim_modelo.c.modelo_id == entrenamientos.c.modelo_id))
                          .order_by(entrenamientos.c.entrenamiento_id.desc())).mappings().all()
    return {"entrenamientos": [{"entrenamiento_id": f["entrenamiento_id"], "estado": f["estado"],
                                "iniciado_en": db.iso(f["iniciado_en"]), "terminado_en": db.iso(f["terminado_en"]),
                                "version": f["version"], "diagnostico": f["diagnostico"]} for f in filas]}


def _fila_entrenamiento(c, eid):
    fila = c.execute(select(entrenamientos, dim_modelo.c.version)
                     .select_from(entrenamientos.outerjoin(dim_modelo,
                                                           dim_modelo.c.modelo_id == entrenamientos.c.modelo_id))
                     .where(entrenamientos.c.entrenamiento_id == eid)).mappings().first()
    if fila is None:
        _error("No existe ese entrenamiento.", 404)
    return fila


@router.get("/entrenamientos/{eid}")
def detalle_entrenamiento(eid: int):
    with db.motor().connect() as c:
        f = _fila_entrenamiento(c, eid)
        hist = c.execute(select(historial_epocas).where(historial_epocas.c.entrenamiento_id == eid)).mappings().all()
        pl = c.execute(select(metricas_pliegue).where(metricas_pliegue.c.entrenamiento_id == eid)
                       .order_by(metricas_pliegue.c.pliegue)).mappings().all()
    def orden(h):
        etapa = str(h["etapa"])
        grupo = 0 if etapa.startswith("pliegue") else {"cabeza": 1, "ajuste_fino": 2}.get(etapa, 3)
        return grupo, etapa, h["epoca"]
    hist = sorted(hist, key=orden)
    tiene_curvas = bool(f["curvas"] and f["version"] and (catalogo.carpeta(f["version"]) / f["curvas"]).is_file())
    return {
        "entrenamiento_id": f["entrenamiento_id"], "estado": f["estado"], "etapa": f["etapa"],
        "epoca_actual": f["epoca_actual"], "epocas_max": f["epocas_max"], "progreso": _f(f["progreso"]) or 0.0,
        "mensaje": f["mensaje"],
        "historial": [{"etapa": h["etapa"], "epoca": h["epoca"], "perdida": _f(h["perdida"]),
                       "exactitud": _f(h["exactitud"]), "perdida_val": _f(h["perdida_val"]),
                       "exactitud_val": _f(h["exactitud_val"]), "tasa_aprendizaje": _f(h["tasa_aprendizaje"])}
                      for h in hist],
        "metricas_pliegue": [{"pliegue": p["pliegue"], "sensibilidad": _f(p["sensibilidad"]),
                              "especificidad": _f(p["especificidad"]), "precision": _f(p["precision"]),
                              "f1": _f(p["f1"]), "auc": _f(p["auc"]), "vp": p["vp"], "vn": p["vn"], "fp": p["fp"],
                              "fn": p["fn"]} for p in pl],
        "mejor_epoca": f["mejor_epoca"], "diagnostico": f["diagnostico"], "explicacion": f["explicacion"],
        "advertencias": db.de_json(f["advertencias"], []) or [], "metricas": db.de_json(f["metricas"]),
        "matriz_confusion": db.de_json(f["matriz_confusion"]),
        "curvas_url": f"/api/admin/entrenamientos/{eid}/curvas" if tiene_curvas else None,
        "version": f["version"],
    }


@router.get("/entrenamientos/{eid}/curvas")
def curvas_entrenamiento(eid: int):
    with db.motor().connect() as c:
        f = _fila_entrenamiento(c, eid)
    if not (f["curvas"] and f["version"]) or not re.match(r"^[\w.-]+\.png$", f["curvas"]):
        _error("Este entrenamiento no tiene curvas.", 404)
    ruta = catalogo.carpeta(f["version"]) / f["curvas"]
    if not ruta.is_file():
        _error("Este entrenamiento no tiene curvas.", 404)
    return FileResponse(ruta, media_type="image/png")


@router.post("/entrenamientos/{eid}/cancelar")
def cancelar_entrenamiento(eid: int, request: Request, usuario=Depends(seguridad.requiere_admin)):
    with db.motor().begin() as c:
        f = _fila_entrenamiento(c, eid)
        if f["estado"] not in ("en_cola", "corriendo"):
            _error(f"El entrenamiento ya está en estado '{f['estado']}'.", 409)
        c.execute(update(entrenamientos).where(entrenamientos.c.entrenamiento_id == eid).values(
            estado="cancelado", mensaje="Cancelación solicitada; se detiene al terminar la época en curso."))
    db.registrar("ENTRENAMIENTO_CANCELADO", f"Entrenamiento {eid}: cancelación solicitada", usuario,
                 seguridad.ip_de(request))
    return {"ok": True}


# ------------------------------------------------------------------ modelos
@router.get("/modelos")
def listar_modelos():
    with db.motor().connect() as c:
        filas = c.execute(select(dim_modelo).order_by(dim_modelo.c.modelo_id)).mappings().all()
    return {"modelos": [{"modelo_id": f["modelo_id"], "version": f["version"], "nombre": f["nombre"], "tipo": f["tipo"],
                         "estado": f["estado"], "umbral": _f(f["umbral"]), "sensibilidad": _f(f["sensibilidad"]),
                         "especificidad": _f(f["especificidad"]), "f1": _f(f["f1"]), "auc": _f(f["auc"]),
                         "origen_metricas": f["origen_metricas"], "creado_en": db.iso(f["creado_en"]),
                         "entrenamiento_id": f["entrenamiento_id"]} for f in filas]}


def _recargar_o_error():
    if not servicio.cargar_produccion():
        _error("El modelo quedó registrado pero no se pudo cargar en memoria: " + (servicio.error or ""), 500)


@router.post("/modelos/revertir")
def revertir(request: Request, usuario=Depends(seguridad.requiere_admin)):
    with db.motor().begin() as c:
        actual = catalogo.modelo_produccion(c)
        q = (select(dim_modelo).where(dim_modelo.c.tipo == "red_keras", dim_modelo.c.estado == "retirado",
                                      dim_modelo.c.aprobado_en.is_not(None))
             .order_by(dim_modelo.c.aprobado_en.desc(), dim_modelo.c.modelo_id.desc()))
        if actual is not None:
            q = q.where(dim_modelo.c.modelo_id != actual["modelo_id"])
        anterior = c.execute(q).mappings().first()
        if anterior is None:
            _error("No hay una versión de producción anterior a la cual regresar.", 409)
        if actual is not None:
            c.execute(update(dim_modelo).where(dim_modelo.c.modelo_id == actual["modelo_id"]).values(estado="retirado"))
        c.execute(update(dim_modelo).where(dim_modelo.c.modelo_id == anterior["modelo_id"])
                  .values(estado="produccion", aprobado_en=db.ahora()))
    _recargar_o_error()
    db.registrar("MODELO_REVERTIDO", f"Producción: {actual['version'] if actual else '-'} -> {anterior['version']}",
                 usuario, seguridad.ip_de(request))
    return {"ok": True, "version": anterior["version"], "modelo_id": anterior["modelo_id"]}


@router.post("/modelos/{modelo_id}/aprobar")
def aprobar(modelo_id: int, request: Request, usuario=Depends(seguridad.requiere_admin)):
    with db.motor().begin() as c:
        m = c.execute(select(dim_modelo).where(dim_modelo.c.modelo_id == modelo_id)).mappings().first()
        if m is None:
            _error("No existe ese modelo.", 404)
        if m["estado"] != "candidato" or m["tipo"] != "red_keras":
            _error("Solo se puede aprobar un modelo candidato de la red.", 409)
        if not (catalogo.carpeta(m["version"]) / "info.json").is_file():
            _error("No se encontraron los archivos de esa versión.", 409)
        actual = catalogo.modelo_produccion(c)
        if actual is not None:
            c.execute(update(dim_modelo).where(dim_modelo.c.modelo_id == actual["modelo_id"]).values(estado="retirado"))
        c.execute(update(dim_modelo).where(dim_modelo.c.modelo_id == modelo_id)
                  .values(estado="produccion", aprobado_en=db.ahora()))
    _recargar_o_error()
    db.registrar("MODELO_APROBADO", f"Producción: {actual['version'] if actual else '-'} -> {m['version']}",
                 usuario, seguridad.ip_de(request))
    return {"ok": True, "version": m["version"], "modelo_id": modelo_id}


# ------------------------------------------------------------------ umbral
def _validacion_produccion():
    with db.motor().connect() as c:
        prod = catalogo.modelo_produccion(c)
    if prod is None:
        _error("No hay un modelo en producción.", 409)
    ruta = catalogo.carpeta(prod["version"]) / "validacion.npz"
    if not ruta.is_file():
        _error("El modelo en producción no tiene validacion.npz.", 409)
    with np.load(ruta, allow_pickle=False) as z:
        y, prob = np.asarray(z["y"]).astype(int), np.asarray(z["prob"], dtype=float)
        origen = str(z["origen"]) if "origen" in z.files else None
    if not origen:
        try:
            origen = catalogo.leer_info(prod["version"]).get("origen_umbral")
        except (OSError, ValueError):
            origen = None
    return prod, y, prob, origen


@router.get("/umbral")
def ver_umbral(valor: Optional[float] = None):
    prod, y, prob, origen = _validacion_produccion()
    actual = float(prod["umbral"])
    v = actual if valor is None else float(valor)
    if not 0.0 <= v <= 1.0:
        _error("El valor debe estar entre 0 y 1.")
    pred = prob >= v
    vp = int(((y == 1) & pred).sum())
    vn = int(((y == 0) & ~pred).sum())
    fp = int(((y == 0) & pred).sum())
    fn = int(((y == 1) & ~pred).sum())
    return {"valor": v, "actual": actual, "n": int(len(y)), "origen": origen, "vp": vp, "vn": vn, "fp": fp, "fn": fn,
            "sensibilidad": vp / (vp + fn) if vp + fn else 0.0, "especificidad": vn / (vn + fp) if vn + fp else 0.0,
            "version": prod["version"]}


class NuevoUmbral(BaseModel):
    valor: float


@router.put("/umbral")
def cambiar_umbral(datos: NuevoUmbral, request: Request, usuario=Depends(seguridad.requiere_admin)):
    if not 0.01 <= datos.valor <= 0.99:
        _error("El umbral debe estar entre 0.01 y 0.99.")
    with db.motor().begin() as c:
        prod = catalogo.modelo_produccion(c)
        if prod is None:
            _error("No hay un modelo en producción.", 409)
        c.execute(update(dim_modelo).where(dim_modelo.c.modelo_id == prod["modelo_id"]).values(umbral=float(datos.valor)))
    if servicio.modelo_id == prod["modelo_id"]:
        servicio.fijar_umbral(datos.valor)
    db.registrar("UMBRAL_ACTUALIZADO", f"{prod['version']}: umbral {float(prod['umbral']):.4f} -> {datos.valor:.4f}",
                 usuario, seguridad.ip_de(request))
    return {"ok": True, "valor": float(datos.valor), "anterior": float(prod["umbral"]), "version": prod["version"]}


# ------------------------------------------------------------------ usuarios
PATRON_USUARIO = re.compile(r"^[a-z0-9_.]{3,30}$")


def _usuario_publico(f):
    return {"usuario_id": f["usuario_id"], "usuario": f["usuario"], "rol": f["rol"], "activo": bool(f["activo"]),
            "creado_en": db.iso(f["creado_en"])}


@router.get("/usuarios")
def listar_usuarios():
    with db.motor().connect() as c:
        filas = c.execute(select(usuarios.c.usuario_id, usuarios.c.usuario, usuarios.c.rol, usuarios.c.activo,
                                 usuarios.c.creado_en).order_by(usuarios.c.usuario_id)).mappings().all()
    return {"usuarios": [_usuario_publico(f) for f in filas]}


class NuevoUsuario(BaseModel):
    usuario: str
    password: str
    rol: str


def _validar_password(p):
    if len(p) < 8 or len(p) > 72:
        _error("La contraseña debe tener entre 8 y 72 caracteres.")


@contextmanager
def _registrar_rechazo(accion, objetivo, usuario, request):
    """Si la operación se rechaza (HTTPException), deja el intento en la bitácora con exito=0."""
    try:
        yield
    except HTTPException as e:
        db.registrar(accion, f"Rechazado ({objetivo}): {e.detail}", usuario, seguridad.ip_de(request), exito=False)
        raise


@router.post("/usuarios")
def crear_usuario(datos: NuevoUsuario, request: Request, usuario=Depends(seguridad.requiere_admin)):
    with _registrar_rechazo("USUARIO_CREADO", f"usuario '{datos.usuario.strip()[:30]}'", usuario, request):
        return _crear_usuario(datos, request, usuario)


def _crear_usuario(datos, request, usuario):
    nombre = datos.usuario.strip().lower()
    if not PATRON_USUARIO.match(nombre):
        _error("El usuario debe tener de 3 a 30 caracteres: letras minúsculas, números, punto o guion bajo.")
    if datos.rol not in seguridad.ROLES:
        _error("El rol debe ser doctor o administrador.")
    _validar_password(datos.password)
    with db.motor().begin() as c:
        if c.execute(select(usuarios.c.usuario_id).where(usuarios.c.usuario == nombre)).first():
            _error("Ya existe un usuario con ese nombre.", 409)
        uid = c.execute(insert(usuarios).values(usuario=nombre, hash_password=seguridad.hash_password(datos.password),
                                                rol=datos.rol, activo=True, creado_en=db.ahora())).inserted_primary_key[0]
        f = c.execute(select(usuarios).where(usuarios.c.usuario_id == uid)).mappings().first()
    db.registrar("USUARIO_CREADO", f"Usuario '{nombre}' ({datos.rol})", usuario, seguridad.ip_de(request))
    return _usuario_publico(f)


class CambioUsuario(BaseModel):
    activo: Optional[bool] = None
    password: Optional[str] = None
    rol: Optional[str] = None


@router.put("/usuarios/{uid}")
def actualizar_usuario(uid: int, datos: CambioUsuario, request: Request, usuario=Depends(seguridad.requiere_admin)):
    with _registrar_rechazo("USUARIO_ACTUALIZADO", f"usuario_id {uid}", usuario, request):
        return _actualizar_usuario(uid, datos, request, usuario)


def _actualizar_usuario(uid, datos, request, usuario):
    cambios, partes = {}, []
    if datos.rol is not None:
        if datos.rol not in seguridad.ROLES:
            _error("El rol debe ser doctor o administrador.")
        cambios["rol"] = datos.rol
        partes.append(f"rol={datos.rol}")
    if datos.activo is not None:
        cambios["activo"] = bool(datos.activo)
        partes.append(f"activo={'sí' if datos.activo else 'no'}")
    if datos.password is not None:
        _validar_password(datos.password)
        cambios["hash_password"] = seguridad.hash_password(datos.password)
        partes.append("contraseña cambiada")
    if not cambios:
        _error("No hay cambios que aplicar.")
    if uid == usuario["usuario_id"] and (cambios.get("activo") is False or cambios.get("rol", "administrador")
                                         != "administrador"):
        _error("No puedes desactivarte ni quitarte el rol de administrador a ti mismo.", 409)
    with db.motor().begin() as c:
        f = c.execute(select(usuarios).where(usuarios.c.usuario_id == uid)).mappings().first()
        if f is None:
            _error("No existe ese usuario.", 404)
        c.execute(update(usuarios).where(usuarios.c.usuario_id == uid).values(**cambios))
        if "hash_password" in cambios or cambios.get("activo") is False or "rol" in cambios:
            seguridad.cerrar_sesiones_de(c, uid)
        f = c.execute(select(usuarios).where(usuarios.c.usuario_id == uid)).mappings().first()
    db.registrar("USUARIO_ACTUALIZADO", f"Usuario '{f['usuario']}': " + ", ".join(partes), usuario,
                 seguridad.ip_de(request))
    return _usuario_publico(f)


# ------------------------------------------------------------------ bitácora
@router.get("/bitacora")
def ver_bitacora(usuario: str = "", accion: str = "", exito: str = "", desde: str = "", hasta: str = "",
                 pagina: int = 1):
    q = select(bitacora)
    if usuario:
        q = q.where(bitacora.c.usuario == usuario.strip()[:50])
    if accion:
        q = q.where(bitacora.c.accion == accion.strip()[:40])
    if exito:
        if exito not in ("si", "no"):
            _error("'exito' debe ser si o no.")
        q = q.where(bitacora.c.exito == (exito == "si"))
    for valor, nombre in ((desde, "desde"), (hasta, "hasta")):
        if valor:
            try:
                d = date.fromisoformat(valor)
            except ValueError:
                _error(f"'{nombre}' debe tener el formato AAAA-MM-DD.")
            if nombre == "desde":
                q = q.where(bitacora.c.fecha_hora >= datetime.combine(d, datetime.min.time()))
            else:
                q = q.where(bitacora.c.fecha_hora < datetime.combine(d + timedelta(days=1), datetime.min.time()))
    pagina = max(1, int(pagina))
    with db.motor().connect() as c:
        total = db.contar(c, q)
        filas = c.execute(q.order_by(bitacora.c.evento_id.desc()).limit(POR_PAGINA)
                          .offset((pagina - 1) * POR_PAGINA)).mappings().all()
    return {"total": total, "pagina": pagina, "paginas": max(1, math.ceil(total / POR_PAGINA)),
            "eventos": [{"evento_id": f["evento_id"], "fecha_hora": db.iso(f["fecha_hora"]), "usuario": f["usuario"],
                         "rol": f["rol"], "accion": f["accion"], "detalle": f["detalle"], "ip": f["ip"],
                         "exito": bool(f["exito"])} for f in filas],
            "acciones": list(db.ACCIONES)}


# ------------------------------------------------------------------ asistente (Fase 5)
class Pregunta(BaseModel):
    pregunta: str = ""


@router.post("/asistente")
def asistente(datos: Pregunta, request: Request, usuario=Depends(seguridad.requiere_admin),
              cliente=Depends(ia.obtener_cliente)):
    """Asistente de consultas (ver app/backend/asistente.py). Sin clave responde 'sin_configurar'."""
    return ia.responder(datos.pregunta, usuario, seguridad.ip_de(request), cliente)
