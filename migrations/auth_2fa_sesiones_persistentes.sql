-- INFORBAXE: códigos 2FA persistentes y sesiones revocables.
-- Idempotente. Aplicar manualmente después de desplegar el código.
CREATE TABLE IF NOT EXISTS public.inforbaxe_2fa_codes (
 sid_hash text PRIMARY KEY, code_hash text NOT NULL, expires_at timestamptz NOT NULL,
 attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.inforbaxe_auth_sessions (
 sid_hash text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL, revoked_at timestamptz
);
CREATE INDEX IF NOT EXISTS inforbaxe_2fa_codes_expires_idx ON public.inforbaxe_2fa_codes(expires_at);
CREATE INDEX IF NOT EXISTS inforbaxe_auth_sessions_expires_idx ON public.inforbaxe_auth_sessions(expires_at);
ALTER TABLE public.inforbaxe_2fa_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.inforbaxe_auth_sessions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS inforbaxe_2fa_codes_service_role_all ON public.inforbaxe_2fa_codes;
CREATE POLICY inforbaxe_2fa_codes_service_role_all ON public.inforbaxe_2fa_codes FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS inforbaxe_auth_sessions_service_role_all ON public.inforbaxe_auth_sessions;
CREATE POLICY inforbaxe_auth_sessions_service_role_all ON public.inforbaxe_auth_sessions FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL PRIVILEGES ON TABLE public.inforbaxe_2fa_codes, public.inforbaxe_auth_sessions FROM PUBLIC, anon, authenticated;
GRANT ALL PRIVILEGES ON TABLE public.inforbaxe_2fa_codes, public.inforbaxe_auth_sessions TO service_role;

-- UPSERT conserva attempts al reenviar; solo renueva hash y caducidad.
CREATE OR REPLACE FUNCTION public.inforbaxe_2fa_store(p_sid_hash text,p_code_hash text,p_ttl_seconds integer)
RETURNS void LANGUAGE plpgsql SET search_path = '' AS $function$
BEGIN
 DELETE FROM public.inforbaxe_2fa_codes WHERE expires_at < pg_catalog.now();
 INSERT INTO public.inforbaxe_2fa_codes(sid_hash,code_hash,expires_at,attempts)
 VALUES(p_sid_hash,p_code_hash,pg_catalog.now()+pg_catalog.make_interval(secs => p_ttl_seconds::double precision),0)
 ON CONFLICT(sid_hash) DO UPDATE SET code_hash=EXCLUDED.code_hash,
   expires_at=EXCLUDED.expires_at,created_at=pg_catalog.now();
END;
$function$;

CREATE OR REPLACE FUNCTION public.inforbaxe_2fa_verify(p_sid_hash text,p_code_hash text,p_max_attempts integer)
RETURNS text LANGUAGE plpgsql SET search_path = '' AS $function$
DECLARE v_row public.inforbaxe_2fa_codes%ROWTYPE;
BEGIN
 SELECT * INTO v_row FROM public.inforbaxe_2fa_codes WHERE sid_hash=p_sid_hash FOR UPDATE;
 IF NOT FOUND THEN RETURN 'missing'; END IF;
 IF v_row.expires_at < pg_catalog.now() THEN DELETE FROM public.inforbaxe_2fa_codes WHERE sid_hash=p_sid_hash; RETURN 'expired'; END IF;
 IF v_row.attempts >= p_max_attempts THEN DELETE FROM public.inforbaxe_2fa_codes WHERE sid_hash=p_sid_hash; RETURN 'locked'; END IF;
 IF v_row.code_hash=p_code_hash THEN DELETE FROM public.inforbaxe_2fa_codes WHERE sid_hash=p_sid_hash; RETURN 'ok'; END IF;
 UPDATE public.inforbaxe_2fa_codes SET attempts=attempts+1 WHERE sid_hash=p_sid_hash;
 IF v_row.attempts+1 >= p_max_attempts THEN DELETE FROM public.inforbaxe_2fa_codes WHERE sid_hash=p_sid_hash; RETURN 'locked'; END IF;
 RETURN 'invalid';
END;
$function$;

CREATE OR REPLACE FUNCTION public.inforbaxe_session_register(p_sid_hash text,p_ttl_seconds integer)
RETURNS void LANGUAGE plpgsql SET search_path = '' AS $function$
BEGIN
 DELETE FROM public.inforbaxe_auth_sessions WHERE expires_at < pg_catalog.now()-interval '1 day';
 INSERT INTO public.inforbaxe_auth_sessions(sid_hash,expires_at)
 VALUES(p_sid_hash,pg_catalog.now()+pg_catalog.make_interval(secs => p_ttl_seconds::double precision))
 ON CONFLICT(sid_hash) DO NOTHING;
END;
$function$;

CREATE OR REPLACE FUNCTION public.inforbaxe_session_check(p_sid_hash text)
RETURNS text LANGUAGE sql STABLE SET search_path = '' AS $function$
 SELECT COALESCE((SELECT CASE WHEN revoked_at IS NOT NULL OR expires_at < pg_catalog.now()
   THEN 'revoked' ELSE 'ok' END FROM public.inforbaxe_auth_sessions WHERE sid_hash=p_sid_hash),'missing');
$function$;

CREATE OR REPLACE FUNCTION public.inforbaxe_session_revoke(p_sid_hash text)
RETURNS void LANGUAGE sql SET search_path = '' AS $function$
 UPDATE public.inforbaxe_auth_sessions SET revoked_at=pg_catalog.now()
 WHERE sid_hash=p_sid_hash AND revoked_at IS NULL;
$function$;

CREATE OR REPLACE FUNCTION public.inforbaxe_session_revoke_all()
RETURNS integer LANGUAGE plpgsql SET search_path = '' AS $function$
DECLARE v_count integer;
BEGIN
 UPDATE public.inforbaxe_auth_sessions SET revoked_at=pg_catalog.now() WHERE revoked_at IS NULL;
 GET DIAGNOSTICS v_count=ROW_COUNT;
 RETURN v_count;
END;
$function$;

DO $$
DECLARE signature text;
BEGIN
 FOREACH signature IN ARRAY ARRAY[
  'public.inforbaxe_2fa_store(text,text,integer)','public.inforbaxe_2fa_verify(text,text,integer)',
  'public.inforbaxe_session_register(text,integer)','public.inforbaxe_session_check(text)',
  'public.inforbaxe_session_revoke(text)','public.inforbaxe_session_revoke_all()'
 ] LOOP
  EXECUTE format('REVOKE ALL PRIVILEGES ON FUNCTION %s FROM PUBLIC, anon, authenticated',signature);
  EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role',signature);
 END LOOP;
END $$;
