import io
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from model_download import ensure_model


class ModelDownloadTests(unittest.TestCase):
    def test_existing_model_never_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / 'models' / 'buffalo_l'
            model.mkdir(parents=True)
            for filename in ('det_10g.onnx', 'w600k_r50.onnx'):
                (model / filename).write_bytes(b'model')
            with patch('model_download._download', side_effect=AssertionError('downloaded')):
                self.assertEqual(ensure_model(directory, 'buffalo_l'), model)

    def test_missing_model_downloads_and_prints_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.zip'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('det_10g.onnx', b'detection')
                archive.writestr('w600k_r50.onnx', b'recognition')

            def fake_urlopen(url, timeout):
                response = source.open('rb')
                response.headers = {'Content-Length': str(source.stat().st_size)}
                return response

            output = io.StringIO()
            with patch('model_download.urllib.request.urlopen', side_effect=fake_urlopen), redirect_stdout(output):
                model = ensure_model(directory, 'buffalo_l')
            self.assertEqual((model / 'det_10g.onnx').read_bytes(), b'detection')
            self.assertEqual((model / 'w600k_r50.onnx').read_bytes(), b'recognition')
            self.assertIn('100%', output.getvalue())


if __name__ == '__main__':
    unittest.main()
