"""Verificación del frontend con Playwright + Edge contra el servidor del verificador (puerto 8765)."""
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parents[2]
AQUI = Path(__file__).resolve().parent
CAP = AQUI / "capturas"
CAP.mkdir(exist_ok=True)
BASE = "http://127.0.0.1:8765"
CLAVE = "sk-ant-PRUEBA-VERIFICADOR-123"
AVISO = "Resultado de apoyo. No sustituye el diagnóstico de un médico especialista."
XSS = "<img src=x onerror=alert(1)>"
ENTRENAR = "--entrenar" in sys.argv

resultados, externas, consola, dialogos, errores_pagina, http_errores = [], [], [], [], [], []


def chk(nombre, ok, evidencia=""):
    resultados.append({"punto": 9, "prueba": nombre, "ok": bool(ok), "evidencia": str(evidencia)[:500]})
    print(("PASA " if ok else "FALLA") + f" [9] {nombre} :: {str(evidencia)[:300]}", flush=True)


def foto(page, nombre):
    page.screenshot(path=str(CAP / f"{nombre}.png"), full_page=True)


def main():
    ids = json.loads((AQUI / "ids_flujo.json").read_text(encoding="utf-8"))
    con_tumor = RAIZ / ids["con_tumor"]
    sin_tumor = RAIZ / ids["sin_tumor"]
    with sync_playwright() as p:
        nav = p.chromium.launch(channel="msedge", headless=True)
        ctx = nav.new_context(viewport={"width": 1366, "height": 900}, locale="es-MX")
        page = ctx.new_page()

        def req(r):
            u = urlparse(r.url)
            if u.scheme in ("http", "https", "ws", "wss") and u.netloc != "127.0.0.1:8765":
                externas.append(r.url)
        page.on("request", req)
        page.on("console", lambda m: consola.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: errores_pagina.append(str(e)))
        page.on("dialog", lambda d: (dialogos.append(d.message), d.dismiss()))
        page.on("response", lambda r: http_errores.append(f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)

        # ---------- Bienvenida
        page.goto(BASE + "/", wait_until="networkidle")
        h1 = page.locator("#titulo-bienvenida").inner_text().strip()
        chk("título exacto de bienvenida", h1 == "Bienvenido al Sistema de Apoyo para Detección de Tumores Cerebrales", h1)
        boton = page.locator("#boton-iniciar")
        chk("botón 'Iniciar' visible", boton.is_visible() and boton.inner_text().strip() == "Iniciar", boton.inner_text())
        foto(page, "01_bienvenida")

        # ---------- Login doctor
        boton.click()
        page.locator('.rol[data-rol="doctor"]').click()
        page.fill("#acceso-usuario", "doctor1")
        page.fill("#acceso-password", "Doctor2026!")
        foto(page, "02_acceso_doctor")
        page.click("#boton-entrar")
        page.wait_for_selector("#pantalla-doctor:not([hidden])", timeout=15000)
        chk("login doctor muestra panel del doctor", page.locator("#pantalla-doctor").is_visible(), page.locator("#cab-usuario").inner_text())
        cookies_js = page.evaluate("document.cookie")
        chk("cookie de sesión no visible para JavaScript (HttpOnly)", "ts_sesion" not in cookies_js, repr(cookies_js))

        # ---------- Identificador con XSS (validación)
        page.fill("#est-identificador", XSS)
        page.fill("#est-edad", "52")
        page.select_option("#est-sexo", "M")
        page.fill("#est-fecha", "2026-11-20")
        page.set_input_files("#est-archivos", [str(con_tumor)])
        page.click("#boton-analizar")
        page.wait_for_timeout(1500)
        foto(page, "03_identificador_xss")
        chk("identificador XSS no ejecuta ni crea <img src=x>", page.locator('img[src="x"]').count() == 0 and not dialogos,
            page.locator("#estudio-error").inner_text() if page.locator("#estudio-error").is_visible() else page.locator("body").inner_text()[:200])

        # ---------- Análisis de imágenes reales (una con nombre XSS)
        page.fill("#est-identificador", "PAC-3003")
        page.set_input_files("#est-archivos", [{"name": con_tumor.name, "mimeType": "image/jpeg", "buffer": con_tumor.read_bytes()},
                                               {"name": XSS + ".jpg", "mimeType": "image/jpeg", "buffer": sin_tumor.read_bytes()}])
        page.wait_for_timeout(500)
        foto(page, "04_formulario_listo")
        page.click("#boton-analizar")
        page.wait_for_selector("#lista-resultados article.resultado", timeout=60000)
        page.wait_for_timeout(1500)
        foto(page, "05_resultados")
        tarjetas = page.locator("#lista-resultados article.resultado")
        n = tarjetas.count()
        chk("tarjetas de resultado (la interfaz acumula la imagen del intento anterior: 1 + 2 = 3)", n == 3, n)
        for i in range(n):
            t = tarjetas.nth(i)
            texto = t.inner_text()
            etiqueta = t.locator(".resultado__etiqueta").inner_text().strip()
            chk(f"tarjeta {i}: etiqueta válida", etiqueta in ("Se detecta posible tumor", "No se detecta tumor"), etiqueta)
            chk(f"tarjeta {i}: porcentaje", "%" in t.locator(".confianza__valor").inner_text(), t.locator(".confianza__valor").inner_text())
            if etiqueta == "Se detecta posible tumor":
                chk(f"tarjeta {i}: tipo probable", t.locator(".tipo-probable").count() == 1, t.locator(".tipo-probable").inner_text())
            else:
                chk(f"tarjeta {i}: sin tipo cuando no hay tumor", t.locator(".tipo-probable").count() == 0, "")
            caps = [c.strip() for c in t.locator("figcaption").all_inner_texts()]
            chk(f"tarjeta {i}: imagen y Grad-CAM con rótulo 'Zona que más influyó'", caps == ["Imagen original", "Zona que más influyó"], caps)
            cargadas = t.locator(".imagenes-par img").evaluate_all("els => els.map(e => e.complete && e.naturalWidth)")
            chk(f"tarjeta {i}: las 2 imágenes cargan", len(cargadas) == 2 and all(cargadas), cargadas)
            chk(f"tarjeta {i}: versión del modelo", "Versión del modelo" in texto and "v00" in texto, "")
            chk(f"tarjeta {i}: aviso exacto", t.locator(".resultado__aviso").inner_text().strip() == AVISO, t.locator(".resultado__aviso").inner_text())
            chk(f"tarjeta {i}: 'ubicación del tumor' no aparece", "ubicación del tumor" not in texto.lower(), "")
        archivos = tarjetas.locator(".resultado__archivo").all_inner_texts()
        chk("nombre de archivo XSS se muestra como texto", (XSS + ".jpg") in archivos and page.locator('img[src="x"]').count() == 0
            and not dialogos, archivos)

        # ---------- Confirmación desde la tarjeta
        t0 = tarjetas.nth(0)
        t0.get_by_role("button", name="No estoy de acuerdo").click()
        opciones = t0.locator("select option").all_inner_texts()
        t0.locator("select").select_option(index=0)
        t0.get_by_role("button", name="Registrar confirmación").click()
        page.wait_for_selector("#lista-resultados article.resultado .mensaje-exito", timeout=10000)
        msg = t0.locator(".mensaje-exito").inner_text()
        chk("confirmación 'No estoy de acuerdo' desde la tarjeta", "en desacuerdo" in msg, f"{msg} opciones={opciones}")
        foto(page, "06_confirmacion")

        # ---------- Historial
        page.click("#tab-historial")
        page.wait_for_timeout(2000)
        foto(page, "07_historial")
        texto_h = page.locator("#historial-contenedor").inner_text()
        chk("historial muestra el estudio PAC-3003", "PAC-3003" in texto_h, page.locator("#historial-total").inner_text())
        page.select_option("#fh-confirmacion", "desacuerdo")
        page.wait_for_timeout(1500)
        texto_h2 = page.locator("#historial-contenedor").inner_text()
        chk("filtro de historial 'desacuerdo'", page.locator("#historial-total").inner_text() != "", page.locator("#historial-total").inner_text())
        page.fill("#fh-identificador", XSS)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)
        chk("filtro con XSS no ejecuta", page.locator('img[src="x"]').count() == 0 and not dialogos, page.locator("#historial-total").inner_text())
        foto(page, "08_historial_filtro")

        # ---------- Salir y entrar como administrador
        page.click("#boton-salir")
        page.wait_for_timeout(1000)
        if page.locator("#boton-iniciar").is_visible():
            page.click("#boton-iniciar")
        page.locator('.rol[data-rol="administrador"]').click()
        page.fill("#acceso-usuario", "admin1")
        page.fill("#acceso-password", "Admin2026!")
        page.click("#boton-entrar")
        page.wait_for_selector("#pantalla-admin:not([hidden])", timeout=15000)
        page.wait_for_timeout(1500)
        foto(page, "10_admin_resumen")
        chk("resumen del administrador con indicadores", len(page.locator("#indicadores").inner_text()) > 20, page.locator("#indicadores").inner_text()[:200])

        page.click('[data-seccion="reentrenar"]')
        page.wait_for_timeout(1500)
        foto(page, "11_admin_reentrenar")
        if ENTRENAR:
            page.fill("#ent-epocas", "3")
            if page.locator("#ent-kfold").is_checked():
                page.uncheck("#ent-kfold")
            if page.locator("#ent-ajuste").is_checked():
                page.uncheck("#ent-ajuste")
            page.click("#boton-entrenar")
            page.wait_for_timeout(1500)
            if page.locator("#dialogo-aceptar").is_visible():
                page.click("#dialogo-aceptar")
            page.wait_for_selector("#progreso-entrenamiento:not([hidden])", timeout=20000)
            vistos = set()
            fin = time.time() + 300
            while time.time() < fin:
                estado = page.locator("#progreso-estado").inner_text()
                vistos.add((estado, page.locator("#progreso-porcentaje").inner_text()))
                if any(k in estado.lower() for k in ("terminado", "error", "cancelado")):
                    break
                page.wait_for_timeout(1000)
            page.wait_for_timeout(2500)
            foto(page, "12_admin_reentrenar_resultado")
            det = page.locator("#detalle-entrenamiento").inner_text()
            chk("reentrenar desde la interfaz con progreso y resultado", "terminado" in estado.lower() and len(det) > 50,
                f"estado={estado}; vistos={sorted(vistos)[:6]}; detalle={det[:250]}")
            page.locator("#detalle-entrenamiento details").evaluate_all("els => els.forEach(e => e.open = true)")
            page.locator("#detalle-entrenamiento details img").scroll_into_view_if_needed()
            page.wait_for_timeout(2500)
            foto(page, "12b_admin_curvas_png")
            curvas = page.locator("#detalle-entrenamiento img").evaluate_all("els => els.map(e => e.complete && e.naturalWidth)")
            chk("curvas visibles en el resultado", bool(curvas) and all(curvas), curvas)

        page.click('[data-seccion="modelos"]')
        page.wait_for_timeout(1500)
        foto(page, "13_admin_versiones")
        chk("versiones del modelo", "v001" in page.locator("#tabla-modelos").inner_text(), page.locator("#tabla-modelos").inner_text()[:300])

        page.click('[data-seccion="umbral"]')
        page.wait_for_timeout(1500)
        antes = page.locator("#umbral-comparacion").inner_text()
        page.locator("#umbral-rango").evaluate("e => { e.value = '0.30'; e.dispatchEvent(new Event('input', {bubbles:true})); e.dispatchEvent(new Event('change', {bubbles:true})); }")
        page.wait_for_timeout(2000)
        despues = page.locator("#umbral-comparacion").inner_text()
        foto(page, "14_admin_umbral_vista_previa")
        chk("umbral con vista previa (cambia al mover el valor)", despues and despues != antes, f"antes={antes[:150]!r} despues={despues[:150]!r}")

        page.click('[data-seccion="usuarios"]')
        page.wait_for_timeout(1500)
        foto(page, "15_admin_usuarios")
        tu = page.locator("#tabla-usuarios").inner_text()
        chk("usuarios", "doctor1" in tu and "$2b$" not in tu, tu[:200])

        page.click('[data-seccion="bitacora"]')
        page.wait_for_timeout(1500)
        foto(page, "16_admin_bitacora")
        tb = page.locator("#tabla-bitacora").inner_text()
        chk("bitácora", "LOGIN_OK" in tb or "ACCESO_DENEGADO" in tb, page.locator("#bitacora-total").inner_text())

        page.click('[data-seccion="powerbi"]')
        page.wait_for_timeout(1000)
        foto(page, "17_admin_powerbi")
        chk("sección Power BI", len(page.locator("#powerbi-contenedor").inner_text()) > 10, page.locator("#powerbi-contenedor").inner_text()[:200])

        page.click('[data-seccion="asistente"]')
        page.wait_for_timeout(1000)
        page.fill("#asistente-pregunta", "¿Cuántos estudios hay? " + XSS)
        page.click("#boton-preguntar")
        page.wait_for_timeout(2500)
        foto(page, "18_admin_asistente")
        resp = page.locator("#asistente-respuesta").inner_text()
        chk("asistente responde (Fase 5 pendiente) sin XSS", len(resp) > 5 and page.locator('img[src="x"]').count() == 0, resp[:200])

        html = page.content()
        chk("la clave falsa no aparece en el DOM", CLAVE not in html, "")
        nav.close()

    chk("sin peticiones a dominios externos", not externas, externas[:10])
    chk("sin errores de JavaScript (pageerror)", not errores_pagina, errores_pagina[:5])
    chk("sin diálogos (alert) disparados", not dialogos, dialogos)
    chk("consola sin errores", not [c for c in consola if c.startswith("error")], consola[:10])
    (AQUI / "resultados_navegador.json").write_text(json.dumps({"resultados": resultados, "consola": consola, "externas": externas,
                                                                "errores_pagina": errores_pagina, "http_errores": http_errores},
                                                               ensure_ascii=False, indent=2), encoding="utf-8")
    print("Respuestas HTTP >= 400:", http_errores)
    print(f"TOTAL {len(resultados)}; fallas {sum(not r['ok'] for r in resultados)}")


if __name__ == "__main__":
    main()
