# NeuroScan — sistema hospitalario web para priorizar resonancias de cerebro

Este archivo es la referencia del proyecto. Los nombres de tablas, vistas, campos, rutas y parámetros que aparecen aquí son definitivos: no se renombran ni se reinterpretan.

# CONTEXTO
- Proyecto final del Diplomado "Liderazgo en la Era de la IA" (Universidad Anáhuac Querétaro). Entrega: sábado 21 de noviembre de 2026.
- Caso: una red de centros de imagen necesita priorizar qué resonancias de cerebro lee primero el radiólogo. El sistema clasifica cada imagen en 4 clases y prioriza; **no diagnostica**.
- Sistema operativo: Windows, sin GPU. Python 3.13 en `C:\Users\raulp\AppData\Local\Programs\Python\Python313\python.exe`
- Carpeta del proyecto: `C:\proyectos\tumores-cerebrales` (fuera de OneDrive a propósito).
- Idioma: todo el código, comentarios, mensajes e interfaz en español.

# LO QUE YA EXISTE (no lo borres)
- `datos/Training` y `datos/Testing`, cada una con las carpetas `glioma`, `meningioma`, `notumor`, `pituitary` (7,200 imágenes).
- `tumores_cerebrales.py`: entrena EfficientNetB0 en Keras. Reutiliza su función `recortar_cerebro` y su lógica de Grad-CAM.
- `resultados_sin_duplicados/modelo_final.keras`: modelo ya entrenado (82.8 % de exactitud en prueba sin duplicados).
- `notebooks/02_modelos_clasicos.ipynb`: modelos clásicos del Módulo 3.

# DATOS DEL MODELO
- Clases, en este orden exacto: `["glioma", "meningioma", "notumor", "pituitary"]`.
- Nombres para mostrar: Glioma, Meningioma, Sin tumor, Tumor hipofisario.
- Entrada: imagen RGB de 224x224 en float32 con valores 0 a 255 (EfficientNet ya incluye su normalización; **no dividas entre 255**).
- Preprocesamiento obligatorio, igual que en el entrenamiento: recortar el contorno del cerebro con OpenCV y redimensionar con `INTER_AREA`.
- Capa para Grad-CAM: `"top_activation"`.
- En Windows, lee y escribe imágenes con `np.fromfile` + `cv2.imdecode` y `cv2.imencode` + `tofile` (`cv2.imread` falla con acentos en la ruta).

# ESTRUCTURA FINAL
```
app/backend/      API en FastAPI
app/frontend/     index.html, styles.css, app.js (JavaScript puro, sin frameworks ni build)
app/modelos/      modelo_final.keras y modelo_info.json
app/almacen/      imágenes subidas y base local (no se sube a GitHub)
app/.env          secretos (no se sube a GitHub)
entrenamiento/    entrenar_kfold.py
sql/              esquema T-SQL y consultas
tablero/          medidas DAX y archivo .pbix
pruebas/          pruebas automáticas
README.md, .gitignore
```

# BASE DE DATOS
Dos modos, elegidos con `DB_MODO` en `app/.env`:
- `"fabric"`: SQL database en Microsoft Fabric (motor SQL Server), con pyodbc y "ODBC Driver 18 for SQL Server". Fabric SOLO acepta Microsoft Entra ID: la cadena ODBC termina con `Authentication=ActiveDirectoryInteractive;`. No existe usuario y contraseña de SQL.
- `"local"`: SQLite de respaldo en `app/almacen/neuroscan.db`, para pruebas y por si falla internet.

Usa SQLAlchemy Core para que el mismo código funcione en los dos. Usa Unicode/NVARCHAR para textos con acentos.

## Tablas
- `usuarios`(id, usuario único, nombre, rol ['operador'|'administrador'], hash_password, activo, creado_en)
- `pacientes`(id, folio único 'P-AAAA-00001', nombre, apellidos, fecha_nacimiento, sexo ['F'|'M'|'Otro'], telefono, medico_solicitante, motivo, creado_por, creado_en)
- `estudios`(id, lote, paciente_id, usuario_id, archivo_original, imagen, gradcam, prediccion, confianza, p_glioma, p_meningioma, p_notumor, p_pituitary, requiere_revision, umbral_usado, modelo_version, estado ['pendiente'|'validado'], clase_confirmada, nota_validacion, validado_por, validado_en, creado_en). Una fila por imagen.
- `dim_clase`(clase, nombre, es_tumor, prioridad)
- `parametros`(clave, valor, tipo ['float'|'int'|'bool'|'str'], descripcion, actualizado_por, actualizado_en)
- `bitacora`(id, fecha, usuario_id, usuario, rol, accion, detalle, ip, exito)
- `consultas_ia`(id, fecha, usuario_id, pregunta, sql_generado, filas, exito, error)

## Vistas del modelo estrella
Las usan Power BI y el asistente. **NO deben exponer nombres, teléfonos ni contraseñas.**
- `vw_fact_estudio`(estudio_id, paciente_id, usuario_id, fecha, fecha_hora, anio, mes, prediccion, clase_confirmada, confianza, requiere_revision, estado, tumor_predicho, acierto, falso_negativo, falso_positivo, p_glioma, p_meningioma, p_notumor, p_pituitary, modelo_version)
- `vw_dim_paciente`(paciente_id, folio, sexo, edad, grupo_edad ['0-17'|'18-39'|'40-59'|'60 o más'], fecha_registro)
- `vw_dim_usuario`(usuario_id, usuario, nombre, rol, activo)
- `vw_bitacora`(evento_id, fecha_hora, fecha, usuario, rol, accion, exito)

Definiciones:
- `tumor_predicho` = prediccion distinta de 'notumor'.
- `acierto` = 1 si clase_confirmada = prediccion, NULL si no se ha validado.
- `falso_negativo` = confirmado con tumor y el modelo dijo 'notumor'.
- `falso_positivo` = confirmado 'notumor' y el modelo dijo tumor.

## Parámetros iniciales
| clave | valor inicial | nota |
|---|---|---|
| nombre_hospital | "Hospital Demostración NeuroScan" | |
| umbral_revision | 0.80 | entre 0.5 y 0.99 |
| max_imagenes | 8 | |
| tam_max_mb | 10 | |
| gradcam_activo | true | |
| limite_filas_ia | 200 | |
| powerbi_url | (vacío) | |

## Acciones de la bitácora
LOGIN_OK, LOGIN_FALLIDO, LOGOUT, PACIENTE_CREADO, ESTUDIO_CREADO, ESTUDIO_VALIDADO, PARAMETRO_ACTUALIZADO, USUARIO_CREADO, USUARIO_ACTUALIZADO, CONSULTA_IA, CONSULTA_IA_BLOQUEADA, ACCESO_DENEGADO, CARGA_DEMO.

# CONTRATO DE LA API (backend y frontend deben respetarlo exactamente)
Sesión por cookie HttpOnly llamada `ns_sesion`. Los errores devuelven `{"detail": "mensaje en español"}`.

- `GET  /api/estado` → {hospital, modelo:{cargado, version, aviso, metricas}, base_datos, asistente_configurado}   (público)
- `POST /api/login` {usuario, password} → {id, usuario, nombre, rol}
- `POST /api/logout`
- `GET  /api/yo` → usuario de la sesión, o 401
- `GET  /api/pacientes?q=` → lista (máx. 25) con campo edad
- `POST /api/pacientes` {nombre, apellidos, fecha_nacimiento, sexo, telefono?, medico_solicitante?, motivo?} → paciente con folio y edad
- `POST /api/estudios` (multipart: paciente_id, archivos[]) → {lote, folio, resultados:[{id, archivo, prediccion, confianza, probabilidades:{glioma,meningioma,notumor,pituitary}, requiere_revision, umbral, imagen, gradcam, demo, modelo_version} | {archivo, error}]}
- `GET  /api/estudios?solo_mios=&clase=&revision=si|no&estado=pendiente|validado&q=&limite=` → filas de estudios con folio, paciente_nombre, paciente_apellidos, operador. El operador solo ve los suyos.
- `POST /api/estudios/{id}/validar` {clase_confirmada, nota?}   (solo administrador)
- `GET  /media/{nombre}` → PNG de la imagen o del mapa de calor (requiere sesión)
- `GET  /api/resumen` → {pacientes, estudios, estudios_hoy, estudios_mes, pacientes_mes, en_revision, pct_revision, pendientes_validar, validados, exactitud_validada, falsos_negativos, falsos_positivos, confianza_media, por_clase:[{clase,nombre,estudios}], serie:[{fecha,estudios}] de 30 días, matriz 4x4}   (solo administrador)
- `GET/PUT /api/parametros`   (solo administrador)
- `GET/POST /api/usuarios` y `PUT /api/usuarios/{id}` {nombre?, rol?, activo?, password?}   (solo administrador)
- `GET  /api/bitacora?usuario=&accion=&exito=si|no&desde=&hasta=&pagina=` → {total, pagina, paginas, eventos, acciones}   (solo administrador)
- `POST /api/asistente` {pregunta} → {estado:'ok'|'sin_consulta'|'bloqueada'|'error', respuesta, sql, columnas, filas}   (solo administrador)

# REGLAS QUE NO SE NEGOCIAN
1. Pacientes ficticios siempre. La interfaz lo dice en la bienvenida.
2. La API key de Claude vive solo en `app/.env` (`ANTHROPIC_API_KEY`). Nunca en el frontend ni en GitHub.
3. El asistente solo ejecuta consultas de lectura, validadas antes de correr.
4. La interfaz inserta los datos del servidor con `textContent`, nunca con `innerHTML`.
5. Cada pantalla que muestre una predicción incluye: "Herramienta de apoyo. Requiere validación médica; no emite diagnósticos."
6. No inventes resultados ni métricas. Si algo no se pudo probar, dímelo.
7. Al terminar cada etapa, ejecuta las pruebas y repórtame qué pasó y qué falló.
