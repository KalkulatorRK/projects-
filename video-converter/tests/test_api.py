import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.main import app  # noqa: E402

client = TestClient(app)


def test_health():
    r = client.get('/api/health')
    assert r.status_code == 200
    data = r.json()
    assert 'status' in data
    assert 'ffmpeg' in data
    assert '.vob' in data['input_extensions']


def test_presets_api():
    r = client.get('/api/presets')
    assert r.status_code == 200
    presets = r.json()
    assert len(presets) >= 8
    ids = {p['id'] for p in presets}
    assert 'mp4_h264' in ids
    assert 'webm_vp9' in ids


def test_upload_rejects_bad_extension():
    r = client.post(
        '/api/jobs/upload',
        data={'preset_id': 'mp4_h264'},
        files={'files': ('test.pdf', b'fake', 'application/pdf')},
    )
    assert r.status_code == 400


def test_jobs_path_not_found():
    r = client.post(
        '/api/jobs/path',
        json={'paths': ['C:\\nonexistent_file_12345.vob'], 'preset_id': 'mp4_h264'},
    )
    assert r.status_code == 404


def test_index_html():
    r = client.get('/')
    assert r.status_code == 200
    assert 'Video Converter' in r.text


def _ffmpeg_available() -> bool:
    import shutil
    if (ROOT / 'bin' / 'ffmpeg.exe').is_file():
        return True
    return shutil.which('ffmpeg') is not None


@pytest.mark.skipif(not _ffmpeg_available(), reason='ffmpeg not in PATH or bin/')
def test_convert_synthetic_video(tmp_path):
    src = tmp_path / 'test_input.mp4'
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    subprocess.run(
        [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'testsrc=duration=1:size=320x240:rate=10',
            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
            '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(src),
        ],
        check=True,
        capture_output=True,
    )
    r = client.post(
        '/api/jobs/path',
        json={
            'paths': [str(src)],
            'preset_id': 'mp4_h264',
            'output_dir': str(out_dir),
        },
    )
    assert r.status_code == 200
    job_id = r.json()['jobs'][0]['id']

    import time
    for _ in range(60):
        st = client.get(f'/api/jobs/{job_id}').json()
        if st['status'] in ('completed', 'failed'):
            break
        time.sleep(0.5)

    assert st['status'] == 'completed', st.get('error', st.get('log_tail'))
    assert Path(st['output_path']).is_file()

    dl = client.get(f'/api/jobs/{job_id}/download')
    assert dl.status_code == 200
    assert len(dl.content) > 1000
