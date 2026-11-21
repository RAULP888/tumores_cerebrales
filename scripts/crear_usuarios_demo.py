"""Crea los usuarios de demostración (idempotente).

Uso: .venv\\Scripts\\python.exe scripts/crear_usuarios_demo.py

- doctor1 / Doctor2026!  (doctor)
- doctor2 / Doctor2026!  (doctor)
- admin1  / Admin2026!   (administrador)

Si el usuario ya existe, se reactiva y se restablecen su contraseña y su rol.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from sqlalchemy import insert, select, update  # noqa: E402

from app.backend import config, db, seguridad  # noqa: E402
from app.backend.tablas import usuarios  # noqa: E402

DEMO = [("doctor1", "Doctor2026!", "doctor"), ("doctor2", "Doctor2026!", "doctor"),
        ("admin1", "Admin2026!", "administrador")]


def crear():
    config.asegurar_carpetas()
    db.crear_esquema()
    creados, actualizados = [], []
    with db.motor().begin() as c:
        for nombre, password, rol in DEMO:
            fila = c.execute(select(usuarios.c.usuario_id, usuarios.c.hash_password, usuarios.c.rol,
                                    usuarios.c.activo).where(usuarios.c.usuario == nombre)).first()
            if fila is None:
                c.execute(insert(usuarios).values(usuario=nombre, hash_password=seguridad.hash_password(password),
                                                  rol=rol, activo=True, creado_en=db.ahora()))
                creados.append(nombre)
            elif not (seguridad.verificar_password(password, fila.hash_password) and fila.rol == rol and fila.activo):
                c.execute(update(usuarios).where(usuarios.c.usuario_id == fila.usuario_id).values(
                    hash_password=seguridad.hash_password(password), rol=rol, activo=True))
                actualizados.append(nombre)
    return creados, actualizados


if __name__ == "__main__":
    nuevos, cambiados = crear()
    print("Creados:", ", ".join(nuevos) or "ninguno")
    print("Restablecidos:", ", ".join(cambiados) or "ninguno")
