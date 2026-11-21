"""Contraseñas (bcrypt), sesiones en cookie httpOnly y dependencias de permisos."""
import hashlib
import secrets
from datetime import timedelta

import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, insert, select

from . import config, db
from .tablas import sesiones, usuarios

ROLES = ("doctor", "administrador")


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verificar_password(password, hash_guardado):
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hash_guardado.encode("ascii"))
    except (ValueError, TypeError):
        return False


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ip_de(request: Request):
    return request.client.host if request.client else None


def crear_sesion(usuario_id):
    """Crea una sesión y devuelve el token en claro (solo viaja en la cookie)."""
    token = secrets.token_urlsafe(32)
    ahora = db.ahora()
    with db.motor().begin() as c:
        c.execute(delete(sesiones).where(sesiones.c.expira_en < ahora))
        c.execute(insert(sesiones), [{"token_hash": hash_token(token), "usuario_id": usuario_id, "creada_en": ahora,
                                      "expira_en": ahora + timedelta(minutes=config.SESION_MINUTOS)}])
    return token


def cerrar_sesion(token):
    if token:
        with db.motor().begin() as c:
            c.execute(delete(sesiones).where(sesiones.c.token_hash == hash_token(token)))


def cerrar_sesiones_de(c, usuario_id):
    c.execute(delete(sesiones).where(sesiones.c.usuario_id == usuario_id))


def poner_cookie(respuesta, token):
    respuesta.set_cookie(config.COOKIE_SESION, token, max_age=config.SESION_MINUTOS * 60, httponly=True,
                         samesite="lax", secure=config.COOKIE_SEGURA, path="/")


def quitar_cookie(respuesta):
    respuesta.delete_cookie(config.COOKIE_SESION, path="/", httponly=True, samesite="lax",
                            secure=config.COOKIE_SEGURA)


def usuario_de_request(request: Request):
    """Dict {usuario_id, usuario, rol} de la sesión vigente, o None."""
    token = request.cookies.get(config.COOKIE_SESION)
    if not token or len(token) > 200:
        return None
    with db.motor().connect() as c:
        fila = c.execute(
            select(usuarios.c.usuario_id, usuarios.c.usuario, usuarios.c.rol)
            .select_from(sesiones.join(usuarios, usuarios.c.usuario_id == sesiones.c.usuario_id))
            .where(sesiones.c.token_hash == hash_token(token), sesiones.c.expira_en > db.ahora(),
                   usuarios.c.activo == (True))).mappings().first()
    return dict(fila) if fila else None


def requiere_sesion(request: Request):
    usuario = usuario_de_request(request)
    if usuario is None:
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
    return usuario


def requiere_admin(request: Request, usuario=Depends(requiere_sesion)):
    if usuario["rol"] != "administrador":
        db.registrar("ACCESO_DENEGADO", f"{request.method} {request.url.path}", usuario, ip_de(request), exito=False)
        raise HTTPException(status_code=403, detail="No tienes permiso para esta sección (solo administradores).")
    return usuario
