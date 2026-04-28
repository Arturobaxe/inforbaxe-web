-- ================================================================
-- AÑADIR A TU SUPABASE — Ejecuta esto en SQL Editor
-- ================================================================

-- Tabla presupuestos (NUEVA)
CREATE TABLE IF NOT EXISTS presupuestos (
    id           BIGSERIAL PRIMARY KEY,
    id_cliente   BIGINT REFERENCES clientes(id) ON DELETE SET NULL,
    fecha        DATE NOT NULL DEFAULT CURRENT_DATE,
    productos    JSONB DEFAULT '[]',
    total_pvp    NUMERIC(10,2) DEFAULT 0,
    total_benef  NUMERIC(10,2) DEFAULT 0,
    estado       TEXT DEFAULT 'pendiente',  -- pendiente / aceptado / rechazado
    notas        TEXT DEFAULT '',
    validez_dias INTEGER DEFAULT 30,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_presup_cliente ON presupuestos(id_cliente);
CREATE INDEX IF NOT EXISTS idx_presup_fecha   ON presupuestos(fecha DESC);

ALTER TABLE presupuestos ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all" ON presupuestos FOR ALL USING (true);


-- ================================================================
-- MIGRACIÓN DESDE SHEETS — 25 clientes
-- Pega esto también en SQL Editor de Supabase
-- Ajusta los datos si difieren de tu hoja
-- ================================================================

INSERT INTO clientes (nombre, email, telefono, notas, activo) VALUES
('Nombre Cliente 1', '', '', 'Importado desde Sheets', true),
('Nombre Cliente 2', '', '', 'Importado desde Sheets', true)
-- IMPORTANTE: Sustituye estas filas con tus datos reales de Sheets.
-- Formato: ('Nombre', 'email@ejemplo.com', '600000000', 'notas', true)
-- 
-- Para exportar fácil desde tu hoja de Sheets:
-- 1. Abre tu Google Sheet
-- 2. En la celda vacía pon esta fórmula para generar el SQL:
--    ="('"&A2&"', '"&B2&"', '"&C2&"', 'Importado', true),"
--    (ajusta A2/B2/C2 a las columnas de nombre/email/teléfono)
-- 3. Copia las filas generadas y pégalas aquí
ON CONFLICT DO NOTHING;
