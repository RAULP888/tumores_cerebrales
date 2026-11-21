/* Utilidades compartidas: creación segura de nodos, íconos, llamadas a la API,
   formatos y componentes pequeños. Los datos del servidor se insertan siempre
   como texto (textContent o nodos de texto), nunca como HTML. */
"use strict";

window.TC = window.TC || {};

(function (TC) {
  const SVG_NS = "http://www.w3.org/2000/svg";

  /* ------------------------------------------------------------------
     Creación de nodos. Las cadenas y números se convierten en nodos de
     texto, de modo que nunca se interpretan como HTML.
     ------------------------------------------------------------------ */
  function agregarHijos(nodo, hijos) {
    for (const hijo of hijos) {
      if (hijo === null || hijo === undefined || hijo === false) continue;
      if (Array.isArray(hijo)) { agregarHijos(nodo, hijo); continue; }
      if (hijo instanceof Node) nodo.appendChild(hijo);
      else nodo.appendChild(document.createTextNode(String(hijo)));
    }
  }

  function el(etiqueta, atributos, ...hijos) {
    const nodo = document.createElement(etiqueta);
    if (atributos) {
      for (const [clave, valor] of Object.entries(atributos)) {
        if (valor === null || valor === undefined || valor === false) continue;
        if (clave === "clase") nodo.className = valor;
        else if (clave === "texto") nodo.textContent = String(valor);
        else if (clave.startsWith("on") && typeof valor === "function") nodo.addEventListener(clave.slice(2), valor);
        else if (clave === "dataset") Object.assign(nodo.dataset, valor);
        else if (valor === true) nodo.setAttribute(clave, "");
        else nodo.setAttribute(clave, String(valor));
      }
    }
    agregarHijos(nodo, hijos);
    return nodo;
  }

  function svg(etiqueta, atributos, ...hijos) {
    const nodo = document.createElementNS(SVG_NS, etiqueta);
    if (atributos) {
      for (const [clave, valor] of Object.entries(atributos)) {
        if (valor === null || valor === undefined) continue;
        if (clave === "clase") nodo.setAttribute("class", valor);
        else if (clave === "texto") nodo.textContent = String(valor);
        else nodo.setAttribute(clave, String(valor));
      }
    }
    for (const hijo of hijos) {
      if (hijo === null || hijo === undefined) continue;
      if (hijo instanceof Node) nodo.appendChild(hijo);
      else nodo.appendChild(document.createTextNode(String(hijo)));
    }
    return nodo;
  }

  function vaciar(nodo) {
    while (nodo.firstChild) nodo.removeChild(nodo.firstChild);
    return nodo;
  }

  /* ------------------------------------------------------------------
     Íconos (trazos propios, 24×24).
     ------------------------------------------------------------------ */
  const ICONOS = {
    alerta: ["M12 3 2.5 20h19L12 3z", "M12 10v4.5", "M12 17.3h.01"],
    ok: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "m8 12.3 2.7 2.7L16.3 9.5"],
    error: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M9 9l6 6", "M15 9l-6 6"],
    info: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 11v5", "M12 8h.01"],
    reloj: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 7v5l3 2"],
    check: ["M20 6 9 17l-5-5"],
    cruz: ["M6 6l12 12", "M18 6 6 18"],
    pulgar: ["M7 11v9H4v-9h3z", "M7 11l4-7a2 2 0 0 1 2 2v4h5.5a2 2 0 0 1 2 2.3l-1.2 6A2 2 0 0 1 17.3 20H7"],
    pulgarAbajo: ["M7 13V4H4v9h3z", "M7 13l4 7a2 2 0 0 0 2-2v-4h5.5a2 2 0 0 0 2-2.3l-1.2-6A2 2 0 0 0 17.3 4H7"],
    estudios: ["M6 3h9l4 4v14H6z", "M14 3v5h5", "M9 13h7", "M9 17h5"],
    calendario: ["M4 6h16v15H4z", "M4 10h16", "M8 3v5", "M16 3v5"],
    porcentaje: ["M19 5 5 19", "M7 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4z", "M17 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4z"],
    desacuerdo: ["M4 5h16v11H9l-5 4z", "M10 8.5l4 4", "M14 8.5l-4 4"],
    modelo: ["M12 3 4 7.5v9L12 21l8-4.5v-9z", "M4 7.5 12 12l8-4.5", "M12 12v9"],
    rayo: ["M13 2 4 14h7l-1 8 9-12h-7z"],
    confirmado: ["M9 12l2 2 4-4", "M12 3l7 3v5c0 5-3.5 8.5-7 10-3.5-1.5-7-5-7-10V6z"],
    buscar: ["M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z", "m20 20-4-4"],
    basura: ["M4 7h16", "M10 11v6", "M14 11v6", "M6 7l1 13h10l1-13", "M9 7V4h6v3"],
    grafica: ["M4 19V5", "M4 19h16", "M8 15l3-4 3 2 4-6"],
    cerebro: ["M12 4c-4.5 0-7 3-7 7.5S8 20 12 20s7-4 7-8.5S16.5 4 12 4z", "M12 5v14", "M8.5 9c1.5.8 1.5 2.3 0 3.4", "M15.5 9c-1.5.8-1.5 2.3 0 3.4"]
  };

  function icono(nombre, clase) {
    const nodo = svg("svg", { viewBox: "0 0 24 24", clase: clase || "icono", "aria-hidden": "true", focusable: "false" });
    for (const d of ICONOS[nombre] || ICONOS.info) {
      nodo.appendChild(svg("path", { d, fill: "none", stroke: "currentColor", "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round" }));
    }
    return nodo;
  }

  /* ------------------------------------------------------------------
     Llamadas a la API.
     ------------------------------------------------------------------ */
  class ErrorApi extends Error {
    constructor(estado, mensaje, datos) {
      super(mensaje);
      this.estado = estado;
      this.datos = datos;
    }
  }

  function textoDetalle(datos) {
    if (!datos) return "";
    const d = datos.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      // Errores de validación de FastAPI: [{loc, msg, type}]
      return d.map((e) => (e && typeof e.msg === "string" ? e.msg : "")).filter(Boolean).join(" ");
    }
    if (d && typeof d === "object" && typeof d.mensaje === "string") return d.mensaje;
    return "";
  }

  /**
   * Llama a la API con la cookie de sesión.
   * opciones: metodo, cuerpo (JSON), formulario (FormData), sin401 (no redirigir en 401).
   */
  async function api(ruta, opciones = {}) {
    const init = { method: opciones.metodo || "GET", credentials: "same-origin", headers: { Accept: "application/json" } };
    if (opciones.formulario) {
      init.body = opciones.formulario;
    } else if (opciones.cuerpo !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opciones.cuerpo);
    }
    let respuesta;
    try {
      respuesta = await fetch(ruta, init);
    } catch (e) {
      throw new ErrorApi(0, "No se pudo conectar con el servidor. Verifique que esté en ejecución e intente de nuevo.");
    }
    let datos = null;
    const tipo = respuesta.headers.get("content-type") || "";
    if (tipo.includes("application/json")) {
      try { datos = await respuesta.json(); } catch (e) { datos = null; }
    }
    if (respuesta.ok) return datos;

    const detalle = textoDetalle(datos);
    if (respuesta.status === 401) {
      if (!opciones.sin401 && typeof TC.alSesionExpirada === "function") TC.alSesionExpirada();
      throw new ErrorApi(401, detalle || "Su sesión no es válida o terminó. Inicie sesión de nuevo.", datos);
    }
    if (respuesta.status === 403) {
      const base = "No tiene permiso para realizar esta acción.";
      throw new ErrorApi(403, detalle && detalle !== base ? base + " " + detalle : base, datos);
    }
    let mensaje = detalle;
    if (!mensaje) {
      if (respuesta.status === 404) mensaje = "No se encontró el recurso solicitado.";
      else if (respuesta.status === 413) mensaje = "Los archivos son demasiado grandes.";
      else if (respuesta.status >= 500) mensaje = "Ocurrió un error en el servidor. Intente de nuevo en unos momentos.";
      else mensaje = "No se pudo completar la solicitud (código " + respuesta.status + ").";
    }
    throw new ErrorApi(respuesta.status, mensaje, datos);
  }

  function consulta(parametros) {
    const p = new URLSearchParams();
    for (const [clave, valor] of Object.entries(parametros)) {
      if (valor === null || valor === undefined || valor === "") continue;
      p.set(clave, String(valor));
    }
    const texto = p.toString();
    return texto ? "?" + texto : "";
  }

  /* ------------------------------------------------------------------
     Formatos.
     ------------------------------------------------------------------ */
  const esNumero = (v) => typeof v === "number" && Number.isFinite(v);

  function pct(valor, decimales = 1) {
    if (!esNumero(valor)) return "—";
    // Evita redondear a 100 % o a 0 % un valor que no lo es.
    const minimo = Math.pow(10, -decimales);
    if (valor < 1 && valor * 100 > 100 - minimo / 2) return "> " + (100 - minimo).toFixed(decimales) + " %";
    if (valor > 0 && valor * 100 < minimo / 2) return "< " + minimo.toFixed(decimales) + " %";
    return (valor * 100).toLocaleString("es-MX", { minimumFractionDigits: decimales, maximumFractionDigits: decimales }) + " %";
  }

  function num(valor, decimales = 0) {
    if (!esNumero(valor)) return "—";
    return valor.toLocaleString("es-MX", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
  }

  function decimal(valor, decimales = 3) {
    if (!esNumero(valor)) return "—";
    return valor.toFixed(decimales);
  }

  function milisegundos(valor) {
    if (!esNumero(valor)) return "—";
    if (valor >= 1000) return (valor / 1000).toLocaleString("es-MX", { maximumFractionDigits: 2 }) + " s";
    return Math.round(valor).toLocaleString("es-MX") + " ms";
  }

  function fechaHora(iso) {
    if (!iso) return "—";
    const f = new Date(iso);
    if (Number.isNaN(f.getTime())) return String(iso);
    return f.toLocaleString("es-MX", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function fecha(iso) {
    if (!iso) return "—";
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso));
    if (!m) return String(iso);
    const f = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return f.toLocaleDateString("es-MX", { day: "2-digit", month: "short", year: "numeric" });
  }

  function hoyISO() {
    const f = new Date();
    const dos = (n) => String(n).padStart(2, "0");
    return f.getFullYear() + "-" + dos(f.getMonth() + 1) + "-" + dos(f.getDate());
  }

  const DIAGNOSTICOS = {
    sin_tumor: "Sin tumor",
    tumor: "Tumor sin tipo definido",
    glioma: "Glioma",
    meningioma: "Meningioma",
    pituitary: "Tumor hipofisario"
  };
  function nombreDiagnostico(clave) {
    if (clave === null || clave === undefined || clave === "") return "—";
    return DIAGNOSTICOS[clave] || String(clave);
  }

  const ROLES = { doctor: "Doctor", administrador: "Administrador" };
  const nombreRol = (rol) => ROLES[rol] || String(rol || "—");

  /* Solo se aceptan rutas del mismo sitio (p. ej. /media/...) o http(s). */
  function urlSegura(url) {
    if (typeof url !== "string" || !url) return null;
    if (url.startsWith("/") && !url.startsWith("//")) return url;
    try {
      const u = new URL(url, window.location.href);
      if (u.protocol === "http:" || u.protocol === "https:") return u.href;
    } catch (e) { /* URL inválida */ }
    return null;
  }

  /* ------------------------------------------------------------------
     Componentes pequeños.
     ------------------------------------------------------------------ */
  function mostrarMensaje(nodo, mensaje) {
    if (!nodo) return;
    vaciar(nodo);
    if (!mensaje) { nodo.hidden = true; return; }
    nodo.appendChild(icono("error"));
    nodo.appendChild(el("span", null, mensaje));
    nodo.hidden = false;
  }

  function distintivo(texto, tipo, nombreIcono) {
    return el("span", { clase: "distintivo distintivo--" + tipo }, nombreIcono ? icono(nombreIcono) : null, texto);
  }

  function distintivoResultado(hayTumor) {
    if (hayTumor === true) return distintivo("Posible tumor", "tumor", "alerta");
    if (hayTumor === false) return distintivo("Sin tumor", "sin-tumor", "ok");
    return distintivo("Sin dato", "neutro", null);
  }

  function distintivoConfirmacion(deAcuerdo, diagnostico) {
    if (deAcuerdo === true) return distintivo("De acuerdo", "ok", "check");
    if (deAcuerdo === false) return distintivo("En desacuerdo", "advertencia", "cruz");
    return distintivo("Pendiente", "pendiente", "reloj");
  }

  /**
   * Tabla accesible. columnas: [{titulo, clase, celda(fila) -> nodo|texto}]
   */
  function tabla(columnas, filas, opciones = {}) {
    if (!filas || filas.length === 0) {
      return el("p", { clase: "vacio" }, opciones.vacio || "No hay registros para mostrar.");
    }
    const encabezado = el("tr", null, columnas.map((c) => el("th", { scope: "col", clase: c.clase || null }, c.titulo)));
    const cuerpo = el("tbody", null, filas.map((fila) =>
      el("tr", null, columnas.map((c) => {
        const contenido = c.celda(fila);
        return el("td", { clase: c.clase || null }, contenido === null || contenido === undefined || contenido === "" ? "—" : contenido);
      }))
    ));
    return el("table", null, opciones.titulo ? el("caption", null, opciones.titulo) : null, el("thead", null, encabezado), cuerpo);
  }

  function avisoFlotante(mensaje, tipo = "info") {
    const contenedor = document.getElementById("avisos-flotantes");
    const nombreIcono = tipo === "exito" ? "ok" : tipo === "error" ? "error" : "info";
    const nodo = el("div", { clase: "aviso-flotante aviso-flotante--" + tipo }, icono(nombreIcono), el("span", null, mensaje));
    contenedor.appendChild(nodo);
    setTimeout(() => nodo.remove(), tipo === "error" ? 7000 : 4500);
  }

  /**
   * Diálogo de confirmación dentro de la página (no usa confirm()).
   * Devuelve una promesa que se resuelve con true si se acepta.
   */
  function abrirDialogo({ titulo, cuerpo, textoAceptar = "Aceptar", textoCancelar = "Cancelar", peligro = false, sinAceptar = false }) {
    const dialogo = document.getElementById("dialogo");
    const anterior = document.activeElement;
    document.getElementById("dialogo-titulo").textContent = titulo;
    const contenedor = vaciar(document.getElementById("dialogo-cuerpo"));
    if (typeof cuerpo === "string") contenedor.appendChild(el("p", null, cuerpo));
    else if (cuerpo) contenedor.appendChild(cuerpo);
    const aceptar = document.getElementById("dialogo-aceptar");
    const cancelar = document.getElementById("dialogo-cancelar");
    aceptar.textContent = textoAceptar;
    aceptar.className = "boton " + (peligro ? "boton--peligro-solido" : "boton--primario");
    aceptar.hidden = sinAceptar;
    cancelar.textContent = textoCancelar;
    dialogo.returnValue = "";
    return new Promise((resolver) => {
      dialogo.addEventListener("close", function alCerrar() {
        dialogo.removeEventListener("close", alCerrar);
        if (anterior && typeof anterior.focus === "function" && document.body.contains(anterior)) anterior.focus();
        resolver(dialogo.returnValue === "aceptar");
      });
      if (typeof dialogo.showModal === "function") dialogo.showModal();
      else dialogo.setAttribute("open", "");
      (sinAceptar ? cancelar : aceptar).focus();
    });
  }

  function cerrarDialogo() {
    const dialogo = document.getElementById("dialogo");
    if (dialogo.open) dialogo.close("cerrar");
  }

  /* Botón con estado de carga: devuelve una función para restaurarlo. */
  function botonCargando(boton, texto) {
    const hijos = Array.from(boton.childNodes);
    const anchoMin = boton.offsetWidth;
    boton.disabled = true;
    boton.setAttribute("aria-busy", "true");
    vaciar(boton);
    boton.appendChild(el("span", { clase: "girador", "aria-hidden": "true" }));
    boton.appendChild(el("span", null, texto));
    if (anchoMin) boton.style.minWidth = anchoMin + "px";
    return function restaurar() {
      vaciar(boton);
      hijos.forEach((h) => boton.appendChild(h));
      boton.disabled = false;
      boton.removeAttribute("aria-busy");
      boton.style.minWidth = "";
    };
  }

  function retrasar(funcion, ms) {
    let temporizador = null;
    return function (...args) {
      clearTimeout(temporizador);
      temporizador = setTimeout(() => funcion.apply(this, args), ms);
    };
  }

  Object.assign(TC, {
    el, svg, vaciar, icono, api, ErrorApi, consulta,
    pct, num, decimal, milisegundos, fecha, fechaHora, hoyISO, esNumero,
    DIAGNOSTICOS, nombreDiagnostico, nombreRol, urlSegura,
    mostrarMensaje, distintivo, distintivoResultado, distintivoConfirmacion, tabla,
    avisoFlotante, abrirDialogo, cerrarDialogo, botonCargando, retrasar,
    AVISO_MEDICO: "Resultado de apoyo. No sustituye el diagnóstico de un médico especialista.",
    estado: { usuario: null, servidor: null }
  });
})(window.TC);
