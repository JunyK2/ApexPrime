import unittest
from unittest.mock import Mock

from apexprime.db import SupabaseREST


class StorageTests(unittest.TestCase):
    def test_public_image_upload_creates_bucket_and_returns_encoded_url(self):
        db = SupabaseREST("https://example.supabase.co", "service-secret")
        missing = Mock(status_code=404, ok=False)
        created = Mock(status_code=200, ok=True, text="")
        uploaded = Mock(status_code=200, ok=True, text="")
        db.session.get = Mock(return_value=missing)
        db.session.post = Mock(side_effect=[created, uploaded])

        url = db.upload_public_image("apexprime-charts", "run-1/1h chart.png", b"fake-image", "image/png")

        self.assertIn("/storage/v1/object/public/apexprime-charts/run-1/1h%20chart.png", url)
        self.assertEqual(db.session.post.call_count, 2)
        upload_call = db.session.post.call_args_list[1]
        self.assertEqual(upload_call.kwargs["data"], b"fake-image")
        self.assertEqual(upload_call.kwargs["headers"]["x-upsert"], "true")

    def test_rejects_non_image_content_type(self):
        db = SupabaseREST("https://example.supabase.co", "service-secret")
        with self.assertRaises(ValueError):
            db.upload_public_image("apexprime-charts", "run/file.txt", b"x", "text/plain")


if __name__ == "__main__":
    unittest.main()
