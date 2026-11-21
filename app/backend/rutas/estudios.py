"""Estudios del Doctor: subir imágenes, confirmar, historial y /media."""
import re
import secrets
import time
from datetime import date, datetime, timedelta

import cv2
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import insert, or_, select, update
from sqlalchemy.orm import aliased

from .. import config, db, seguridad
from ..ml.config import NOMBRES_ES
from ..servicio_modelo import servicio
from ..tablas import dim_diagnostico, dim_fecha, dim_modelo, dim_paciente, hecho_prediccion, usuarios

router = APIRouter()

PATRON_ID = re.compile(config.PATRON_IDENTIFICADOR)
PATRON_MEDIA = re.compile(r"^[a-f0-9]{32}_(img|cam)\.png$")
SEXOS = ("F", "M", "Otro")
ETIQUETA_TUMOR = "Se detecta posible tumor"
ETIQUETA_SIN = "No se detecta tumor"


def _error(mensaje, codigo=422):
    raise HTTPException(status_code=codigo, detail=mensaje)


def grupo_edad(edad):
    if edad is None:
        return None
    if edad < 18:
        return "0-17"
    if edad < 40:
        return "18-39"
    if edad < 60:
        return "40-59"
    return "60+"


def tipo_contenido(datos):
    """'jpg' o 'png' según la firma del contenido (no la extensión); None si es otra cosa."""
    if datos[:3] == b"\xff\xd8\xff":
        return "jpg"
    if datos[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return None


def validar_identificador(valor):
    ident = (valor or "").strip().upper()
    if not PATRON_ID.match(ident):
        _error("El identificador debe ser ficticio con el formato PAC-0001 (2 a 5 letras, guion y 1 a 6 dígitos). "
               "No escribas nombres ni datos personales.")
    return ident


def _guardar_png(rgb, sufijo):
    nombre = f"{secrets.token_hex(16)}_{sufijo}.png"
    ok, buf = cv2.imencode(".png", rgb[..., ::-1])
    if not ok:
        raise RuntimeError("No se pudo codificar la imagen.")
    config.MEDIA.mkdir(parents=True, exist_ok=True)
    (config.MEDIA / nombre).write_bytes(buf.tobytes())
    return nombre


def _url(nombre):
    return f"/media/{nombre}" if nombre and PATRON_MEDIA.match(nombre) else None


def _confianza(prob, hay):
    return float(prob) if hay else float(1.0 - prob)


# ------------------------------------------------------------------ consulta de estudios
dp = aliased(dim_diagnostico, name="dp")
dc = aliased(dim_diagnostico, name="dc")


def consulta_estudios():
    return (select(hecho_prediccion.c.prediccion_id, hecho_prediccion.c.creado_en, hecho_prediccion.c.usuario_id,
                   dim_paciente.c.identificador, dim_paciente.c.edad, dim_paciente.c.sexo,
                   dim_fecha.c.fecha.label("fecha_estudio"), dp.c.es_tumor.label("hay_tumor"),
                   hecho_prediccion.c.probabilidad_tumor, hecho_prediccion.c.umbral,
                   hecho_prediccion.c.tipo_probable, hecho_prediccion.c.probabilidad_tipo,
                   dim_modelo.c.version.label("modelo_version"), hecho_prediccion.c.de_acuerdo,
                   dc.c.clave.label("diagnostico_confirmado"), hecho_prediccion.c.archivo_imagen,
                   hecho_prediccion.c.archivo_gradcam, hecho_prediccion.c.tiempo_respuesta_ms,
                   usuarios.c.usuario.label("doctor"))
            .select_from(hecho_prediccion
                         .join(dim_fecha, dim_fecha.c.fecha_id == hecho_prediccion.c.fecha_id)
                         .join(dim_modelo, dim_modelo.c.modelo_id == hecho_prediccion.c.modelo_id)
                         .join(dp, dp.c.diagnostico_id == hecho_prediccion.c.diagnostico_predicho_id)
                         .outerjoin(dc, dc.c.diagnostico_id == hecho_prediccion.c.diagnostico_confirmado_id)
                         .outerjoin(dim_paciente, dim_paciente.c.paciente_id == hecho_prediccion.c.paciente_id)
                         .outerjoin(usuarios, usuarios.c.usuario_id == hecho_prediccion.c.usuario_id))
            .where(hecho_prediccion.c.origen == "uso"))


def a_estudio(f):
    hay = bool(f["hay_tumor"])
    tipo = f["tipo_probable"] if hay else None
    return {"prediccion_id": f["prediccion_id"], "creado_en": db.iso(f["creado_en"]),
            "identificador": f["identificador"], "edad": f["edad"], "sexo": f["sexo"],
            "fecha_estudio": db.iso(f["fecha_estudio"]), "hay_tumor": hay,
            "etiqueta": ETIQUETA_TUMOR if hay else ETIQUETA_SIN, "probabilidad_tumor": float(f["probabilidad_tumor"]),
            "confianza": _confianza(f["probabilidad_tumor"], hay), "tipo_nombre": NOMBRES_ES.get(tipo) if tipo else None,
            "modelo_version": f["modelo_version"],
            "de_acuerdo": None if f["de_acuerdo"] is None else bool(f["de_acuerdo"]),
            "diagnostico_confirmado": f["diagnostico_confirmado"], "imagen_url": _url(f["archivo_imagen"]),
            "gradcam_url": _url(f["archivo_gradcam"]), "doctor": f["doctor"]}


# ------------------------------------------------------------------ subir estudio
@router.post("/api/estudios")
def crear_estudio(request: Request, identificador: str = Form(""), edad: str = Form(""), sexo: str = Form(""),
                  fecha_estudio: str = Form(""), archivos: list[UploadFile] = File(default=[]),
                  usuario=Depends(seguridad.requiere_sesion)):
    ident = validar_identificador(identificador)
    try:
        edad_n = int(str(edad).strip())
    except ValueError:
        edad_n = -1
    if not 0 <= edad_n <= 120:
        _error("La edad debe ser un número entero entre 0 y 120.")
    if sexo not in SEXOS:
        _error("El sexo debe ser F, M u Otro.")
    try:
        f_estudio = date.fromisoformat(str(fecha_estudio).strip())
    except ValueError:
        f_estudio = None
    if f_estudio is None or f_estudio < date(2000, 1, 1) or f_estudio > date.today() + timedelta(days=1):
        _error("La fecha del estudio debe tener el formato AAAA-MM-DD y no puede ser futura.")
    if not archivos:
        _error("Sube al menos una imagen.")
    if len(archivos) > config.MAX_ARCHIVOS:
        _error(f"Puedes subir como máximo {config.MAX_ARCHIVOS} imágenes por estudio.")
    if not servicio.cargado:
        _error("El modelo no está disponible en este momento.", 503)

    from ..ml.preprocesar import leer_bytes
    ip = seguridad.ip_de(request)
    with db.motor().begin() as c:
        fila = c.execute(select(dim_paciente.c.paciente_id).where(dim_paciente.c.identificador == ident)).first()
        datos_pac = {"edad": edad_n, "grupo_edad": grupo_edad(edad_n), "sexo": sexo}
        if fila is None:
            paciente_id = c.execute(insert(dim_paciente).values(identificador=ident, **datos_pac)).inserted_primary_key[0]
        else:
            paciente_id = fila[0]
            c.execute(update(dim_paciente).where(dim_paciente.c.paciente_id == paciente_id).values(**datos_pac))
        fecha_id = db.asegurar_fecha(c, f_estudio)

    resultados = []
    for archivo in archivos:
        nombre_archivo = (archivo.filename or "imagen")[:200]
        inicio = time.perf_counter()
        try:
            datos = archivo.file.read(config.MAX_BYTES + 1)
            if len(datos) > config.MAX_BYTES:
                resultados.append({"archivo": nombre_archivo, "error": "El archivo pesa más de 10 MB."})
                continue
            if tipo_contenido(datos) is None:
                resultados.append({"archivo": nombre_archivo, "error": "El archivo no es una imagen JPG o PNG."})
                continue
            try:
                img = leer_bytes(datos)
            except ValueError:
                resultados.append({"archivo": nombre_archivo, "error": "No se pudo leer la imagen: está dañada o no es válida."})
                continue
            r, modelo_id, version = servicio.predecir(img)
            nombre_img = _guardar_png(r["imagen_preparada"], "img")
            nombre_cam = _guardar_png(r["gradcam_superpuesto"], "cam")
            hay = bool(r["hay_tumor"])
            ms = round((time.perf_counter() - inicio) * 1000.0, 1)
            with db.motor().begin() as c:
                pid = c.execute(insert(hecho_prediccion).values(
                    paciente_id=paciente_id, fecha_id=fecha_id, usuario_id=usuario["usuario_id"], modelo_id=modelo_id,
                    diagnostico_predicho_id=db.ID_DIAGNOSTICO["tumor" if hay else "sin_tumor"],
                    diagnostico_confirmado_id=None, origen="uso", probabilidad_tumor=float(r["probabilidad_tumor"]),
                    umbral=float(r["umbral"]), tipo_probable=r["tipo_probable"] if hay else None,
                    probabilidad_tipo=float(r["probabilidad_tipo"]) if hay else None, de_acuerdo=None,
                    tiempo_respuesta_ms=ms, archivo_imagen=nombre_img, archivo_gradcam=nombre_cam,
                    creado_en=db.ahora())).inserted_primary_key[0]
                db.registrar("ESTUDIO_CREADO", f"Predicción {pid} con {version}: "
                             f"{'tumor' if hay else 'sin tumor'} (p={r['probabilidad_tumor']:.3f})",
                             usuario, ip, conexion=c)
            resultados.append({
                "prediccion_id": int(pid), "archivo": nombre_archivo, "hay_tumor": hay,
                "etiqueta": ETIQUETA_TUMOR if hay else ETIQUETA_SIN,
                "probabilidad_tumor": float(r["probabilidad_tumor"]),
                "confianza": _confianza(r["probabilidad_tumor"], hay), "umbral": float(r["umbral"]),
                "tipo_probable": r["tipo_probable"] if hay else None,
                "tipo_nombre": NOMBRES_ES.get(r["tipo_probable"]) if hay else None,
                "probabilidad_tipo": float(r["probabilidad_tipo"]) if hay else None,
                "imagen_url": _url(nombre_img), "gradcam_url": _url(nombre_cam), "modelo_version": version,
                "tiempo_respuesta_ms": ms, "aviso": config.AVISO})
        except Exception:  # noqa: BLE001 - una imagen con problema no tumba las demás
            resultados.append({"archivo": nombre_archivo, "error": "Ocurrió un error al procesar esta imagen."})
    return {"resultados": resultados}


# ------------------------------------------------------------------ confirmación
class Confirmacion(BaseModel):
    de_acuerdo: bool
    diagnostico_real: str


@router.post("/api/estudios/{prediccion_id}/confirmacion")
def confirmar(prediccion_id: int, datos: Confirmacion, request: Request, usuario=Depends(seguridad.requiere_sesion)):
    clave = datos.diagnostico_real.strip()
    if clave not in db.ID_DIAGNOSTICO:
        _error("diagnostico_real debe ser una de: " + ", ".join(db.ID_DIAGNOSTICO))
    with db.motor().connect() as c:
        fila = c.execute(consulta_estudios().where(hecho_prediccion.c.prediccion_id == prediccion_id)).mappings().first()
    if fila is None:
        _error("No existe ese estudio.", 404)
    if usuario["rol"] != "administrador" and fila["usuario_id"] != usuario["usuario_id"]:
        db.registrar("ACCESO_DENEGADO", f"Confirmar estudio ajeno {prediccion_id}", usuario,
                     seguridad.ip_de(request), exito=False)
        _error("Solo puedes confirmar tus propios estudios.", 403)
    if datos.de_acuerdo and bool(fila["hay_tumor"]) != db.ES_TUMOR[clave]:
        _error("Marcaste 'de acuerdo' pero el diagnóstico real contradice el resultado del sistema.")
    with db.motor().begin() as c:
        c.execute(update(hecho_prediccion).where(hecho_prediccion.c.prediccion_id == prediccion_id).values(
            de_acuerdo=bool(datos.de_acuerdo), diagnostico_confirmado_id=db.ID_DIAGNOSTICO[clave]))
        db.registrar("ESTUDIO_CONFIRMADO", f"Predicción {prediccion_id}: "
                     f"{'de acuerdo' if datos.de_acuerdo else 'en desacuerdo'}, real={clave}",
                     usuario, seguridad.ip_de(request), conexion=c)
        fila = c.execute(consulta_estudios().where(hecho_prediccion.c.prediccion_id == prediccion_id)).mappings().first()
    return a_estudio(fila)


# ------------------------------------------------------------------ historial
def _fecha_param(valor, nombre):
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        _error(f"'{nombre}' debe tener el formato AAAA-MM-DD.")


@router.get("/api/estudios")
def listar(desde: str = "", hasta: str = "", resultado: str = "", confirmacion: str = "", identificador: str = "",
           limite: int = 100, usuario=Depends(seguridad.requiere_sesion)):
    q = consulta_estudios()
    if usuario["rol"] != "administrador":
        q = q.where(hecho_prediccion.c.usuario_id == usuario["usuario_id"])
    d, h = _fecha_param(desde, "desde"), _fecha_param(hasta, "hasta")
    if d:
        q = q.where(hecho_prediccion.c.creado_en >= datetime.combine(d, datetime.min.time()))
    if h:
        q = q.where(hecho_prediccion.c.creado_en < datetime.combine(h + timedelta(days=1), datetime.min.time()))
    if resultado:
        if resultado not in ("tumor", "sin_tumor"):
            _error("'resultado' debe ser tumor o sin_tumor.")
        q = q.where(dp.c.es_tumor == (resultado == "tumor"))
    if confirmacion:
        if confirmacion == "pendiente":
            q = q.where(hecho_prediccion.c.diagnostico_confirmado_id.is_(None))
        elif confirmacion == "de_acuerdo":
            q = q.where(hecho_prediccion.c.de_acuerdo == (True))
        elif confirmacion == "desacuerdo":
            q = q.where(hecho_prediccion.c.de_acuerdo == (False))
        else:
            _error("'confirmacion' debe ser pendiente, de_acuerdo o desacuerdo.")
    if identificador:
        q = q.where(dim_paciente.c.identificador == identificador.strip().upper()[:20])
    limite = max(1, min(int(limite), 500))
    q = q.order_by(hecho_prediccion.c.creado_en.desc(), hecho_prediccion.c.prediccion_id.desc()).limit(limite)
    with db.motor().connect() as c:
        filas = c.execute(q).mappings().all()
    return {"estudios": [a_estudio(f) for f in filas]}


# ------------------------------------------------------------------ media
@router.get("/media/{nombre}")
def media(nombre: str, request: Request, usuario=Depends(seguridad.requiere_sesion)):
    if ".." in nombre or "/" in nombre or "\\" in nombre or not PATRON_MEDIA.match(nombre):
        _error("Nombre de archivo no válido.", 404)
    with db.motor().connect() as c:
        fila = c.execute(select(hecho_prediccion.c.usuario_id).where(
            hecho_prediccion.c.origen == "uso",
            or_(hecho_prediccion.c.archivo_imagen == nombre, hecho_prediccion.c.archivo_gradcam == nombre))).first()
    if fila is None:
        _error("No existe esa imagen.", 404)
    if usuario["rol"] != "administrador" and fila[0] != usuario["usuario_id"]:
        db.registrar("ACCESO_DENEGADO", "Imagen de otro doctor", usuario, seguridad.ip_de(request), exito=False)
        _error("No tienes permiso para ver esta imagen.", 403)
    ruta = config.MEDIA / nombre
    if not ruta.is_file():
        _error("No existe esa imagen.", 404)
    return FileResponse(ruta, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

