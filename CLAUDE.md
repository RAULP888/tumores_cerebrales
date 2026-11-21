# Sistema de Apoyo para Detección de Tumores Cerebrales

Proyecto final del Diplomado en IA Generativa, BI y Ciencia de Datos (Universidad Anáhuac Querétaro; alumno: Raúl Pichardo Manzano). Tablero web de hospital: el Doctor sube una resonancia magnética y el sistema indica si **hay o no hay tumor**, con su nivel de confianza. Todo se registra en SQL Server (Microsoft Fabric) y se analiza en Power BI.

**Es un proyecto académico de apoyo a la decisión, no un dispositivo médico.**

Este archivo sustituye a `CLAUDE_anterior.md` (especificación "NeuroScan" del 17 de noviembre), que se conserva solo como referencia.

## Contexto
- Entrega: **sábado 21 de noviembre de 2026, antes de la 1:00 pm**. Primero que todo funcione de principio a fin; después las funciones extra.
- Carpeta: `C:\proyectos\tumores-cerebrales`. Windows 11, **sin GPU**: todo entrena en CPU.
- Python: `.venv\Scripts\python.exe` (Python 3.12). Kernel de Jupyter: `tumores`.
- Idioma: español de México, formal, sencillo y claro, en código, comentarios, mensajes e interfaz.
- Se entregan archivos completos y ejecutables, nunca fragmentos.

## Reglas que no se negocian
1. **No inventes resultados ni métricas.** Todo número sale de una ejecución real. Si algo no se pudo ejecutar, se dice.
2. No borres ni sobrescribas material del usuario sin preguntar. `referencia/` y `datos/Training`, `datos/Testing` son de solo lectura.
3. Pacientes siempre ficticios: identificador, edad, sexo y fecha del estudio. Sin nombres ni datos personales.
4. No presentes el sistema como diagnóstico médico. Toda pantalla de resultado muestra: **"Resultado de apoyo. No sustituye el diagnóstico de un médico especialista."**
5. El Grad-CAM se describe como **"zona que más influyó"**, nunca como "ubicación del tumor".
6. La red neuronal que se evalúa y se usa en la app es de **Keras (TensorFlow)**, no de PyTorch.
7. `ANTHROPIC_API_KEY` vive solo en `.env`. Nunca llega al frontend, al repositorio ni a los registros.
8. Consultas SQL siempre parametrizadas.
9. El frontend inserta los datos del servidor con `textContent`, nunca con `innerHTML`. Sin CDN ni dependencias de internet.
10. Si algo es ambiguo, se pregunta con opciones numeradas antes de decidir.
11. Una fase no se da por terminada si el Verificador reporta una falla.

## Decisiones tomadas (no se cambian sin preguntar)
- Backend FastAPI; frontend HTML + JavaScript sin frameworks.
- Inicio de sesión con usuario y contraseña para **Doctor** y **Administrador** (roles `doctor` y `administrador`).
- Base en Microsoft Fabric (SQL Server) con respaldo SQLite, elegido con `DB_MODO` en `.env` (`local` o `fabric`).
- Validación cruzada K-fold estratificada de 5 pliegues.
- K-fold de la red: los 5 pliegues entrenan la cabeza de Keras sobre rasgos guardados; el ajuste fino se hace **una sola vez** con validación apartada, y así se reporta.
- Asistente de consultas SQL con la API de Claude.
- Tres pausas: después de las fases 1+2, 3+4 y 5+6.

## Estructura
```
datos/        Training/, Testing/ (dataset), FUENTE.md, diccionario_datos.md, manifiesto.csv, rasgos/
notebooks/    01_eda · 02_rasgos · 03_modelos_ml · 04_red_keras · 05_ia_generativa
resultados/   tablas, figuras y predicciones que generan los notebooks
sql/          01_crear_tablas.sql · 02_cargar_datos.py · 03_consultas.sql
tablero/      GUIA_POWER_BI.md (el .pbix lo construye el usuario)
app/backend/  FastAPI; app/backend/ml/ es el único lugar con preprocesamiento, entrenamiento y diagnóstico
app/frontend/ index.html, estilos.css, app.js
app/modelos/  vNNN/modelo.keras + info.json (no se sube a GitHub)
app/almacen/  imágenes subidas y SQLite local (no se sube a GitHub)
scripts/      utilidades (usuarios de demostración, correr notebooks)
pruebas/      pruebas automáticas
anexos/       PROMPTS.md
referencia/   material anterior, intacto
```
Los notebooks importan `app.backend.ml` para que el modelo de la app sea exactamente el evaluado.

## Ciencia de datos
- **Problema:** clasificación binaria, "tumor" (glioma + meningioma + pituitary) contra "sin tumor" (notumor). Dato secundario: tipo de tumor más probable.
- **El error más costoso es el falso negativo.** Métrica principal: **sensibilidad**. El umbral se elige para priorizarla (objetivo 0.98 en validación). Se reportan también especificidad, precisión, F1 y AUC.
- **Duplicados:** se juntan Training y Testing, se detectan por hash y se eliminan antes de dividir. Los grupos con etiquetas contradictorias se descartan.
- **Prueba:** 20 % estratificado, semilla 42, que no se toca hasta el final. La validación cruzada usa solo el 80 %.
- **Desbalance:** pesos de clase, documentado.
- **Preprocesamiento único:** recorte del contorno del cerebro (OpenCV) → 160×160 con `INTER_AREA` → RGB 0 a 255. La normalización de MobileNetV2 va dentro del modelo.
- **Lectura de imágenes en Windows:** `np.fromfile` + `cv2.imdecode` (`cv2.imread` falla con acentos).
- **Rasgos:** MobileNetV2 congelada (ImageNet, 160×160, promedio global → 1,280 valores), extraídos una sola vez y guardados en `datos/rasgos/`.
- **Modelos, mismo K-fold y mismas métricas:**
  1. Regresión logística sobre rasgos básicos (brillo, contraste, histograma): la solución más simple.
  2. Regresión logística sobre rasgos de MobileNetV2.
  3. Random Forest.
  4. SVM (RBF).
  5. Red en Keras: MobileNetV2 + cabeza densa con dropout, y después ajuste fino de las últimas capas con tasa baja.
- **Convergencia:** `EarlyStopping(monitor="val_loss", restore_best_weights=True)`, `ReduceLROnPlateau`, `ModelCheckpoint`. Historial por época en archivo y en SQL. Curvas con la mejor época marcada. Diagnóstico automático: "convergió", "se detuvo antes de converger", "sobreajuste" o "no aprende". Es un mínimo de la pérdida de validación, no una garantía de mínimo global.
- Semilla 42 en todo; versiones registradas.

## Base de datos
SQLAlchemy Core. Fabric: `pyodbc`, "ODBC Driver 18 for SQL Server", `Authentication=ActiveDirectoryInteractive`. Los datos de conexión los da el usuario; no se inventan.

**Modelo estrella**
- `hecho_prediccion`(prediccion_id, paciente_id, fecha_id, usuario_id, modelo_id, diagnostico_predicho_id, diagnostico_confirmado_id, origen ['uso'|'prueba'], probabilidad_tumor, umbral, tipo_probable, probabilidad_tipo, de_acuerdo, tiempo_respuesta_ms, archivo_imagen, archivo_gradcam, creado_en)
- `dim_paciente`(paciente_id, identificador, edad, grupo_edad, sexo)
- `dim_fecha`(fecha_id AAAAMMDD, fecha, anio, mes, nombre_mes, semana, dia_semana)
- `dim_usuario`: vista sobre `usuarios` sin el hash (usuario_id, usuario, rol, activo)
- `dim_modelo`(modelo_id, nombre, tipo ['clasico'|'red_keras'], version, estado ['referencia'|'candidato'|'produccion'|'retirado'], umbral, entrenamiento_id, creado_en)
- `dim_diagnostico`(diagnostico_id, clave, nombre, es_tumor): sin_tumor, tumor, glioma, meningioma, pituitary

**Operación**
- `usuarios`(usuario_id, usuario, hash_password, rol, activo, creado_en)
- `sesiones`(token_hash, usuario_id, creada_en, expira_en)
- `bitacora`(evento_id, fecha_hora, usuario_id, usuario, rol, accion, detalle, ip, exito)
- `entrenamientos`(entrenamiento_id, modelo_id, estado, parametros, epoca_actual, epocas_max, mejor_epoca, diagnostico, metricas, matriz_confusion, iniciado_en, terminado_en, solicitado_por)
- `historial_epocas`(entrenamiento_id, etapa, epoca, perdida, exactitud, perdida_val, exactitud_val, tasa_aprendizaje)
- `metricas_pliegue`(entrenamiento_id, modelo_id, pliegue, sensibilidad, especificidad, precision, f1, auc, vp, vn, fp, fn)

Los resultados de prueba de cada modelo se cargan en `hecho_prediccion` con `origen='prueba'`.

## Aplicación
- Bienvenida → elegir rol e iniciar sesión → panel del Doctor o del Administrador.
- Contraseñas con bcrypt. Sesión en cookie httpOnly. Permisos validados en el backend: Doctor recibe 403 en rutas de administrador.
- Cada inicio de sesión, cierre y acción importante va a `bitacora`.
- El modelo nuevo queda como **candidato**; pasa a producción solo cuando el administrador lo aprueba, y se puede regresar al anterior.
- Reentrenamiento en un proceso aparte, con progreso y cancelación. El conjunto de prueba nunca entra al reentrenamiento.

## Contrato de la API (backend y frontend lo respetan exactamente)
- Arranque: `.venv\Scripts\python.exe -m uvicorn app.backend.main:app --port 8000`. FastAPI sirve `app/frontend/` en `/` y la API en `/api`.
- Sesión en cookie httpOnly `ts_sesion` (SameSite=Lax). Errores: `{"detail": "mensaje en español"}`. 401 sin sesión; 403 sin permiso.
- Todas las fechas en ISO 8601. Diagnósticos: `sin_tumor`, `tumor`, `glioma`, `meningioma`, `pituitary`.

**Público y sesión**
- `GET /api/estado` → `{modelo:{cargado, version, nombre, umbral}, base_datos:"local"|"fabric", asistente_configurado, powerbi_url, aviso}`
- `POST /api/login` `{usuario, password, rol}` → `{usuario_id, usuario, rol}`. 401 si las credenciales fallan; 403 si el rol elegido no es el del usuario.
- `POST /api/logout` → `{ok:true}`
- `GET /api/yo` → `{usuario_id, usuario, rol}` o 401

**Doctor (y administrador)**
- `POST /api/estudios` multipart: `identificador` (ficticio, p. ej. `PAC-0001`), `edad` (0–120), `sexo` (`F`|`M`|`Otro`), `fecha_estudio` (AAAA-MM-DD), `archivos` (1 a 8 JPG/PNG, máx. 10 MB c/u) →
  `{resultados:[{prediccion_id, archivo, hay_tumor, etiqueta, probabilidad_tumor, confianza, umbral, tipo_probable, tipo_nombre, probabilidad_tipo, imagen_url, gradcam_url, modelo_version, tiempo_respuesta_ms, aviso} | {archivo, error}]}`.
  `etiqueta` = "Se detecta posible tumor" | "No se detecta tumor". `confianza` = probabilidad_tumor si hay_tumor, si no 1 − probabilidad_tumor. `tipo_*` es null si no hay tumor.
- `POST /api/estudios/{prediccion_id}/confirmacion` `{de_acuerdo: bool, diagnostico_real: clave de diagnóstico}` → el estudio actualizado. Un doctor solo confirma los suyos.
- `GET /api/estudios?desde=&hasta=&resultado=tumor|sin_tumor&confirmacion=pendiente|de_acuerdo|desacuerdo&identificador=&limite=100` → `{estudios:[{prediccion_id, creado_en, identificador, edad, sexo, fecha_estudio, hay_tumor, etiqueta, probabilidad_tumor, confianza, tipo_nombre, modelo_version, de_acuerdo, diagnostico_confirmado, imagen_url, gradcam_url, doctor}]}`. El doctor ve solo los suyos; el administrador, todos.
- `GET /media/{nombre}` → PNG de la imagen o del mapa (requiere sesión).

**Administrador (`/api/admin/*`; un doctor recibe 403 y se registra `ACCESO_DENEGADO`)**
- `GET /api/admin/resumen` → `{estudios, estudios_hoy, con_tumor, pct_tumor, confirmados, desacuerdos, falsos_negativos, falsos_positivos, tiempo_promedio_ms, modelo_produccion}`
- `POST /api/admin/entrenamientos` `{epocas_max, tasa, lote, kfold: bool, ajuste_fino: bool}` → `{entrenamiento_id}`; 409 si ya hay uno corriendo.
- `GET /api/admin/entrenamientos` → `{entrenamientos:[{entrenamiento_id, estado, iniciado_en, terminado_en, version, diagnostico}]}`
- `GET /api/admin/entrenamientos/{id}` → `{entrenamiento_id, estado:"en_cola"|"corriendo"|"terminado"|"cancelado"|"error", etapa, epoca_actual, epocas_max, progreso (0 a 1), mensaje, historial:[{etapa, epoca, perdida, exactitud, perdida_val, exactitud_val, tasa_aprendizaje}], metricas_pliegue:[{pliegue, sensibilidad, especificidad, precision, f1, auc, vp, vn, fp, fn}], mejor_epoca, diagnostico, explicacion, advertencias:[], metricas, matriz_confusion:[[vn,fp],[fn,vp]], curvas_url, version}`
- `POST /api/admin/entrenamientos/{id}/cancelar` → `{ok:true}`
- `GET /api/admin/modelos` → `{modelos:[{modelo_id, version, nombre, tipo, estado:"referencia"|"candidato"|"produccion"|"retirado", umbral, sensibilidad, especificidad, f1, auc, creado_en, entrenamiento_id}]}`
- `POST /api/admin/modelos/{modelo_id}/aprobar` (candidato → producción; la anterior pasa a retirado) · `POST /api/admin/modelos/revertir` (regresa a la versión de producción anterior)
- `GET /api/admin/umbral?valor=0.37` → `{valor, actual, n, origen, vp, vn, fp, fn, sensibilidad, especificidad}` calculado sobre `validacion.npz` del modelo en producción · `PUT /api/admin/umbral` `{valor}` (entre 0.01 y 0.99)
- `GET /api/admin/usuarios` · `POST /api/admin/usuarios` `{usuario, password, rol}` · `PUT /api/admin/usuarios/{id}` `{activo?, password?, rol?}`
- `GET /api/admin/bitacora?usuario=&accion=&exito=si|no&desde=&hasta=&pagina=1` → `{total, pagina, paginas, eventos:[{evento_id, fecha_hora, usuario, rol, accion, detalle, ip, exito}], acciones:[...]}`
- `POST /api/admin/asistente` `{pregunta}` → `{estado:"ok"|"bloqueada"|"error"|"sin_configurar", respuesta, sql, columnas, filas}` (Fase 5)

**Acciones de la bitácora:** LOGIN_OK, LOGIN_FALLIDO, LOGOUT, ACCESO_DENEGADO, ESTUDIO_CREADO, ESTUDIO_CONFIRMADO, ENTRENAMIENTO_INICIADO, ENTRENAMIENTO_TERMINADO, ENTRENAMIENTO_CANCELADO, ENTRENAMIENTO_ERROR, MODELO_APROBADO, MODELO_REVERTIDO, UMBRAL_ACTUALIZADO, USUARIO_CREADO, USUARIO_ACTUALIZADO, CONSULTA_IA, CONSULTA_IA_BLOQUEADA, CARGA_DATOS.

## Asistente de consultas (IA generativa)
- Solo `SELECT`, sobre una lista blanca de tablas o vistas, con límite de filas.
- Cualquier otra sentencia se rechaza y se registra en la bitácora.
- No se envían a la API datos que identifiquen a pacientes.
- Los prompts se guardan en `notebooks/05_ia_generativa.ipynb` y en `anexos/PROMPTS.md`.

## Verificación al cierre de cada bloque
El Verificador no escribe el código que revisa y comprueba **ejecutando**: notebooks completos, cero imágenes repetidas entre entrenamiento y prueba, métricas iguales a las recalculadas desde las predicciones guardadas, curvas y diagnóstico coherentes con el historial, flujo completo de la app, 403 para el Doctor, rechazos del asistente y ausencia de la API key en frontend y repositorio. Entrega: qué pasó, qué falló y qué no pudo comprobar.
