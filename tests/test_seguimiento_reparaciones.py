import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO

from PIL import Image

from seguimiento_reparaciones import (
    PUBLIC_STATES, _expiration_for, _is_expired, _prepare_photo, _token_hash
)


class Upload:
    filename = "device.png"
    def __init__(self, content):
        self.stream = BytesIO(content)
    def read(self, size=-1):
        return self.stream.read(size)


class SeguimientoHelpersTests(unittest.TestCase):
    def test_exactly_three_public_states(self):
        self.assertEqual([x[0] for x in PUBLIC_STATES], [
            "pieza_en_camino", "reparando", "reparacion_acabada"
        ])

    def test_token_is_stored_as_sha256(self):
        token = "token-privado-no-reutilizable"
        self.assertNotEqual(_token_hash(token), token)
        self.assertEqual(len(_token_hash(token)), 64)

    def test_expiry_is_five_days_after_completion(self):
        completed = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(_expiration_for(completed), completed + timedelta(days=5))

    def test_expiry_boundary_is_inclusive(self):
        expiry = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)
        row = {"fecha_caducidad": expiry.isoformat()}
        self.assertFalse(_is_expired(row, expiry - timedelta(seconds=1)))
        self.assertTrue(_is_expired(row, expiry))
        self.assertTrue(_is_expired(row, expiry + timedelta(seconds=1)))

    def test_photo_is_reencoded_to_jpeg(self):
        image = Image.new("RGB", (300, 200), "orange")
        stream = BytesIO()
        image.save(stream, format="PNG")
        result = _prepare_photo(Upload(stream.getvalue()))
        self.assertTrue(result.startswith(bytes.fromhex("ffd8")))
        self.assertLessEqual(len(result), 5 * 1024 * 1024)

    def test_non_image_is_rejected(self):
        with self.assertRaises(ValueError):
            _prepare_photo(Upload(b"not an image"))


if __name__ == "__main__":
    unittest.main()
