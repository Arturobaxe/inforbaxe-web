"""Localización de fichas para EB-BN980ABY con respuestas simuladas (sin red).
Ejecutar: python -m unittest tests.test_despiece_localizacion -v"""
import sys, types, unittest
sys.modules.setdefault("database", types.ModuleType("database"))
import despiece_inteligente as d  # noqa: E402

REF = "EB-BN980ABY"
OV_PROD = "https://ovisat.com/es/baterias-samsung/12345-bateria-samsung-galaxy-note-20-eb-bn980aby.html"
OV_GEN = "https://ovisat.com/es/baterias-apple/999-bateria-iphone-11.html"
SP_PROD = "https://servicepacksamsung.com/es/bateria/gh82-23456a.html"
SP_GEN = "https://servicepacksamsung.com/es/pantalla/gh82-99999a.html"
PAGE = lambda t: f"<html><body><h1>{t}</h1><p>Compatible con Samsung Galaxy Note 20 SM-N980F, Galaxy Note 20 5G SM-N981B</p></body></html>"

PAGES = {
    "https://ovisat.com/es/search?controller=search&s=" + REF: f"""<html><body><h2>Resultados de búsqueda para {REF}</h2>
      <a href="{OV_PROD}">Batería Note 20</a><a href="{OV_GEN}">Batería iPhone 11</a>
      <a href="/es/search?controller=search&s={REF}&page=2">2</a></body></html>""",
    "https://servicepacksamsung.com/es/search?controller=search&s=" + REF: f"""<html><body><p>Resultados de búsqueda</p>
      <div><a href="{SP_PROD}">Batería Galaxy Note 20</a><span>Ref: {REF}</span></div>
      <div><a href="{SP_GEN}">Pantalla A52</a><span>Ref: GH82-99999A</span></div></body></html>""",
    OV_PROD: PAGE(f"Batería {REF}"), SP_PROD: PAGE(f"Batería {REF}"),
    OV_GEN: "<html><body>Batería iPhone 11</body></html>", SP_GEN: "<html><body>Pantalla</body></html>",
}
GENERIC_SEARCH = f"""<html><body><h2>Resultados de búsqueda para {REF}</h2>
  <a href="{OV_GEN}">Batería iPhone 11</a><a href="/otro-p5">Cargador</a></body></html>"""

BING = f"""<?xml version="1.0"?><rss><channel><item><title>Batería Samsung {REF}</title><link>{OV_PROD}</link></item>
<item><title>Otra</title><link>{OV_GEN}</link></item></channel></rss>"""


class Base(unittest.TestCase):
    def setUp(self):
        self.o = (d._http_text, d._robots_can_fetch); self.fetched = []
        d._robots_can_fetch = lambda u: True
        def fake(url, limit=0, timeout=0):
            self.fetched.append(url)
            if url in self.pages: return self.pages[url], url, 200
            raise OSError("no simulada")
        d._http_text = fake; self.pages = dict(PAGES)
    def tearDown(self): d._http_text, d._robots_can_fetch = self.o


class DirectCatalog(Base):
    def run_cat(self, name, domain, tpl):
        return d._search_direct_catalog(name, domain, (tpl,), REF, "bateria")

    def test_ovisat_url_sin_formato_p123_con_referencia(self):
        ev, diag = self.run_cat("Ovisat", "ovisat.com", "https://ovisat.com/es/search?controller=search&s={q}")
        self.assertEqual([p["url"] for p in diag["found_pages"]], [OV_PROD])
        self.assertTrue(diag["found_pages"][0]["has_reference"])
        self.assertEqual(len(ev), 1)
        self.assertNotIn(OV_GEN, self.fetched)          # genérica no leída
        self.assertEqual(diag["pages_read"], 1)

    def test_service_pack_ficha_con_referencia_en_la_tarjeta(self):
        ev, diag = self.run_cat("Service Pack", "servicepacksamsung.com", "https://servicepacksamsung.com/es/search?controller=search&s={q}")
        self.assertEqual([p["url"] for p in diag["found_pages"]], [SP_PROD])
        self.assertNotIn(SP_GEN, self.fetched)
        self.assertEqual(diag["pages_read"], 1)
        self.assertTrue(ev and {e["source_group"] for e in ev} == {"domain:servicepacksamsung.com"})

    def test_resultados_genericos_no_se_leen(self):
        self.pages["https://ovisat.com/es/search?controller=search&s=" + REF] = GENERIC_SEARCH
        ev, diag = self.run_cat("Ovisat", "ovisat.com", "https://ovisat.com/es/search?controller=search&s={q}")
        self.assertEqual((ev, diag["pages_read"], diag["found_pages"]), ([], 0, []))
        self.assertEqual(diag["status"], "sin_resultados_especificos")
        self.assertEqual(self.fetched, ["https://ovisat.com/es/search?controller=search&s=" + REF])


class GlobalSearch(Base):
    def test_consulta_site_localiza_ficha_y_la_muestra_en_diagnostico(self):
        self.pages = {}
        orig = d._http_text
        def fake(url, limit=0, timeout=0):
            if "bing.com" in url and "site%3Aovisat.com" in url: return BING, url, 200
            raise OSError("sin respuesta")
        d._http_text = fake
        urls, diags = d._global_search_urls(REF, "bateria")
        self.assertEqual(urls[0][1], OV_PROD)                 # específica primero
        summary = diags[-1]
        self.assertTrue(summary["urls"][0]["referencia_en_url_o_titulo"])
        self.assertEqual(summary["urls"][0]["url"], OV_PROD)
        d._http_text = orig


if __name__ == "__main__":
    unittest.main()
