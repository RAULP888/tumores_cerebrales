"""Verificación independiente (Fases 3 y 4): flujo, permisos, seguridad, bitácora, umbral y latencia.

Uso: .venv\\Scripts\\python.exe pruebas/verificacion_fase34/flujo.py
Requiere el servidor del verificador en http://127.0.0.1:8765 con la base de entorno/verif.db.
"""
import io
import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
AQUI = Path(__file__).resolve().parent
ENT = AQUI / "entorno"
DB = ENT / "verif.db"
BASE = "http://127.0.0.1:8765"
CLAVE = "sk-ant-PRUEBA-VERIFICADOR-123"
AVISO = "Resultado de apoyo. No sustituye el diagnóstico de un médico especialista."
CAMPOS = {"prediccion_id", "archivo", "hay_tumor", "etiqueta", "probabilidad_tumor", "confianza", "umbral",
          "tipo_probable", "tipo_nombre", "probabilidad_tipo", "imagen_url", "gradcam_url", "modelo_version",
          "tiempo_respuesta_ms", "aviso"}

resultados = []      # (punto, prueba, ok, evidencia)
respuestas = []      # textos de todas las respuestas (para buscar la clave)


def chk(punto, nombre, ok, evidencia=""):
    resultados.append({"punto": punto, "prueba": nombre, "ok": bool(ok), "evidencia": str(evidencia)[:600]})
    print(("PASA " if ok else "FALLA") + f" [{punto}] {nombre} :: {str(evidencia)[:300]}", flush=True)


class Cli(httpx.Client):
    def request(self, *a, **k):
        r = super().request(*a, **k)
        try:
            respuestas.append(r.text if not r.headers.get("content-type", "").startswith("image") else "")
            respuestas.append(json.dumps(dict(r.headers)))
        except Exception:
            pass
        return r


def cliente():
    return Cli(base_url=BASE, timeout=120)


def sql(q, params=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(q, params).fetchall()]
    finally:
        con.close()


def login(c, usuario, password, rol):
    return c.post("/api/login", json={"usuario": usuario, "password": password, "rol": rol})


def subir(c, archivos, ident="PAC-9001", edad="45", sexo="F", fecha="2026-11-20"):
    return c.post("/api/estudios", data={"identificador": ident, "edad": edad, "sexo": sexo, "fecha_estudio": fecha},
                  files=[("archivos", a) for a in archivos])


def leer(ruta):
    return (Path(ruta).name, (RAIZ / ruta).read_bytes(), "image/jpeg")


def main():
    man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
    pred = pd.read_csv(RAIZ / "resultados" / "predicciones_prueba.csv")
    red = pred[pred["modelo"].str.contains("Red Keras")].set_index("ruta")
    prueba = man[man["particion"] == "prueba"]
    con_tumor = prueba[(prueba["es_tumor"] == 1) & prueba["ruta"].isin(red.index)].iloc[0]["ruta"]
    sin_tumor = prueba[(prueba["es_tumor"] == 0) & prueba["ruta"].isin(red.index)].iloc[0]["ruta"]
    print("Imágenes de prueba:", con_tumor, sin_tumor)

    # ================= 3. Flujo
    d1 = cliente()
    r = login(d1, "doctor1", "Doctor2026!", "doctor")
    chk(3, "login doctor1 200", r.status_code == 200 and r.json().get("rol") == "doctor", r.text)
    set_cookie = r.headers.get("set-cookie", "")
    chk(4, "cookie ts_sesion con HttpOnly y SameSite=Lax", "ts_sesion=" in set_cookie and "httponly" in set_cookie.lower()
        and "samesite=lax" in set_cookie.lower(), set_cookie[:30] + "..." + set_cookie[-80:])

    r = subir(d1, [leer(con_tumor), leer(sin_tumor), ("notas.txt", b"esto no es una imagen\n" * 10, "text/plain")])
    chk(3, "POST /api/estudios 200", r.status_code == 200, r.status_code)
    res = r.json()["resultados"]
    (AQUI / "evidencia_estudio.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    ok_imgs = [x for x in res if "error" not in x]
    err = [x for x in res if "error" in x]
    chk(3, "2 resultados válidos + 1 error para el .txt", len(ok_imgs) == 2 and len(err) == 1
        and err[0]["archivo"] == "notas.txt", json.dumps(err, ensure_ascii=False))
    for x, ruta in zip(ok_imgs, (con_tumor, sin_tumor)):
        faltan = CAMPOS - set(x)
        chk(3, f"campos del contrato ({Path(ruta).name})", not faltan, f"faltan={faltan}")
        chk(3, f"aviso exacto ({Path(ruta).name})", x.get("aviso") == AVISO, x.get("aviso"))
        esperado = x["probabilidad_tumor"] >= x["umbral"]
        chk(3, f"hay_tumor == (p >= umbral) y etiqueta ({Path(ruta).name})",
            x["hay_tumor"] == esperado and x["etiqueta"] == ("Se detecta posible tumor" if esperado else "No se detecta tumor"),
            f"p={x['probabilidad_tumor']:.6f} umbral={x['umbral']:.6f} etiqueta={x['etiqueta']}")
        conf = x["probabilidad_tumor"] if x["hay_tumor"] else 1 - x["probabilidad_tumor"]
        chk(3, f"confianza coherente ({Path(ruta).name})", abs(conf - x["confianza"]) < 1e-9, x["confianza"])
        if not x["hay_tumor"]:
            chk(3, "tipo_* nulo si no hay tumor", x["tipo_probable"] is None and x["tipo_nombre"] is None
                and x["probabilidad_tipo"] is None, x)
        else:
            chk(3, "tipo_* presente si hay tumor", x["tipo_probable"] is not None and x["tipo_nombre"], x["tipo_nombre"])
        p_csv = float(red.loc[ruta, "probabilidad_tumor"])
        chk(3, f"probabilidad vs predicciones_prueba.csv Red Keras ({Path(ruta).name})",
            abs(p_csv - x["probabilidad_tumor"]) < 1e-4, f"api={x['probabilidad_tumor']:.7f} csv={p_csv:.7f} "
            f"dif={abs(p_csv - x['probabilidad_tumor']):.2e}")
        for clave in ("imagen_url", "gradcam_url"):
            m = d1.get(x[clave])
            chk(3, f"/media {clave} PNG ({Path(ruta).name})", m.status_code == 200 and m.content[:8] == b"\x89PNG\r\n\x1a\n"
                and m.headers.get("content-type") == "image/png", f"{x[clave]} -> {m.status_code} {len(m.content)} bytes")
    ids = [x["prediccion_id"] for x in ok_imgs]
    filas = sql("""SELECT h.prediccion_id, p.identificador, f.fecha, u.usuario AS doctor, m.version AS modelo,
                          h.probabilidad_tumor, h.umbral, h.tiempo_respuesta_ms, h.origen, d.clave AS predicho
                   FROM hecho_prediccion h JOIN dim_paciente p ON p.paciente_id = h.paciente_id
                   JOIN dim_fecha f ON f.fecha_id = h.fecha_id JOIN usuarios u ON u.usuario_id = h.usuario_id
                   JOIN dim_modelo m ON m.modelo_id = h.modelo_id
                   JOIN dim_diagnostico d ON d.diagnostico_id = h.diagnostico_predicho_id
                   WHERE h.prediccion_id IN (?, ?) ORDER BY h.prediccion_id""", tuple(ids))
    chk(3, "consulta SQL parametrizada recupera las 2 filas", len(filas) == 2 and all(
        f["identificador"] == "PAC-9001" and f["doctor"] == "doctor1" and f["modelo"] == "v001" and f["origen"] == "uso"
        and str(f["fecha"]).startswith("2026-11-20") and f["tiempo_respuesta_ms"] > 0 for f in filas)
        and all(abs(f["probabilidad_tumor"] - x["probabilidad_tumor"]) < 1e-9 for f, x in zip(filas, ok_imgs)),
        json.dumps(filas, ensure_ascii=False, default=str))

    # Confirmación "No estoy de acuerdo" sobre la imagen sin tumor (dice sin tumor) con diagnóstico real meningioma
    pid_sin = ok_imgs[1]["prediccion_id"]
    r = d1.post(f"/api/estudios/{pid_sin}/confirmacion", json={"de_acuerdo": False, "diagnostico_real": "meningioma"})
    chk(3, "confirmación desacuerdo 200", r.status_code == 200 and r.json().get("de_acuerdo") is False
        and r.json().get("diagnostico_confirmado") == "meningioma", r.text[:300])
    f = sql("SELECT h.de_acuerdo, d.clave FROM hecho_prediccion h JOIN dim_diagnostico d ON "
            "d.diagnostico_id = h.diagnostico_confirmado_id WHERE h.prediccion_id = ?", (pid_sin,))
    chk(3, "confirmación guardada en la base", f and f[0]["de_acuerdo"] == 0 and f[0]["clave"] == "meningioma", f)
    r = d1.post(f"/api/estudios/{pid_sin}/confirmacion", json={"de_acuerdo": True, "diagnostico_real": "glioma"})
    chk(3, "de_acuerdo=true contradictorio -> 422", r.status_code == 422, r.text)
    r = d1.post(f"/api/estudios/{pid_sin}/confirmacion", json={"de_acuerdo": False, "diagnostico_real": "gato"})
    chk(3, "diagnóstico real inválido -> 422", r.status_code == 422, r.text)
    # vuelve a dejar el desacuerdo (lo anterior falló sin cambiar)
    f = sql("SELECT de_acuerdo FROM hecho_prediccion WHERE prediccion_id = ?", (pid_sin,))
    chk(3, "intentos rechazados no alteran la confirmación", f[0]["de_acuerdo"] == 0, f)

    # Historial y filtros
    r = d1.get("/api/estudios")
    todos = r.json()["estudios"]
    chk(3, "historial doctor1 ve sus 2 estudios", r.status_code == 200 and {e["prediccion_id"] for e in todos} >= set(ids)
        and all(e["doctor"] == "doctor1" for e in todos), f"n={len(todos)}")
    r = d1.get("/api/estudios", params={"confirmacion": "desacuerdo"})
    chk(3, "filtro confirmacion=desacuerdo", [e["prediccion_id"] for e in r.json()["estudios"]] == [pid_sin], r.text[:200])
    r = d1.get("/api/estudios", params={"confirmacion": "pendiente"})
    chk(3, "filtro confirmacion=pendiente", [e["prediccion_id"] for e in r.json()["estudios"]] == [ids[0]], r.text[:200])
    r = d1.get("/api/estudios", params={"resultado": "tumor" if ok_imgs[0]["hay_tumor"] else "sin_tumor"})
    chk(3, "filtro resultado", ids[0] in [e["prediccion_id"] for e in r.json()["estudios"]], r.text[:200])
    r = d1.get("/api/estudios", params={"identificador": "pac-9001", "desde": "2026-11-01", "hasta": "2030-01-01"})
    chk(3, "filtro identificador (minúsculas) + fechas", len(r.json()["estudios"]) == 2, len(r.json()["estudios"]))
    r = d1.get("/api/estudios", params={"desde": "2030-01-01"})
    chk(3, "filtro desde futuro -> vacío", r.json()["estudios"] == [], r.text[:100])
    r = d1.get("/api/estudios", params={"limite": 1})
    chk(3, "limite=1", len(r.json()["estudios"]) == 1, len(r.json()["estudios"]))

    d2 = cliente()
    login(d2, "doctor2", "Doctor2026!", "doctor")
    r2 = subir(d2, [leer(con_tumor)], ident="PAC-9002")
    pid_d2 = r2.json()["resultados"][0]["prediccion_id"]
    r = d2.get("/api/estudios")
    vistos = r.json()["estudios"]
    chk(3, "doctor2 no ve estudios de doctor1", all(e["doctor"] == "doctor2" for e in vistos)
        and not set(ids) & {e["prediccion_id"] for e in vistos}, [(e["prediccion_id"], e["doctor"]) for e in vistos])
    r = d2.get("/api/estudios", params={"identificador": "PAC-9001"})
    chk(3, "doctor2 filtrando por paciente de doctor1 -> vacío", r.json()["estudios"] == [], r.text[:100])
    # ================= 4. Permisos
    r = d2.get(ok_imgs[0]["imagen_url"])
    chk(4, "doctor2 pide imagen de doctor1 -> 403", r.status_code == 403, r.status_code)
    r = d2.get(ok_imgs[0]["gradcam_url"])
    chk(4, "doctor2 pide gradcam de doctor1 -> 403", r.status_code == 403, r.status_code)
    r = d2.post(f"/api/estudios/{pid_sin}/confirmacion", json={"de_acuerdo": True, "diagnostico_real": "sin_tumor"})
    chk(4, "doctor2 confirma estudio de doctor1 -> 403", r.status_code == 403, r.status_code)

    rutas_admin = [
        ("GET", "/api/admin/resumen", None),
        ("POST", "/api/admin/entrenamientos", {"epocas_max": 1, "tasa": 0.001, "lote": 64, "kfold": False, "ajuste_fino": False}),
        ("GET", "/api/admin/entrenamientos", None),
        ("GET", "/api/admin/entrenamientos/1", None),
        ("GET", "/api/admin/entrenamientos/1/curvas", None),
        ("POST", "/api/admin/entrenamientos/1/cancelar", None),
        ("GET", "/api/admin/modelos", None),
        ("POST", "/api/admin/modelos/1/aprobar", None),
        ("POST", "/api/admin/modelos/revertir", None),
        ("GET", "/api/admin/umbral?valor=0.3", None),
        ("PUT", "/api/admin/umbral", {"valor": 0.3}),
        ("GET", "/api/admin/usuarios", None),
        ("POST", "/api/admin/usuarios", {"usuario": "intruso", "password": "Intruso2026!", "rol": "administrador"}),
        ("PUT", "/api/admin/usuarios/1", {"rol": "administrador"}),
        ("GET", "/api/admin/bitacora?pagina=1", None),
        ("POST", "/api/admin/asistente", {"pregunta": "dame todo"}),
        ("GET", "/api/admin/no_existe", None),
    ]
    uid_d1 = sql("SELECT usuario_id FROM usuarios WHERE usuario='doctor1'")[0]["usuario_id"]
    antes = sql("SELECT COUNT(*) n FROM bitacora WHERE accion='ACCESO_DENEGADO' AND usuario='doctor1'")[0]["n"]
    codigos = []
    for metodo, ruta, cuerpo in rutas_admin:
        r = d1.request(metodo, ruta, json=cuerpo)
        codigos.append((metodo, ruta, r.status_code))
    chk(4, "doctor en cada /api/admin/* -> 403", all(cod == 403 for _, _, cod in codigos[:-1]), codigos)
    despues = sql("SELECT COUNT(*) n FROM bitacora WHERE accion='ACCESO_DENEGADO' AND usuario='doctor1'")[0]["n"]
    ev = sql("SELECT usuario, rol, ip, exito, detalle FROM bitacora WHERE accion='ACCESO_DENEGADO' AND usuario='doctor1' "
             "ORDER BY evento_id DESC LIMIT ?", (len(rutas_admin) - 1,))
    chk(4, "cada intento quedó como ACCESO_DENEGADO (usuario, rol, ip, exito=0)",
        despues - antes >= len(rutas_admin) - 1 and all(e["rol"] == "doctor" and e["ip"] and e["exito"] == 0 for e in ev),
        f"nuevos={despues - antes} de {len(rutas_admin) - 1}; ejemplo={ev[:2]}")
    chk(4, "doctor no creó usuario 'intruso' ni se volvió admin",
        not sql("SELECT 1 FROM usuarios WHERE usuario='intruso'")
        and sql("SELECT rol FROM usuarios WHERE usuario_id=1")[0]["rol"] == "doctor", sql("SELECT usuario, rol FROM usuarios"))
    chk(4, "umbral no cambió por el doctor", abs(sql("SELECT umbral FROM dim_modelo WHERE estado='produccion'")[0]["umbral"]
                                                   - 0.5205068290233612) < 1e-9, "")

    anon = cliente()
    protegidas = [("GET", "/api/yo"), ("GET", "/api/estudios"), ("POST", "/api/estudios"),
                  ("POST", f"/api/estudios/{pid_sin}/confirmacion"), ("GET", "/api/admin/resumen"),
                  ("GET", "/api/admin/bitacora"), ("PUT", "/api/admin/umbral"), ("POST", "/api/admin/entrenamientos"),
                  ("GET", ok_imgs[0]["imagen_url"]), ("GET", ok_imgs[0]["gradcam_url"])]
    cod = [(m, u, anon.request(m, u, json={} if m != "GET" else None).status_code) for m, u in protegidas]
    chk(4, "sin sesión -> 401 en protegidas y /media", all(c == 401 for _, _, c in cod), cod)
    r = anon.get("/api/estudios", cookies={"ts_sesion": "token-falso-inventado"})
    chk(4, "cookie inventada -> 401", r.status_code == 401, r.status_code)

    r = login(anon, "doctor1", "Doctor2026!", "administrador")
    chk(4, "login con rol equivocado -> 403", r.status_code == 403 and "set-cookie" not in r.headers, r.text)
    r = login(anon, "admin1", "Admin2026!", "doctor")
    chk(4, "admin con rol doctor -> 403", r.status_code == 403, r.text)
    antes = sql("SELECT COUNT(*) n FROM bitacora WHERE accion='LOGIN_FALLIDO'")[0]["n"]
    r = login(anon, "doctor1", "ContraseñaMala1", "doctor")
    despues = sql("SELECT COUNT(*) n FROM bitacora WHERE accion='LOGIN_FALLIDO'")[0]["n"]
    ult = sql("SELECT usuario, ip, exito, detalle FROM bitacora WHERE accion='LOGIN_FALLIDO' ORDER BY evento_id DESC LIMIT 1")
    chk(4, "contraseña mala -> 401 y LOGIN_FALLIDO", r.status_code == 401 and despues == antes + 1 and ult[0]["exito"] == 0,
        f"{r.status_code} {ult}")
    r = login(anon, "no_existe", "x", "doctor")
    chk(4, "usuario inexistente -> 401 mismo mensaje", r.status_code == 401, r.text)
    chk(4, "la contraseña mala no se guardó en la bitácora",
        not sql("SELECT 1 FROM bitacora WHERE detalle LIKE ? OR usuario LIKE ?", ("%ContraseñaMala1%", "%ContraseñaMala1%")), "")

    adm = cliente()
    r = login(adm, "admin1", "Admin2026!", "administrador")
    chk(4, "login admin1", r.status_code == 200, r.text)
    r = adm.post("/api/admin/usuarios", json={"usuario": "doctor3", "password": "Doctor3x2026!", "rol": "doctor"})
    chk(6, "admin crea usuario doctor3", r.status_code == 200 and "hash" not in r.text, r.text)
    uid3 = r.json().get("usuario_id")
    d3 = cliente()
    r = login(d3, "doctor3", "Doctor3x2026!", "doctor")
    chk(4, "doctor3 entra mientras está activo", r.status_code == 200, r.status_code)
    r = adm.put(f"/api/admin/usuarios/{uid3}", json={"activo": False})
    chk(6, "admin desactiva doctor3", r.status_code == 200 and r.json()["activo"] is False, r.text)
    r = d3.get("/api/yo")
    chk(4, "sesión abierta de doctor3 se invalida al desactivarlo", r.status_code == 401, r.status_code)
    r = login(cliente(), "doctor3", "Doctor3x2026!", "doctor")
    chk(4, "usuario desactivado no puede entrar", r.status_code == 401, r.text)
    r = adm.put(f"/api/admin/usuarios/{uid3}", json={"password": "corta"})
    chk(4, "contraseña corta rechazada", r.status_code == 422, r.text)
    r = adm.put(f"/api/admin/usuarios/{sql('SELECT usuario_id FROM usuarios WHERE usuario=?', ('admin1',))[0]['usuario_id']}",
                json={"activo": False})
    chk(4, "admin no puede desactivarse a sí mismo", r.status_code == 409, r.text)
    r = adm.get("/api/admin/usuarios")
    chk(4, "GET usuarios sin hash", r.status_code == 200 and "$2b$" not in r.text and "hash" not in r.text, r.text[:200])

    hashes = sql("SELECT usuario, hash_password FROM usuarios")
    chk(4, "contraseñas con bcrypt $2b$ y no en claro", all(h["hash_password"].startswith("$2b$12$") for h in hashes)
        and not any(p in h["hash_password"] for h in hashes for p in ("Doctor2026!", "Admin2026!", "Doctor3x2026!")),
        [(h["usuario"], h["hash_password"][:7]) for h in hashes])
    vistas = sql("SELECT name, sql FROM sqlite_master WHERE type='view'")
    cols = {v["name"]: [c["name"] for c in sql(f"PRAGMA table_info({v['name']})")] for v in vistas}
    chk(4, "dim_usuario y vistas sin hash", "dim_usuario" in cols and cols["dim_usuario"] == ["usuario_id", "usuario", "rol", "activo"]
        and not any("hash" in c for cs in cols.values() for c in cs) and not any(
            "$2b$" in json.dumps(sql(f"SELECT * FROM {v} LIMIT 50"), default=str) for v in cols), cols)
    r = d1.post("/api/logout")
    chk(6, "logout doctor1", r.status_code == 200 and r.json() == {"ok": True}, r.text)
    r = d1.get("/api/yo")
    chk(4, "tras logout la sesión ya no sirve", r.status_code == 401, r.status_code)
    login(d1, "doctor1", "Doctor2026!", "doctor")

    # ================= 5. Seguridad
    n_pac = sql("SELECT COUNT(*) n FROM dim_paciente")[0]["n"]
    for ident in ("PAC-1' OR '1'='1", "PAC-1'; DROP TABLE usuarios;--", "Juan Pérez", "JUAN-PEREZ", "María López García",
                  "<img src=x onerror=alert(1)>", "PAC-0001 Juan"):
        r = subir(d1, [leer(con_tumor)], ident=ident)
        chk(5, f"identificador rechazado: {ident!r}", r.status_code == 422, r.text[:160])
    chk(5, "no se crearon pacientes con esos identificadores", sql("SELECT COUNT(*) n FROM dim_paciente")[0]["n"] == n_pac, "")
    chk(5, "tabla usuarios intacta", len(sql("SELECT * FROM usuarios")) == 4, "")
    filtros = [{"identificador": "' OR '1'='1"}, {"identificador": "PAC-9002' OR 1=1 --"}]
    for p in filtros:
        r = d1.get("/api/estudios", params=p)
        chk(5, f"SQLi en filtro {p}", r.status_code in (200, 422) and all(
            e["doctor"] == "doctor1" for e in r.json().get("estudios", [])) and pid_d2 not in [
            e["prediccion_id"] for e in r.json().get("estudios", [])] and len(r.json().get("estudios", [])) == 0,
            f"{r.status_code} n={len(r.json().get('estudios', []))}")
    for p in ({"resultado": "tumor' OR '1'='1"}, {"confirmacion": "pendiente' OR 1=1--"}, {"desde": "2026-01-01' OR 1=1--"},
              {"hasta": "x'); DROP TABLE bitacora;--"}, {"limite": "1; DROP TABLE usuarios"}):
        r = d1.get("/api/estudios", params=p)
        chk(5, f"SQLi en filtro {p} -> 422", r.status_code == 422, f"{r.status_code} {r.text[:120]}")
    r = adm.get("/api/admin/bitacora", params={"usuario": "' OR '1'='1", "accion": "x' OR 1=1--"})
    chk(5, "SQLi en filtros de bitácora -> 0 eventos", r.status_code == 200 and r.json()["total"] == 0, r.text[:120])
    r = adm.get("/api/estudios", params={"identificador": "' OR 1=1--"})
    chk(5, "SQLi identificador como admin -> 0", r.json()["estudios"] == [], r.text[:100])
    r = login(cliente(), "admin1' OR '1'='1' --", "x", "administrador")
    chk(5, "SQLi en login -> 401", r.status_code == 401, r.status_code)
    chk(5, "tablas siguen existiendo", len(sql("SELECT name FROM sqlite_master WHERE type='table'")) >= 12, "")

    raw = httpx.Client(base_url=BASE)
    cookies = dict(d1.cookies)
    for ruta in ("/media/../entorno/verif.db", "/media/..%2F..%2Fapp%2Fbackend%2Fconfig.py", "/media/..%5C..%5Cverif.db",
                 "/media/%2e%2e%2f%2e%2e%2fCLAUDE.md", "/media/....//....//CLAUDE.md", "/media/..",
                 "/media/" + "a" * 32 + "_img.png/../../verif.db", "/media/C:%5CWindows%5Cwin.ini"):
        r = raw.get(ruta, cookies=cookies)
        fuga = b"SQLite format" in r.content or b"ANTHROPIC" in r.content or b"[fonts]" in r.content or b"Sistema de Apoyo" in r.content
        chk(5, f"ruta con .. en /media: {ruta}", r.status_code in (400, 404, 422) and not fuga, f"{r.status_code} {r.content[:80]!r}")

    grande = b"\x89PNG\r\n\x1a\n" + b"\0" * (10 * 1024 * 1024 + 10)
    r = subir(d1, [("grande.png", grande, "image/png"), leer(sin_tumor)])
    rr = r.json().get("resultados", []) if r.status_code == 200 else []
    chk(5, "archivo > 10 MB rechazado (sin tumbar los demás)", r.status_code == 200 and "error" in rr[0]
        and "10 MB" in rr[0]["error"] and "error" not in rr[1], f"{r.status_code} {json.dumps(rr, ensure_ascii=False)[:250]}")
    justo = (RAIZ / sin_tumor).read_bytes()
    r = subir(d1, [(f"i{i}.jpg", justo, "image/jpeg") for i in range(9)])
    chk(5, "9 archivos -> 422", r.status_code == 422, r.text[:150])
    n_antes = sql("SELECT COUNT(*) n FROM hecho_prediccion WHERE origen='uso'")[0]["n"]
    r = subir(d1, [(f"i{i}.jpg", justo, "image/jpeg") for i in range(8)])
    chk(5, "8 archivos -> 200 con 8 resultados", r.status_code == 200 and len(r.json()["resultados"]) == 8
        and sql("SELECT COUNT(*) n FROM hecho_prediccion WHERE origen='uso'")[0]["n"] == n_antes + 8, r.status_code)
    r = subir(d1, [("falsa.png", b"\x89PNG\r\n\x1a\n" + b"basura" * 100, "image/png")])
    chk(5, "PNG con firma pero dañado -> error controlado", r.status_code == 200 and "error" in r.json()["resultados"][0],
        r.text[:200])
    r = subir(d1, [("script.jpg", b"<script>alert(1)</script>", "image/jpeg")])
    chk(5, "contenido no imagen con extensión .jpg -> error", "error" in r.json()["resultados"][0], r.text[:200])
    xss = "<img src=x onerror=alert(1)>.jpg"
    r = subir(d1, [(xss, justo, "image/jpeg")], ident="PAC-7777")
    chk(5, "nombre de archivo XSS se devuelve como dato (texto)", r.status_code == 200 and r.json()["resultados"][0]["archivo"] == xss,
        r.json()["resultados"][0].get("archivo"))
    for campo, valor in (("edad", "121"), ("edad", "-1"), ("edad", "abc"), ("sexo", "X"), ("fecha", "2099-01-01"),
                         ("fecha", "21/11/2026")):
        kw = {campo: valor}
        r = subir(d1, [leer(sin_tumor)], **kw)
        chk(5, f"validación {campo}={valor} -> 422", r.status_code == 422, r.text[:120])
    r = d1.post("/api/estudios", data={"identificador": "PAC-1", "edad": "4", "sexo": "F", "fecha_estudio": "2026-11-20"})
    chk(5, "sin archivos -> 422", r.status_code == 422, r.text[:120])

    # ================= 8. Umbral
    npz = np.load(ENT / "modelos" / "v001" / "validacion.npz", allow_pickle=False)
    y, prob = npz["y"].astype(int), npz["prob"].astype(float)
    for v in (0.2, 0.5205068290233612, 0.9):
        r = adm.get("/api/admin/umbral", params={"valor": v}).json()
        pr = prob >= v
        mio = dict(vp=int(((y == 1) & pr).sum()), vn=int(((y == 0) & ~pr).sum()), fp=int(((y == 0) & pr).sum()),
                   fn=int(((y == 1) & ~pr).sum()))
        chk(8, f"umbral {v}: VP/VN/FP/FN recalculados", all(r[k] == mio[k] for k in mio) and r["n"] == len(y)
            and abs(r["sensibilidad"] - mio["vp"] / (mio["vp"] + mio["fn"])) < 1e-12,
            f"api={ {k: r[k] for k in mio} } mio={mio} n={r['n']} origen={r.get('origen')}")
    for malo in (0, 0.005, 0.995, 1, 1.5, -0.2, "abc"):
        r = adm.put("/api/admin/umbral", json={"valor": malo})
        chk(8, f"PUT umbral {malo} rechazado", r.status_code == 422, f"{r.status_code} {r.text[:100]}")
    r = adm.get("/api/admin/umbral", params={"valor": 1.5})
    chk(8, "GET umbral valor=1.5 rechazado", r.status_code == 422, r.status_code)
    r = adm.put("/api/admin/umbral", json={"valor": 0.999999})
    chk(8, "PUT 0.999999 rechazado", r.status_code == 422, r.status_code)
    r = adm.put("/api/admin/umbral", json={"valor": 0.97})
    chk(8, "PUT umbral 0.97", r.status_code == 200 and r.json()["valor"] == 0.97, r.text)
    r = subir(d1, [leer(sin_tumor)], ident="PAC-8888")
    x = r.json()["resultados"][0]
    chk(8, "la siguiente predicción usa el umbral nuevo", abs(x["umbral"] - 0.97) < 1e-12
        and x["hay_tumor"] == (x["probabilidad_tumor"] >= 0.97), f"umbral={x['umbral']} p={x['probabilidad_tumor']}")
    chk(8, "/api/estado refleja el umbral", abs(httpx.get(BASE + "/api/estado").json()["modelo"]["umbral"] - 0.97) < 1e-12, "")
    ev = sql("SELECT usuario, rol, ip, exito, detalle FROM bitacora WHERE accion='UMBRAL_ACTUALIZADO' ORDER BY evento_id DESC LIMIT 1")
    chk(8, "UMBRAL_ACTUALIZADO en bitácora", ev and ev[0]["usuario"] == "admin1" and ev[0]["ip"] and ev[0]["exito"] == 1, ev)
    r = adm.put("/api/admin/umbral", json={"valor": 0.5205068290233612})
    chk(8, "umbral restaurado", r.status_code == 200, r.text)

    # ================= 11. Latencia
    imgs = prueba[prueba["ruta"].isin(red.index)].sample(10, random_state=7)["ruta"].tolist()
    servidor, ida = [], []
    difs = []
    for ruta in imgs:
        t0 = time.perf_counter()
        r = subir(d1, [leer(ruta)], ident="PAC-5555")
        ida.append((time.perf_counter() - t0) * 1000)
        x = r.json()["resultados"][0]
        servidor.append(x["tiempo_respuesta_ms"])
        difs.append(abs(x["probabilidad_tumor"] - float(red.loc[ruta, "probabilidad_tumor"])))
    chk(11, "mediana de latencia (10 imágenes)", True,
        f"servidor mediana={statistics.median(servidor):.1f} ms (min {min(servidor):.1f}, max {max(servidor):.1f}); "
        f"ida y vuelta mediana={statistics.median(ida):.1f} ms (min {min(ida):.1f}, max {max(ida):.1f})")
    chk(3, "10 imágenes extra de prueba: |p_api - p_csv| < 1e-4", max(difs) < 1e-4, f"máx dif={max(difs):.2e}")

    # ================= 6. Bitácora
    r = adm.get("/api/admin/bitacora", params={"pagina": 1})
    b = r.json()
    chk(6, "bitácora paginada", r.status_code == 200 and len(b["eventos"]) <= 50 and b["paginas"] == -(-b["total"] // 50)
        and b["acciones"], f"total={b['total']} paginas={b['paginas']} n={len(b['eventos'])}")
    r2 = adm.get("/api/admin/bitacora", params={"pagina": 2})
    chk(6, "página 2 distinta de la 1", r2.status_code == 200 and (b["paginas"] < 2 or not {e["evento_id"] for e in b["eventos"]}
                                                                 & {e["evento_id"] for e in r2.json()["eventos"]}),
        f"pagina2 n={len(r2.json()['eventos'])}")
    r = adm.get("/api/admin/bitacora", params={"usuario": "doctor1", "accion": "ACCESO_DENEGADO", "exito": "no"})
    j = r.json()
    chk(6, "filtros usuario+accion+exito", j["total"] >= 16 and all(e["usuario"] == "doctor1" and e["accion"] == "ACCESO_DENEGADO"
                                                                   and e["exito"] is False for e in j["eventos"]), f"total={j['total']}")
    hoy = time.strftime("%Y-%m-%d")
    r = adm.get("/api/admin/bitacora", params={"desde": hoy, "hasta": hoy})
    chk(6, "filtro desde/hasta hoy", r.json()["total"] == b["total"], f"{r.json()['total']} vs {b['total']}")
    r = adm.get("/api/admin/bitacora", params={"desde": "2030-01-01"})
    chk(6, "filtro desde futuro -> 0", r.json()["total"] == 0, r.json()["total"])
    r = adm.get("/api/admin/bitacora", params={"exito": "quizá"})
    chk(6, "exito inválido -> 422", r.status_code == 422, r.status_code)
    r = adm.get("/api/admin/bitacora", params={"pagina": 0})
    chk(6, "pagina=0 no rompe", r.status_code in (200, 422), r.status_code)

    r = adm.get("/api/admin/resumen")
    chk(3, "resumen admin", r.status_code == 200 and set(r.json()) >= {"estudios", "estudios_hoy", "con_tumor", "pct_tumor",
                                                                      "confirmados", "desacuerdos", "falsos_negativos",
                                                                      "falsos_positivos", "tiempo_promedio_ms",
                                                                      "modelo_produccion"}, r.text[:300])
    rs = r.json()
    n_uso = sql("SELECT COUNT(*) n FROM hecho_prediccion WHERE origen='uso'")[0]["n"]
    chk(3, "resumen.estudios == filas de uso en la base; falsos_negativos=1 (desacuerdo sin_tumor->meningioma)",
        rs["estudios"] == n_uso and rs["desacuerdos"] == 1 and rs["falsos_negativos"] == 1, rs)
    r = adm.post("/api/admin/asistente", json={"pregunta": "¿cuántos estudios hay?"})
    chk(10, "asistente responde sin la clave", r.status_code == 200 and CLAVE not in r.text, r.text[:200])

    # guardar ids
    (AQUI / "ids_flujo.json").write_text(json.dumps({"ids_doctor1": ids, "pid_desacuerdo": pid_sin, "pid_doctor2": pid_d2,
                                                     "con_tumor": con_tumor, "sin_tumor": sin_tumor}), encoding="utf-8")
    texto = "\n".join(respuestas)
    chk(10, "la clave falsa no aparece en ninguna respuesta HTTP", CLAVE not in texto and "PRUEBA-VERIFICADOR" not in texto,
        f"{len(respuestas)} respuestas revisadas")
    (AQUI / "resultados_flujo.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    fallas = [x for x in resultados if not x["ok"]]
    print(f"\nTOTAL {len(resultados)} comprobaciones, {len(fallas)} fallas")
    for x in fallas:
        print("FALLA", x)


if __name__ == "__main__":
    main()
