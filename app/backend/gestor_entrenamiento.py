"""Lanza el reentrenamiento en un proceso aparte y vigila los huérfanos."""
import subprocess
import sys

from sqlalchemy import or_, select, update

from . import config, db
from .tablas import entrenamientos

_procesos = {}   # entrenamiento_id -> Popen (para recoger el proceso al terminar)
ACTIVOS = ("en_cola", "corriendo")


def proceso_vivo(pid):
    if not pid:
        return False
    try:
        import psutil
        p = psutil.Process(int(pid))
        if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
            return False
        return "reentrenar" in " ".join(p.cmdline())
    except Exception:  # noqa: BLE001 - proceso inexistente o sin permiso
        return False


def _recoger():
    for eid, p in list(_procesos.items()):
        if p.poll() is not None:
            _procesos.pop(eid, None)


def hay_activo(c):
    """True si hay un entrenamiento en cola, corriendo, o cancelado cuyo proceso aún no termina."""
    _recoger()
    filas = c.execute(select(entrenamientos.c.entrenamiento_id, entrenamientos.c.estado, entrenamientos.c.pid,
                             entrenamientos.c.terminado_en)
                      .where(or_(entrenamientos.c.estado.in_(ACTIVOS),
                                 (entrenamientos.c.estado == "cancelado") & entrenamientos.c.terminado_en.is_(None))))
    for eid, estado, pid, _ in filas:
        if estado in ACTIVOS:
            return True
        if eid in _procesos or proceso_vivo(pid):
            return True
    return False


def lanzar(entrenamiento_id):
    config.REGISTROS.mkdir(parents=True, exist_ok=True)
    salida = open(config.REGISTROS / f"entrenamiento_{entrenamiento_id}.log", "ab")
    banderas = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    p = subprocess.Popen([sys.executable, "-m", "app.backend.reentrenar", "--id", str(entrenamiento_id)],
                         cwd=str(config.RAIZ), stdout=salida, stderr=subprocess.STDOUT, creationflags=banderas)
    salida.close()
    _procesos[entrenamiento_id] = p
    with db.motor().begin() as c:
        c.execute(update(entrenamientos).where(entrenamientos.c.entrenamiento_id == entrenamiento_id)
                  .values(pid=p.pid))
    return p.pid


def limpiar_huerfanos():
    """Al arrancar: los entrenamientos 'en_cola'/'corriendo' sin proceso vivo pasan a 'error'."""
    n = 0
    with db.motor().begin() as c:
        filas = c.execute(select(entrenamientos.c.entrenamiento_id, entrenamientos.c.pid, entrenamientos.c.estado)
                          .where(or_(entrenamientos.c.estado.in_(ACTIVOS),
                                     (entrenamientos.c.estado == "cancelado")
                                     & entrenamientos.c.terminado_en.is_(None)))).all()
        for eid, pid, estado in filas:
            if proceso_vivo(pid):
                continue
            if estado == "cancelado":
                c.execute(update(entrenamientos).where(entrenamientos.c.entrenamiento_id == eid)
                          .values(terminado_en=db.ahora()))
                continue
            c.execute(update(entrenamientos).where(entrenamientos.c.entrenamiento_id == eid).values(
                estado="error", terminado_en=db.ahora(),
                mensaje="El servidor se reinició mientras el entrenamiento corría; se marcó como error."))
            quien, ip = db.solicitante_entrenamiento(c, eid)
            db.registrar("ENTRENAMIENTO_ERROR", f"Entrenamiento {eid} huérfano tras reiniciar el servidor",
                         quien, ip, exito=False, conexion=c)
            n += 1
    return n
