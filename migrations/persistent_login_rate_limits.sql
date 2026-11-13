-- INFORBAXE: límites persistentes para contraseña y verificación 2FA.
-- La migración equivalente ya está aplicada en producción.
CREATE TABLE public.inforbaxe_rate_limits (
    rate_key text PRIMARY KEY,
    window_started_at timestamptz NOT NULL,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX inforbaxe_rate_limits_updated_at_idx
    ON public.inforbaxe_rate_limits (updated_at);

ALTER TABLE public.inforbaxe_rate_limits ENABLE ROW LEVEL SECURITY;

CREATE POLICY inforbaxe_rate_limits_service_role_all
    ON public.inforbaxe_rate_limits
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

REVOKE ALL PRIVILEGES ON TABLE public.inforbaxe_rate_limits
    FROM PUBLIC, anon, authenticated;
GRANT ALL PRIVILEGES ON TABLE public.inforbaxe_rate_limits
    TO service_role;

CREATE OR REPLACE FUNCTION public.inforbaxe_rate_limit(
    p_rate_key text,
    p_limit integer,
    p_window_seconds integer,
    p_increment boolean DEFAULT false,
    p_reset boolean DEFAULT false
)
RETURNS TABLE (
    blocked boolean,
    retry_after integer,
    attempt_count integer
)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
DECLARE
    v_started_at timestamptz;
    v_attempts integer;
BEGIN
    IF p_rate_key IS NULL OR length(p_rate_key) < 16 OR length(p_rate_key) > 128 THEN
        RAISE EXCEPTION 'Invalid rate limit key';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 1000 THEN
        RAISE EXCEPTION 'Invalid rate limit';
    END IF;
    IF p_window_seconds IS NULL OR p_window_seconds < 1 OR p_window_seconds > 86400 THEN
        RAISE EXCEPTION 'Invalid rate limit window';
    END IF;

    IF p_reset THEN
        DELETE FROM public.inforbaxe_rate_limits AS rl
        WHERE rl.rate_key = p_rate_key;
        RETURN QUERY SELECT false, 0, 0;
        RETURN;
    END IF;

    INSERT INTO public.inforbaxe_rate_limits AS current_window
        (rate_key, window_started_at, attempts, updated_at)
    VALUES
        (p_rate_key, pg_catalog.clock_timestamp(), 0, pg_catalog.clock_timestamp())
    ON CONFLICT (rate_key) DO UPDATE
    SET
        window_started_at = CASE
            WHEN current_window.window_started_at
                 + pg_catalog.make_interval(secs => p_window_seconds::double precision)
                 <= pg_catalog.clock_timestamp()
            THEN pg_catalog.clock_timestamp()
            ELSE current_window.window_started_at
        END,
        attempts = CASE
            WHEN current_window.window_started_at
                 + pg_catalog.make_interval(secs => p_window_seconds::double precision)
                 <= pg_catalog.clock_timestamp()
            THEN 0
            ELSE current_window.attempts
        END,
        updated_at = pg_catalog.clock_timestamp()
    RETURNING current_window.window_started_at, current_window.attempts
    INTO v_started_at, v_attempts;

    IF p_increment THEN
        UPDATE public.inforbaxe_rate_limits AS rl
        SET attempts = rl.attempts + 1,
            updated_at = pg_catalog.clock_timestamp()
        WHERE rl.rate_key = p_rate_key
        RETURNING rl.attempts INTO v_attempts;
    END IF;

    IF pg_catalog.random() < 0.01 THEN
        DELETE FROM public.inforbaxe_rate_limits AS rl
        WHERE rl.updated_at < pg_catalog.clock_timestamp() - interval '1 day';
    END IF;

    RETURN QUERY
    SELECT
        (v_attempts >= p_limit),
        GREATEST(
            0,
            CEIL(EXTRACT(EPOCH FROM (
                v_started_at
                + pg_catalog.make_interval(secs => p_window_seconds::double precision)
                - pg_catalog.clock_timestamp()
            )))::integer
        ),
        v_attempts;
END;
$function$;

REVOKE ALL PRIVILEGES ON FUNCTION public.inforbaxe_rate_limit(text, integer, integer, boolean, boolean)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.inforbaxe_rate_limit(text, integer, integer, boolean, boolean)
    TO service_role;
