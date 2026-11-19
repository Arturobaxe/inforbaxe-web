import os
import unittest
from unittest import mock

import app as A
import auth
import datos_sensibles
import despiece_inteligente as d


class SecurityHelpersTests(unittest.TestCase):
    def test_number_helper_rejects_nonfinite_and_unbounded_values(self):
        self.assertIsNone(A._bounded_number("NaN"))
        self.assertIsNone(A._bounded_number("Infinity"))
        self.assertIsNone(A._bounded_number("1e99"))
        self.assertEqual(A._bounded_number("12,345"), 12.35)

    def test_products_are_bounded_and_discounts_remain_possible(self):
        rows = A._sanitizar_productos([
            {"nombre": " Pantalla ", "coste": "NaN", "pvp": "1e99",
             "cantidad": "-5", "beneficio": "-10,5", "extra": float("inf")},
            "not a dict", {"cantidad": 50000}
        ] + [{}] * 300)
        self.assertEqual(rows[0]["nombre"], "Pantalla")
        self.assertEqual(rows[0]["coste"], 0.0)
        self.assertEqual(rows[0]["pvp"], 0.0)
        self.assertEqual(rows[0]["cantidad"], 1)
        self.assertEqual(rows[0]["beneficio"], -10.5)
        self.assertNotIn("extra", rows[0])
        self.assertEqual(rows[1]["cantidad"], 50000)
        self.assertLessEqual(len(rows), 200)
        self.assertEqual(A._sanitizar_productos("bad"), [])

    def test_cipher_encrypts_and_keeps_legacy_plaintext_readable(self):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        with mock.patch.dict(os.environ, {"DATA_ENCRYPTION_KEY": key}):
            encrypted = datos_sensibles.cifrar("PIN-1234")
            self.assertTrue(encrypted.startswith(datos_sensibles.PREFIX))
            self.assertEqual(datos_sensibles.descifrar(encrypted), "PIN-1234")
            self.assertEqual(datos_sensibles.descifrar("legacy"), "legacy")

    def test_cipher_fails_closed_without_key_or_with_wrong_key(self):
        from cryptography.fernet import Fernet
        first, second = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with mock.patch.dict(os.environ, {"DATA_ENCRYPTION_KEY": first}):
            encrypted = datos_sensibles.cifrar("patron")
        with mock.patch.dict(os.environ, {"DATA_ENCRYPTION_KEY": ""}):
            with self.assertRaises(datos_sensibles.SensitiveDataError):
                datos_sensibles.descifrar(encrypted)
        with mock.patch.dict(os.environ, {"DATA_ENCRYPTION_KEY": second}):
            with self.assertRaises(datos_sensibles.SensitiveDataError):
                datos_sensibles.descifrar(encrypted)

    def test_fernet_rotation_reads_previous_key(self):
        from cryptography.fernet import Fernet
        old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with mock.patch.dict(os.environ, {"DATA_ENCRYPTION_KEY": old}):
            encrypted = datos_sensibles.cifrar("patrón")
        with mock.patch.dict(os.environ, {"DATA_ENCRYPTION_KEY": f"{new},{old}"}):
            self.assertEqual(datos_sensibles.descifrar(encrypted), "patrón")
            self.assertEqual(datos_sensibles.descifrar(datos_sensibles.cifrar("nuevo")), "nuevo")

    def test_search_engines_are_allowed_but_private_dns_is_rejected(self):
        public_info = [(2, 1, 6, "", ("93.184.216.34", 443))]
        with mock.patch("socket.getaddrinfo", return_value=public_info):
            for url in (
                "https://www.google.com/search?q=pieza", "https://www.bing.com/search?q=pieza",
                "https://lite.duckduckgo.com/lite/?q=pieza", "https://search.yahoo.com/search?p=pieza",
                "https://www.mojeek.com/search?q=pieza"
            ):
                d._validate_external_target(url)
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("169.254.169.254", 443))]):
            with self.assertRaises(ValueError):
                d._validate_external_target("https://www.bing.com/")

    def test_non_allowlisted_hosts_and_non_https_are_rejected(self):
        public_info = [(2, 1, 6, "", ("93.184.216.34", 443))]
        with mock.patch("socket.getaddrinfo", return_value=public_info):
            for url in ("http://www.bing.com/", "https://evil.example/", "https://www.bing.com:8443/",
                        "https://user:pw@www.bing.com/", "https://www.bing.com.evil.example/"):
                with self.assertRaises(ValueError, msg=url):
                    d._validate_external_target(url)

    def test_pinned_connection_uses_ip_and_original_tls_hostname(self):
        info = [(2, 1, 6, "", ("93.184.216.34", 443))]
        conn = d._PinnedHTTPSConnection("www.bing.com", 443, timeout=3)
        fake_context = mock.MagicMock()
        sock = mock.MagicMock()
        with mock.patch.object(d.socket, "getaddrinfo", return_value=info) as dns, \
             mock.patch.object(d.socket, "create_connection", return_value=sock) as connect, \
             mock.patch.object(conn, "_context", fake_context):
            conn.connect()
        self.assertEqual(dns.call_count, 1)
        self.assertEqual(connect.call_args.args[0], ("93.184.216.34", 443))
        self.assertEqual(fake_context.wrap_socket.call_args.kwargs["server_hostname"], "www.bing.com")

    def test_templates_keep_animations_and_safe_data_attributes(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        base = (root / "templates/base.html").read_text(encoding="utf-8")
        sales = (root / "templates/ventas.html").read_text(encoding="utf-8")
        form = (root / "templates/venta_form.html").read_text(encoding="utf-8")
        citas = (root / "templates/citas.html").read_text(encoding="utf-8")
        products = (root / "templates/productos.html").read_text(encoding="utf-8")
        links = (root / "templates/enlaces_activos.html").read_text(encoding="utf-8")
        self.assertIn("saleConfettiFall", base)
        self.assertIn("saleCreated", base)
        self.assertIn("celebrarPago", sales)
        self.assertIn("moneyFloat", sales)
        self.assertIn("equipo_contrasena", form)
        self.assertIn("includes(el.name)", form)
        self.assertIn("data-msg=", citas)
        self.assertIn("data-msg=", products)
        self.assertIn("data-nombre=", links)

    def test_external_scripts_and_styles_have_sri(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        for path in (
            "templates/base.html", "templates/ventas.html", "templates/dashboard.html",
            "templates/estadisticas.html", "templates/averias_frecuentes.html"
        ):
            for line in (root / path).read_text(encoding="utf-8").splitlines():
                if ("cdn.jsdelivr.net" in line or "cdnjs.cloudflare.com" in line) and ("<script" in line or "<link" in line):
                    self.assertIn("integrity=", line, f"{path}: {line}")


class AuthMemoryFallbackTests(unittest.TestCase):
    def setUp(self):
        auth._codigos.clear()

    def test_resend_does_not_reset_attempts_and_codes_are_single_use(self):
        with A.app.app_context(), mock.patch.object(auth, "_rpc", side_effect=RuntimeError("migration not applied")):
            auth.guardar_codigo("sid-test", "123456")
            for _ in range(4):
                auth.verificar_codigo("sid-test", "000000")
            auth.guardar_codigo("sid-test", "654321")
            for _ in range(3):
                auth.verificar_codigo("sid-test", "000000")
            self.assertEqual(auth.verificar_codigo("sid-test", "654321"), (False, "Demasiados intentos"))
            auth.guardar_codigo("sid-second", "222222")
            self.assertEqual(auth.verificar_codigo("sid-second", "222222"), (True, "ok"))
            self.assertFalse(auth.verificar_codigo("sid-second", "222222")[0])


if __name__ == "__main__":
    unittest.main()
