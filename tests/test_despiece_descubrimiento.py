"""Descubrimiento de la ruta de búsqueda y diagnóstico de intentos (respuestas simuladas, sin red).
Las rutas del test son inventadas a propósito: demuestran que el código usa la del formulario, no una fija."""
import sys, types, unittest
from urllib.error import HTTPError
sys.modules.setdefault("database", types.ModuleType("database"))
import despiece_inteligente as d  # noqa: E402

REF = "EB-BN980ABY"
HOME = """<html><head><title>Tienda · Inicio</title></head><body>
<form method="get" action="/es/zoek-resultaten" class="search-widget"><input type="hidden" name="controller" value="search">
<input type="text" name="s" placeholder="Buscar"></form>
<form method="post" action="/newsletter"><input type="text" name="email"></form></body></html>"""
RESULT = '<html><head><title>Resultados</title></head><body><a href="/p/bateria-eb-bn980aby.html">Batería EB-BN980ABY</a></body></html>'
PRODUCT = f"<html><body><h1>Batería {REF}</h1><p>Compatible con Samsung Galaxy Note 20 SM-N980F</p></body></html>"


class Discovery(unittest.TestCase):
    def setUp(self):
        self.o = (d._http_text, d._robots_can_fetch); self.calls = []
        d._robots_can_fetch = lambda u: True
        def fake(url, limit=0, timeout=0):
            self.calls.append(url)
            if url == "https://ovisat.com/": return HOME, "https://www.ovisat.com/", 200
            if url.startswith("https://www.ovisat.com/es/zoek-resultaten?"): return RESULT, url, 200
            if url == "https://www.ovisat.com/p/bateria-eb-bn980aby.html": return PRODUCT, url, 200
            raise HTTPError(url, 404, "nf", {}, None)
        d._http_text = fake
    def tearDown(self): d._http_text, d._robots_can_fetch = self.o

    def test_usa_la_ruta_del_formulario_y_registra_intentos(self):
        ev, diag = d._search_direct_catalog("T", "ovisat.com", ("https://ovisat.com/search?s={q}",), REF, "bateria")
        kinds = [a["kind"] for a in diag["attempts"]]
        self.assertEqual(kinds[:2], ["portada", "formulario"])
        form = diag["attempts"][1]
        self.assertTrue(form["url"].startswith("https://www.ovisat.com/es/zoek-resultaten?"))
        self.assertIn("controller=search", form["url"]); self.assertIn("s=EB-BN980ABY", form["url"])
        self.assertEqual((form["http"], form["title"]), (200, "Resultados"))
        self.assertEqual(diag["attempts"][0]["final_url"], "https://www.ovisat.com/")
        self.assertEqual(diag["attempts"][0]["formularios_de_busqueda"], 1)   # el POST de newsletter se ignora
        self.assertTrue(ev and diag["found_pages"][0]["has_reference"])
        self.assertNotIn("https://ovisat.com/search?s=EB-BN980ABY", self.calls)  # la plantilla ya no hace falta

    def test_intento_fallido_queda_registrado_con_http_y_url_final(self):
        d._http_text = lambda url, limit=0, timeout=0: (_ for _ in ()).throw(HTTPError(url, 403, "forbidden", {}, None))
        ev, diag = d._search_direct_catalog("T", "ovisat.com", ("https://ovisat.com/search?s={q}",), REF, "b")
        self.assertEqual(ev, [])
        self.assertEqual([(a["kind"], a["http"], a["status"]) for a in diag["attempts"]], [("portada", 403, "http_403"), ("plantilla", 403, "http_403")])
        self.assertEqual(diag["status"], "http_403")


if __name__ == "__main__":
    unittest.main()
