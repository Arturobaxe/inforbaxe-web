-- ================================================================
-- INFORBAXE - Supabase SQL Schema
-- Ejecuta esto en el SQL Editor de tu proyecto Supabase
-- ================================================================

-- Clientes
CREATE TABLE IF NOT EXISTS clientes (
    id          BIGSERIAL PRIMARY KEY,
    nombre      TEXT NOT NULL,
    email       TEXT DEFAULT '',
    telefono    TEXT DEFAULT '',
    activo      BOOLEAN DEFAULT TRUE,
    fecha_alta  DATE DEFAULT CURRENT_DATE,
    notas       TEXT DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Productos
CREATE TABLE IF NOT EXISTS productos (
    id         BIGSERIAL PRIMARY KEY,
    nombre     TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Ventas
CREATE TABLE IF NOT EXISTS ventas (
    id           BIGSERIAL PRIMARY KEY,
    id_cliente   BIGINT REFERENCES clientes(id) ON DELETE SET NULL,
    fecha        DATE NOT NULL DEFAULT CURRENT_DATE,
    productos    JSONB DEFAULT '[]',
    suma_coste   NUMERIC(10,2) DEFAULT 0,
    total_benef  NUMERIC(10,2) DEFAULT 0,
    total_pvp    NUMERIC(10,2) DEFAULT 0,
    metodo_pago  TEXT DEFAULT 'Efectivo',
    pagado       TEXT DEFAULT 'Sí',
    comentarios  TEXT DEFAULT '',
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Mensualidades
CREATE TABLE IF NOT EXISTS mensualidades (
    id          BIGSERIAL PRIMARY KEY,
    id_cliente  BIGINT REFERENCES clientes(id) ON DELETE CASCADE,
    concepto    TEXT NOT NULL,
    importe     NUMERIC(10,2) NOT NULL,
    mes         TEXT NOT NULL,         -- formato YYYY-MM
    pagado      TEXT DEFAULT 'No',
    fecha_pago  DATE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(id_cliente, concepto, mes)
);

-- Citas
CREATE TABLE IF NOT EXISTS citas (
    id            BIGSERIAL PRIMARY KEY,
    id_cliente    BIGINT REFERENCES clientes(id) ON DELETE CASCADE,
    fecha         DATE NOT NULL,
    hora          TIME NOT NULL,
    observaciones TEXT DEFAULT '',
    estado        TEXT DEFAULT 'pendiente',  -- pendiente / completada / cancelada
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para búsquedas frecuentes
CREATE INDEX IF NOT EXISTS idx_ventas_fecha      ON ventas(fecha DESC);
CREATE INDEX IF NOT EXISTS idx_ventas_cliente    ON ventas(id_cliente);
CREATE INDEX IF NOT EXISTS idx_mensual_cliente   ON mensualidades(id_cliente);
CREATE INDEX IF NOT EXISTS idx_mensual_mes       ON mensualidades(mes);
CREATE INDEX IF NOT EXISTS idx_citas_fecha       ON citas(fecha);
CREATE INDEX IF NOT EXISTS idx_citas_cliente     ON citas(id_cliente);

-- Habilitar Row Level Security (opcional pero recomendado)
ALTER TABLE clientes      ENABLE ROW LEVEL SECURITY;
ALTER TABLE ventas        ENABLE ROW LEVEL SECURITY;
ALTER TABLE mensualidades ENABLE ROW LEVEL SECURITY;
ALTER TABLE citas         ENABLE ROW LEVEL SECURITY;
ALTER TABLE productos     ENABLE ROW LEVEL SECURITY;

-- Políticas permisivas para service_role (el backend usa service_role key)
CREATE POLICY "service_role_all" ON clientes      FOR ALL USING (true);
CREATE POLICY "service_role_all" ON ventas        FOR ALL USING (true);
CREATE POLICY "service_role_all" ON mensualidades FOR ALL USING (true);
CREATE POLICY "service_role_all" ON citas         FOR ALL USING (true);
CREATE POLICY "service_role_all" ON productos     FOR ALL USING (true);
