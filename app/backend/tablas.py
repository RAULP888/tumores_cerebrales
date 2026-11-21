"""Tablas de la base (SQLAlchemy Core). Este módulo es el único dueño del esquema.

Modelo estrella: hecho_prediccion + dim_paciente, dim_fecha, dim_usuario (vista), dim_modelo y
dim_diagnostico. Tablas de operación: usuarios, sesiones, bitacora, entrenamientos,
historial_epocas y metricas_pliegue.

Los textos usan Unicode (NVARCHAR en SQL Server). Las columnas que no aparecen en CLAUDE.md
(p. ej. entrenamientos.etapa/progreso/mensaje o las métricas de dim_modelo) son adicionales y
están documentadas en app/backend/DESVIACIONES_CONTRATO.md.
"""
from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, MetaData,
                        Table, Unicode, UnicodeText, UniqueConstraint)

metadata = MetaData()

usuarios = Table(
    "usuarios", metadata,
    Column("usuario_id", Integer, primary_key=True, autoincrement=True),
    Column("usuario", Unicode(50), nullable=False, unique=True),
    Column("hash_password", Unicode(100), nullable=False),
    Column("rol", Unicode(20), nullable=False),
    Column("activo", Boolean, nullable=False, default=True),
    Column("creado_en", DateTime, nullable=False),
)

sesiones = Table(
    "sesiones", metadata,
    Column("token_hash", Unicode(64), primary_key=True),
    Column("usuario_id", Integer, ForeignKey("usuarios.usuario_id"), nullable=False),
    Column("creada_en", DateTime, nullable=False),
    Column("expira_en", DateTime, nullable=False),
    Index("ix_sesiones_usuario", "usuario_id"),
)

bitacora = Table(
    "bitacora", metadata,
    Column("evento_id", Integer, primary_key=True, autoincrement=True),
    Column("fecha_hora", DateTime, nullable=False),
    Column("usuario_id", Integer, nullable=True),
    Column("usuario", Unicode(50), nullable=True),
    Column("rol", Unicode(20), nullable=True),
    Column("accion", Unicode(40), nullable=False),
    Column("detalle", Unicode(1000), nullable=True),
    Column("ip", Unicode(45), nullable=True),
    Column("exito", Boolean, nullable=False),
    Index("ix_bitacora_fecha", "fecha_hora"),
    Index("ix_bitacora_accion", "accion"),
)

dim_paciente = Table(
    "dim_paciente", metadata,
    Column("paciente_id", Integer, primary_key=True, autoincrement=True),
    Column("identificador", Unicode(20), nullable=False, unique=True),
    Column("edad", Integer, nullable=True),
    Column("grupo_edad", Unicode(10), nullable=True),
    Column("sexo", Unicode(10), nullable=True),
)

dim_fecha = Table(
    "dim_fecha", metadata,
    Column("fecha_id", Integer, primary_key=True, autoincrement=False),
    Column("fecha", Date, nullable=False),
    Column("anio", Integer, nullable=False),
    Column("mes", Integer, nullable=False),
    Column("nombre_mes", Unicode(15), nullable=False),
    Column("semana", Integer, nullable=False),
    Column("dia_semana", Unicode(15), nullable=False),
)

dim_diagnostico = Table(
    "dim_diagnostico", metadata,
    Column("diagnostico_id", Integer, primary_key=True, autoincrement=False),
    Column("clave", Unicode(20), nullable=False, unique=True),
    Column("nombre", Unicode(60), nullable=False),
    Column("es_tumor", Boolean, nullable=False),
)

# entrenamiento_id no lleva llave foránea para evitar la referencia circular con entrenamientos.
dim_modelo = Table(
    "dim_modelo", metadata,
    Column("modelo_id", Integer, primary_key=True, autoincrement=True),
    Column("nombre", Unicode(100), nullable=False),
    Column("tipo", Unicode(20), nullable=False),
    Column("version", Unicode(40), nullable=False),
    Column("estado", Unicode(20), nullable=False),
    Column("umbral", Float, nullable=True),
    Column("entrenamiento_id", Integer, nullable=True),
    Column("sensibilidad", Float, nullable=True),
    Column("especificidad", Float, nullable=True),
    Column("f1", Float, nullable=True),
    Column("auc", Float, nullable=True),
    Column("origen_metricas", Unicode(20), nullable=True),
    Column("aprobado_en", DateTime, nullable=True),
    Column("creado_en", DateTime, nullable=False),
    UniqueConstraint("tipo", "version", name="uq_dim_modelo_tipo_version"),
)

entrenamientos = Table(
    "entrenamientos", metadata,
    Column("entrenamiento_id", Integer, primary_key=True, autoincrement=True),
    Column("modelo_id", Integer, ForeignKey("dim_modelo.modelo_id"), nullable=True),
    Column("estado", Unicode(20), nullable=False),
    Column("parametros", UnicodeText, nullable=True),
    Column("etapa", Unicode(30), nullable=True),
    Column("epoca_actual", Integer, nullable=True),
    Column("epocas_max", Integer, nullable=True),
    Column("progreso", Float, nullable=True),
    Column("mensaje", Unicode(500), nullable=True),
    Column("mejor_epoca", Integer, nullable=True),
    Column("diagnostico", Unicode(40), nullable=True),
    Column("explicacion", UnicodeText, nullable=True),
    Column("advertencias", UnicodeText, nullable=True),
    Column("metricas", UnicodeText, nullable=True),
    Column("matriz_confusion", Unicode(200), nullable=True),
    Column("curvas", Unicode(100), nullable=True),
    Column("pid", Integer, nullable=True),
    Column("iniciado_en", DateTime, nullable=True),
    Column("terminado_en", DateTime, nullable=True),
    Column("solicitado_por", Integer, ForeignKey("usuarios.usuario_id"), nullable=True),
    Index("ix_entrenamientos_estado", "estado"),
)

historial_epocas = Table(
    "historial_epocas", metadata,
    Column("entrenamiento_id", Integer, ForeignKey("entrenamientos.entrenamiento_id"), primary_key=True),
    Column("etapa", Unicode(30), primary_key=True),
    Column("epoca", Integer, primary_key=True, autoincrement=False),
    Column("perdida", Float, nullable=True),
    Column("exactitud", Float, nullable=True),
    Column("perdida_val", Float, nullable=True),
    Column("exactitud_val", Float, nullable=True),
    Column("tasa_aprendizaje", Float, nullable=True),
)

metricas_pliegue = Table(
    "metricas_pliegue", metadata,
    Column("metrica_id", Integer, primary_key=True, autoincrement=True),
    Column("entrenamiento_id", Integer, ForeignKey("entrenamientos.entrenamiento_id"), nullable=True),
    Column("modelo_id", Integer, ForeignKey("dim_modelo.modelo_id"), nullable=True),
    Column("pliegue", Integer, nullable=False),
    Column("sensibilidad", Float, nullable=True),
    Column("especificidad", Float, nullable=True),
    Column("precision", Float, nullable=True),
    Column("f1", Float, nullable=True),
    Column("auc", Float, nullable=True),
    Column("vp", Integer, nullable=True),
    Column("vn", Integer, nullable=True),
    Column("fp", Integer, nullable=True),
    Column("fn", Integer, nullable=True),
    Index("ix_metricas_pliegue_entrenamiento", "entrenamiento_id"),
)

hecho_prediccion = Table(
    "hecho_prediccion", metadata,
    Column("prediccion_id", Integer, primary_key=True, autoincrement=True),
    Column("paciente_id", Integer, ForeignKey("dim_paciente.paciente_id"), nullable=True),
    Column("fecha_id", Integer, ForeignKey("dim_fecha.fecha_id"), nullable=False),
    Column("usuario_id", Integer, ForeignKey("usuarios.usuario_id"), nullable=True),
    Column("modelo_id", Integer, ForeignKey("dim_modelo.modelo_id"), nullable=False),
    Column("diagnostico_predicho_id", Integer, ForeignKey("dim_diagnostico.diagnostico_id"), nullable=False),
    Column("diagnostico_confirmado_id", Integer, ForeignKey("dim_diagnostico.diagnostico_id"), nullable=True),
    Column("origen", Unicode(10), nullable=False),
    Column("probabilidad_tumor", Float, nullable=False),
    Column("umbral", Float, nullable=False),
    Column("tipo_probable", Unicode(20), nullable=True),
    Column("probabilidad_tipo", Float, nullable=True),
    Column("de_acuerdo", Boolean, nullable=True),
    Column("tiempo_respuesta_ms", Float, nullable=True),
    Column("archivo_imagen", Unicode(300), nullable=True),
    Column("archivo_gradcam", Unicode(300), nullable=True),
    Column("creado_en", DateTime, nullable=False),
    Index("ix_hecho_usuario", "usuario_id"),
    Index("ix_hecho_fecha", "fecha_id"),
    Index("ix_hecho_modelo", "modelo_id"),
    Index("ix_hecho_origen", "origen"),
    Index("ix_hecho_creado", "creado_en"),
    Index("ix_hecho_paciente", "paciente_id"),
)

# Vistas (se crean con SQL; mismo texto para SQLite y SQL Server).
VISTAS = {
    "dim_usuario": """
        SELECT usuario_id, usuario, rol, activo FROM usuarios""",
    "vw_predicciones": """
        SELECT h.prediccion_id, h.origen, h.creado_en, f.fecha AS fecha, f.anio, f.mes, f.nombre_mes,
               f.semana, f.dia_semana, p.edad, p.grupo_edad, p.sexo, u.usuario AS doctor,
               m.nombre AS modelo, m.tipo AS tipo_modelo, m.version AS modelo_version,
               m.estado AS estado_modelo, dp.clave AS diagnostico_predicho, dp.es_tumor AS predicho_tumor,
               dc.clave AS diagnostico_confirmado, dc.es_tumor AS confirmado_tumor,
               h.probabilidad_tumor, h.umbral, h.tipo_probable, h.probabilidad_tipo, h.de_acuerdo,
               h.tiempo_respuesta_ms,
               CASE WHEN dc.diagnostico_id IS NULL THEN NULL
                    WHEN dp.es_tumor = dc.es_tumor THEN 1 ELSE 0 END AS acierto,
               CASE WHEN dc.diagnostico_id IS NULL THEN NULL
                    WHEN dp.es_tumor = 0 AND dc.es_tumor = 1 THEN 1 ELSE 0 END AS falso_negativo,
               CASE WHEN dc.diagnostico_id IS NULL THEN NULL
                    WHEN dp.es_tumor = 1 AND dc.es_tumor = 0 THEN 1 ELSE 0 END AS falso_positivo
        FROM hecho_prediccion h
        JOIN dim_fecha f ON f.fecha_id = h.fecha_id
        JOIN dim_modelo m ON m.modelo_id = h.modelo_id
        JOIN dim_diagnostico dp ON dp.diagnostico_id = h.diagnostico_predicho_id
        LEFT JOIN dim_diagnostico dc ON dc.diagnostico_id = h.diagnostico_confirmado_id
        LEFT JOIN dim_paciente p ON p.paciente_id = h.paciente_id
        LEFT JOIN usuarios u ON u.usuario_id = h.usuario_id""",
    "vw_bitacora": """
        SELECT evento_id, fecha_hora, usuario, rol, accion, detalle, exito FROM bitacora""",
    "vw_modelos": """
        SELECT modelo_id, nombre, tipo, version, estado, umbral, sensibilidad, especificidad, f1, auc,
               origen_metricas, entrenamiento_id, aprobado_en, creado_en FROM dim_modelo""",
    "vw_entrenamientos": """
        SELECT e.entrenamiento_id, e.estado, e.epocas_max, e.epoca_actual, e.mejor_epoca, e.diagnostico,
               e.iniciado_en, e.terminado_en, m.version AS version, u.usuario AS solicitado_por
        FROM entrenamientos e
        LEFT JOIN dim_modelo m ON m.modelo_id = e.modelo_id
        LEFT JOIN usuarios u ON u.usuario_id = e.solicitado_por""",
    "vw_metricas_pliegue": """
        SELECT mp.entrenamiento_id, m.nombre AS modelo, m.version AS modelo_version, mp.pliegue,
               mp.sensibilidad, mp.especificidad, mp."precision", mp.f1, mp.auc, mp.vp, mp.vn, mp.fp, mp.fn
        FROM metricas_pliegue mp
        LEFT JOIN dim_modelo m ON m.modelo_id = mp.modelo_id""",
    "vw_historial_epocas": """
        SELECT entrenamiento_id, etapa, epoca, perdida, exactitud, perdida_val, exactitud_val,
               tasa_aprendizaje FROM historial_epocas""",
    # Matriz de confusión por versión de modelo y origen, sobre los casos con diagnóstico confirmado.
    "vw_metricas_modelo": """
        SELECT m.modelo_id, m.nombre AS modelo, m.tipo AS tipo_modelo, m.version AS modelo_version,
               m.estado AS estado_modelo, h.origen,
               COUNT(*) AS casos,
               SUM(CASE WHEN dp.es_tumor = 1 AND dc.es_tumor = 1 THEN 1 ELSE 0 END) AS vp,
               SUM(CASE WHEN dp.es_tumor = 0 AND dc.es_tumor = 0 THEN 1 ELSE 0 END) AS vn,
               SUM(CASE WHEN dp.es_tumor = 1 AND dc.es_tumor = 0 THEN 1 ELSE 0 END) AS fp,
               SUM(CASE WHEN dp.es_tumor = 0 AND dc.es_tumor = 1 THEN 1 ELSE 0 END) AS fn,
               AVG(h.tiempo_respuesta_ms) AS tiempo_promedio_ms
        FROM hecho_prediccion h
        JOIN dim_modelo m ON m.modelo_id = h.modelo_id
        JOIN dim_diagnostico dp ON dp.diagnostico_id = h.diagnostico_predicho_id
        JOIN dim_diagnostico dc ON dc.diagnostico_id = h.diagnostico_confirmado_id
        GROUP BY m.modelo_id, m.nombre, m.tipo, m.version, m.estado, h.origen""",
    # Estudios de uso por semana ISO (de la fecha del estudio) y doctor, sin datos del paciente.
    "vw_estudios_semana": """
        SELECT f.anio, f.semana, MIN(f.fecha) AS primer_dia, u.usuario AS doctor,
               COUNT(*) AS estudios,
               SUM(CASE WHEN dp.es_tumor = 1 THEN 1 ELSE 0 END) AS con_posible_tumor,
               SUM(CASE WHEN h.diagnostico_confirmado_id IS NOT NULL THEN 1 ELSE 0 END) AS confirmados,
               SUM(CASE WHEN h.de_acuerdo = 0 THEN 1 ELSE 0 END) AS desacuerdos
        FROM hecho_prediccion h
        JOIN dim_fecha f ON f.fecha_id = h.fecha_id
        JOIN dim_diagnostico dp ON dp.diagnostico_id = h.diagnostico_predicho_id
        LEFT JOIN usuarios u ON u.usuario_id = h.usuario_id
        WHERE h.origen = 'uso'
        GROUP BY f.anio, f.semana, u.usuario""",
}

# Tablas y vistas que puede leer el asistente de consultas (Fase 5): sin hashes ni identificadores.
# La descripción de columnas está en app/backend/asistente.py (ESQUEMA); una prueba verifica que
# coincida con las columnas reales.
LISTA_BLANCA_ASISTENTE = ["vw_predicciones", "vw_estudios_semana", "vw_metricas_modelo", "vw_modelos",
                          "vw_entrenamientos", "vw_metricas_pliegue", "vw_historial_epocas", "vw_bitacora",
                          "dim_fecha", "dim_diagnostico", "dim_usuario"]
