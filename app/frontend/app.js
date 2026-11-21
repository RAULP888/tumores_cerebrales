/* Arranque de la aplicación: pantallas, inicio de sesión, cabecera y sesión.
   Depende de js/util.js, js/graficas.js, js/doctor.js y js/admin.js. */
"use strict";

(function (TC) {
  const $ = (id) => document.getElementById(id);
  const PANTALLAS = ["bienvenida", "acceso", "doctor", "admin"];
  let rolElegido = null;

  /* ---------------- Pantallas ---------------- */
  function mostrarPantalla(nombre) {
    PANTALLAS.forEach((p) => { $("pantalla-" + p).hidden = p !== nombre; });
    const conSesion = nombre === "doctor" || nombre === "admin";
    $("cabecera").hidden = !conSesion;
    const titulos = {
      bienvenida: "Bienvenida",
      acceso: "Iniciar sesión",
      doctor: "Panel del Doctor",
      admin: "Panel del Administrador"
    };
    document.title = titulos[nombre] + " · Sistema de Apoyo para Detección de Tumores Cerebrales";
    window.scrollTo(0, 0);
  }

  /* ---------------- Estado del servidor y cabecera ---------------- */
  async function refrescarEstado() {
    try {
      const estado = await TC.api("/api/estado", { sin401: true });
      TC.estado.servidor = estado;
      pintarModelo(estado);
      return estado;
    } catch (e) {
      $("cab-modelo").textContent = "Sin conexión";
      return TC.estado.servidor;
    }
  }

  function pintarModelo(estado) {
    const modelo = estado && estado.modelo;
    let texto = "Sin modelo cargado";
    if (modelo && modelo.cargado !== false && (modelo.version || modelo.nombre)) {
      texto = [modelo.version, modelo.nombre].filter(Boolean).join(" · ");
    }
    $("cab-modelo").textContent = texto;
  }

  function pintarUsuario(usuario) {
    $("cab-usuario").textContent = usuario.usuario || "—";
    $("cab-rol").textContent = TC.nombreRol(usuario.rol);
  }

  /* ---------------- Sesión ---------------- */
  function entrarAlPanel(usuario) {
    TC.estado.usuario = usuario;
    pintarUsuario(usuario);
    refrescarEstado();
    if (usuario.rol === "administrador") {
      mostrarPantalla("admin");
      TC.admin.iniciar();
    } else {
      mostrarPantalla("doctor");
      TC.doctor.iniciar();
    }
    $("contenido").focus();
  }

  function limpiarSesion() {
    TC.estado.usuario = null;
    TC.cerrarDialogo();
    TC.admin.reiniciar();
    TC.doctor.reiniciar();
  }

  function irAlAcceso(mensaje) {
    limpiarSesion();
    elegirRol(null);
    const aviso = $("aviso-sesion");
    aviso.textContent = mensaje || "";
    aviso.hidden = !mensaje;
    mostrarPantalla("acceso");
  }

  let avisandoExpiracion = false;
  TC.alSesionExpirada = function () {
    if (avisandoExpiracion || !TC.estado.usuario) return;
    avisandoExpiracion = true;
    irAlAcceso("Su sesión terminó o no es válida. Inicie sesión de nuevo.");
    setTimeout(() => { avisandoExpiracion = false; }, 500);
  };

  async function cerrarSesion() {
    const boton = $("boton-salir");
    boton.disabled = true;
    try {
      await TC.api("/api/logout", { metodo: "POST", sin401: true });
    } catch (e) {
      /* Aunque falle la llamada, se regresa al inicio de sesión. */
    } finally {
      boton.disabled = false;
    }
    irAlAcceso("Cerró su sesión correctamente.");
  }

  /* ---------------- Elegir rol e iniciar sesión ---------------- */
  function elegirRol(rol) {
    rolElegido = rol;
    document.querySelectorAll(".rol").forEach((b) => b.setAttribute("aria-pressed", b.dataset.rol === rol ? "true" : "false"));
    const formulario = $("formulario-acceso");
    formulario.hidden = !rol;
    TC.mostrarMensaje($("acceso-error"), "");
    $("acceso-password").value = "";
    if (rol) {
      $("titulo-formulario-acceso").textContent = "Iniciar sesión como " + TC.nombreRol(rol);
      $("acceso-usuario").focus();
    }
  }

  async function iniciarSesion(evento) {
    evento.preventDefault();
    const usuario = $("acceso-usuario").value.trim();
    const password = $("acceso-password").value;
    const errorNodo = $("acceso-error");
    $("acceso-usuario").removeAttribute("aria-invalid");
    $("acceso-password").removeAttribute("aria-invalid");
    if (!rolElegido) { TC.mostrarMensaje(errorNodo, "Elija primero si entra como Doctor o como Administrador."); return; }
    if (!usuario || !password) {
      if (!usuario) $("acceso-usuario").setAttribute("aria-invalid", "true");
      if (!password) $("acceso-password").setAttribute("aria-invalid", "true");
      TC.mostrarMensaje(errorNodo, "Escriba su usuario y su contraseña.");
      (usuario ? $("acceso-password") : $("acceso-usuario")).focus();
      return;
    }
    const restaurar = TC.botonCargando($("boton-entrar"), "Verificando…");
    try {
      const datos = await TC.api("/api/login", { metodo: "POST", cuerpo: { usuario, password, rol: rolElegido }, sin401: true });
      TC.mostrarMensaje(errorNodo, "");
      $("acceso-password").value = "";
      $("aviso-sesion").hidden = true;
      entrarAlPanel(datos);
    } catch (e) {
      let mensaje = e.message;
      const detalle = e.datos && typeof e.datos.detail === "string" ? e.datos.detail : "";
      if (e.estado === 401) mensaje = detalle || "Usuario o contraseña incorrectos. Revise sus datos e intente de nuevo.";
      if (e.estado === 403) mensaje = detalle || "Su usuario no tiene el rol " + TC.nombreRol(rolElegido) + ". Elija el rol que le corresponde.";
      TC.mostrarMensaje(errorNodo, mensaje);
      $("acceso-password").select();
      $("acceso-password").focus();
    } finally {
      restaurar();
    }
  }

  /* ---------------- Arranque ---------------- */
  function enlazar() {
    $("boton-iniciar").addEventListener("click", () => { mostrarPantalla("acceso"); $("aviso-sesion").hidden = true; $("titulo-acceso").setAttribute("tabindex", "-1"); $("titulo-acceso").focus(); });
    $("boton-volver-bienvenida").addEventListener("click", () => { elegirRol(null); mostrarPantalla("bienvenida"); $("boton-iniciar").focus(); });
    document.querySelectorAll(".rol").forEach((b) => b.addEventListener("click", () => elegirRol(b.dataset.rol)));
    $("formulario-acceso").addEventListener("submit", iniciarSesion);
    $("boton-ver-password").addEventListener("click", (e) => {
      const campo = $("acceso-password");
      const mostrar = campo.type === "password";
      campo.type = mostrar ? "text" : "password";
      e.currentTarget.textContent = mostrar ? "Ocultar" : "Mostrar";
      e.currentTarget.setAttribute("aria-pressed", mostrar ? "true" : "false");
    });
    $("boton-salir").addEventListener("click", cerrarSesion);
  }

  TC.refrescarEstado = refrescarEstado;

  async function arrancar() {
    enlazar();
    refrescarEstado();
    try {
      const usuario = await TC.api("/api/yo", { sin401: true });
      if (usuario && usuario.rol) { entrarAlPanel(usuario); return; }
    } catch (e) {
      /* Sin sesión: se muestra la bienvenida. */
    }
    mostrarPantalla("bienvenida");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arrancar);
  else arrancar();
})(window.TC);
