"""Rutas públicas y de sesión: /api/estado, /api/login, /api/logout, /api/yo."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from .. import config, db, seguridad
from ..servicio_modelo import servicio
from ..tablas import usuarios

router = APIRouter(prefix="/api")


class Credenciales(BaseModel):
    usuario: str
    password: str
    rol: str


@router.get("/estado")
def estado():
    return {"modelo": servicio.estado(), "base_datos": config.DB_MODO,
            "asistente_configurado": config.asistente_configurado(), "powerbi_url": config.POWERBI_URL or None,
            "aviso": config.AVISO}


@router.post("/login")
def login(datos: Credenciales, request: Request, response: Response):
    ip = seguridad.ip_de(request)
    nombre = datos.usuario.strip()[:50]
    with db.motor().connect() as c:
        fila = c.execute(select(usuarios).where(usuarios.c.usuario == nombre)).mappings().first()
    if fila is None or not fila["activo"] or not seguridad.verificar_password(datos.password, fila["hash_password"]):
        motivo = "usuario inexistente" if fila is None else ("usuario inactivo" if not fila["activo"]
                                                              else "contraseña incorrecta")
        intento = {"usuario_id": fila["usuario_id"] if fila else None, "usuario": nombre or None, "rol": None}
        db.registrar("LOGIN_FALLIDO", f"Intento fallido: {motivo}", intento, ip, exito=False)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")
    usuario = {"usuario_id": fila["usuario_id"], "usuario": fila["usuario"], "rol": fila["rol"]}
    if datos.rol != fila["rol"]:
        db.registrar("LOGIN_FALLIDO", f"Rol elegido '{datos.rol[:20]}' no corresponde al usuario", usuario, ip,
                     exito=False)
        raise HTTPException(status_code=403, detail="Este usuario no tiene el rol elegido.")
    token = seguridad.crear_sesion(fila["usuario_id"])
    seguridad.poner_cookie(response, token)
    db.registrar("LOGIN_OK", f"Inicio de sesión como {fila['rol']}", usuario, ip)
    return usuario


@router.post("/logout")
def logout(request: Request, response: Response):
    usuario = seguridad.usuario_de_request(request)
    seguridad.cerrar_sesion(request.cookies.get(config.COOKIE_SESION))
    seguridad.quitar_cookie(response)
    if usuario:
        db.registrar("LOGOUT", "Cierre de sesión", usuario, seguridad.ip_de(request))
    return {"ok": True}


@router.get("/yo")
def yo(usuario=Depends(seguridad.requiere_sesion)):
    return usuario
