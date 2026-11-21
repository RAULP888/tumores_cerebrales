/* =====================================================================================
   03_consultas.sql  -  Consultas de análisis sobre el modelo estrella
   -------------------------------------------------------------------------------------
   Todas están escritas para correr IGUAL en SQLite (DB_MODO=local) y en SQL Server /
   Microsoft Fabric (T-SQL):
   - sin LIMIT/TOP, sin funciones de fecha propias de un motor (se usan las columnas de
     dim_fecha: anio, mes, semana);
   - las columnas BIT (es_tumor, de_acuerdo) se comparan con 1/0 y se suman con CASE;
   - las divisiones se hacen con 1.0 * ... / NULLIF(..., 0) para evitar división entera;
   - GROUP BY repite las expresiones (T-SQL no acepta alias en GROUP BY).
   Ninguna devuelve el identificador del paciente.
   Formato: cada consulta empieza con una línea "-- @consulta N: título" y termina en ";".
   pruebas/test_consultas_sql.py las ejecuta todas contra una base cargada.
   ===================================================================================== */

-- @consulta 1: Sensibilidad y especificidad por versión de modelo y origen (prueba y uso)
-- Solo cuenta casos con diagnóstico confirmado. Sensibilidad = VP / (VP + FN): la métrica
-- principal, porque el error más costoso es el falso negativo.
SELECT m.nombre AS modelo,
       m.version AS modelo_version,
       h.origen,
       COUNT(*) AS casos,
       SUM(CASE WHEN dp.es_tumor = 1 AND dc.es_tumor = 1 THEN 1 ELSE 0 END) AS vp,
       SUM(CASE WHEN dp.es_tumor = 0 AND dc.es_tumor = 0 THEN 1 ELSE 0 END) AS vn,
       SUM(CASE WHEN dp.es_tumor = 1 AND dc.es_tumor = 0 THEN 1 ELSE 0 END) AS fp,
       SUM(CASE WHEN dp.es_tumor = 0 AND dc.es_tumor = 1 THEN 1 ELSE 0 END) AS fn,
       ROUND(1.0 * SUM(CASE WHEN dp.es_tumor = 1 AND dc.es_tumor = 1 THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN dc.es_tumor = 1 THEN 1 ELSE 0 END), 0), 4) AS sensibilidad,
       ROUND(1.0 * SUM(CASE WHEN dp.es_tumor = 0 AND dc.es_tumor = 0 THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN dc.es_tumor = 0 THEN 1 ELSE 0 END), 0), 4) AS especificidad
FROM hecho_prediccion h
JOIN dim_modelo m ON m.modelo_id = h.modelo_id
JOIN dim_diagnostico dp ON dp.diagnostico_id = h.diagnostico_predicho_id
JOIN dim_diagnostico dc ON dc.diagnostico_id = h.diagnostico_confirmado_id
GROUP BY m.nombre, m.version, h.origen
ORDER BY h.origen, m.version;

-- @consulta 2: Estudios por doctor y semana (uso real)
-- La semana es la semana ISO de la fecha del estudio (dim_fecha).
SELECT u.usuario AS doctor,
       f.anio,
       f.semana,
       COUNT(*) AS estudios,
       SUM(CASE WHEN dp.es_tumor = 1 THEN 1 ELSE 0 END) AS con_posible_tumor,
       ROUND(100.0 * SUM(CASE WHEN dp.es_tumor = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_posible_tumor
FROM hecho_prediccion h
JOIN dim_fecha f ON f.fecha_id = h.fecha_id
JOIN dim_usuario u ON u.usuario_id = h.usuario_id
JOIN dim_diagnostico dp ON dp.diagnostico_id = h.diagnostico_predicho_id
WHERE h.origen = 'uso'
GROUP BY u.usuario, f.anio, f.semana
ORDER BY f.anio, f.semana, u.usuario;

-- @consulta 3: Casos en que el doctor no estuvo de acuerdo con el sistema
-- Útil para revisar qué tipo de error comete el modelo en la práctica.
SELECT h.prediccion_id,
       f.fecha AS fecha_estudio,
       u.usuario AS doctor,
       m.version AS modelo_version,
       dp.clave AS diagnostico_predicho,
       dc.clave AS diagnostico_confirmado,
       ROUND(h.probabilidad_tumor, 4) AS probabilidad_tumor,
       ROUND(h.umbral, 4) AS umbral
FROM hecho_prediccion h
JOIN dim_fecha f ON f.fecha_id = h.fecha_id
JOIN dim_modelo m ON m.modelo_id = h.modelo_id
JOIN dim_diagnostico dp ON dp.diagnostico_id = h.diagnostico_predicho_id
JOIN dim_diagnostico dc ON dc.diagnostico_id = h.diagnostico_confirmado_id
LEFT JOIN dim_usuario u ON u.usuario_id = h.usuario_id
WHERE h.origen = 'uso' AND h.de_acuerdo = 0
ORDER BY h.creado_en DESC;

-- @consulta 4: Tiempo de respuesta por versión de modelo (uso real)
-- Promedio, mínimo y máximo en milisegundos de cada predicción con Grad-CAM.
SELECT m.version AS modelo_version,
       COUNT(*) AS predicciones,
       ROUND(AVG(h.tiempo_respuesta_ms), 1) AS promedio_ms,
       ROUND(MIN(h.tiempo_respuesta_ms), 1) AS minimo_ms,
       ROUND(MAX(h.tiempo_respuesta_ms), 1) AS maximo_ms
FROM hecho_prediccion h
JOIN dim_modelo m ON m.modelo_id = h.modelo_id
WHERE h.origen = 'uso' AND h.tiempo_respuesta_ms IS NOT NULL
GROUP BY m.version
ORDER BY m.version;

-- @consulta 5: Falsos negativos confirmados por modelo y origen
-- El modelo dijo "sin tumor" y el diagnóstico confirmado es un tumor (el error más costoso).
SELECT m.nombre AS modelo,
       m.version AS modelo_version,
       h.origen,
       dc.clave AS tumor_real,
       COUNT(*) AS falsos_negativos,
       ROUND(AVG(h.probabilidad_tumor), 4) AS probabilidad_promedio
FROM hecho_prediccion h
JOIN dim_modelo m ON m.modelo_id = h.modelo_id
JOIN dim_diagnostico dp ON dp.diagnostico_id = h.diagnostico_predicho_id
JOIN dim_diagnostico dc ON dc.diagnostico_id = h.diagnostico_confirmado_id
WHERE dp.es_tumor = 0 AND dc.es_tumor = 1
GROUP BY m.nombre, m.version, h.origen, dc.clave
ORDER BY h.origen, m.version, dc.clave;

-- @consulta 6: Porcentaje con posible tumor por grupo de edad y sexo (uso real)
-- Usa la edad y el sexo ficticios de dim_paciente; no muestra el identificador.
SELECT p.grupo_edad,
       p.sexo,
       COUNT(*) AS estudios,
       SUM(CASE WHEN dp.es_tumor = 1 THEN 1 ELSE 0 END) AS con_posible_tumor,
       ROUND(100.0 * SUM(CASE WHEN dp.es_tumor = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_posible_tumor
FROM hecho_prediccion h
JOIN dim_paciente p ON p.paciente_id = h.paciente_id
JOIN dim_diagnostico dp ON dp.diagnostico_id = h.diagnostico_predicho_id
WHERE h.origen = 'uso'
GROUP BY p.grupo_edad, p.sexo
ORDER BY p.grupo_edad, p.sexo;

-- @consulta 7: Comparación de los 5 modelos en el conjunto de prueba
-- Mismas imágenes de prueba para todos; cada modelo con su propio umbral.
SELECT m.nombre AS modelo,
       m.tipo AS tipo_modelo,
       COUNT(*) AS n,
       SUM(CASE WHEN dp.es_tumor = 1 AND dc.es_tumor = 1 THEN 1 ELSE 0 END) AS vp,
       SUM(CASE WHEN dp.es_tumor = 0 AND dc.es_tumor = 0 THEN 1 ELSE 0 END) AS vn,
       SUM(CASE WHEN dp.es_tumor = 1 AND dc.es_tumor = 0 THEN 1 ELSE 0 END) AS fp,
       SUM(CASE WHEN dp.es_tumor = 0 AND dc.es_tumor = 1 THEN 1 ELSE 0 END) AS fn,
       ROUND(1.0 * SUM(CASE WHEN dp.es_tumor = 1 AND dc.es_tumor = 1 THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN dc.es_tumor = 1 THEN 1 ELSE 0 END), 0), 4) AS sensibilidad,
       ROUND(1.0 * SUM(CASE WHEN dp.es_tumor = 0 AND dc.es_tumor = 0 THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN dc.es_tumor = 0 THEN 1 ELSE 0 END), 0), 4) AS especificidad,
       ROUND(1.0 * SUM(CASE WHEN dp.es_tumor = 1 AND dc.es_tumor = 1 THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN dp.es_tumor = 1 THEN 1 ELSE 0 END), 0), 4) AS precision_vpp,
       ROUND(1.0 * SUM(CASE WHEN dp.es_tumor = dc.es_tumor THEN 1 ELSE 0 END) / COUNT(*), 4) AS exactitud
FROM hecho_prediccion h
JOIN dim_modelo m ON m.modelo_id = h.modelo_id
JOIN dim_diagnostico dp ON dp.diagnostico_id = h.diagnostico_predicho_id
JOIN dim_diagnostico dc ON dc.diagnostico_id = h.diagnostico_confirmado_id
WHERE h.origen = 'prueba'
GROUP BY m.nombre, m.tipo
ORDER BY sensibilidad DESC, especificidad DESC;

-- @consulta 8: Actividad de la bitácora por usuario y acción
-- Cuántas veces, cuántas fallidas y la última vez. Los eventos sin usuario (p. ej. la carga
-- de datos o el proceso de reentrenamiento) aparecen como "(sistema)".
SELECT COALESCE(b.usuario, '(sistema)') AS usuario,
       b.accion,
       COUNT(*) AS eventos,
       SUM(CASE WHEN b.exito = 0 THEN 1 ELSE 0 END) AS fallidos,
       MAX(b.fecha_hora) AS ultimo_evento
FROM bitacora b
GROUP BY COALESCE(b.usuario, '(sistema)'), b.accion
ORDER BY usuario, eventos DESC;

-- @consulta 9: Entrenamientos con su diagnóstico, mejor época y mejor pérdida de validación
-- Une entrenamientos con el modelo que generó y resume su historial por época.
SELECT e.entrenamiento_id,
       e.estado,
       m.version AS modelo_version,
       m.estado AS estado_modelo,
       e.diagnostico,
       e.mejor_epoca,
       e.epocas_max,
       he.epocas_registradas,
       ROUND(he.mejor_perdida_val, 4) AS mejor_perdida_val,
       e.iniciado_en,
       e.terminado_en
FROM entrenamientos e
LEFT JOIN dim_modelo m ON m.modelo_id = e.modelo_id
LEFT JOIN (SELECT entrenamiento_id,
                  COUNT(*) AS epocas_registradas,
                  MIN(perdida_val) AS mejor_perdida_val
           FROM historial_epocas
           WHERE etapa IN ('cabeza', 'ajuste_fino')
           GROUP BY entrenamiento_id) he ON he.entrenamiento_id = e.entrenamiento_id
ORDER BY e.entrenamiento_id;

-- @consulta 10: Tipo de tumor probable contra tipo confirmado (red Keras, prueba)
-- Dato secundario: solo en casos donde la red detectó tumor y el tumor es real.
SELECT h.tipo_probable,
       dc.clave AS tipo_confirmado,
       COUNT(*) AS casos
FROM hecho_prediccion h
JOIN dim_modelo m ON m.modelo_id = h.modelo_id
JOIN dim_diagnostico dc ON dc.diagnostico_id = h.diagnostico_confirmado_id
WHERE h.origen = 'prueba' AND m.tipo = 'red_keras' AND h.tipo_probable IS NOT NULL AND dc.es_tumor = 1
GROUP BY h.tipo_probable, dc.clave
ORDER BY h.tipo_probable, dc.clave;

-- @consulta 11: Variación de métricas entre pliegues de la validación cruzada
-- Media y rango de sensibilidad por modelo (estabilidad del modelo entre particiones).
SELECT m.nombre AS modelo,
       COUNT(*) AS pliegues,
       ROUND(AVG(mp.sensibilidad), 4) AS sensibilidad_media,
       ROUND(MIN(mp.sensibilidad), 4) AS sensibilidad_min,
       ROUND(MAX(mp.sensibilidad), 4) AS sensibilidad_max,
       ROUND(AVG(mp.especificidad), 4) AS especificidad_media
FROM metricas_pliegue mp
JOIN dim_modelo m ON m.modelo_id = mp.modelo_id
GROUP BY m.nombre
ORDER BY sensibilidad_media DESC;
