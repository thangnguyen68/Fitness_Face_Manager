"""Install an InsightFace model pack with progress visible in the API console."""

import os
import re
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from filelock import FileLock


MODEL_URL = 'https://github.com/deepinsight/insightface/releases/download/model-zoo/{name}.zip'
BUFFALO_L_FILES = ('det_10g.onnx', 'w600k_r50.onnx')


def _installed(model_dir: Path, name: str) -> bool:
    if name == 'buffalo_l':
        return all((model_dir / file).is_file() and (model_dir / file).stat().st_size > 0
                   for file in BUFFALO_L_FILES)
    return any(file.is_file() and file.stat().st_size > 0 for file in model_dir.glob('*.onnx'))


def _valid_archive(path: Path, name: str) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            files = {entry.filename for entry in archive.infolist() if not entry.is_dir()}
            if name == 'buffalo_l' and not set(BUFFALO_L_FILES) <= files:
                return False
            if not any(file.endswith('.onnx') for file in files):
                return False
            return archive.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def _download(url: str, destination: Path) -> None:
    print(f'[Model] Dang tai {url}', flush=True)
    with urllib.request.urlopen(url, timeout=60) as response, destination.open('wb') as output:
        total = int(response.headers.get('Content-Length') or 0)
        received = 0
        last_percent = -1
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            received += len(chunk)
            if total:
                percent = min(100, received * 100 // total)
                if percent != last_percent:
                    print(f'\r[Model] Tai: {percent:3d}% ({received / 1048576:.1f}/{total / 1048576:.1f} MB)', end='', flush=True)
                    last_percent = percent
            else:
                print(f'\r[Model] Da tai: {received / 1048576:.1f} MB', end='', flush=True)
    print(flush=True)
    if total and received != total:
        raise RuntimeError(f'Tai model chua du: {received}/{total} bytes')


def ensure_model(root: str, name: str) -> Path:
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('INSIGHTFACE_MODEL khong hop le')
    model_root = Path(root).expanduser() / 'models'
    model_dir = model_root / name
    if _installed(model_dir, name):
        print(f'[Model] Da co model {name}: {model_dir}', flush=True)
        return model_dir

    model_root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(model_root / f'{name}.lock')):
        if _installed(model_dir, name):
            return model_dir
        archive_path = model_root / f'{name}.zip'
        if not archive_path.is_file() or not _valid_archive(archive_path, name):
            temporary = archive_path.with_suffix('.zip.download')
            try:
                _download(MODEL_URL.format(name=name), temporary)
                if not _valid_archive(temporary, name):
                    raise RuntimeError('File model tai ve bi loi hoac thieu ONNX')
                os.replace(temporary, archive_path)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            print(f'[Model] Dung file model da co: {archive_path}', flush=True)

        model_dir.mkdir(parents=True, exist_ok=True)
        print(f'[Model] Dang giai nen {name}...', flush=True)
        with zipfile.ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                # Official packs use flat filenames; never extract a path from an archive.
                if Path(entry.filename).name != entry.filename:
                    raise RuntimeError(f'Duong dan khong hop le trong model: {entry.filename}')
                with tempfile.NamedTemporaryFile(dir=model_dir, delete=False) as output:
                    temporary_file = Path(output.name)
                    try:
                        with archive.open(entry) as source:
                            shutil.copyfileobj(source, output)
                    except BaseException:
                        temporary_file.unlink(missing_ok=True)
                        raise
                os.replace(temporary_file, model_dir / entry.filename)
        if not _installed(model_dir, name):
            raise RuntimeError(f'Model {name} thieu file ONNX can thiet')
        print(f'[Model] San sang: {model_dir}', flush=True)
        return model_dir
