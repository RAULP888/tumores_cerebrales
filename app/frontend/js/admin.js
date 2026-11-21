/* Panel del Administrador: resumen, reentrenamiento, versiones del modelo,
   umbral de decisión, usuarios, bitácora, Power BI y asistente de consultas. */
"use strict";

(function (TC) {
  const { el, icono, vaciar, api } = TC;
  const $ = (id) => document.getElementById(id);

  const SECCIONES = ["resumen", "reentrenar", "modelos", "umbral", "usuarios", "bitacora", "powerbi", "asistente"];
  const CARGADORES = {};
  let iniciado = false;
  let seccionActual = null;

  function mensajeErrorEn(contenedor, mensaje) {
    const nodo = el("p", { clase: "mensaje-error", role: "alert" });
    TC.mostrarMensaje(nodo, mensaje);
    vaciar(contenedor).appendChild(nodo);
  }

  /* =========================== Navegación =========================== */
  function mostrarSeccion(nombre, enfocar) {
    if (!SECCIONES.includes(nombre)) nombre = "resumen";
    seccionActual = nombre;
    SECCIONES.forEach((s) => { $("sec-" + s).hidden = s !== nombre; });
    document.querySelectorAll("#menu-admin button").forEach((b) => {
      if (b.dataset.seccion === nombre) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
    if (enfocar) {
      const titulo = $("sec-" + nombre).querySelector("h2");
      if (titulo) titulo.focus();
    }
    if (CARGADORES[nombre]) CARGADORES[nombre]();
  }

  /* ============================= Resumen ============================ */
  function indicador({ titulo, valor, nota, nombreIcono, variante }) {
    return el("article", { clase: "indicador" + (variante ? " indicador--" + variante : "") },
      icono(nombreIcono, "indicador__icono"),
      el("div", null,
        el("h3", { clase: "indicador__titulo" }, titulo),
        el("p", { clase: "indicador__valor" }, valor),
        nota ? el("p", { clase: "indicador__nota" }, nota) : null));
  }

  function textoModelo(modelo) {
    if (!modelo) return { valor: "Sin modelo", nota: "No hay una versión en producción." };
    if (typeof modelo === "string") return { valor: modelo, nota: null };
    return { valor: modelo.version || "—", nota: [modelo.nombre, TC.esNumero(modelo.umbral) ? "umbral " + modelo.umbral.toFixed(2) : null].filter(Boolean).join(" · ") || null };
  }

  async function cargarResumen() {
    const contenedor = $("indicadores");
    vaciar(contenedor).appendChild(el("p", { clase: "vacio" }, "Cargando indicadores…"));
    try {
      const r = (await api("/api/admin/resumen")) || {};
      let proporcion = null;
      if (TC.esNumero(r.estudios) && r.estudios > 0 && TC.esNumero(r.con_tumor)) proporcion = r.con_tumor / r.estudios;
      else if (TC.esNumero(r.pct_tumor)) proporcion = r.pct_tumor > 1 ? r.pct_tumor / 100 : r.pct_tumor;
      const modelo = textoModelo(r.modelo_produccion);
      vaciar(contenedor);
      [
        { titulo: "Estudios registrados", valor: TC.num(r.estudios), nombreIcono: "estudios" },
        { titulo: "Estudios de hoy", valor: TC.num(r.estudios_hoy), nombreIcono: "calendario" },
        { titulo: "Con posible tumor", valor: TC.pct(proporcion), nota: TC.esNumero(r.con_tumor) ? TC.num(r.con_tumor) + " de " + TC.num(r.estudios) + " estudios" : null, nombreIcono: "porcentaje", variante: "alerta" },
        { titulo: "Confirmados por un doctor", valor: TC.num(r.confirmados), nombreIcono: "confirmado", variante: "verde" },
        { titulo: "Desacuerdos del doctor", valor: TC.num(r.desacuerdos), nota: "El doctor no coincidió con el sistema", nombreIcono: "desacuerdo", variante: "ambar" },
        { titulo: "Falsos negativos confirmados", valor: TC.num(r.falsos_negativos), nota: "Tumores que el sistema no detectó", nombreIcono: "alerta", variante: "alerta" },
        { titulo: "Falsos positivos confirmados", valor: TC.num(r.falsos_positivos), nota: "Alertas que resultaron sin tumor", nombreIcono: "info", variante: "ambar" },
        { titulo: "Tiempo promedio de respuesta", valor: TC.milisegundos(r.tiempo_promedio_ms), nota: "Por imagen analizada", nombreIcono: "rayo" },
        { titulo: "Modelo en producción", valor: modelo.valor, nota: modelo.nota, nombreIcono: "modelo", variante: "verde" }
      ].forEach((d) => contenedor.appendChild(indicador(d)));
    } catch (e) {
      mensajeErrorEn(contenedor, e.message);
    }
  }

  /* =========================== Reentrenar =========================== */
  const ESTADOS_ENTRENAMIENTO = {
    en_cola: ["En cola", "info", "reloj"],
    corriendo: ["En curso", "info", "reloj"],
    terminado: ["Terminado", "ok", "check"],
    cancelado: ["Cancelado", "neutro", "cruz"],
    error: ["Con error", "error", "error"]
  };
  const TERMINALES = ["terminado", "cancelado", "error"];

  function distintivoEstado(estado) {
    const [texto, tipo, nombreIcono] = ESTADOS_ENTRENAMIENTO[estado] || [String(estado || "Desconocido"), "neutro", "info"];
    return TC.distintivo(texto, tipo, nombreIcono);
  }

  function textoDiagnostico(diagnostico) {
    if (!diagnostico) return null;
    if (typeof diagnostico === "object") return diagnostico.etiqueta || null;
    return String(diagnostico);
  }

  function claseDiagnostico(texto) {
    const t = (texto || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    if (t.includes("antes de converger")) return ["advertencia", "reloj"];
    if (t.includes("converg")) return ["ok", "ok"];
    if (t.includes("sobreajuste")) return ["advertencia", "alerta"];
    if (t.includes("no aprende")) return ["alerta", "error"];
    return ["neutro", "info"];
  }

  let seguimiento = { id: null, temporizador: null, activo: false };

  function detenerSeguimiento() {
    seguimiento.activo = false;
    clearTimeout(seguimiento.temporizador);
    seguimiento.temporizador = null;
  }

  function seguirEntrenamiento(id) {
    detenerSeguimiento();
    seguimiento = { id, temporizador: null, activo: true };
    $("progreso-entrenamiento").hidden = false;
    $("boton-cancelar-entrenamiento").hidden = false;
    $("boton-cancelar-entrenamiento").disabled = false;
    $("progreso-titulo").textContent = "Entrenamiento #" + id;
    vaciar($("detalle-entrenamiento"));
    consultarEntrenamiento();
  }

  async function consultarEntrenamiento() {
    const id = seguimiento.id;
    if (!seguimiento.activo || id === null) return;
    try {
      const datos = await api("/api/admin/entrenamientos/" + encodeURIComponent(id));
      if (!seguimiento.activo || seguimiento.id !== id) return;
      pintarProgreso(datos);
      if (TERMINALES.includes(datos.estado)) {
        detenerSeguimiento();
        TC.mostrarMensaje($("entrenamiento-error"), "");
        dibujarDetalle(datos);
        cargarEntrenamientos();
        if (datos.estado === "terminado") TC.avisoFlotante("El entrenamiento terminó." + (datos.version ? " Nueva versión candidata: " + datos.version + "." : ""), "exito");
        else if (datos.estado === "cancelado") TC.avisoFlotante("El entrenamiento se canceló.", "info");
        else TC.avisoFlotante("El entrenamiento terminó con error.", "error");
        return;
      }
      if (Array.isArray(datos.historial) && datos.historial.length) dibujarDetalle(datos, true);
    } catch (e) {
      if (!seguimiento.activo) return;
      $("progreso-mensaje").textContent = "No se pudo consultar el avance: " + e.message + " Se intentará de nuevo.";
      if (e.estado === 401 || e.estado === 403 || e.estado === 404) { detenerSeguimiento(); return; }
    }
    if (seguimiento.activo && seguimiento.id === id) seguimiento.temporizador = setTimeout(consultarEntrenamiento, 2000);
  }

  function pintarProgreso(d) {
    const progreso = TC.esNumero(d.progreso) ? Math.max(0, Math.min(1, d.progreso)) : 0;
    const porcentaje = Math.round(progreso * 100);
    $("progreso-relleno").style.width = porcentaje + "%";
    $("progreso-barra").setAttribute("aria-valuenow", String(porcentaje));
    $("progreso-barra").setAttribute("aria-valuetext", porcentaje + " %");
    $("progreso-porcentaje").textContent = porcentaje + " %";
    $("progreso-etapa").textContent = d.etapa ? TC.nombreEtapa(d.etapa) : "—";
    $("progreso-epoca").textContent = TC.esNumero(d.epoca_actual) ? d.epoca_actual + " de " + (TC.esNumero(d.epocas_max) ? d.epocas_max : "—") + " máximas" : "—";
    $("progreso-mensaje").textContent = d.mensaje || "";
    vaciar($("progreso-estado")).appendChild(distintivoEstado(d.estado));
    const terminal = TERMINALES.includes(d.estado);
    $("boton-cancelar-entrenamiento").hidden = terminal;
    $("progreso-titulo").textContent = (terminal ? "Entrenamiento #" : "Entrenamiento en curso #") + d.entrenamiento_id;
  }

  function filasMetricas(metricas) {
    const NOMBRES = {
      sensibilidad: "Sensibilidad", especificidad: "Especificidad", precision: "Precisión", f1: "F1",
      auc: "AUC", exactitud: "Exactitud", umbral: "Umbral", perdida: "Pérdida", origen: "Datos usados",
      n: "Casos evaluados", vp: "Verdaderos positivos (VP)", vn: "Verdaderos negativos (VN)",
      fp: "Falsos positivos (FP)", fn: "Falsos negativos (FN)"
    };
    const VALORES = { validacion: "Validación", prueba: "Prueba", entrenamiento: "Entrenamiento" };
    const PORCENTAJE = ["sensibilidad", "especificidad", "precision", "exactitud"];
    const filas = [];
    const agregar = (clave, valor, prefijo) => {
      if (TC.esNumero(valor)) {
        const base = clave.split("_")[0];
        const nombre = (prefijo ? prefijo + " · " : "") + (NOMBRES[clave] || clave.replace(/_/g, " "));
        const texto = PORCENTAJE.includes(clave) || PORCENTAJE.includes(base) ? TC.pct(valor) : (Number.isInteger(valor) ? TC.num(valor) : valor.toFixed(3));
        filas.push([nombre, texto]);
      } else if (typeof valor === "string" || typeof valor === "boolean") {
        filas.push([(prefijo ? prefijo + " · " : "") + (NOMBRES[clave] || clave.replace(/_/g, " ")), VALORES[valor] || String(valor)]);
      }
    };
    if (metricas && typeof metricas === "object") {
      for (const [clave, valor] of Object.entries(metricas)) {
        if (valor && typeof valor === "object" && !Array.isArray(valor)) {
          for (const [sub, v] of Object.entries(valor)) agregar(sub, v, clave.replace(/_/g, " "));
        } else agregar(clave, valor, null);
      }
    }
    return filas;
  }

  function tablaPliegues(pliegues) {
    if (!Array.isArray(pliegues) || pliegues.length === 0) {
      return el("p", { clase: "vacio" }, "Este entrenamiento no usó validación cruzada K-fold, así que no hay métricas por pliegue.");
    }
    const promedio = (clave) => {
      const valores = pliegues.map((p) => p[clave]).filter(TC.esNumero);
      return valores.length ? valores.reduce((a, b) => a + b, 0) / valores.length : null;
    };
    const columnas = [
      { titulo: "Pliegue", celda: (p) => String(p.pliegue) },
      { titulo: "Sensibilidad", clase: "num", celda: (p) => TC.pct(p.sensibilidad) },
      { titulo: "Especificidad", clase: "num", celda: (p) => TC.pct(p.especificidad) },
      { titulo: "Precisión", clase: "num", celda: (p) => TC.pct(p.precision) },
      { titulo: "F1", clase: "num", celda: (p) => TC.decimal(p.f1, 3) },
      { titulo: "AUC", clase: "num", celda: (p) => TC.decimal(p.auc, 3) },
      { titulo: "VP", clase: "num", celda: (p) => TC.num(p.vp) },
      { titulo: "VN", clase: "num", celda: (p) => TC.num(p.vn) },
      { titulo: "FP", clase: "num", celda: (p) => TC.num(p.fp) },
      { titulo: "FN", clase: "num", celda: (p) => TC.num(p.fn) }
    ];
    const tablaNodo = TC.tabla(columnas, pliegues, { titulo: "Métricas por pliegue (validación cruzada estratificada)" });
    const fila = el("tr", null,
      el("th", { scope: "row" }, "Promedio"),
      el("td", { clase: "num" }, TC.pct(promedio("sensibilidad"))),
      el("td", { clase: "num" }, TC.pct(promedio("especificidad"))),
      el("td", { clase: "num" }, TC.pct(promedio("precision"))),
      el("td", { clase: "num" }, TC.decimal(promedio("f1"), 3)),
      el("td", { clase: "num" }, TC.decimal(promedio("auc"), 3)),
      el("td", { colspan: 4 }));
    fila.style.fontWeight = "700";
    tablaNodo.appendChild(el("tfoot", null, fila));
    return tablaNodo;
  }

  function dibujarDetalle(d, parcial) {
    const contenedor = vaciar($("detalle-entrenamiento"));
    const tarjeta = el("div", { clase: "tarjeta" });
    tarjeta.appendChild(el("div", { clase: "tarjeta__encabezado" },
      el("h3", null, parcial ? "Curvas de aprendizaje (en vivo)" : "Resultado del entrenamiento #" + d.entrenamiento_id),
      d.version ? TC.distintivo("Versión generada: " + d.version, "info", "modelo") : null));

    if (!parcial) {
      tarjeta.appendChild(el("div", { clase: "aviso aviso--info aviso--compacto", role: "note" }, icono("info"),
        el("p", null, "Las métricas del candidato son de validación (datos apartados del entrenamiento), no del conjunto de prueba. El candidato pasa a producción solo si usted lo aprueba.")));
    }

    tarjeta.appendChild(TC.curvasAprendizaje(d.historial, d.mejor_epoca));
    if (parcial) { contenedor.appendChild(tarjeta); return; }

    const etiqueta = textoDiagnostico(d.diagnostico);
    const explicacion = d.explicacion || (d.diagnostico && d.diagnostico.explicacion) || "";
    const advertencias = Array.isArray(d.advertencias) && d.advertencias.length ? d.advertencias : (d.diagnostico && Array.isArray(d.diagnostico.advertencias) ? d.diagnostico.advertencias : []);
    if (etiqueta) {
      const [variante, nombreIcono] = claseDiagnostico(etiqueta);
      tarjeta.appendChild(el("div", { clase: "diagnostico diagnostico--" + variante },
        icono(nombreIcono, "diagnostico__icono"),
        el("div", null,
          el("p", { clase: "diagnostico__titulo" }, "Diagnóstico de convergencia"),
          el("p", { clase: "diagnostico__valor" }, etiqueta.charAt(0).toUpperCase() + etiqueta.slice(1)),
          explicacion ? el("p", null, explicacion) : null,
          TC.esNumero(d.mejor_epoca) && d.mejor_epoca > 0 ? el("p", { clase: "texto-secundario" }, "Mejor época (mínimo de la pérdida de validación): " + d.mejor_epoca + ". Es un mínimo observado en esta corrida, no una garantía de mínimo global.") : null,
          advertencias.length ? el("div", null, el("strong", null, "Advertencias:"), el("ul", { clase: "advertencias" }, advertencias.map((a) => el("li", null, String(a))))) : null)));
    } else if (d.estado === "error") {
      tarjeta.appendChild(el("p", { clase: "mensaje-error" }, icono("error"), el("span", null, d.mensaje || "El entrenamiento terminó con error.")));
    }

    const filas = filasMetricas(d.metricas);
    tarjeta.appendChild(el("div", { clase: "bloque-resultados" },
      el("div", null,
        el("h4", null, "Métricas de validación del candidato"),
        filas.length ? TC.tabla([
          { titulo: "Métrica", celda: (f) => f[0] },
          { titulo: "Valor", clase: "num", celda: (f) => f[1] }
        ], filas) : el("p", { clase: "vacio" }, "Sin métricas registradas.")),
      el("div", null,
        el("h4", null, "Matriz de confusión (validación)"),
        TC.matrizConfusion(d.matriz_confusion))));

    tarjeta.appendChild(el("h4", { style: "margin-top:1.2rem" }, "Métricas por pliegue"));
    tarjeta.appendChild(el("div", { clase: "tabla-contenedor" }, tablaPliegues(d.metricas_pliegue)));

    const urlCurvas = TC.urlSegura(d.curvas_url);
    if (urlCurvas) {
      tarjeta.appendChild(el("details", { style: "margin-top:1rem" },
        el("summary", null, "Ver la figura de curvas generada por el servidor"),
        el("img", { src: urlCurvas, alt: "Curvas de aprendizaje generadas por el servidor", loading: "lazy", style: "margin-top:.6rem;border:1px solid #dfe6ee;border-radius:8px" })));
    }
    contenedor.appendChild(tarjeta);
  }

  async function verEntrenamiento(id) {
    try {
      const datos = await api("/api/admin/entrenamientos/" + encodeURIComponent(id));
      if (!TERMINALES.includes(datos.estado)) { seguirEntrenamiento(id); return; }
      detenerSeguimiento();
      seguimiento.id = id;
      $("progreso-entrenamiento").hidden = false;
      pintarProgreso(datos);
      dibujarDetalle(datos);
      $("progreso-entrenamiento").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      TC.avisoFlotante(e.message, "error");
    }
  }

  async function cargarEntrenamientos(seguirSiCorre) {
    const contenedor = $("lista-entrenamientos");
    try {
      const datos = await api("/api/admin/entrenamientos");
      const lista = (datos && datos.entrenamientos) || [];
      vaciar(contenedor).appendChild(TC.tabla([
        { titulo: "N.º", celda: (e) => "#" + e.entrenamiento_id },
        { titulo: "Estado", celda: (e) => distintivoEstado(e.estado) },
        { titulo: "Iniciado", celda: (e) => TC.fechaHora(e.iniciado_en) },
        { titulo: "Terminado", celda: (e) => (e.terminado_en ? TC.fechaHora(e.terminado_en) : null) },
        { titulo: "Versión", celda: (e) => e.version },
        { titulo: "Diagnóstico", celda: (e) => textoDiagnostico(e.diagnostico) },
        { titulo: "Acciones", celda: (e) => el("button", { type: "button", clase: "boton boton--secundario boton--chico", onclick: () => verEntrenamiento(e.entrenamiento_id) }, TERMINALES.includes(e.estado) ? "Ver resultados" : "Ver avance") }
      ], lista, { vacio: "Todavía no hay entrenamientos registrados." }));
      if (seguirSiCorre && !seguimiento.activo) {
        const enCurso = lista.find((e) => e.estado === "corriendo" || e.estado === "en_cola");
        if (enCurso) seguirEntrenamiento(enCurso.entrenamiento_id);
      }
      return lista;
    } catch (e) {
      mensajeErrorEn(contenedor, e.message);
      return [];
    }
  }

  async function iniciarEntrenamiento(evento) {
    evento.preventDefault();
    const error = $("entrenamiento-error");
    const epocas = Number($("ent-epocas").value);
    const tasa = Number($("ent-tasa").value);
    const lote = Number($("ent-lote").value);
    const errores = [];
    $("ent-epocas").removeAttribute("aria-invalid");
    $("ent-tasa").removeAttribute("aria-invalid");
    if (!Number.isInteger(epocas) || epocas < 1 || epocas > 100) { errores.push("Las épocas máximas deben ser un número entero entre 1 y 100."); $("ent-epocas").setAttribute("aria-invalid", "true"); }
    if (!Number.isFinite(tasa) || tasa <= 0 || tasa > 1) { errores.push("La tasa de aprendizaje debe ser mayor que 0 y como máximo 1."); $("ent-tasa").setAttribute("aria-invalid", "true"); }
    if (![16, 32, 64, 128].includes(lote)) errores.push("Elija un tamaño de lote válido.");
    TC.mostrarMensaje(error, errores.join(" "));
    if (errores.length) return;

    const restaurar = TC.botonCargando($("boton-entrenar"), "Iniciando…");
    try {
      const r = await api("/api/admin/entrenamientos", {
        metodo: "POST",
        cuerpo: { epocas_max: epocas, tasa, lote, kfold: $("ent-kfold").checked, ajuste_fino: $("ent-ajuste").checked }
      });
      TC.avisoFlotante("El entrenamiento #" + r.entrenamiento_id + " comenzó.", "exito");
      seguirEntrenamiento(r.entrenamiento_id);
      cargarEntrenamientos();
    } catch (e) {
      TC.mostrarMensaje(error, e.estado === 409 ? (e.message || "Ya hay un entrenamiento en curso.") + " Se muestra su avance abajo." : e.message);
      if (e.estado === 409) cargarEntrenamientos(true);
    } finally {
      restaurar();
    }
  }

  async function cancelarEntrenamiento() {
    if (seguimiento.id === null) return;
    const aceptar = await TC.abrirDialogo({
      titulo: "Cancelar el entrenamiento",
      cuerpo: "Se detendrá el entrenamiento #" + seguimiento.id + ". No se creará una versión candidata con este entrenamiento. ¿Desea cancelarlo?",
      textoAceptar: "Sí, cancelar", textoCancelar: "No, continuar", peligro: true
    });
    if (!aceptar) return;
    const boton = $("boton-cancelar-entrenamiento");
    boton.disabled = true;
    try {
      await api("/api/admin/entrenamientos/" + encodeURIComponent(seguimiento.id) + "/cancelar", { metodo: "POST" });
      $("progreso-mensaje").textContent = "Cancelación solicitada. Esperando a que termine la época en curso…";
      if (!seguimiento.activo) seguirEntrenamiento(seguimiento.id);
    } catch (e) {
      boton.disabled = false;
      TC.avisoFlotante(e.message, "error");
    }
  }

  function cargarReentrenar() {
    cargarEntrenamientos(true);
  }

  /* ======================= Versiones del modelo ===================== */
  const ESTADOS_MODELO = {
    produccion: ["En producción", "produccion", "check"],
    candidato: ["Candidato", "candidato", "reloj"],
    referencia: ["Referencia", "referencia", "info"],
    retirado: ["Retirado", "retirado", "cruz"]
  };
  const TIPOS_MODELO = { clasico: "Clásico", red_keras: "Red Keras" };
  let modelos = [];

  async function cargarModelos() {
    const contenedor = $("tabla-modelos");
    vaciar(contenedor).appendChild(el("p", { clase: "vacio" }, "Cargando versiones…"));
    try {
      const datos = await api("/api/admin/modelos");
      modelos = (datos && datos.modelos) || [];
      vaciar(contenedor).appendChild(TC.tabla([
        { titulo: "Versión", celda: (m) => el("strong", null, m.version || "—") },
        { titulo: "Nombre", celda: (m) => m.nombre },
        { titulo: "Tipo", celda: (m) => TIPOS_MODELO[m.tipo] || m.tipo },
        { titulo: "Estado", celda: (m) => { const [t, c, i] = ESTADOS_MODELO[m.estado] || [String(m.estado), "neutro", "info"]; return TC.distintivo(t, c, i); } },
        { titulo: "Umbral", clase: "num", celda: (m) => TC.decimal(m.umbral, 2) },
        { titulo: "Sensibilidad", clase: "num", celda: (m) => TC.pct(m.sensibilidad) },
        { titulo: "Especificidad", clase: "num", celda: (m) => TC.pct(m.especificidad) },
        { titulo: "F1", clase: "num", celda: (m) => TC.decimal(m.f1, 3) },
        { titulo: "AUC", clase: "num", celda: (m) => TC.decimal(m.auc, 3) },
        { titulo: "Fecha", celda: (m) => TC.fechaHora(m.creado_en) },
        { titulo: "Acciones", celda: (m) => (m.estado === "candidato"
          ? el("button", { type: "button", clase: "boton boton--exito boton--chico", onclick: () => aprobarModelo(m) }, icono("check"), "Aprobar para producción")
          : null) }
      ], modelos, { vacio: "No hay versiones del modelo registradas." }));
    } catch (e) {
      mensajeErrorEn(contenedor, e.message);
    }
  }

  async function aprobarModelo(modelo) {
    const actual = modelos.find((m) => m.estado === "produccion");
    const cuerpo = el("div", null,
      el("p", null, "La versión ", el("strong", null, modelo.version || ""), " atenderá los nuevos estudios a partir de ahora.",
        actual ? " La versión en producción actual (" + (actual.version || "") + ") pasará a «Retirado»." : ""),
      el("ul", null,
        el("li", null, "Sensibilidad de validación: " + TC.pct(modelo.sensibilidad)),
        el("li", null, "Especificidad de validación: " + TC.pct(modelo.especificidad)),
        el("li", null, "Umbral: " + TC.decimal(modelo.umbral, 2))),
      el("p", { clase: "texto-secundario" }, "Podrá regresar a la versión anterior si es necesario."));
    const aceptar = await TC.abrirDialogo({ titulo: "Aprobar para producción", cuerpo, textoAceptar: "Aprobar para producción" });
    if (!aceptar) return;
    try {
      await api("/api/admin/modelos/" + encodeURIComponent(modelo.modelo_id) + "/aprobar", { metodo: "POST" });
      TC.avisoFlotante("La versión " + (modelo.version || "") + " quedó en producción.", "exito");
      await cargarModelos();
      TC.refrescarEstado();
    } catch (e) {
      TC.avisoFlotante(e.message, "error");
    }
  }

  async function revertirModelo() {
    const aceptar = await TC.abrirDialogo({
      titulo: "Regresar a la versión anterior",
      cuerpo: "La versión en producción actual se retirará y volverá a producción la versión que estaba antes. Los estudios nuevos usarán esa versión. ¿Desea continuar?",
      textoAceptar: "Regresar a la versión anterior", peligro: true
    });
    if (!aceptar) return;
    try {
      const r = await api("/api/admin/modelos/revertir", { metodo: "POST" });
      TC.avisoFlotante("Se regresó a la versión anterior" + (r && r.version ? " (" + r.version + ")" : "") + ".", "exito");
      await cargarModelos();
      TC.refrescarEstado();
    } catch (e) {
      TC.avisoFlotante(e.message, "error");
    }
  }

  /* ============================== Umbral ============================ */
  let umbral = { actual: null, base: null, propuesto: null, secuencia: 0 };

  /* El umbral guardado puede tener más de dos decimales (p. ej. 0.5205); se muestra completo. */
  const textoUmbral = (v) => (TC.esNumero(v) ? String(Number(v.toFixed(4))) : "—");

  async function consultarUmbral(valor, exacto) {
    return api("/api/admin/umbral" + TC.consulta({ valor: exacto ? String(Number(valor)) : Number(valor).toFixed(2) }));
  }

  async function cargarUmbral() {
    TC.mostrarMensaje($("umbral-error"), "");
    vaciar($("umbral-comparacion")).appendChild(el("p", { clase: "vacio" }, "Calculando…"));
    $("umbral-frase").textContent = "";
    try {
      const estado = await TC.refrescarEstado();
      const inicial = estado && estado.modelo && TC.esNumero(estado.modelo.umbral) ? estado.modelo.umbral : Number($("umbral-rango").value);
      let base = await consultarUmbral(inicial, true);
      const actual = TC.esNumero(base.actual) ? base.actual : inicial;
      if (Math.abs(actual - Number(base.valor)) > 0.00001) base = await consultarUmbral(actual, true);
      umbral.actual = actual;
      umbral.base = base;
      umbral.propuesto = base;
      $("umbral-actual").textContent = textoUmbral(actual);
      $("umbral-rango").value = actual.toFixed(2);
      $("umbral-valor").textContent = actual.toFixed(2);
      pintarUmbral();
    } catch (e) {
      vaciar($("umbral-comparacion"));
      TC.mostrarMensaje($("umbral-error"), e.message);
    }
  }

  const recalcularUmbral = TC.retrasar(async (valor) => {
    const secuencia = ++umbral.secuencia;
    try {
      const r = await consultarUmbral(valor);
      if (secuencia !== umbral.secuencia) return;
      umbral.propuesto = r;
      TC.mostrarMensaje($("umbral-error"), "");
      pintarUmbral();
    } catch (e) {
      if (secuencia !== umbral.secuencia) return;
      TC.mostrarMensaje($("umbral-error"), e.message);
    }
  }, 250);

  function cambio(actual, propuesto, menosEsMejor, esPorcentaje) {
    if (!TC.esNumero(actual) || !TC.esNumero(propuesto)) return "—";
    const diferencia = propuesto - actual;
    if (Math.abs(diferencia) < 1e-9) return el("span", null, "Sin cambio");
    const mejora = menosEsMejor ? diferencia < 0 : diferencia > 0;
    const magnitud = esPorcentaje
      ? (Math.abs(diferencia) * 100).toFixed(1) + " puntos"
      : Math.abs(diferencia) + (Math.abs(diferencia) === 1 ? " caso" : " casos");
    return el("span", { clase: mejora ? "diferencia--mejor" : "diferencia--peor" },
      icono(mejora ? "check" : "alerta"), " " + (diferencia > 0 ? "+" : "−") + magnitud + (mejora ? " (mejora)" : " (empeora)"));
  }

  function pintarUmbral() {
    const a = umbral.base, p = umbral.propuesto;
    if (!a || !p) return;
    const valorP = TC.esNumero(Number(p.valor)) ? Number(p.valor) : Number($("umbral-rango").value);
    const filas = [
      ["Falsos negativos (tumores no detectados)", TC.num(a.fn), TC.num(p.fn), cambio(a.fn, p.fn, true, false)],
      ["Falsos positivos (falsas alarmas)", TC.num(a.fp), TC.num(p.fp), cambio(a.fp, p.fp, true, false)],
      ["Sensibilidad", TC.pct(a.sensibilidad), TC.pct(p.sensibilidad), cambio(a.sensibilidad, p.sensibilidad, false, true)],
      ["Especificidad", TC.pct(a.especificidad), TC.pct(p.especificidad), cambio(a.especificidad, p.especificidad, false, true)]
    ];
    vaciar($("umbral-comparacion")).appendChild(el("div", { clase: "tabla-contenedor" }, TC.tabla([
      { titulo: "Indicador", celda: (f) => f[0] },
      { titulo: "Umbral actual (" + textoUmbral(umbral.actual) + ")", celda: (f) => f[1] },
      { titulo: "Umbral propuesto (" + textoUmbral(valorP) + ")", celda: (f) => el("strong", null, f[2]) },
      { titulo: "Cambio", celda: (f) => f[3] }
    ], filas)));

    const conTumor = (Number(p.vp) || 0) + (Number(p.fn) || 0);
    const sinTumor = (Number(p.vn) || 0) + (Number(p.fp) || 0);
    let frase = "Con este umbral, de " + TC.num(conTumor) + " casos con tumor, " + TC.num(p.fn) + (p.fn === 1 ? " se habría pasado por alto" : " se habrían pasado por alto") +
      "; y de " + TC.num(sinTumor) + " casos sin tumor, " + TC.num(p.fp) + (p.fp === 1 ? " habría recibido una falsa alarma." : " habrían recibido una falsa alarma.");
    if (TC.esNumero(p.sensibilidad) && p.sensibilidad < 0.98) frase += " La sensibilidad queda por debajo del objetivo de 98 %.";
    $("umbral-frase").textContent = frase;
    $("umbral-origen").textContent = "Cálculo sobre " + TC.num(p.n) + " imágenes" + (p.origen ? " de " + p.origen : "") + " del modelo en producción. No incluye el conjunto de prueba.";
    $("boton-guardar-umbral").disabled = Math.abs(valorP - umbral.actual) < 0.005;
  }

  async function guardarUmbral() {
    const valor = Number(Number($("umbral-rango").value).toFixed(2));
    if (!(valor >= 0.01 && valor <= 0.99)) { TC.mostrarMensaje($("umbral-error"), "El umbral debe estar entre 0.01 y 0.99."); return; }
    const restaurar = TC.botonCargando($("boton-guardar-umbral"), "Guardando…");
    try {
      await api("/api/admin/umbral", { metodo: "PUT", cuerpo: { valor } });
      TC.avisoFlotante("El umbral quedó guardado en " + valor.toFixed(2) + ".", "exito");
      umbral.actual = valor;
      umbral.base = umbral.propuesto;
      $("umbral-actual").textContent = valor.toFixed(2);
      TC.refrescarEstado();
    } catch (e) {
      TC.mostrarMensaje($("umbral-error"), e.message);
    } finally {
      restaurar();
      pintarUmbral();
    }
  }

  /* ============================= Usuarios =========================== */
  async function cargarUsuarios() {
    const contenedor = $("tabla-usuarios");
    try {
      const datos = await api("/api/admin/usuarios");
      const lista = Array.isArray(datos) ? datos : (datos && datos.usuarios) || [];
      const yo = TC.estado.usuario;
      const tablaNodo = TC.tabla([
        { titulo: "Usuario", celda: (u) => el("strong", null, u.usuario || "—") },
        { titulo: "Rol", celda: (u) => TC.nombreRol(u.rol) },
        { titulo: "Estado", celda: (u) => (u.activo ? TC.distintivo("Activo", "ok", "check") : TC.distintivo("Inactivo", "neutro", "cruz")) },
        { titulo: "Creado", celda: (u) => TC.fechaHora(u.creado_en) },
        { titulo: "Acciones", celda: (u) => el("div", { clase: "celda-acciones" },
          el("button", {
            type: "button", clase: "boton boton--chico " + (u.activo ? "boton--peligro" : "boton--secundario"),
            disabled: yo && yo.usuario_id === u.usuario_id ? true : null,
            title: yo && yo.usuario_id === u.usuario_id ? "No puede desactivar su propia cuenta" : null,
            onclick: () => cambiarActivo(u)
          }, u.activo ? "Desactivar" : "Activar"),
          el("button", { type: "button", clase: "boton boton--secundario boton--chico", onclick: (e) => mostrarCambioPassword(u, e.currentTarget) }, "Cambiar contraseña")) }
      ], lista, { vacio: "No hay usuarios registrados." });
      vaciar(contenedor).appendChild(tablaNodo);
    } catch (e) {
      mensajeErrorEn(contenedor, e.message);
    }
  }

  async function cambiarActivo(u) {
    if (u.activo) {
      const aceptar = await TC.abrirDialogo({
        titulo: "Desactivar usuario",
        cuerpo: "El usuario «" + u.usuario + "» ya no podrá iniciar sesión hasta que lo active de nuevo. ¿Desea continuar?",
        textoAceptar: "Desactivar", peligro: true
      });
      if (!aceptar) return;
    }
    try {
      await api("/api/admin/usuarios/" + encodeURIComponent(u.usuario_id), { metodo: "PUT", cuerpo: { activo: !u.activo } });
      TC.avisoFlotante("El usuario «" + u.usuario + "» quedó " + (u.activo ? "inactivo" : "activo") + ".", "exito");
      cargarUsuarios();
    } catch (e) {
      TC.avisoFlotante(e.message, "error");
    }
  }

  function mostrarCambioPassword(u, boton) {
    const filaUsuario = boton.closest("tr");
    const siguiente = filaUsuario.nextElementSibling;
    if (siguiente && siguiente.classList.contains("fila-edicion")) { siguiente.remove(); return; }
    document.querySelectorAll("#tabla-usuarios .fila-edicion").forEach((f) => f.remove());
    const idCampo = "pw-" + String(u.usuario_id).replace(/[^A-Za-z0-9_-]/g, "");
    const campo = el("input", { id: idCampo, type: "password", required: true, maxlength: 128, autocomplete: "new-password" });
    const error = el("p", { clase: "mensaje-error", role: "alert", hidden: true });
    const formulario = el("form", { novalidate: true },
      el("div", { clase: "campo" }, el("label", { for: idCampo }, "Nueva contraseña para «" + u.usuario + "»"), campo),
      el("button", { type: "submit", clase: "boton boton--primario" }, "Guardar contraseña"),
      el("button", { type: "button", clase: "boton boton--texto", onclick: () => { fila.remove(); boton.focus(); } }, "Cancelar"));
    const fila = el("tr", { clase: "fila-edicion" }, el("td", { colspan: 5 }, formulario, error));
    formulario.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (campo.value.length < 8) { TC.mostrarMensaje(error, "La contraseña debe tener al menos 8 caracteres."); campo.focus(); return; }
      try {
        await api("/api/admin/usuarios/" + encodeURIComponent(u.usuario_id), { metodo: "PUT", cuerpo: { password: campo.value } });
        fila.remove();
        TC.avisoFlotante("Se cambió la contraseña de «" + u.usuario + "».", "exito");
        boton.focus();
      } catch (err) {
        TC.mostrarMensaje(error, err.message);
      }
    });
    filaUsuario.after(fila);
    campo.focus();
  }

  async function crearUsuario(evento) {
    evento.preventDefault();
    const error = $("usuario-error");
    const usuario = $("nu-usuario").value.trim().toLowerCase();
    const password = $("nu-password").value;
    const rol = $("nu-rol").value;
    const errores = [];
    $("nu-usuario").removeAttribute("aria-invalid");
    $("nu-password").removeAttribute("aria-invalid");
    if (!/^[a-z0-9_.]{3,30}$/.test(usuario)) { errores.push("El usuario debe tener de 3 a 30 caracteres: letras minúsculas sin acentos, números, punto o guion bajo.");$("nu-usuario").setAttribute("aria-invalid", "true"); }
    if (password.length < 8) { errores.push("La contraseña debe tener al menos 8 caracteres."); $("nu-password").setAttribute("aria-invalid", "true"); }
    TC.mostrarMensaje(error, errores.join(" "));
    if (errores.length) return;
    try {
      await api("/api/admin/usuarios", { metodo: "POST", cuerpo: { usuario, password, rol } });
      TC.avisoFlotante("Se creó el usuario «" + usuario + "» con rol " + TC.nombreRol(rol) + ".", "exito");
      $("formulario-usuario").reset();
      cargarUsuarios();
    } catch (e) {
      TC.mostrarMensaje(error, e.message);
    }
  }

  /* ============================= Bitácora =========================== */
  const ACCIONES_CONTRATO = ["LOGIN_OK", "LOGIN_FALLIDO", "LOGOUT", "ACCESO_DENEGADO", "ESTUDIO_CREADO", "ESTUDIO_CONFIRMADO",
    "ENTRENAMIENTO_INICIADO", "ENTRENAMIENTO_TERMINADO", "ENTRENAMIENTO_CANCELADO", "ENTRENAMIENTO_ERROR", "MODELO_APROBADO",
    "MODELO_REVERTIDO", "UMBRAL_ACTUALIZADO", "USUARIO_CREADO", "USUARIO_ACTUALIZADO", "CONSULTA_IA", "CONSULTA_IA_BLOQUEADA", "CARGA_DATOS"];
  let bitacora = { pagina: 1, paginas: 1, accionesCargadas: false };

  function llenarAcciones(acciones) {
    const selector = $("fb-accion");
    const elegido = selector.value;
    const lista = Array.isArray(acciones) && acciones.length ? acciones : ACCIONES_CONTRATO;
    while (selector.options.length > 1) selector.remove(1);
    lista.forEach((a) => selector.appendChild(el("option", { value: String(a) }, String(a))));
    if (lista.includes(elegido)) selector.value = elegido;
    bitacora.accionesCargadas = true;
  }

  function textoDetalle(detalle) {
    if (detalle === null || detalle === undefined || detalle === "") return null;
    if (typeof detalle === "object") { try { return JSON.stringify(detalle); } catch (e) { return String(detalle); } }
    return String(detalle);
  }

  async function cargarBitacora(pagina) {
    if (pagina) bitacora.pagina = pagina;
    const contenedor = $("tabla-bitacora");
    if (!bitacora.accionesCargadas) llenarAcciones(null);
    const parametros = {
      usuario: $("fb-usuario").value.trim(), accion: $("fb-accion").value, exito: $("fb-exito").value,
      desde: $("fb-desde").value, hasta: $("fb-hasta").value, pagina: bitacora.pagina
    };
    try {
      const d = await api("/api/admin/bitacora" + TC.consulta(parametros));
      if (Array.isArray(d.acciones) && d.acciones.length) llenarAcciones(d.acciones);
      bitacora.pagina = TC.esNumero(d.pagina) ? d.pagina : bitacora.pagina;
      bitacora.paginas = TC.esNumero(d.paginas) ? Math.max(1, d.paginas) : 1;
      $("bitacora-total").textContent = TC.num(d.total) + (d.total === 1 ? " evento" : " eventos");
      $("bitacora-pagina").textContent = "Página " + bitacora.pagina + " de " + bitacora.paginas;
      $("bitacora-anterior").disabled = bitacora.pagina <= 1;
      $("bitacora-siguiente").disabled = bitacora.pagina >= bitacora.paginas;
      vaciar(contenedor).appendChild(TC.tabla([
        { titulo: "Fecha y hora", celda: (e) => TC.fechaHora(e.fecha_hora) },
        { titulo: "Usuario", celda: (e) => e.usuario },
        { titulo: "Rol", celda: (e) => (e.rol ? TC.nombreRol(e.rol) : null) },
        { titulo: "Acción", celda: (e) => el("code", null, String(e.accion || "—")) },
        { titulo: "Detalle", clase: "detalle-largo", celda: (e) => textoDetalle(e.detalle) },
        { titulo: "IP", celda: (e) => e.ip },
        { titulo: "Resultado", celda: (e) => (e.exito === false || e.exito === 0 ? TC.distintivo("Sin éxito", "error", "error") : TC.distintivo("Con éxito", "ok", "check")) }
      ], d.eventos || [], { vacio: "No hay eventos que coincidan con los filtros." }));
    } catch (e) {
      mensajeErrorEn(contenedor, e.message);
    }
  }

  /* ============================= Power BI =========================== */
  async function cargarPowerBI() {
    const contenedor = $("powerbi-contenedor");
    vaciar(contenedor).appendChild(el("p", { clase: "vacio" }, "Cargando…"));
    const estado = await TC.refrescarEstado();
    vaciar(contenedor);
    const url = estado && typeof estado.powerbi_url === "string" ? estado.powerbi_url.trim() : "";
    let valida = null;
    try { valida = url ? new URL(url) : null; } catch (e) { valida = null; }
    if (valida && valida.protocol === "https:") {
      contenedor.appendChild(el("p", { clase: "texto-secundario" }, "El tablero se carga desde el servicio de Power BI; requiere conexión a internet y una cuenta con acceso al informe."));
      contenedor.appendChild(el("iframe", { clase: "marco-powerbi", src: valida.href, title: "Tablero de Power BI del sistema", loading: "lazy", allowfullscreen: true, referrerpolicy: "no-referrer" }));
      contenedor.appendChild(el("p", { style: "margin-top:.6rem" }, el("a", { href: valida.href, target: "_blank", rel: "noopener noreferrer" }, "Abrir el tablero en una pestaña nueva")));
      return;
    }
    contenedor.appendChild(el("div", { clase: "aviso aviso--info", role: "note" }, icono("info"),
      el("p", null, url ? "La dirección configurada en POWERBI_URL no es válida; debe comenzar con https://." : "Todavía no hay un tablero de Power BI configurado.")));
    contenedor.appendChild(el("h3", { style: "margin-top:1rem" }, "Cómo configurarlo"));
    contenedor.appendChild(el("ol", { clase: "pasos" },
      el("li", null, "Construya el informe en Power BI Desktop siguiendo ", el("code", null, "tablero/GUIA_POWER_BI.md"), " y publíquelo en el servicio de Power BI."),
      el("li", null, "En el servicio de Power BI, abra el informe y elija ", el("strong", null, "Archivo › Insertar informe › Sitio web o portal"), ". Copie el vínculo que empieza con ", el("code", null, "https://app.powerbi.com/"), "."),
      el("li", null, "En el archivo ", el("code", null, ".env"), " de la carpeta del proyecto agregue la línea ", el("code", null, "POWERBI_URL=https://app.powerbi.com/…"), " con el vínculo copiado."),
      el("li", null, "Reinicie el servidor y vuelva a abrir esta sección.")));
  }

  /* ============================ Asistente =========================== */
  function valorCelda(v) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "object") { try { return JSON.stringify(v); } catch (e) { return String(v); } }
    return String(v);
  }

  function tablaResultadosSQL(columnas, filas) {
    const cols = Array.isArray(columnas) ? columnas.map(String) : [];
    const lista = Array.isArray(filas) ? filas : [];
    if (cols.length === 0 && lista.length && lista[0] && typeof lista[0] === "object" && !Array.isArray(lista[0])) cols.push(...Object.keys(lista[0]));
    return TC.tabla(cols.map((c, i) => ({
      titulo: c,
      celda: (f) => valorCelda(Array.isArray(f) ? f[i] : f && typeof f === "object" ? f[c] : f)
    })), lista, { vacio: "La consulta no devolvió filas." });
  }

  async function preguntar(evento) {
    if (evento) evento.preventDefault();
    const campo = $("asistente-pregunta");
    const pregunta = campo.value.trim();
    const salida = $("asistente-respuesta");
    if (!pregunta) { campo.setAttribute("aria-invalid", "true"); campo.focus(); mensajeErrorEn(salida, "Escriba una pregunta."); return; }
    campo.removeAttribute("aria-invalid");
    const restaurar = TC.botonCargando($("boton-preguntar"), "Consultando…");
    vaciar(salida).appendChild(el("p", { clase: "vacio" }, "El asistente está preparando la consulta…"));
    try {
      const r = (await api("/api/admin/asistente", { metodo: "POST", cuerpo: { pregunta } })) || {};
      dibujarRespuesta(r, pregunta);
    } catch (e) {
      mensajeErrorEn(salida, e.message);
    } finally {
      restaurar();
    }
  }

  function dibujarRespuesta(r, pregunta) {
    const salida = vaciar($("asistente-respuesta"));
    const tarjeta = el("div", { clase: "tarjeta" });
    tarjeta.appendChild(el("div", { clase: "tarjeta__encabezado" }, el("h3", null, "Respuesta"),
      r.estado === "ok" ? TC.distintivo("Consulta de lectura ejecutada", "ok", "check")
        : r.estado === "bloqueada" ? TC.distintivo("Consulta bloqueada", "advertencia", "alerta")
          : r.estado === "sin_configurar" ? TC.distintivo("Sin configurar", "neutro", "info")
            : TC.distintivo("Error", "error", "error")));
    tarjeta.appendChild(el("p", { clase: "texto-secundario" }, "Pregunta: " + pregunta));

    if (r.estado === "bloqueada") {
      tarjeta.appendChild(el("div", { clase: "aviso aviso--advertencia", role: "alert" }, icono("alerta"),
        el("p", null, el("strong", null, "Solo se permiten consultas de lectura."), r.respuesta ? " " + r.respuesta : " La solicitud se rechazó y quedó registrada en la bitácora.")));
    } else if (r.estado === "sin_configurar") {
      tarjeta.appendChild(el("div", { clase: "aviso aviso--advertencia", role: "alert" }, icono("info"),
        el("p", null, el("strong", null, "Configure ANTHROPIC_API_KEY en .env"), " y reinicie el servidor para usar el asistente.")));
    } else if (r.estado === "error") {
      tarjeta.appendChild(el("p", { clase: "mensaje-error", role: "alert" }, icono("error"), el("span", null, r.respuesta || "No se pudo responder la pregunta.")));
    } else if (r.respuesta) {
      tarjeta.appendChild(el("p", { clase: "respuesta-texto" }, r.respuesta));
    }

    if (r.sql) {
      tarjeta.appendChild(el("h4", null, "Consulta SQL usada"));
      tarjeta.appendChild(el("pre", { clase: "bloque-codigo" }, el("code", null, String(r.sql))));
    }
    if (r.estado === "ok") {
      const n = Array.isArray(r.filas) ? r.filas.length : 0;
      tarjeta.appendChild(el("h4", { style: "margin-top:1rem" }, "Resultados (" + n + (n === 1 ? " fila)" : " filas)")));
      tarjeta.appendChild(el("div", { clase: "tabla-contenedor" }, tablaResultadosSQL(r.columnas, r.filas)));
    }
    salida.appendChild(tarjeta);
  }

  async function cargarAsistente() {
    const estado = await TC.refrescarEstado();
    $("asistente-sin-configurar").hidden = !(estado && estado.asistente_configurado === false);
  }

  /* ============================== Inicio ============================ */
  Object.assign(CARGADORES, {
    resumen: cargarResumen, reentrenar: cargarReentrenar, modelos: cargarModelos, umbral: cargarUmbral,
    usuarios: cargarUsuarios, bitacora: () => cargarBitacora(1), powerbi: cargarPowerBI, asistente: cargarAsistente
  });

  function enlazar() {
    document.querySelectorAll("#menu-admin button").forEach((b) => b.addEventListener("click", () => mostrarSeccion(b.dataset.seccion, true)));
    $("boton-actualizar-resumen").addEventListener("click", cargarResumen);

    $("formulario-entrenamiento").addEventListener("submit", iniciarEntrenamiento);
    $("boton-cancelar-entrenamiento").addEventListener("click", cancelarEntrenamiento);
    $("boton-actualizar-entrenamientos").addEventListener("click", () => cargarEntrenamientos());

    $("boton-revertir").addEventListener("click", revertirModelo);

    $("umbral-rango").addEventListener("input", (e) => {
      const valor = Number(e.target.value);
      $("umbral-valor").textContent = valor.toFixed(2);
      $("boton-guardar-umbral").disabled = umbral.actual !== null && Math.abs(valor - umbral.actual) < 0.005;
      recalcularUmbral(valor);
    });
    $("boton-guardar-umbral").addEventListener("click", guardarUmbral);

    $("formulario-usuario").addEventListener("submit", crearUsuario);

    $("filtros-bitacora").addEventListener("submit", (e) => { e.preventDefault(); cargarBitacora(1); });
    $("filtros-bitacora").addEventListener("reset", () => setTimeout(() => cargarBitacora(1), 0));
    $("bitacora-anterior").addEventListener("click", () => cargarBitacora(Math.max(1, bitacora.pagina - 1)));
    $("bitacora-siguiente").addEventListener("click", () => cargarBitacora(Math.min(bitacora.paginas, bitacora.pagina + 1)));

    $("formulario-asistente").addEventListener("submit", preguntar);
    document.querySelectorAll("[data-ejemplo]").forEach((b) => b.addEventListener("click", () => {
      $("asistente-pregunta").value = b.textContent.trim();
      preguntar();
    }));
  }

  function iniciar() {
    if (!iniciado) { enlazar(); iniciado = true; }
    mostrarSeccion(seccionActual || "resumen");
  }

  function reiniciar() {
    detenerSeguimiento();
    seguimiento = { id: null, temporizador: null, activo: false };
    seccionActual = null;
    if (!iniciado) return;
    $("progreso-entrenamiento").hidden = true;
    vaciar($("detalle-entrenamiento"));
    vaciar($("asistente-respuesta"));
    umbral = { actual: null, base: null, propuesto: null, secuencia: 0 };
  }

  TC.admin = { iniciar, reiniciar, mostrarSeccion };
})(window.TC);
