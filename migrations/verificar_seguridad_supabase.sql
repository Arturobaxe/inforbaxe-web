-- Solo lectura: auditoría de permisos/RLS en INFORBAXE Supabase.
SELECT tablename FROM pg_tables WHERE schemaname='public' AND NOT rowsecurity;
SELECT tablename,policyname,roles,cmd FROM pg_policies
 WHERE schemaname IN ('public','storage') AND roles && ARRAY['public','anon','authenticated']::name[];
SELECT grantee,table_name,privilege_type FROM information_schema.role_table_grants
 WHERE table_schema='public' AND grantee IN ('anon','authenticated');
SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='public' AND p.prokind='f'
 AND (has_function_privilege('anon',p.oid,'execute') OR has_function_privilege('authenticated',p.oid,'execute'));
SELECT id,public FROM storage.buckets WHERE public;
SELECT table_name FROM information_schema.role_table_grants WHERE table_schema='public'
 AND grantee IN ('anon','authenticated')
 AND table_name IN (SELECT viewname FROM pg_views WHERE schemaname='public');
-- Inventario informativo de funciones privilegiadas (revisar una a una).
SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='public' AND p.prosecdef;
