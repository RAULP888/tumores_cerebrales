"""Prueba de punta a punta del frontend con un navegador sin cabeza (Playwright + Microsoft Edge).

Uso:
    # Contra el servidor simulado (lo arranca esta misma prueba en el puerto 8011):
    .venv\\Scripts\\python.exe pruebas\\prueba_frontend.py --modo simulador
    # Contra el backend real ya arrancado (no modifica modelos, umbral ni usuarios):
    .venv\\Scripts\\python.exe pruebas\\prueba_frontend.py --modo real --url http://127.0.0.1:8010

Guarda capturas en pruebas/capturas/<modo>/ y termina con código 1 si alguna comprobación falla.
Requiere: pip install playwright (usa el Edge instalado en Windows; no descarga navegadores).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import threading
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

RAIZ = Path(__file__).resolve().parents[1]
IMAGENES = [RAIZ / "datos" / "Testing" / "meningioma" / "Te-aug-me_1.jpg",
            RAIZ / "datos" / "Testing" / "notumor" / "Te-no_1.jpg",
            RAIZ / "datos" / "Testing" / "glioma" / "Te-gl_1.jpg"]

fallas: list[str] = []
aprobadas: list[str] = []


def comprobar(condicion: bool, descripcion: str):
    (aprobadas if condicion else fallas).append(descripcion)
    print(("  OK   " if condicion else "  FALLA ") + descripcion, flush=True)


def arrancar_simulador(puerto: int):
    import uvicorn
    sys.path.insert(0, str(RAIZ))
    from pruebas.simulador_frontend import app
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="warning"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    for _ in range(100):
        if servidor.started:
            return servidor
        time.sleep(0.1)
    raise RuntimeError("No arrancó el simulador")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modo", choices=["simulador", "real"], default="simulador")
    parser.add_argument("--url", default=None)
    parser.add_argument("--doctor", default="doctor1:Doctor2026!")
    parser.add_argument("--admin", default="admin1:Admin2026!")
    args = parser.parse_args()
    real = args.modo == "real"
    if real and not args.url:
        parser.error("--url es obligatorio en modo real")
    url = args.url or "http://127.0.0.1:8011"
    if not real:
        arrancar_simulador(8011)

    capturas = RAIZ / "pruebas" / "capturas" / args.modo
    capturas.mkdir(parents=True, exist_ok=True)
    doc_u, doc_p = args.doctor.split(":", 1)
    adm_u, adm_p = args.admin.split(":", 1)

    tmp = Path(tempfile.mkdtemp())
    danada = tmp / "imagen_danada.png"
    danada.write_bytes(b"esto no es una imagen")

    with sync_playwright() as p:
        navegador = p.chromium.launch(channel="msedge", headless=True)
        contexto = navegador.new_context(viewport={"width": 1366, "height": 768}, locale="es-MX")
        pagina = contexto.new_page()
        errores_consola: list[str] = []
        pagina.on("console", lambda m: errores_consola.append(m.text) if m.type == "error" else None)
        pagina.on("pageerror", lambda e: errores_consola.append("pageerror: " + str(e)))

        def captura(nombre, completa=True):
            pagina.wait_for_timeout(250)
            pagina.screenshot(path=str(capturas / f"{nombre}.png"), full_page=completa)

        def sin_desborde(nombre):
            ancho = pagina.evaluate("document.documentElement.scrollWidth")
            vista = pagina.evaluate("window.innerWidth")
            comprobar(ancho <= vista + 1, f"{nombre}: sin desplazamiento horizontal a {vista}px (scrollWidth={ancho})")

        print("== Bienvenida")
        pagina.goto(url + "/")
        expect(pagina.locator("#titulo-bienvenida")).to_have_text("Bienvenido al Sistema de Apoyo para Detección de Tumores Cerebrales")
        comprobar(pagina.locator("#pantalla-bienvenida").is_visible(), "La bienvenida se muestra sin sesión")
        comprobar("identificadores ficticios" in pagina.locator("#pantalla-bienvenida").inner_text(), "La bienvenida avisa de datos ficticios")
        captura("01_bienvenida", completa=False)

        print("== Inicio de sesión")
        pagina.click("#boton-iniciar")
        expect(pagina.locator("#pantalla-acceso")).to_be_visible()
        captura("02_elegir_rol", completa=False)
        pagina.click(".rol[data-rol='doctor']")
        pagina.fill("#acceso-usuario", doc_u)
        pagina.fill("#acceso-password", "incorrecta")
        pagina.click("#boton-entrar")
        expect(pagina.locator("#acceso-error")).to_be_visible()
        comprobar("incorrect" in pagina.locator("#acceso-error").inner_text().lower(), "Mensaje claro con contraseña incorrecta (401)")
        captura("03_acceso_error", completa=False)

        pagina.click(".rol[data-rol='administrador']")
        pagina.fill("#acceso-usuario", doc_u)
        pagina.fill("#acceso-password", doc_p)
        pagina.click("#boton-entrar")
        expect(pagina.locator("#acceso-error")).to_be_visible()
        comprobar(pagina.locator("#pantalla-acceso").is_visible(), "Rol equivocado (403) no deja entrar: " + pagina.locator("#acceso-error").inner_text())

        pagina.click(".rol[data-rol='doctor']")
        pagina.fill("#acceso-usuario", doc_u)
        pagina.fill("#acceso-password", doc_p)
        pagina.click("#boton-entrar")
        expect(pagina.locator("#pantalla-doctor")).to_be_visible()
        expect(pagina.locator("#cab-usuario")).to_have_text(doc_u)
        comprobar(pagina.locator("#cab-rol").inner_text() == "Doctor", "Cabecera muestra usuario y rol Doctor")
        comprobar(pagina.locator("#est-fecha").input_value() != "", "La fecha del estudio trae hoy por defecto")

        print("== Sesión retomada con /api/yo")
        pagina.reload()
        expect(pagina.locator("#pantalla-doctor")).to_be_visible()
        comprobar(True, "Al recargar se retoma la sesión del doctor")

        print("== Validación del formulario")
        pagina.fill("#est-identificador", "juan perez")
        pagina.fill("#est-edad", "45")
        pagina.select_option("#est-sexo", "F")
        pagina.click("#boton-analizar")
        expect(pagina.locator("#estudio-error")).to_be_visible()
        comprobar(pagina.locator("#est-identificador").get_attribute("aria-invalid") == "true", "Identificador inválido marcado (patrón ^[A-Z]{2,5}-\\d{1,6}$)")
        captura("04_validacion", completa=False)

        print("== Análisis")
        pagina.fill("#est-identificador", "pac-0042")
        comprobar(pagina.locator("#est-identificador").input_value() == "PAC-0042", "El identificador se convierte a mayúsculas")
        pagina.set_input_files("#est-archivos", [str(i) for i in IMAGENES] + [str(danada)])
        expect(pagina.locator("#miniaturas li")).to_have_count(4)
        captura("05_miniaturas")
        pagina.click("#boton-analizar")
        expect(pagina.locator("#lista-resultados .resultado")).to_have_count(4, timeout=120000)
        texto = pagina.locator("#lista-resultados").inner_text()
        comprobar(texto.count("Resultado de apoyo. No sustituye el diagnóstico de un médico especialista.") >= 4, "Cada tarjeta muestra el aviso médico")
        comprobar("Zona que más influyó" in texto, "El Grad-CAM se rotula «Zona que más influyó»")
        comprobar("ubicación del tumor" not in pagina.content().lower(), "No aparece «ubicación del tumor»")
        comprobar(pagina.locator(".resultado--error").count() == 1, "La imagen dañada muestra su error en su tarjeta")
        comprobar(pagina.locator(".resultado--tumor, .resultado--sin-tumor").count() == 3, "Tres tarjetas con resultado")
        cargadas = pagina.evaluate("Array.from(document.querySelectorAll('#lista-resultados img')).filter(i => i.complete && i.naturalWidth > 0).length")
        comprobar(cargadas >= 6, f"Las imágenes original y Grad-CAM cargan con la sesión ({cargadas})")
        captura("06_resultados")

        print("== Confirmación del doctor")
        tarjeta = pagina.locator("#lista-resultados .resultado").first
        tarjeta.get_by_role("button", name="No estoy de acuerdo").click()
        opciones = tarjeta.locator("select option").all_inner_texts()
        tarjeta.get_by_role("button", name="Registrar confirmación").click()
        expect(tarjeta.locator(".mensaje-exito")).to_be_visible()
        comprobar(True, "Desacuerdo registrado (opciones: " + ", ".join(opciones) + ")")
        segunda = pagina.locator("#lista-resultados .resultado:not(.resultado--error)").nth(1)
        segunda.get_by_role("button", name="De acuerdo", exact=True).click()
        segunda.get_by_role("button", name="Registrar confirmación").click()
        expect(segunda.locator(".mensaje-exito")).to_be_visible()
        comprobar(True, "Acuerdo registrado")
        captura("07_confirmaciones")

        print("== Historial")
        pagina.click("#tab-historial")
        expect(pagina.locator("#historial-contenedor table")).to_be_visible()
        filas = pagina.locator("#historial-contenedor tbody tr").count()
        comprobar(filas >= 3, f"El historial lista estudios ({filas})")
        captura("08_historial")
        pagina.select_option("#fh-confirmacion", "pendiente")
        pagina.click("#filtros-historial button[type=submit]")
        pagina.wait_for_timeout(600)
        pendientes = pagina.locator("#historial-contenedor tbody tr").count()
        comprobar(pendientes >= 1, f"Filtro «Pendiente» ({pendientes})")
        pagina.locator("#historial-contenedor tbody tr").first.get_by_role("button", name="Confirmar").click()
        dialogo = pagina.locator("#dialogo")
        expect(dialogo).to_be_visible()
        dialogo.get_by_role("button", name="De acuerdo", exact=True).click()
        captura("09_confirmar_desde_historial", completa=False)
        dialogo.get_by_role("button", name="Registrar confirmación").click()
        expect(dialogo.locator(".mensaje-exito")).to_be_visible()
        comprobar(True, "Confirmación desde el historial")
        dialogo.get_by_role("button", name="Cerrar").click()
        pagina.wait_for_timeout(500)

        estado_admin = pagina.evaluate("fetch('/api/admin/resumen', {credentials:'same-origin'}).then(r => r.status)")
        comprobar(estado_admin == 403, f"El doctor recibe 403 en /api/admin/resumen ({estado_admin})")

        print("== Vista de 400 px (doctor)")
        pagina.set_viewport_size({"width": 400, "height": 860})
        pagina.click("#tab-nuevo")
        pagina.wait_for_timeout(300)
        sin_desborde("Panel del doctor")
        captura("10_doctor_400px")
        pagina.set_viewport_size({"width": 1366, "height": 768})

        print("== Cerrar sesión")
        pagina.click("#boton-salir")
        expect(pagina.locator("#pantalla-acceso")).to_be_visible()
        comprobar(pagina.locator("#cabecera").is_hidden(), "Al cerrar sesión se oculta la cabecera")

        print("== Administrador")
        pagina.click(".rol[data-rol='administrador']")
        pagina.fill("#acceso-usuario", adm_u)
        pagina.fill("#acceso-password", adm_p)
        pagina.click("#boton-entrar")
        expect(pagina.locator("#pantalla-admin")).to_be_visible()
        expect(pagina.locator("#indicadores .indicador")).to_have_count(9)
        comprobar(pagina.locator("#cab-modelo").inner_text() not in ("—", ""), "Cabecera muestra el modelo en producción: " + pagina.locator("#cab-modelo").inner_text())
        captura("11_admin_resumen")

        def ir(seccion):
            pagina.click(f"#menu-admin button[data-seccion='{seccion}']")
            expect(pagina.locator(f"#sec-{seccion}")).to_be_visible()

        ir("reentrenar")
        expect(pagina.locator("#lista-entrenamientos")).not_to_be_empty()
        if not real:
            pagina.fill("#ent-epocas", "12")
            pagina.check("#ent-kfold")
            pagina.check("#ent-ajuste")
            pagina.click("#boton-entrenar")
            expect(pagina.locator("#progreso-entrenamiento")).to_be_visible()
            pagina.wait_for_timeout(5000)
            captura("12_entrenamiento_en_curso")
            pagina.click("#boton-entrenar")
            expect(pagina.locator("#entrenamiento-error")).to_be_visible()
            comprobar("en curso" in pagina.locator("#entrenamiento-error").inner_text(), "409 si ya hay un entrenamiento corriendo")
            expect(pagina.locator("#detalle-entrenamiento .diagnostico")).to_be_visible(timeout=60000)
            comprobar(pagina.locator("#detalle-entrenamiento .grafica > svg").count() == 2, "Curvas de pérdida y exactitud dibujadas en SVG")
            comprobar(pagina.locator("#detalle-entrenamiento .matriz").count() == 1, "Matriz de confusión 2×2")
            comprobar("Mejor época" in pagina.locator("#detalle-entrenamiento").inner_text(), "Marca de la mejor época")
            captura("13_entrenamiento_terminado")
            pagina.select_option("#detalle-entrenamiento select", index=1)
            pagina.wait_for_timeout(300)
            captura("13b_curvas_pliegue", completa=False)
            # Cancelación
            pagina.fill("#ent-epocas", "50")
            pagina.click("#boton-entrenar")
            pagina.wait_for_timeout(2500)
            pagina.click("#boton-cancelar-entrenamiento")
            pagina.locator("#dialogo").get_by_role("button", name="Sí, cancelar").click()
            expect(pagina.locator("#progreso-estado")).to_contain_text("Cancelado", timeout=15000)
            comprobar(True, "Cancelación del entrenamiento")
        else:
            filas = pagina.locator("#lista-entrenamientos tbody tr")
            if filas.count():
                filas.first.get_by_role("button").click()
                pagina.wait_for_timeout(1500)
                comprobar(pagina.locator("#detalle-entrenamiento .grafica, #detalle-entrenamiento .vacio").count() >= 1, "Se puede ver un entrenamiento anterior")
        captura("14_reentrenar")

        ir("modelos")
        expect(pagina.locator("#tabla-modelos table")).to_be_visible()
        comprobar(pagina.locator("#tabla-modelos").inner_text().count("En producción") == 1, "Exactamente un modelo en producción")
        captura("15_modelos")
        aprobar = pagina.get_by_role("button", name="Aprobar para producción")
        if aprobar.count():
            aprobar.first.click()
            expect(pagina.locator("#dialogo")).to_be_visible()
            captura("16_dialogo_aprobar", completa=False)
            if real:
                pagina.locator("#dialogo").get_by_role("button", name="Cancelar").click()
            else:
                pagina.locator("#dialogo").get_by_role("button", name="Aprobar para producción").click()
                expect(pagina.locator(".aviso-flotante--exito").last).to_be_visible()
                comprobar(True, "Aprobación de candidato con confirmación en la página")

        ir("umbral")
        expect(pagina.locator("#umbral-frase")).not_to_be_empty(timeout=20000)
        pagina.locator("#umbral-rango").fill("0.15")
        pagina.wait_for_timeout(1200)
        frase = pagina.locator("#umbral-frase").inner_text()
        comprobar("se habría" in frase, "Frase del umbral: " + frase)
        comprobar("0.15" in pagina.locator("#umbral-comparacion").inner_text(), "La comparación usa el umbral propuesto")
        captura("17_umbral")
        if not real:
            pagina.click("#boton-guardar-umbral")
            expect(pagina.locator("#umbral-actual")).to_have_text("0.15")
            comprobar(True, "Guardar umbral (PUT)")

        ir("usuarios")
        expect(pagina.locator("#tabla-usuarios table")).to_be_visible()
        if not real:
            pagina.fill("#nu-usuario", "doctor3")
            pagina.fill("#nu-password", "Doctor2026!")
            pagina.click("#formulario-usuario button[type=submit]")
            expect(pagina.locator("#tabla-usuarios")).to_contain_text("doctor3")
            fila = pagina.locator("#tabla-usuarios tbody tr", has_text="doctor3")
            fila.get_by_role("button", name="Desactivar").click()
            pagina.locator("#dialogo").get_by_role("button", name="Desactivar").click()
            expect(pagina.locator("#tabla-usuarios tbody tr", has_text="doctor3")).to_contain_text("Inactivo")
            pagina.locator("#tabla-usuarios tbody tr", has_text="doctor3").get_by_role("button", name="Cambiar contraseña").click()
            pagina.locator(".fila-edicion input").fill("NuevaClave2026!")
            pagina.locator(".fila-edicion").get_by_role("button", name="Guardar contraseña").click()
            expect(pagina.locator(".aviso-flotante--exito").last).to_contain_text("contraseña")
            comprobar(True, "Crear, desactivar y cambiar contraseña de un usuario")
        captura("18_usuarios")

        ir("bitacora")
        expect(pagina.locator("#tabla-bitacora table")).to_be_visible()
        n_acciones = pagina.locator("#fb-accion option").count()
        comprobar(n_acciones > 5, f"Lista de acciones cargada en el filtro ({n_acciones - 1})")
        captura("19_bitacora")
        if pagina.locator("#bitacora-siguiente").is_enabled():
            pagina.click("#bitacora-siguiente")
            expect(pagina.locator("#bitacora-pagina")).to_contain_text("Página 2")
            comprobar(True, "Paginación de la bitácora")
        pagina.select_option("#fb-accion", "LOGIN_OK")
        pagina.click("#filtros-bitacora button[type=submit]")
        pagina.wait_for_timeout(700)
        acciones = set(pagina.locator("#tabla-bitacora tbody td:nth-child(4)").all_inner_texts())
        comprobar(acciones <= {"LOGIN_OK"}, f"Filtro por acción ({acciones})")

        ir("powerbi")
        expect(pagina.locator("#powerbi-contenedor .pasos, #powerbi-contenedor iframe")).to_have_count(1, timeout=15000)
        comprobar("POWERBI_URL" in pagina.locator("#powerbi-contenedor").inner_text() or pagina.locator("#powerbi-contenedor iframe").count() == 1, "Power BI: iframe o instrucciones")
        captura("20_powerbi")

        ir("asistente")
        pagina.locator("[data-ejemplo]").first.click()
        expect(pagina.locator("#asistente-respuesta .tarjeta")).to_be_visible(timeout=60000)
        respuesta = pagina.locator("#asistente-respuesta").inner_text()
        comprobar(len(respuesta) > 10, "El asistente muestra una respuesta: " + respuesta[:90].replace("\n", " "))
        if not real:
            comprobar(pagina.locator("#asistente-respuesta pre code").count() == 1, "Se muestra la consulta SQL en un bloque de código")
            comprobar("<b>no-html</b>" in respuesta, "Los datos se insertan como texto (no se interpreta HTML)")
        captura("21_asistente")
        if not real:
            pagina.fill("#asistente-pregunta", "Borra todos los estudios")
            pagina.click("#boton-preguntar")
            expect(pagina.locator("#asistente-respuesta")).to_contain_text("Solo se permiten consultas de lectura")
            comprobar(True, "Estado «bloqueada» del asistente")
            captura("22_asistente_bloqueada")

        print("== Vista de 400 px (administrador)")
        pagina.set_viewport_size({"width": 400, "height": 860})
        ir("resumen")
        pagina.wait_for_timeout(500)
        sin_desborde("Panel del administrador")
        captura("23_admin_400px")
        pagina.set_viewport_size({"width": 1366, "height": 768})

        print("== Sesión expirada (401)")
        contexto.clear_cookies()
        pagina.click("#boton-actualizar-resumen")
        expect(pagina.locator("#pantalla-acceso")).to_be_visible()
        comprobar(pagina.locator("#aviso-sesion").is_visible(), "Con 401 se regresa al inicio de sesión con aviso")
        captura("24_sesion_expirada", completa=False)

        print("== Movimiento reducido")
        reducido = navegador.new_context(viewport={"width": 1366, "height": 768}, reduced_motion="reduce")
        pr = reducido.new_page()
        pr.goto(url + "/")
        anim = pr.evaluate("getComputedStyle(document.querySelector('.escaner__barrido')).animationName")
        comprobar(anim == "none", f"Con prefers-reduced-motion la línea de escaneo no se anima ({anim})")
        reducido.close()

        print("== Bienvenida a 400 px")
        movil = navegador.new_context(viewport={"width": 400, "height": 860})
        pm = movil.new_page()
        pm.goto(url + "/")
        pm.wait_for_timeout(300)
        ancho = pm.evaluate("document.documentElement.scrollWidth")
        comprobar(ancho <= 401, f"Bienvenida sin desplazamiento horizontal a 400px ({ancho})")
        pm.screenshot(path=str(capturas / "00_bienvenida_400px.png"), full_page=True)
        movil.close()

        reales = [e for e in errores_consola if "401" not in e and "403" not in e and "409" not in e and "Failed to load resource" not in e]
        comprobar(not reales, "Sin errores de JavaScript en la consola" + (": " + " | ".join(reales[:5]) if reales else ""))
        navegador.close()

    print(f"\nComprobaciones aprobadas: {len(aprobadas)} · fallas: {len(fallas)}")
    for f in fallas:
        print("  FALLA:", f)
    print("Capturas en", capturas)
    sys.exit(1 if fallas else 0)


if __name__ == "__main__":
    main()
