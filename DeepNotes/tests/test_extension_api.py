"""Additive extension bridge regressions; the original API is never patched."""
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from deepnotes.api import create_app as original_app
from deepnotes.extension_api import create_app
from deepnotes.config import Settings

EXTENSION = 'a' * 32
OTHER = 'b' * 32
ORIGIN = 'chrome-extension://' + EXTENSION


class ExtensionBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(db_path=Path(self.temp.name) / 'extension.sqlite3', demo_mode=True)
        self.app = create_app(settings=self.settings, extension_id=EXTENSION, start_worker=False)
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8000')
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    @staticmethod
    def headers(origin=ORIGIN, identity=EXTENSION):
        result = {'X-DeepNotes-Extension': identity}
        if origin is not None:
            result['Origin'] = origin
        return result

    def test_trusted_extension_capture_query_and_context(self):
        headers = self.headers()
        saved = self.client.post('/api/entries', json={'content': '  Java generics\n', 'source_url': 'https://example.com/java'}, headers=headers)
        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual(saved.json()['content'], '  Java generics\n')
        self.assertEqual(saved.headers['Access-Control-Allow-Origin'], ORIGIN)
        self.assertEqual(saved.headers['X-DeepNotes-Extension-Bridge'], '1')
        self.assertEqual(saved.headers.get('Access-Control-Allow-Credentials'), None)
        self.assertEqual(self.client.post('/api/guidance', json={'scope': 'entry', 'target_id': str(saved.json()['id']), 'content': 'Lecture context'}, headers=headers).status_code, 201)
        answer = self.client.post('/api/queries', json={'question': 'Java'}, headers=headers)
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertTrue(answer.json()['answer'])
        self.assertEqual(answer.json()['references']['notes'][0]['id'], saved.json()['id'])
        self.assertEqual(self.client.post('/api/structure/reorganize', json={}, headers=headers).status_code, 200)

    def test_trusted_preflight_and_private_network(self):
        response = self.client.options('/api/entries', headers={
            'Origin': ORIGIN, 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'Content-Type, X-DeepNotes-Extension',
            'Access-Control-Request-Private-Network': 'true',
        })
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], ORIGIN)
        self.assertEqual(response.headers['Access-Control-Allow-Private-Network'], 'true')
        self.assertNotIn('*', response.headers['Access-Control-Allow-Headers'])

    def test_wrong_extension_origin_even_with_correct_public_id_is_rejected(self):
        for origin in ('https://evil.example', 'null', 'chrome-extension://' + OTHER, ORIGIN + '/'):
            response = self.client.post('/api/entries', json={'content': 'bad'}, headers=self.headers(origin=origin))
            self.assertEqual(response.status_code, 403, origin)
            self.assertNotIn('Access-Control-Allow-Origin', response.headers)
        self.assertFalse(self.client.get('/api/entries').json()['items'])

    def test_missing_or_wrong_identity_is_rejected(self):
        for headers in ({'Origin': ORIGIN}, self.headers(identity=OTHER), self.headers(identity='')):
            self.assertEqual(self.client.get('/api/status', headers=headers).status_code, 403)

    def test_originless_extension_context_with_identity_is_supported(self):
        response = self.client.get('/api/status', headers=self.headers(origin=None))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-DeepNotes-Extension-Bridge'], '1')

    def test_duplicate_identity_headers_rejected(self):
        response = self.client.get('/api/status', headers=[('Origin', ORIGIN), ('X-DeepNotes-Extension', EXTENSION), ('X-DeepNotes-Extension', OTHER)])
        self.assertEqual(response.status_code, 403)

    def test_extension_path_method_and_host_restrictions(self):
        self.assertEqual(self.client.get('/', headers=self.headers()).status_code, 403)
        self.assertEqual(self.client.delete('/api/entries', headers=self.headers()).status_code, 403)
        self.assertEqual(self.client.get('/api/status', headers={**self.headers(), 'Host': 'evil.example'}).status_code, 403)

    def test_json_content_type_policy_still_applies(self):
        response = self.client.post('/api/entries', content='content=bad', headers={**self.headers(), 'Content-Type': 'text/plain'})
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], ORIGIN)

    def test_preflight_rejects_unapproved_headers_and_methods(self):
        for method, requested in [('DELETE', 'content-type'), ('POST', 'authorization')]:
            response = self.client.options('/api/entries', headers={'Origin': ORIGIN, 'Access-Control-Request-Method': method, 'Access-Control-Request-Headers': requested})
            self.assertEqual(response.status_code, 403)

    def test_same_origin_website_and_api_remain_available(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        saved = self.client.post('/api/entries', json={'content': 'Website note'}, headers={'Origin': 'http://127.0.0.1:8000'})
        self.assertEqual(saved.status_code, 201)
        self.assertNotIn('Access-Control-Allow-Origin', saved.headers)
        self.assertEqual(self.client.post('/api/entries', json={'content': 'bad'}, headers={'Origin': 'https://evil.example'}).status_code, 403)

    def test_original_launcher_still_rejects_extension_writes(self):
        with TestClient(original_app(settings=self.settings, start_worker=False), base_url='http://127.0.0.1:8000') as client:
            response = client.post('/api/entries', json={'content': 'not saved'}, headers=self.headers())
            self.assertEqual(response.status_code, 403)
            self.assertNotIn('X-DeepNotes-Extension-Bridge', response.headers)

    def test_unconfigured_launcher_fails_closed_for_extensions(self):
        with TestClient(create_app(settings=self.settings, extension_id='', start_worker=False), base_url='http://127.0.0.1:8000') as client:
            response = client.get('/api/status', headers=self.headers())
            self.assertEqual(response.status_code, 503)
            self.assertIn('DEEPNOTES_EXTENSION_ID', response.json()['detail'])
            self.assertEqual(client.get('/api/status').status_code, 200)

    def test_invalid_configuration_rejected(self):
        for identity in ('*', 'chrome-extension://' + EXTENSION, 'q' * 32, EXTENSION + ',' + OTHER):
            with self.assertRaises(ValueError):
                create_app(settings=self.settings, extension_id=identity, start_worker=False)


if __name__ == '__main__':
    unittest.main()
