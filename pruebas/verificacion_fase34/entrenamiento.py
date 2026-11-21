"""Verificación del reentrenamiento en segundo plano (Fase 4), aprobación, reversión y K-fold."""
import json
import sqlite3
import statistics
import sys
import threading
import time
from pathlib import Path

import httpx
import psutil

RAIZ = Path(__file__).resolve().parents[2]
AQUI = Path(__file__).resolve().parent
ENT = AQUI / "entorno"
DB = ENT / "verif.db"
BASE = "http://127.0.0.1:8765"
import re
PID_UVICORN = int(re.sub(rb"[^0-9]", b"", (AQUI / "pid_uvicorn.txt").read_bytes()).decode())
resultados = []


def chk(punto, nombre, ok, evidencia=""):
    resultados.append({"punto": punto, "prueba": nombre, "ok": bool(ok), "evidencia": str(evidencia)[:800]})
    print(("PASA " if ok else "FALLA") + f" [{punto}] {nombre} :: {str(evidencia)[:400]}", flush=True)


def sql(q, params=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(q, params).fetchall()]
    finally:
        con.close()


def esperar(adm, eid, limite=900, al_ver=None):
    t0 = time.time()
    visto = []
    while time.time() - t0 < limite:
        d = adm.get(f"/api/admin/entrenamientos/{eid}").json()
        visto.append((round(time.time() - t0, 1), d["estado"], d["etapa"], d["epoca_actual"], round(d["progreso"], 3)))
        if al_ver:
            al_ver(d)
        if d["estado"] in ("terminado", "error") or (d["estado"] == "cancelado" and d["etapa"] == "cancelado"):
            return d, visto
        time.sleep(0.5)
    return d, visto


def main():
    adm = httpx.Client(base_url=BASE, timeout=300)
    adm.post("/api/login", json={"usuario": "admin1", "password": "Admin2026!", "rol": "administrador"})
    d1 = httpx.Client(base_url=BASE, timeout=300)
    d1.post("/api/login", json={"usuario": "doctor1", "password": "Doctor2026!", "rol": "doctor"})
    ids = json.loads((AQUI / "ids_flujo.json").read_text(encoding="utf-8"))
    img = (ids["sin_tumor"], (RAIZ / ids["sin_tumor"]).read_bytes(), "image/jpeg")

    def predecir():
        r = d1.post("/api/estudios", data={"identificador": "PAC-4444", "edad": "50", "sexo": "M",
                                           "fecha_estudio": "2026-11-21"}, files=[("archivos", img)])
        return r.json()["resultados"][0]

    # Latencia base de /api/estado
    base_lat = []
    for _ in range(20):
        t = time.perf_counter(); httpx.get(BASE + "/api/estado"); base_lat.append((time.perf_counter() - t) * 1000)

    # ---------------- Entrenamiento corto
    r = adm.post("/api/admin/entrenamientos", json={"epocas_max": 3, "tasa": 0.001, "lote": 64, "kfold": False,
                                                    "ajuste_fino": False})
    chk(7, "POST entrenamiento corto", r.status_code == 200, r.text)
    eid = r.json()["entrenamiento_id"]
    r2 = adm.post("/api/admin/entrenamientos", json={"epocas_max": 3, "tasa": 0.001, "lote": 64, "kfold": False,
                                                     "ajuste_fino": False})
    chk(7, "segundo entrenamiento mientras corre -> 409", r2.status_code == 409, f"{r2.status_code} {r2.text}")
    fila = sql("SELECT pid FROM entrenamientos WHERE entrenamiento_id=?", (eid,))[0]
    pid = fila["pid"]
    try:
        p = psutil.Process(pid)
        info_p = {"pid": pid, "ppid": p.ppid(), "cmd": " ".join(p.cmdline())[-80:], "uvicorn": PID_UVICORN}
        aparte = pid != PID_UVICORN and "app.backend.reentrenar" in " ".join(p.cmdline())
    except psutil.NoSuchProcess:
        info_p, aparte = {"pid": pid, "nota": "ya terminó"}, pid != PID_UVICORN
    chk(7, "corre en un proceso aparte (pid distinto, cmdline reentrenar)", aparte, info_p)

    lat, parar = [], threading.Event()

    def sondeo():
        while not parar.is_set():
            t = time.perf_counter()
            try:
                httpx.get(BASE + "/api/estado", timeout=30)
                lat.append((time.perf_counter() - t) * 1000)
            except Exception as e:  # noqa: BLE001
                lat.append(99999)
            time.sleep(0.2)
    hilo = threading.Thread(target=sondeo, daemon=True); hilo.start()
    t0 = time.time()
    pred_durante = None
    estados_vistos = set()

    def al_ver(d):
        nonlocal pred_durante
        estados_vistos.add(d["estado"])
        if pred_durante is None and d["estado"] == "corriendo":
            t = time.perf_counter(); x = predecir(); pred_durante = (x.get("modelo_version"), (time.perf_counter() - t) * 1000)
    d, visto = esperar(adm, eid, al_ver=al_ver)
    parar.set(); hilo.join()
    dur = time.time() - t0
    (AQUI / "evidencia_entrenamiento_corto.json").write_text(json.dumps({"detalle": d, "sondeo": visto}, ensure_ascii=False,
                                                                        indent=2), encoding="utf-8")
    chk(7, "entrenamiento corto termina", d["estado"] == "terminado", f"{d['estado']} {d['mensaje']} en {dur:.0f}s; vistos={estados_vistos}")
    chk(7, "progreso sondeado y avanza", len({v[4] for v in visto}) >= 2 and d["progreso"] == 1.0, visto[:3] + visto[-2:])
    chk(7, "/api/estado responde durante el entrenamiento",
        lat and max(lat) < 5000, f"n={len(lat)} mediana={statistics.median(lat):.1f} ms máx={max(lat):.1f} ms "
                                 f"(base mediana={statistics.median(base_lat):.1f} ms); predicción durante={pred_durante}")
    hist = sql("SELECT etapa, epoca, perdida, perdida_val, exactitud_val, tasa_aprendizaje FROM historial_epocas "
               "WHERE entrenamiento_id=? ORDER BY epoca", (eid,))
    chk(7, "historial_epocas por época (3 filas, cabeza)", len(hist) == 3 and all(h["etapa"] == "cabeza" and h["perdida_val"] is not None
                                                                                  for h in hist), hist)
    chk(7, "detalle trae historial = base", len(d["historial"]) == len(hist), len(d["historial"]))
    chk(7, "diagnóstico, explicación, métricas, matriz", d["diagnostico"] and d["explicacion"] and d["metricas"]
        and d["matriz_confusion"] and len(d["matriz_confusion"]) == 2,
        f"diag={d['diagnostico']}; mejor_epoca={d['mejor_epoca']}; matriz={d['matriz_confusion']}; "
        f"metricas={ {k: d['metricas'].get(k) for k in ('origen', 'n', 'sensibilidad', 'especificidad', 'auc', 'confirmadas_encontradas', 'confirmadas_excluidas_por_prueba', 'confirmadas_usadas')} }")
    m = d["metricas"]
    chk(7, "matriz = vn,fp,fn,vp de las métricas", d["matriz_confusion"] == [[m["vn"], m["fp"]], [m["fn"], m["vp"]]]
        and m["vp"] + m["fn"] + m["vn"] + m["fp"] == m["n"], d["matriz_confusion"])
    chk(7, "métricas del candidato en validación, no en prueba", m.get("origen") == "validacion", m.get("origen"))
    chk(7, "la imagen confirmada de PRUEBA se excluyó del reentrenamiento",
        m.get("confirmadas_encontradas", 0) >= 1 and m.get("confirmadas_excluidas_por_prueba") == m.get("confirmadas_encontradas"),
        {k: m.get(k) for k in ("confirmadas_encontradas", "confirmadas_excluidas_por_prueba", "confirmadas_usadas")})
    if d["curvas_url"]:
        c = adm.get(d["curvas_url"])
        (AQUI / "capturas" / f"curvas_entrenamiento_{eid}.png").write_bytes(c.content)
        chk(7, "curvas PNG descargables", c.status_code == 200 and c.content[:4] == b"\x89PNG", f"{len(c.content)} bytes")
    else:
        chk(7, "curvas_url presente", False, d)
    version = d["version"]
    cand = sql("SELECT modelo_id, version, estado, umbral, sensibilidad, origen_metricas, entrenamiento_id FROM dim_modelo "
               "WHERE version=?", (version,))
    chk(7, "candidato nuevo en dim_modelo", cand and cand[0]["estado"] == "candidato" and cand[0]["entrenamiento_id"] == eid
        and (ENT / "modelos" / version / "modelo.keras").is_file(), cand)
    info = json.loads((ENT / "modelos" / version / "info.json").read_text(encoding="utf-8"))
    chk(7, "info.json del candidato: metricas_prueba null", info.get("metricas_prueba") is None, info.get("nota_prueba"))
    chk(7, "app/modelos real no recibió versiones nuevas", sorted(p.name for p in (RAIZ / "app" / "modelos").iterdir()) == [".gitkeep", "v001"],
        sorted(p.name for p in (RAIZ / "app" / "modelos").iterdir()))
    # n del entrenamiento = no-prueba
    import pandas as pd
    man = pd.read_csv(RAIZ / "datos" / "manifiesto.csv")
    n_no_prueba = int((man["particion"] != "prueba").sum())
    tr = info["entrenamiento"]
    chk(7, "n_entrenamiento + n_validacion == filas no-prueba del manifiesto (+ confirmadas usadas)",
        tr["n_entrenamiento"] + tr["n_validacion"] == n_no_prueba + tr.get("confirmadas_usadas", 0),
        f"{tr['n_entrenamiento']}+{tr['n_validacion']} vs no_prueba={n_no_prueba} conf_usadas={tr.get('confirmadas_usadas')}")

    # ---------------- Entrenamiento que se cancela
    r = adm.post("/api/admin/entrenamientos", json={"epocas_max": 60, "tasa": 0.001, "lote": 64, "kfold": False,
                                                    "ajuste_fino": False, "paciencia": 60})
    eid2 = r.json()["entrenamiento_id"]
    t0 = time.time()
    cancelado = {"hecho": False}

    def al_ver2(dd):
        if not cancelado["hecho"] and dd["estado"] == "corriendo" and dd["etapa"] == "cabeza" and dd["epoca_actual"] >= 3:
            rc = adm.post(f"/api/admin/entrenamientos/{eid2}/cancelar")
            cancelado.update(hecho=True, codigo=rc.status_code, epoca=dd["epoca_actual"])
            r409 = adm.post("/api/admin/entrenamientos", json={"epocas_max": 3, "tasa": 0.001, "lote": 64, "kfold": False,
                                                               "ajuste_fino": False})
            cancelado["nuevo_mientras_se_detiene"] = r409.status_code
    d2, visto2 = esperar(adm, eid2, al_ver=al_ver2)
    (AQUI / "evidencia_entrenamiento_cancelado.json").write_text(json.dumps({"detalle": d2, "sondeo": visto2, "cancelacion": cancelado},
                                                                            ensure_ascii=False, indent=2), encoding="utf-8")
    chk(7, "cancelar a la mitad -> cancelado", cancelado["hecho"] and cancelado.get("codigo") == 200 and d2["estado"] == "cancelado"
        and d2["etapa"] == "cancelado", f"{cancelado} estado={d2['estado']} etapa={d2['etapa']} época={d2['epoca_actual']}/{d2['epocas_max']}")
    chk(7, "diagnóstico del cancelado no dice 'convergió'", "converg" not in str(d2["diagnostico"]).lower()
        or "no" in str(d2["diagnostico"]).lower(), f"diagnostico={d2['diagnostico']!r} explicacion={d2['explicacion']!r}")
    chk(7, "cancelado sin candidato ni curvas", d2["version"] is None and d2["curvas_url"] is None, (d2["version"], d2["curvas_url"]))
    chk(7, "nuevo entrenamiento mientras el cancelado aún se detiene -> 409 (o 200 si ya terminó)",
        cancelado.get("nuevo_mientras_se_detiene") in (409, 200), cancelado.get("nuevo_mientras_se_detiene"))
    if cancelado.get("nuevo_mientras_se_detiene") == 200:
        # se lanzó uno nuevo; esperarlo
        ult = adm.get("/api/admin/entrenamientos").json()["entrenamientos"][0]["entrenamiento_id"]
        esperar(adm, ult)
    r = adm.post(f"/api/admin/entrenamientos/{eid2}/cancelar")
    chk(7, "cancelar uno ya cancelado -> 409", r.status_code == 409, r.status_code)

    # ---------------- Aprobar y revertir
    mid = cand[0]["modelo_id"]
    r = adm.post(f"/api/admin/modelos/{mid}/aprobar")
    chk(7, "aprobar candidato", r.status_code == 200 and r.json()["version"] == version, r.text)
    est = httpx.get(BASE + "/api/estado").json()["modelo"]
    x = predecir()
    chk(7, "tras aprobar: /api/estado y predicción usan la versión nueva", est["version"] == version and x["modelo_version"] == version
        and abs(x["umbral"] - cand[0]["umbral"]) < 1e-12, f"estado={est} pred={x['modelo_version']} umbral={x['umbral']}")
    estados = {f["version"]: f["estado"] for f in sql("SELECT version, estado FROM dim_modelo WHERE tipo='red_keras'")}
    chk(7, "v001 pasó a retirado", estados.get("v001") == "retirado" and estados.get(version) == "produccion", estados)
    r = adm.post(f"/api/admin/modelos/{mid}/aprobar")
    chk(7, "aprobar de nuevo (ya en producción) -> 409", r.status_code == 409, r.status_code)
    r = adm.post("/api/admin/modelos/1/aprobar")
    chk(7, "aprobar un clásico -> 409", r.status_code == 409, f"{r.status_code} {r.text}")
    r = adm.post("/api/admin/modelos/revertir")
    est = httpx.get(BASE + "/api/estado").json()["modelo"]
    x = predecir()
    chk(7, "revertir regresa a v001 y la predicción la usa", r.status_code == 200 and r.json()["version"] == "v001"
        and est["version"] == "v001" and x["modelo_version"] == "v001", f"{r.text} estado={est['version']} pred={x['modelo_version']}")
    estados = {f["version"]: f["estado"] for f in sql("SELECT version, estado FROM dim_modelo WHERE tipo='red_keras'")}
    chk(7, "estados tras revertir", estados.get("v001") == "produccion" and estados.get(version) == "retirado", estados)

    # ---------------- K-fold
    r = adm.post("/api/admin/entrenamientos", json={"epocas_max": 3, "tasa": 0.001, "lote": 64, "kfold": True,
                                                    "ajuste_fino": False})
    eid3 = r.json()["entrenamiento_id"]
    d3, visto3 = esperar(adm, eid3)
    (AQUI / "evidencia_entrenamiento_kfold.json").write_text(json.dumps({"detalle": d3, "sondeo": visto3}, ensure_ascii=False,
                                                                        indent=2), encoding="utf-8")
    mp = sql("SELECT pliegue, sensibilidad, especificidad, vp, vn, fp, fn FROM metricas_pliegue WHERE entrenamiento_id=? ORDER BY pliegue", (eid3,))
    chk(7, "kfold=true: 5 filas en metricas_pliegue", d3["estado"] == "terminado" and len(mp) == 5 and [f["pliegue"] for f in mp] == [1, 2, 3, 4, 5],
        f"estado={d3['estado']} filas={mp}")
    if len(mp) == 5:
        import pandas as pd
        tot = sum(f["vp"] + f["vn"] + f["fp"] + f["fn"] for f in mp)
        chk(7, "pliegues suman las imágenes no-prueba (+confirmadas)", tot == n_no_prueba + d3["metricas"].get("confirmadas_usadas", 0), f"{tot} vs {n_no_prueba}")
    etapas = sorted({h["etapa"] for h in d3["historial"]})
    chk(7, "historial kfold con pliegue_1..5 y cabeza", etapas == ["cabeza", "pliegue_1", "pliegue_2", "pliegue_3", "pliegue_4", "pliegue_5"], etapas)

    # ---------------- Bitácora de las acciones de administración
    for accion in ("ENTRENAMIENTO_INICIADO", "ENTRENAMIENTO_TERMINADO", "ENTRENAMIENTO_CANCELADO", "MODELO_APROBADO",
                   "MODELO_REVERTIDO"):
        ev = sql("SELECT usuario, rol, ip, exito, detalle FROM bitacora WHERE accion=? ORDER BY evento_id", (accion,))
        con_usuario = [e for e in ev if e["usuario"] and e["rol"] and e["ip"]]
        chk(6, f"bitácora {accion}", ev and (con_usuario or accion == "ENTRENAMIENTO_TERMINADO"),
            f"n={len(ev)} con usuario/rol/ip={len(con_usuario)} ejemplo={ev[-1] if ev else None}")
    (AQUI / "resultados_entrenamiento.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    fallas = [x for x in resultados if not x["ok"]]
    print(f"\nTOTAL {len(resultados)} comprobaciones, {len(fallas)} fallas")
    for x in fallas:
        print("FALLA", x)


if __name__ == "__main__":
    main()
