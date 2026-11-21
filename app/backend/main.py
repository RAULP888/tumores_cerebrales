"""Aplicación FastAPI.

Arranque: .venv\\Scripts\\python.exe -m uvicorn app.backend.main:app --port 8000

- /api/...   API (contrato en CLAUDE.md)
- /media/... imágenes guardadas (requiere sesión)
- /          app/frontend/ como archivos estáticos (index.html por omisión)
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import catalogo, config, db, gestor_entrenamiento
from .rutas import admin, estudios, publico
from .servicio_modelo import servicio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tumores")


def preparar_base():
    config.asegurar_carpetas()
    db.crear_esquema()
    db.llenar_dimensiones()
    catalogo.asegurar_produccion()
    n = gestor_entrenamiento.limpiar_huerfanos()
    if n:
        log.warning("%d entrenamiento(s) huérfano(s) marcados como error", n)


@asynccontextmanager
async def ciclo_de_vida(_app):
    preparar_base()
    servicio.cargar_produccion()
    yield


# La documentación interactiva de la API queda apagada salvo que exista TS_DOCS=1 (solo desarrollo).
_DOCS = os.environ.get("TS_DOCS", "").strip() == "1"
app = FastAPI(title="Apoyo para detección de tumores cerebrales", version="1.0", lifespan=ciclo_de_vida,
              docs_url="/api/docs" if _DOCS else None, redoc_url=None,
              openapi_url="/api/openapi.json" if _DOCS else None)


@app.exception_handler(RequestValidationError)
async def _validacion(_request: Request, exc: RequestValidationError):
    campos = []
    for e in exc.errors():
        loc = [str(p) for p in e.get("loc", []) if p not in ("body", "query", "path", "form")]
        if loc:
            campos.append(".".join(loc))
    texto = "Datos no válidos" + (f" en: {', '.join(sorted(set(campos)))}." if campos else ".")
    return JSONResponse(status_code=422, content={"detail": texto})


@app.exception_handler(StarletteHTTPException)
async def _http(_request: Request, exc: StarletteHTTPException):
    detalle = exc.detail
    if exc.status_code == 404 and detalle == "Not Found":
        detalle = "No se encontró el recurso."
    elif exc.status_code == 405 and detalle == "Method Not Allowed":
        detalle = "Método no permitido."
    return JSONResponse(status_code=exc.status_code, content={"detail": detalle}, headers=getattr(exc, "headers", None))


@app.exception_handler(Exception)
async def _inesperado(_request: Request, exc: Exception):
    log.error("Error no controlado: %s", type(exc).__name__, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Ocurrió un error interno en el servidor."})


app.include_router(publico.router)
app.include_router(estudios.router)
app.include_router(admin.router)

config.FRONTEND.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(config.FRONTEND), html=True, check_dir=False), name="frontend")

__all__ = ["app", "HTTPException"]
