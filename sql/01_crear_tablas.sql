/* =====================================================================================
   01_crear_tablas.sql  -  Esquema en T-SQL para la SQL database de Microsoft Fabric
   (motor SQL Server). Equivale a app/backend/tablas.py (SQLAlchemy Core), que es el
   dueño del esquema; si cambia uno, se cambia el otro.

   Uso: ejecutar completo en el editor de consultas de Fabric (o con sqlcmd / SSMS con
   autenticación de Microsoft Entra ID). Es re-ejecutable: solo crea lo que falta y
   recrea las vistas con CREATE OR ALTER.
   Después: python sql/02_cargar_datos.py con DB_MODO=fabric en .env (carga dimensiones,
   modelos, resultados de prueba y la corrida original de v001).

   NOTA: este script no se ha podido ejecutar contra Fabric desde el equipo de desarrollo
   (no hay acceso al servidor); se probó el esquema equivalente en SQLite.
   ===================================================================================== */

/* ------------------------------------------------------------------ operación */
IF OBJECT_ID(N'dbo.usuarios', N'U') IS NULL
CREATE TABLE dbo.usuarios (
    usuario_id     INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_usuarios PRIMARY KEY,
    usuario        NVARCHAR(50)  NOT NULL CONSTRAINT uq_usuarios_usuario UNIQUE,
    hash_password  NVARCHAR(100) NOT NULL,
    rol            NVARCHAR(20)  NOT NULL CONSTRAINT ck_usuarios_rol CHECK (rol IN (N'doctor', N'administrador')),
    activo         BIT           NOT NULL CONSTRAINT df_usuarios_activo DEFAULT (1),
    creado_en      DATETIME2(0)  NOT NULL
);

IF OBJECT_ID(N'dbo.sesiones', N'U') IS NULL
CREATE TABLE dbo.sesiones (
    token_hash  NVARCHAR(64) NOT NULL CONSTRAINT pk_sesiones PRIMARY KEY,
    usuario_id  INT          NOT NULL CONSTRAINT fk_sesiones_usuario REFERENCES dbo.usuarios (usuario_id),
    creada_en   DATETIME2(0) NOT NULL,
    expira_en   DATETIME2(0) NOT NULL
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_sesiones_usuario')
    CREATE INDEX ix_sesiones_usuario ON dbo.sesiones (usuario_id);

IF OBJECT_ID(N'dbo.bitacora', N'U') IS NULL
CREATE TABLE dbo.bitacora (
    evento_id   INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_bitacora PRIMARY KEY,
    fecha_hora  DATETIME2(0)   NOT NULL,
    usuario_id  INT            NULL,
    usuario     NVARCHAR(50)   NULL,
    rol         NVARCHAR(20)   NULL,
    accion      NVARCHAR(40)   NOT NULL,
    detalle     NVARCHAR(1000) NULL,
    ip          NVARCHAR(45)   NULL,
    exito       BIT            NOT NULL
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_bitacora_fecha')
    CREATE INDEX ix_bitacora_fecha ON dbo.bitacora (fecha_hora);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_bitacora_accion')
    CREATE INDEX ix_bitacora_accion ON dbo.bitacora (accion);

/* ------------------------------------------------------------------ dimensiones */
IF OBJECT_ID(N'dbo.dim_paciente', N'U') IS NULL
CREATE TABLE dbo.dim_paciente (
    paciente_id    INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_dim_paciente PRIMARY KEY,
    identificador  NVARCHAR(20) NOT NULL CONSTRAINT uq_dim_paciente_identificador UNIQUE,  -- ficticio, p. ej. PAC-0001
    edad           INT          NULL,
    grupo_edad     NVARCHAR(10) NULL,
    sexo           NVARCHAR(10) NULL
);

IF OBJECT_ID(N'dbo.dim_fecha', N'U') IS NULL
CREATE TABLE dbo.dim_fecha (
    fecha_id    INT          NOT NULL CONSTRAINT pk_dim_fecha PRIMARY KEY,   -- AAAAMMDD
    fecha       DATE         NOT NULL,
    anio        INT          NOT NULL,
    mes         INT          NOT NULL,
    nombre_mes  NVARCHAR(15) NOT NULL,
    semana      INT          NOT NULL,                                       -- semana ISO
    dia_semana  NVARCHAR(15) NOT NULL
);

IF OBJECT_ID(N'dbo.dim_diagnostico', N'U') IS NULL
CREATE TABLE dbo.dim_diagnostico (
    diagnostico_id  INT          NOT NULL CONSTRAINT pk_dim_diagnostico PRIMARY KEY,
    clave           NVARCHAR(20) NOT NULL CONSTRAINT uq_dim_diagnostico_clave UNIQUE,
    nombre          NVARCHAR(60) NOT NULL,
    es_tumor        BIT          NOT NULL
);

IF OBJECT_ID(N'dbo.dim_modelo', N'U') IS NULL
CREATE TABLE dbo.dim_modelo (
    modelo_id         INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_dim_modelo PRIMARY KEY,
    nombre            NVARCHAR(100) NOT NULL,
    tipo              NVARCHAR(20)  NOT NULL CONSTRAINT ck_dim_modelo_tipo CHECK (tipo IN (N'clasico', N'red_keras')),
    version           NVARCHAR(40)  NOT NULL,
    estado            NVARCHAR(20)  NOT NULL CONSTRAINT ck_dim_modelo_estado
                          CHECK (estado IN (N'referencia', N'candidato', N'produccion', N'retirado')),
    umbral            FLOAT         NULL,
    entrenamiento_id  INT           NULL,     -- sin llave foránea para evitar la referencia circular
    sensibilidad      FLOAT         NULL,
    especificidad     FLOAT         NULL,
    f1                FLOAT         NULL,
    auc               FLOAT         NULL,
    origen_metricas   NVARCHAR(20)  NULL,     -- 'prueba' (clásicos) o 'validacion' (red)
    aprobado_en       DATETIME2(0)  NULL,     -- última vez que pasó a producción (para revertir)
    creado_en         DATETIME2(0)  NOT NULL,
    CONSTRAINT uq_dim_modelo_tipo_version UNIQUE (tipo, version)
);

/* ------------------------------------------------------------------ entrenamiento */
IF OBJECT_ID(N'dbo.entrenamientos', N'U') IS NULL
CREATE TABLE dbo.entrenamientos (
    entrenamiento_id  INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_entrenamientos PRIMARY KEY,
    modelo_id         INT            NULL CONSTRAINT fk_entrenamientos_modelo REFERENCES dbo.dim_modelo (modelo_id),
    estado            NVARCHAR(20)   NOT NULL CONSTRAINT ck_entrenamientos_estado
                          CHECK (estado IN (N'en_cola', N'corriendo', N'terminado', N'cancelado', N'error')),
    parametros        NVARCHAR(MAX)  NULL,    -- JSON
    etapa             NVARCHAR(30)   NULL,
    epoca_actual      INT            NULL,
    epocas_max        INT            NULL,
    progreso          FLOAT          NULL,    -- 0 a 1
    mensaje           NVARCHAR(500)  NULL,
    mejor_epoca       INT            NULL,
    diagnostico       NVARCHAR(40)   NULL,
    explicacion       NVARCHAR(MAX)  NULL,
    advertencias      NVARCHAR(MAX)  NULL,    -- JSON (lista)
    metricas          NVARCHAR(MAX)  NULL,    -- JSON (métricas en validación)
    matriz_confusion  NVARCHAR(200)  NULL,    -- JSON [[vn,fp],[fn,vp]]
    curvas            NVARCHAR(100)  NULL,
    pid               INT            NULL,
    iniciado_en       DATETIME2(0)   NULL,
    terminado_en      DATETIME2(0)   NULL,
    solicitado_por    INT            NULL CONSTRAINT fk_entrenamientos_usuario REFERENCES dbo.usuarios (usuario_id)
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_entrenamientos_estado')
    CREATE INDEX ix_entrenamientos_estado ON dbo.entrenamientos (estado);

IF OBJECT_ID(N'dbo.historial_epocas', N'U') IS NULL
CREATE TABLE dbo.historial_epocas (
    entrenamiento_id  INT          NOT NULL CONSTRAINT fk_historial_entrenamiento
                          REFERENCES dbo.entrenamientos (entrenamiento_id),
    etapa             NVARCHAR(30) NOT NULL,  -- pliegue_1..pliegue_5, cabeza, ajuste_fino
    epoca             INT          NOT NULL,
    perdida           FLOAT        NULL,
    exactitud         FLOAT        NULL,
    perdida_val       FLOAT        NULL,
    exactitud_val     FLOAT        NULL,
    tasa_aprendizaje  FLOAT        NULL,
    CONSTRAINT pk_historial_epocas PRIMARY KEY (entrenamiento_id, etapa, epoca)
);

IF OBJECT_ID(N'dbo.metricas_pliegue', N'U') IS NULL
CREATE TABLE dbo.metricas_pliegue (
    metrica_id        INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_metricas_pliegue PRIMARY KEY,
    entrenamiento_id  INT   NULL CONSTRAINT fk_metricas_entrenamiento REFERENCES dbo.entrenamientos (entrenamiento_id),
    modelo_id         INT   NULL CONSTRAINT fk_metricas_modelo REFERENCES dbo.dim_modelo (modelo_id),
    pliegue           INT   NOT NULL,
    sensibilidad      FLOAT NULL,
    especificidad     FLOAT NULL,
    [precision]       FLOAT NULL,
    f1                FLOAT NULL,
    auc               FLOAT NULL,
    vp INT NULL, vn INT NULL, fp INT NULL, fn INT NULL
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_metricas_pliegue_entrenamiento')
    CREATE INDEX ix_metricas_pliegue_entrenamiento ON dbo.metricas_pliegue (entrenamiento_id);

/* ------------------------------------------------------------------ hecho */
IF OBJECT_ID(N'dbo.hecho_prediccion', N'U') IS NULL
CREATE TABLE dbo.hecho_prediccion (
    prediccion_id              INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_hecho_prediccion PRIMARY KEY,
    paciente_id                INT  NULL CONSTRAINT fk_hecho_paciente REFERENCES dbo.dim_paciente (paciente_id),
    fecha_id                   INT  NOT NULL CONSTRAINT fk_hecho_fecha REFERENCES dbo.dim_fecha (fecha_id),  -- fecha del estudio
    usuario_id                 INT  NULL CONSTRAINT fk_hecho_usuario REFERENCES dbo.usuarios (usuario_id),
    modelo_id                  INT  NOT NULL CONSTRAINT fk_hecho_modelo REFERENCES dbo.dim_modelo (modelo_id),
    diagnostico_predicho_id    INT  NOT NULL CONSTRAINT fk_hecho_predicho REFERENCES dbo.dim_diagnostico (diagnostico_id),
    diagnostico_confirmado_id  INT  NULL CONSTRAINT fk_hecho_confirmado REFERENCES dbo.dim_diagnostico (diagnostico_id),
    origen                     NVARCHAR(10) NOT NULL CONSTRAINT ck_hecho_origen CHECK (origen IN (N'uso', N'prueba')),
    probabilidad_tumor         FLOAT NOT NULL,
    umbral                     FLOAT NOT NULL,
    tipo_probable              NVARCHAR(20) NULL,
    probabilidad_tipo          FLOAT NULL,
    de_acuerdo                 BIT NULL,
    tiempo_respuesta_ms        FLOAT NULL,
    archivo_imagen             NVARCHAR(300) NULL,
    archivo_gradcam            NVARCHAR(300) NULL,
    creado_en                  DATETIME2(0) NOT NULL
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_hecho_usuario')
    CREATE INDEX ix_hecho_usuario ON dbo.hecho_prediccion (usuario_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_hecho_fecha')
    CREATE INDEX ix_hecho_fecha ON dbo.hecho_prediccion (fecha_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_hecho_modelo')
    CREATE INDEX ix_hecho_modelo ON dbo.hecho_prediccion (modelo_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_hecho_origen')
    CREATE INDEX ix_hecho_origen ON dbo.hecho_prediccion (origen);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_hecho_creado')
    CREATE INDEX ix_hecho_creado ON dbo.hecho_prediccion (creado_en);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_hecho_paciente')
    CREATE INDEX ix_hecho_paciente ON dbo.hecho_prediccion (paciente_id);
GO

/* ------------------------------------------------------------------ datos fijos */
IF NOT EXISTS (SELECT 1 FROM dbo.dim_diagnostico)
INSERT INTO dbo.dim_diagnostico (diagnostico_id, clave, nombre, es_tumor) VALUES
    (1, N'sin_tumor',  N'Sin tumor', 0),
    (2, N'tumor',      N'Tumor (tipo no especificado)', 1),
    (3, N'glioma',     N'Glioma', 1),
    (4, N'meningioma', N'Meningioma', 1),
    (5, N'pituitary',  N'Tumor hipofisario', 1);

/* dim_fecha: 2025-01-01 a 2027-12-31 (nombres en español, sin depender de SET LANGUAGE). */
;WITH dias AS (
    SELECT CAST('2025-01-01' AS DATE) AS fecha
    UNION ALL
    SELECT DATEADD(DAY, 1, fecha) FROM dias WHERE fecha < '2027-12-31'
)
INSERT INTO dbo.dim_fecha (fecha_id, fecha, anio, mes, nombre_mes, semana, dia_semana)
SELECT YEAR(d.fecha) * 10000 + MONTH(d.fecha) * 100 + DAY(d.fecha), d.fecha, YEAR(d.fecha), MONTH(d.fecha),
       CHOOSE(MONTH(d.fecha), N'enero', N'febrero', N'marzo', N'abril', N'mayo', N'junio', N'julio', N'agosto',
              N'septiembre', N'octubre', N'noviembre', N'diciembre'),
       DATEPART(ISO_WEEK, d.fecha),
       -- 1900-01-01 fue lunes: el residuo da 0 = lunes ... 6 = domingo
       CHOOSE(DATEDIFF(DAY, '19000101', d.fecha) % 7 + 1, N'lunes', N'martes', N'miércoles', N'jueves',
              N'viernes', N'sábado', N'domingo')
FROM dias d
WHERE NOT EXISTS (SELECT 1 FROM dbo.dim_fecha f WHERE f.fecha = d.fecha)
OPTION (MAXRECURSION 2000);
GO

/* ------------------------------------------------------------------ vistas
   Sin hashes ni identificadores de paciente. Las usan Power BI y el asistente. */
CREATE OR ALTER VIEW dbo.dim_usuario AS
    SELECT usuario_id, usuario, rol, activo FROM dbo.usuarios;
GO
CREATE OR ALTER VIEW dbo.vw_predicciones AS
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
    FROM dbo.hecho_prediccion h
    JOIN dbo.dim_fecha f ON f.fecha_id = h.fecha_id
    JOIN dbo.dim_modelo m ON m.modelo_id = h.modelo_id
    JOIN dbo.dim_diagnostico dp ON dp.diagnostico_id = h.diagnostico_predicho_id
    LEFT JOIN dbo.dim_diagnostico dc ON dc.diagnostico_id = h.diagnostico_confirmado_id
    LEFT JOIN dbo.dim_paciente p ON p.paciente_id = h.paciente_id
    LEFT JOIN dbo.usuarios u ON u.usuario_id = h.usuario_id;
GO
CREATE OR ALTER VIEW dbo.vw_bitacora AS
    SELECT evento_id, fecha_hora, usuario, rol, accion, detalle, exito FROM dbo.bitacora;
GO
CREATE OR ALTER VIEW dbo.vw_modelos AS
    SELECT modelo_id, nombre, tipo, version, estado, umbral, sensibilidad, especificidad, f1, auc,
           origen_metricas, entrenamiento_id, aprobado_en, creado_en FROM dbo.dim_modelo;
GO
CREATE OR ALTER VIEW dbo.vw_entrenamientos AS
    SELECT e.entrenamiento_id, e.estado, e.epocas_max, e.epoca_actual, e.mejor_epoca, e.diagnostico,
           e.iniciado_en, e.terminado_en, m.version AS version, u.usuario AS solicitado_por
    FROM dbo.entrenamientos e
    LEFT JOIN dbo.dim_modelo m ON m.modelo_id = e.modelo_id
    LEFT JOIN dbo.usuarios u ON u.usuario_id = e.solicitado_por;
GO
CREATE OR ALTER VIEW dbo.vw_metricas_pliegue AS
    SELECT mp.entrenamiento_id, m.nombre AS modelo, m.version AS modelo_version, mp.pliegue,
           mp.sensibilidad, mp.especificidad, mp.[precision], mp.f1, mp.auc, mp.vp, mp.vn, mp.fp, mp.fn
    FROM dbo.metricas_pliegue mp
    LEFT JOIN dbo.dim_modelo m ON m.modelo_id = mp.modelo_id;
GO
CREATE OR ALTER VIEW dbo.vw_historial_epocas AS
    SELECT entrenamiento_id, etapa, epoca, perdida, exactitud, perdida_val, exactitud_val, tasa_aprendizaje
    FROM dbo.historial_epocas;
GO
/* Matriz de confusión por versión de modelo y origen (solo casos con diagnóstico confirmado). */
CREATE OR ALTER VIEW dbo.vw_metricas_modelo AS
    SELECT m.modelo_id, m.nombre AS modelo, m.tipo AS tipo_modelo, m.version AS modelo_version,
           m.estado AS estado_modelo, h.origen,
           COUNT(*) AS casos,
           SUM(CASE WHEN dp.es_tumor = 1 AND dc.es_tumor = 1 THEN 1 ELSE 0 END) AS vp,
           SUM(CASE WHEN dp.es_tumor = 0 AND dc.es_tumor = 0 THEN 1 ELSE 0 END) AS vn,
           SUM(CASE WHEN dp.es_tumor = 1 AND dc.es_tumor = 0 THEN 1 ELSE 0 END) AS fp,
           SUM(CASE WHEN dp.es_tumor = 0 AND dc.es_tumor = 1 THEN 1 ELSE 0 END) AS fn,
           AVG(h.tiempo_respuesta_ms) AS tiempo_promedio_ms
    FROM dbo.hecho_prediccion h
    JOIN dbo.dim_modelo m ON m.modelo_id = h.modelo_id
    JOIN dbo.dim_diagnostico dp ON dp.diagnostico_id = h.diagnostico_predicho_id
    JOIN dbo.dim_diagnostico dc ON dc.diagnostico_id = h.diagnostico_confirmado_id
    GROUP BY m.modelo_id, m.nombre, m.tipo, m.version, m.estado, h.origen;
GO
/* Estudios de uso por semana ISO (fecha del estudio) y doctor; sin datos del paciente. */
CREATE OR ALTER VIEW dbo.vw_estudios_semana AS
    SELECT f.anio, f.semana, MIN(f.fecha) AS primer_dia, u.usuario AS doctor,
           COUNT(*) AS estudios,
           SUM(CASE WHEN dp.es_tumor = 1 THEN 1 ELSE 0 END) AS con_posible_tumor,
           SUM(CASE WHEN h.diagnostico_confirmado_id IS NOT NULL THEN 1 ELSE 0 END) AS confirmados,
           SUM(CASE WHEN h.de_acuerdo = 0 THEN 1 ELSE 0 END) AS desacuerdos
    FROM dbo.hecho_prediccion h
    JOIN dbo.dim_fecha f ON f.fecha_id = h.fecha_id
    JOIN dbo.dim_diagnostico dp ON dp.diagnostico_id = h.diagnostico_predicho_id
    LEFT JOIN dbo.usuarios u ON u.usuario_id = h.usuario_id
    WHERE h.origen = N'uso'
    GROUP BY f.anio, f.semana, u.usuario;
GO

/* ------------------------------------------------------------------ asistente: solo lectura
   El asistente ejecuta sus consultas con un usuario de SOLO LECTURA. En Fabric, crear un usuario
   de Microsoft Entra ID para la app del asistente y darle lectura únicamente sobre las vistas de
   la lista blanca (no sobre las tablas ni sobre usuarios/sesiones). Ejemplo (ajustar el nombre):

   CREATE USER [asistente-tumores@dominio] FROM EXTERNAL PROVIDER;
   GRANT SELECT ON dbo.vw_predicciones     TO [asistente-tumores@dominio];
   GRANT SELECT ON dbo.vw_estudios_semana  TO [asistente-tumores@dominio];
   GRANT SELECT ON dbo.vw_metricas_modelo  TO [asistente-tumores@dominio];
   GRANT SELECT ON dbo.vw_modelos          TO [asistente-tumores@dominio];
   GRANT SELECT ON dbo.vw_entrenamientos   TO [asistente-tumores@dominio];
   GRANT SELECT ON dbo.vw_metricas_pliegue TO [asistente-tumores@dominio];
   GRANT SELECT ON dbo.vw_historial_epocas TO [asistente-tumores@dominio];
   GRANT SELECT ON dbo.vw_bitacora         TO [asistente-tumores@dominio];
   GRANT SELECT ON dbo.dim_fecha           TO [asistente-tumores@dominio];
   GRANT SELECT ON dbo.dim_diagnostico     TO [asistente-tumores@dominio];
   GRANT SELECT ON dbo.dim_usuario         TO [asistente-tumores@dominio];
   (Alternativa más amplia: ALTER ROLE db_datareader ADD MEMBER [...]; la lista blanca de la
   aplicación sigue limitando qué vistas puede consultar.)
   ------------------------------------------------------------------ */
