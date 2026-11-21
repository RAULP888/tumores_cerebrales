/* Panel del Doctor: datos del paciente ficticio, carga de resonancias,
   resultados por imagen, confirmación del doctor e historial. */
"use strict";

(function (TC) {
  const { el, icono, vaciar, api } = TC;

  const MAX_ARCHIVOS = 8;
  const MAX_BYTES = 10 * 1024 * 1024;
  const PATRON_ID = /^[A-Z]{2,5}-\d{1,6}$/;
  const TIPOS_VALIDOS = ["image/jpeg", "image/png"];
  const EXTENSIONES = /\.(jpe?g|png)$/i;
  const CLAVES_TUMOR = ["tumor", "glioma", "meningioma", "pituitary"];

  const $ = (id) => document.getElementById(id);
  let seleccion = []; // [{archivo, url}]
  let iniciado = false;

  /* ---------------- Pestañas ---------------- */
  function seleccionarPestana(nombre, enfocar) {
    const pestanas = [["nuevo", $("tab-nuevo"), $("doc-nuevo")], ["historial", $("tab-historial"), $("doc-historial")]];
    for (const [clave, tab, panel] of pestanas) {
      const activa = clave === nombre;
      tab.setAttribute("aria-selected", activa ? "true" : "false");
      tab.tabIndex = activa ? 0 : -1;
      panel.hidden = !activa;
      if (activa && enfocar) tab.focus();
    }
    if (nombre === "historial") cargarHistorial();
  }

  function teclasPestanas(evento) {
    if (evento.key !== "ArrowRight" && evento.key !== "ArrowLeft" && evento.key !== "Home" && evento.key !== "End") return;
    evento.preventDefault();
    const actual = $("tab-nuevo").getAttribute("aria-selected") === "true" ? "nuevo" : "historial";
    seleccionarPestana(actual === "nuevo" ? "historial" : "nuevo", true);
  }

  /* ---------------- Archivos ---------------- */
  function agregarArchivos(lista) {
    const errores = [];
    for (const archivo of Array.from(lista || [])) {
      const tipoValido = TIPOS_VALIDOS.includes(archivo.type) || (!archivo.type && EXTENSIONES.test(archivo.name));
      if (!tipoValido || !EXTENSIONES.test(archivo.name)) {
        errores.push("«" + archivo.name + "» no es una imagen JPG o PNG.");
        continue;
      }
      if (archivo.size > MAX_BYTES) {
        errores.push("«" + archivo.name + "» pesa más de 10 MB.");
        continue;
      }
      if (seleccion.some((s) => s.archivo.name === archivo.name && s.archivo.size === archivo.size && s.archivo.lastModified === archivo.lastModified)) {
        continue;
      }
      if (seleccion.length >= MAX_ARCHIVOS) {
        errores.push("Solo se pueden analizar hasta " + MAX_ARCHIVOS + " imágenes por estudio; «" + archivo.name + "» no se agregó.");
        continue;
      }
      seleccion.push({ archivo, url: URL.createObjectURL(archivo) });
    }
    TC.mostrarMensaje($("archivos-error"), errores.join(" "));
    dibujarMiniaturas();
  }

  function quitarArchivo(indice) {
    const [quitado] = seleccion.splice(indice, 1);
    if (quitado) URL.revokeObjectURL(quitado.url);
    dibujarMiniaturas();
    const botones = $("miniaturas").querySelectorAll("button");
    if (botones.length) botones[Math.min(indice, botones.length - 1)].focus();
    else $("boton-seleccionar").focus();
  }

  function dibujarMiniaturas() {
    const lista = vaciar($("miniaturas"));
    seleccion.forEach((s, i) => {
      lista.appendChild(el("li", { clase: "miniatura" },
        el("img", { src: s.url, alt: "Vista previa de " + s.archivo.name, onerror: (e) => { e.currentTarget.replaceWith(el("div", { clase: "miniatura__sin-vista" }, "Sin vista previa")); } }),
        el("div", { clase: "miniatura__pie" },
          el("span", { clase: "miniatura__nombre", title: s.archivo.name }, s.archivo.name),
          el("button", { type: "button", clase: "miniatura__quitar", "aria-label": "Quitar " + s.archivo.name, onclick: () => quitarArchivo(i) }, icono("basura")))
      ));
    });
  }

  function limpiarSeleccion() {
    seleccion.forEach((s) => URL.revokeObjectURL(s.url));
    seleccion = [];
    dibujarMiniaturas();
    $("est-archivos").value = "";
    TC.mostrarMensaje($("archivos-error"), "");
  }

  /* ---------------- Validación del formulario ---------------- */
  function validarEstudio() {
    const errores = [];
    const campos = {
      identificador: $("est-identificador"), edad: $("est-edad"), sexo: $("est-sexo"), fecha: $("est-fecha")
    };
    Object.values(campos).forEach((c) => c.removeAttribute("aria-invalid"));
    let primero = null;
    const marcar = (campo, mensaje) => { campo.setAttribute("aria-invalid", "true"); errores.push(mensaje); if (!primero) primero = campo; };

    const identificador = campos.identificador.value.trim().toUpperCase();
    campos.identificador.value = identificador;
    if (!PATRON_ID.test(identificador)) marcar(campos.identificador, "El identificador debe tener el formato PAC-0001 (de 2 a 5 letras mayúsculas, guion y de 1 a 6 dígitos).");
    const edadTexto = campos.edad.value.trim();
    const edad = Number(edadTexto);
    if (edadTexto === "" || !Number.isInteger(edad) || edad < 0 || edad > 120) marcar(campos.edad, "La edad debe ser un número entero entre 0 y 120.");
    if (!["F", "M", "Otro"].includes(campos.sexo.value)) marcar(campos.sexo, "Seleccione el sexo.");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(campos.fecha.value)) marcar(campos.fecha, "Indique la fecha del estudio.");
    if (seleccion.length === 0) {
      errores.push("Agregue al menos una resonancia (JPG o PNG).");
      if (!primero) primero = $("boton-seleccionar");
    }
    return { errores, primero, datos: { identificador, edad, sexo: campos.sexo.value, fecha_estudio: campos.fecha.value } };
  }

  async function analizar(evento) {
    evento.preventDefault();
    const { errores, primero, datos } = validarEstudio();
    TC.mostrarMensaje($("estudio-error"), errores.join(" "));
    if (errores.length) { if (primero) primero.focus(); return; }

    const formulario = new FormData();
    formulario.append("identificador", datos.identificador);
    formulario.append("edad", String(datos.edad));
    formulario.append("sexo", datos.sexo);
    formulario.append("fecha_estudio", datos.fecha_estudio);
    seleccion.forEach((s) => formulario.append("archivos", s.archivo, s.archivo.name));

    const restaurar = TC.botonCargando($("boton-analizar"), seleccion.length > 1 ? "Analizando " + seleccion.length + " imágenes…" : "Analizando…");
    try {
      const respuesta = await api("/api/estudios", { metodo: "POST", formulario });
      dibujarResultados((respuesta && respuesta.resultados) || [], datos);
    } catch (error) {
      TC.mostrarMensaje($("estudio-error"), error.message);
    } finally {
      restaurar();
    }
  }

  /* ---------------- Resultados ---------------- */
  function dibujarResultados(resultados, datos) {
    const contenedor = vaciar($("lista-resultados"));
    const conTumor = resultados.filter((r) => !r.error && r.hay_tumor === true).length;
    const conError = resultados.filter((r) => r.error).length;
    const partes = ["Paciente " + datos.identificador, resultados.length + (resultados.length === 1 ? " imagen" : " imágenes")];
    if (conTumor) partes.push(conTumor + " con posible tumor");
    if (conError) partes.push(conError + " con error");
    $("resultados-resumen").textContent = partes.join(" · ");
    resultados.forEach((r) => contenedor.appendChild(r.error ? tarjetaError(r) : tarjetaResultado(r)));
    if (resultados.length === 0) contenedor.appendChild(el("p", { clase: "vacio" }, "El servidor no devolvió resultados."));
    $("resultados").hidden = false;
    $("titulo-resultados").focus();
    $("resultados").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function tarjetaError(r) {
    return el("article", { clase: "resultado resultado--error" },
      el("div", { clase: "resultado__cabeza" },
        icono("error", "resultado__icono"),
        el("div", null,
          el("p", { clase: "resultado__etiqueta" }, "No se pudo analizar la imagen"),
          el("p", { clase: "resultado__archivo" }, r.archivo || "Archivo sin nombre"))),
      el("div", { clase: "resultado__error" }, el("p", { clase: "mensaje-error", role: "alert" }, icono("error"), el("span", null, String(r.error)))),
      el("p", { clase: "aviso aviso--medico resultado__aviso" }, icono("alerta"), el("span", null, TC.AVISO_MEDICO)));
  }

  function barraConfianza(valor) {
    const porcentaje = TC.esNumero(valor) ? Math.max(0, Math.min(100, valor * 100)) : 0;
    const relleno = el("div", { clase: "barra-progreso__relleno" });
    relleno.style.width = porcentaje.toFixed(1) + "%";
    return el("div", {
      clase: "barra-progreso", role: "meter", "aria-valuemin": 0, "aria-valuemax": 100,
      "aria-valuenow": porcentaje.toFixed(1), "aria-label": "Nivel de confianza", "aria-valuetext": TC.pct(valor)
    }, relleno);
  }

  function imagenesPar(imagenUrl, gradcamUrl, nombre) {
    const original = TC.urlSegura(imagenUrl);
    const mapa = TC.urlSegura(gradcamUrl);
    const figura = (url, titulo, alt) => el("figure", null,
      url ? el("img", { src: url, alt }) : el("div", { clase: "vacio" }, "Imagen no disponible"),
      el("figcaption", null, titulo));
    return el("div", null,
      el("div", { clase: "imagenes-par" },
        figura(original, "Imagen original", "Resonancia original " + (nombre || "")),
        figura(mapa, "Zona que más influyó", "Mapa Grad-CAM: zona que más influyó en la decisión del modelo")),
      el("p", { clase: "nota-gradcam" }, "El mapa resalta las regiones que más pesaron en la decisión del modelo. No delimita una lesión ni sustituye la lectura del especialista."));
  }

  function tarjetaResultado(r) {
    const hayTumor = r.hay_tumor === true;
    const etiqueta = r.etiqueta || (hayTumor ? "Se detecta posible tumor" : "No se detecta tumor");
    const tipoNombre = hayTumor && r.tipo_nombre ? r.tipo_nombre : null;

    const datos = el("div", { clase: "resultado__datos" },
      el("div", { clase: "confianza" },
        el("div", { clase: "confianza__titulo" }, el("span", null, "Nivel de confianza"), el("span", { clase: "confianza__valor" }, TC.pct(r.confianza))),
        barraConfianza(r.confianza)),
      tipoNombre ? el("p", { clase: "tipo-probable" }, "Tipo más probable: ", el("strong", null, tipoNombre),
        TC.esNumero(r.probabilidad_tipo) ? " (" + TC.pct(r.probabilidad_tipo, 0) + ")" : "") : null,
      el("dl", { clase: "datos-tecnicos" },
        el("div", null, el("dt", null, "Probabilidad de tumor"), el("dd", null, TC.pct(r.probabilidad_tumor))),
        el("div", null, el("dt", null, "Umbral de decisión"), el("dd", null, TC.decimal(r.umbral, 2))),
        el("div", null, el("dt", null, "Versión del modelo"), el("dd", null, r.modelo_version || "—")),
        el("div", null, el("dt", null, "Tiempo de respuesta"), el("dd", null, TC.milisegundos(r.tiempo_respuesta_ms)))));

    return el("article", { clase: "resultado " + (hayTumor ? "resultado--tumor" : "resultado--sin-tumor"), "aria-label": etiqueta + ": " + (r.archivo || "") },
      el("div", { clase: "resultado__cabeza" },
        icono(hayTumor ? "alerta" : "ok", "resultado__icono"),
        el("div", null,
          el("p", { clase: "resultado__etiqueta" }, etiqueta),
          el("p", { clase: "resultado__archivo" }, r.archivo || ""))),
      el("div", { clase: "resultado__cuerpo" }, datos, imagenesPar(r.imagen_url, r.gradcam_url, r.archivo)),
      el("p", { clase: "aviso aviso--medico resultado__aviso" }, icono("alerta"), el("strong", null, TC.AVISO_MEDICO)),
      TC.esNumero(r.prediccion_id) || typeof r.prediccion_id === "string"
        ? crearConfirmacion({ prediccion_id: r.prediccion_id, hay_tumor: hayTumor, tipo_probable: r.tipo_probable, tipo_nombre: r.tipo_nombre, de_acuerdo: null })
        : null);
  }

  /* ---------------- Confirmación del doctor ---------------- */
  function claveTipo(estudio) {
    if (estudio.tipo_probable && TC.DIAGNOSTICOS[estudio.tipo_probable]) return estudio.tipo_probable;
    if (estudio.tipo_nombre) {
      const nombre = String(estudio.tipo_nombre).toLowerCase();
      for (const [clave, texto] of Object.entries(TC.DIAGNOSTICOS)) {
        if (clave === nombre || texto.toLowerCase() === nombre) return clave;
      }
    }
    return "tumor";
  }

  /**
   * Componente de confirmación. estudio: {prediccion_id, hay_tumor, tipo_probable?, tipo_nombre?, de_acuerdo?}.
   * alRegistrar(estudioActualizado) se llama cuando el servidor acepta la confirmación.
   */
  function crearConfirmacion(estudio, opciones = {}) {
    const contenedor = el("div", { clase: "confirmacion" + (opciones.enDialogo ? " confirmacion--en-dialogo" : "") });
    const idBase = "conf-" + String(estudio.prediccion_id).replace(/[^A-Za-z0-9_-]/g, "") + (opciones.enDialogo ? "-d" : "");

    function mostrarRegistrado(deAcuerdo, diagnostico) {
      vaciar(contenedor);
      contenedor.appendChild(el("p", { clase: "mensaje-exito", role: "status" }, icono("ok"),
        el("span", null, "Confirmación registrada: " + (deAcuerdo ? "de acuerdo" : "en desacuerdo") + " con el resultado. Diagnóstico real indicado: " + TC.nombreDiagnostico(diagnostico) + ".")));
    }

    if (estudio.de_acuerdo === true || estudio.de_acuerdo === false) {
      mostrarRegistrado(estudio.de_acuerdo, estudio.diagnostico_confirmado);
      return contenedor;
    }

    const hayTumor = estudio.hay_tumor === true;
    const botonSi = el("button", { type: "button", clase: "boton boton--secundario", "aria-pressed": "false" }, icono("pulgar"), "De acuerdo");
    const botonNo = el("button", { type: "button", clase: "boton boton--secundario", "aria-pressed": "false" }, icono("pulgarAbajo"), "No estoy de acuerdo");
    const selector = el("select", { id: idBase + "-diag" });
    const ayuda = el("small", { id: idBase + "-ayuda" });
    selector.setAttribute("aria-describedby", idBase + "-ayuda");
    const error = el("p", { clase: "mensaje-error", role: "alert", hidden: true });
    const botonRegistrar = el("button", { type: "button", clase: "boton boton--primario" }, "Registrar confirmación");
    const detalle = el("div", { clase: "confirmacion__detalle", hidden: true },
      el("div", { clase: "campo" }, el("label", { for: idBase + "-diag" }, "Diagnóstico real"), selector, ayuda),
      error,
      el("div", { clase: "acciones acciones--izquierda" }, botonRegistrar));
    let deAcuerdo = null;

    function elegir(valor) {
      deAcuerdo = valor;
      botonSi.setAttribute("aria-pressed", valor ? "true" : "false");
      botonNo.setAttribute("aria-pressed", valor ? "false" : "true");
      // Si coincide con el modelo: hay tumor → precisar el tipo; sin tumor → "Sin tumor".
      // Si no coincide: el diagnóstico real es el contrario.
      const realEsTumor = valor ? hayTumor : !hayTumor;
      const claves = realEsTumor ? CLAVES_TUMOR : ["sin_tumor"];
      vaciar(selector);
      claves.forEach((c) => selector.appendChild(el("option", { value: c }, TC.nombreDiagnostico(c))));
      selector.value = realEsTumor ? (valor ? claveTipo(estudio) : "tumor") : "sin_tumor";
      ayuda.textContent = realEsTumor
        ? (valor ? "Precise el tipo de tumor si lo conoce; si no, elija «Tumor sin tipo definido»." : "Indique el tipo de tumor si lo conoce; si no, elija «Tumor sin tipo definido».")
        : (valor ? "El estudio quedará registrado como «Sin tumor»." : "El estudio quedará registrado como «Sin tumor» (posible falso positivo).");
      detalle.hidden = false;
      TC.mostrarMensaje(error, "");
      selector.focus();
    }
    botonSi.addEventListener("click", () => elegir(true));
    botonNo.addEventListener("click", () => elegir(false));

    botonRegistrar.addEventListener("click", async () => {
      if (deAcuerdo === null) return;
      const diagnostico = selector.value;
      const restaurar = TC.botonCargando(botonRegistrar, "Registrando…");
      try {
        const actualizado = await api("/api/estudios/" + encodeURIComponent(estudio.prediccion_id) + "/confirmacion", {
          metodo: "POST", cuerpo: { de_acuerdo: deAcuerdo, diagnostico_real: diagnostico }
        });
        const finalAcuerdo = actualizado && typeof actualizado.de_acuerdo === "boolean" ? actualizado.de_acuerdo : deAcuerdo;
        const finalDiag = actualizado && actualizado.diagnostico_confirmado ? actualizado.diagnostico_confirmado : diagnostico;
        mostrarRegistrado(finalAcuerdo, finalDiag);
        TC.avisoFlotante("La confirmación quedó registrada.", "exito");
        if (typeof opciones.alRegistrar === "function") opciones.alRegistrar(actualizado);
      } catch (e) {
        restaurar();
        TC.mostrarMensaje(error, e.message);
      }
    });

    contenedor.appendChild(el("p", { clase: "confirmacion__pregunta" }, "¿Está de acuerdo con este resultado?"));
    contenedor.appendChild(el("div", { clase: "confirmacion__botones", role: "group", "aria-label": "Confirmación del doctor" }, botonSi, botonNo));
    contenedor.appendChild(detalle);
    return contenedor;
  }

  /* ---------------- Historial ---------------- */
  let historialSecuencia = 0;

  async function cargarHistorial() {
    const contenedor = $("historial-contenedor");
    const secuencia = ++historialSecuencia;
    const parametros = {
      desde: $("fh-desde").value, hasta: $("fh-hasta").value,
      resultado: $("fh-resultado").value, confirmacion: $("fh-confirmacion").value,
      identificador: $("fh-identificador").value.trim().toUpperCase(), limite: 100
    };
    vaciar(contenedor).appendChild(el("p", { clase: "vacio" }, "Cargando estudios…"));
    try {
      const datos = await api("/api/estudios" + TC.consulta(parametros));
      if (secuencia !== historialSecuencia) return;
      const estudios = (datos && datos.estudios) || [];
      $("historial-total").textContent = estudios.length === 1 ? "1 estudio" : estudios.length + " estudios" + (estudios.length >= 100 ? " (se muestran los 100 más recientes)" : "");
      vaciar(contenedor).appendChild(tablaHistorial(estudios));
    } catch (e) {
      if (secuencia !== historialSecuencia) return;
      $("historial-total").textContent = "";
      const mensaje = el("p", { clase: "mensaje-error", role: "alert" });
      TC.mostrarMensaje(mensaje, e.message);
      vaciar(contenedor).appendChild(mensaje);
    }
  }

  function tablaHistorial(estudios) {
    const esAdmin = TC.estado.usuario && TC.estado.usuario.rol === "administrador";
    const columnas = [
      { titulo: "Imagen", celda: (e) => {
        const url = TC.urlSegura(e.imagen_url);
        return url ? el("img", { src: url, alt: "Resonancia de " + (e.identificador || "paciente"), clase: "tabla-miniatura", loading: "lazy" }) : "—";
      } },
      { titulo: "Registrado", celda: (e) => TC.fechaHora(e.creado_en) },
      { titulo: "Paciente", celda: (e) => el("span", null, el("strong", null, e.identificador || "—"),
        el("br"), (TC.esNumero(e.edad) ? e.edad + " años" : "—") + " · " + (e.sexo || "—") + " · " + TC.fecha(e.fecha_estudio)) },
      { titulo: "Resultado", celda: (e) => TC.distintivoResultado(e.hay_tumor) },
      { titulo: "Confianza", clase: "num", celda: (e) => TC.pct(e.confianza) },
      { titulo: "Tipo más probable", celda: (e) => (e.hay_tumor ? e.tipo_nombre : null) },
      { titulo: "Versión", celda: (e) => e.modelo_version },
      { titulo: "Confirmación", celda: (e) => el("span", null, TC.distintivoConfirmacion(e.de_acuerdo),
        e.diagnostico_confirmado ? el("span", null, el("br"), "Real: " + TC.nombreDiagnostico(e.diagnostico_confirmado)) : null) },
      { titulo: "Acciones", celda: (e) => el("div", { clase: "celda-acciones" },
        el("button", { type: "button", clase: "boton boton--texto boton--chico", onclick: () => verImagenes(e) }, "Ver imágenes"),
        e.de_acuerdo !== true && e.de_acuerdo !== false
          ? el("button", { type: "button", clase: "boton boton--primario boton--chico", onclick: () => confirmarDesdeHistorial(e) }, "Confirmar")
          : null) }
    ];
    if (esAdmin) columnas.splice(3, 0, { titulo: "Doctor", celda: (e) => e.doctor });
    return TC.tabla(columnas, estudios, { vacio: "No hay estudios que coincidan con los filtros.", titulo: "Historial de estudios" });
  }

  function verImagenes(estudio) {
    const cuerpo = el("div", null,
      el("p", null, el("strong", null, estudio.etiqueta || (estudio.hay_tumor ? "Se detecta posible tumor" : "No se detecta tumor")),
        " · Confianza " + TC.pct(estudio.confianza)),
      imagenesPar(estudio.imagen_url, estudio.gradcam_url, estudio.identificador),
      el("p", { clase: "aviso aviso--medico", style: "margin-top:.8rem" }, icono("alerta"), el("strong", null, TC.AVISO_MEDICO)));
    TC.abrirDialogo({ titulo: "Estudio de " + (estudio.identificador || "paciente"), cuerpo, sinAceptar: true, textoCancelar: "Cerrar" });
  }

  function confirmarDesdeHistorial(estudio) {
    const cuerpo = el("div", null,
      el("p", null, "Resultado del sistema: ", el("strong", null, estudio.etiqueta || (estudio.hay_tumor ? "Se detecta posible tumor" : "No se detecta tumor")),
        " (confianza " + TC.pct(estudio.confianza) + ")."),
      el("p", { clase: "aviso-medico-linea" }, TC.AVISO_MEDICO),
      crearConfirmacion(estudio, { enDialogo: true, alRegistrar: () => cargarHistorial() }));
    TC.abrirDialogo({ titulo: "Confirmar estudio " + (estudio.identificador || ""), cuerpo, sinAceptar: true, textoCancelar: "Cerrar" });
  }

  /* ---------------- Inicio ---------------- */
  function enlazar() {
    $("tab-nuevo").addEventListener("click", () => seleccionarPestana("nuevo"));
    $("tab-historial").addEventListener("click", () => seleccionarPestana("historial"));
    $("tab-nuevo").addEventListener("keydown", teclasPestanas);
    $("tab-historial").addEventListener("keydown", teclasPestanas);

    $("est-identificador").addEventListener("input", (e) => {
      const campo = e.target;
      const inicio = campo.selectionStart;
      campo.value = campo.value.toUpperCase();
      try { campo.setSelectionRange(inicio, inicio); } catch (err) { /* sin cursor */ }
      campo.removeAttribute("aria-invalid");
    });
    ["est-edad", "est-sexo", "est-fecha"].forEach((id) => $(id).addEventListener("input", (e) => e.target.removeAttribute("aria-invalid")));

    const zona = $("zona-carga");
    const entrada = $("est-archivos");
    $("boton-seleccionar").addEventListener("click", () => entrada.click());
    entrada.addEventListener("change", () => { agregarArchivos(entrada.files); entrada.value = ""; });
    ["dragenter", "dragover"].forEach((tipo) => zona.addEventListener(tipo, (e) => { e.preventDefault(); zona.classList.add("zona-carga--activa"); }));
    ["dragleave", "dragend"].forEach((tipo) => zona.addEventListener(tipo, (e) => { if (!zona.contains(e.relatedTarget)) zona.classList.remove("zona-carga--activa"); }));
    zona.addEventListener("drop", (e) => {
      e.preventDefault();
      zona.classList.remove("zona-carga--activa");
      if (e.dataTransfer && e.dataTransfer.files) agregarArchivos(e.dataTransfer.files);
    });
    // Evita que soltar un archivo fuera de la zona abra la imagen en el navegador.
    window.addEventListener("dragover", (e) => e.preventDefault());
    window.addEventListener("drop", (e) => e.preventDefault());

    $("formulario-estudio").addEventListener("submit", analizar);
    $("boton-limpiar-estudio").addEventListener("click", () => {
      $("formulario-estudio").reset();
      $("est-fecha").value = TC.hoyISO();
      limpiarSeleccion();
      TC.mostrarMensaje($("estudio-error"), "");
      $("formulario-estudio").querySelectorAll("[aria-invalid]").forEach((c) => c.removeAttribute("aria-invalid"));
      $("resultados").hidden = true;
      $("est-identificador").focus();
    });

    $("filtros-historial").addEventListener("submit", (e) => { e.preventDefault(); cargarHistorial(); });
    $("filtros-historial").addEventListener("reset", () => setTimeout(cargarHistorial, 0));
  }

  function iniciar() {
    if (!iniciado) { enlazar(); iniciado = true; }
    const fecha = $("est-fecha");
    if (!fecha.value) fecha.value = TC.hoyISO();
    fecha.max = TC.hoyISO();
    seleccionarPestana("nuevo");
  }

  function reiniciar() {
    if (!iniciado) return;
    $("formulario-estudio").reset();
    limpiarSeleccion();
    vaciar($("lista-resultados"));
    $("resultados").hidden = true;
    vaciar($("historial-contenedor"));
    TC.mostrarMensaje($("estudio-error"), "");
  }

  TC.doctor = { iniciar, reiniciar, crearConfirmacion };
})(window.TC);
