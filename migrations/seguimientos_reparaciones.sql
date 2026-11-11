-- INFORBAXE: seguimiento privado de reparaciones. Ejecutar una vez en Supabase SQL Editor.
CREATE TABLE IF NOT EXISTS public.seguimientos_reparacion (
 id BIGSERIAL PRIMARY KEY,
 id_cliente BIGINT NOT NULL REFERENCES public.clientes(id) ON DELETE CASCADE,
 equipo TEXT NOT NULL,
 trabajo TEXT NOT NULL DEFAULT '',
 estado TEXT NOT NULL DEFAULT 'pieza_en_camino' CHECK (estado IN ('pieza_en_camino','reparando','reparacion_acabada')),
 activo BOOLEAN NOT NULL DEFAULT FALSE,
 token_hash TEXT UNIQUE,
 foto_path TEXT,
 fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 fecha_actualizacion TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 fecha_finalizacion TIMESTAMPTZ,
 fecha_caducidad TIMESTAMPTZ,
 fecha_foto_eliminada TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_seguimientos_cliente_fecha ON public.seguimientos_reparacion(id_cliente,fecha_creacion DESC);
CREATE INDEX IF NOT EXISTS idx_seguimientos_caducidad ON public.seguimientos_reparacion(fecha_caducidad) WHERE foto_path IS NOT NULL;
ALTER TABLE public.seguimientos_reparacion ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS seguimientos_service_role_all ON public.seguimientos_reparacion;
CREATE POLICY seguimientos_service_role_all ON public.seguimientos_reparacion FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
INSERT INTO storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
VALUES('inforbaxe-seguimientos','inforbaxe-seguimientos',FALSE,5242880,ARRAY['image/jpeg'])
ON CONFLICT(id) DO UPDATE SET public=FALSE,file_size_limit=5242880,allowed_mime_types=ARRAY['image/jpeg'];