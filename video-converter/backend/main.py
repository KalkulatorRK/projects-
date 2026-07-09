"""FastAPI приложение Video Converter."""

from __future__ import annotations

import shutil
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.ffmpeg_runner import (
    OUTPUT,
    UPLOADS,
    JobStatus,
    ensure_dirs,
    ffmpeg_version,
    probe_media,
    queue,
)
from backend.presets import INPUT_EXTENSIONS, list_presets

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'frontend'
HOST = '127.0.0.1'
PORT = 8765


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_dirs()
    yield


app = FastAPI(title='Video Converter', version='1.0.0', lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[f'http://{HOST}:{PORT}', f'http://localhost:{PORT}'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


class PathJobRequest(BaseModel):
    paths: list[str] = Field(..., min_length=1)
    preset_id: str = 'mp4_h264'
    output_dir: str | None = None


class ConcatJobRequest(BaseModel):
    paths: list[str] = Field(..., min_length=2)
    preset_id: str = 'mp4_h264'
    output_dir: str | None = None
    output_name: str | None = None


@app.get('/api/health')
def health() -> dict:
    version = ffmpeg_version()
    ffmpeg_ok = version.lower().startswith('ffmpeg version')
    return {
        'status': 'ok' if ffmpeg_ok else 'no_ffmpeg',
        'ffmpeg': version,
        'input_extensions': sorted(INPUT_EXTENSIONS),
        'output_dir': str(OUTPUT.resolve()),
    }


@app.get('/api/presets')
def presets() -> list[dict]:
    return list_presets()


@app.post('/api/probe')
async def probe(path: str = Form(...)) -> dict:
    p = Path(path)
    if not p.is_file():
        raise HTTPException(404, 'Файл не найден')
    try:
        return probe_media(str(p.resolve()))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc


@app.post('/api/jobs/upload')
async def upload_jobs(
    files: list[UploadFile] = File(...),
    preset_id: str = Form('mp4_h264'),
    output_dir: str | None = Form(None),
) -> dict:
    if not files:
        raise HTTPException(400, 'Не выбраны файлы')
    out = Path(output_dir).resolve() if output_dir else None
    created = []
    for upload in files:
        suffix = Path(upload.filename or 'video.bin').suffix.lower()
        if suffix not in INPUT_EXTENSIONS:
            raise HTTPException(400, f'Неподдерживаемый формат: {suffix}')
        dest = UPLOADS / f'{Path(upload.filename or "video").stem}_{id(upload)}{suffix}'
        with dest.open('wb') as fh:
            shutil.copyfileobj(upload.file, fh)
        try:
            job = queue.add_job(str(dest), preset_id, str(out) if out else None)
            created.append(job.to_dict())
        except (ValueError, KeyError) as exc:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, str(exc)) from exc
    return {'jobs': created}


@app.post('/api/jobs/path')
def jobs_from_paths(body: PathJobRequest) -> dict:
    out = Path(body.output_dir).resolve() if body.output_dir else None
    created = []
    for raw in body.paths:
        p = Path(raw).resolve()
        if not p.is_file():
            raise HTTPException(404, f'Файл не найден: {raw}')
        try:
            job = queue.add_job(str(p), body.preset_id, str(out) if out else None)
            created.append(job.to_dict())
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc
    return {'jobs': created}


@app.post('/api/jobs/concat')
def concat_jobs(body: ConcatJobRequest) -> dict:
    """Склеить несколько VOB/частей в один файл (concat demuxer)."""
    from backend.ffmpeg_runner import ffmpeg_path
    from backend.presets import get_preset
    import subprocess
    import tempfile

    paths = []
    for raw in body.paths:
        p = Path(raw).resolve()
        if not p.is_file():
            raise HTTPException(404, f'Файл не найден: {raw}')
        paths.append(str(p))

    preset = get_preset(body.preset_id)
    out_dir = Path(body.output_dir).resolve() if body.output_dir else OUTPUT
    out_dir.mkdir(parents=True, exist_ok=True)
    name = body.output_name or 'merged_video'
    merged_input = out_dir / f'_concat_{name}.ts'
    list_file = tempfile.NamedTemporaryFile(
        mode='w', suffix='.txt', delete=False, encoding='utf-8',
    )
    try:
        for p in paths:
            normalized = p.replace('\\', '/')
            list_file.write(f"file '{normalized}'\n")
        list_file.close()
        cmd = [
            ffmpeg_path(), '-hide_banner', '-y',
            '-f', 'concat', '-safe', '0', '-i', list_file.name,
            '-c', 'copy', str(merged_input),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)
        if proc.returncode != 0:
            raise HTTPException(500, proc.stderr or 'concat failed')
        job = queue.add_job(str(merged_input), body.preset_id, str(out_dir))
        return {'jobs': [job.to_dict()]}
    finally:
        Path(list_file.name).unlink(missing_ok=True)


@app.get('/api/jobs')
def list_jobs() -> dict:
    return {'jobs': queue.list_jobs()}


@app.get('/api/jobs/{job_id}')
def get_job(job_id: str) -> dict:
    job = queue.get_job(job_id)
    if not job:
        raise HTTPException(404, 'Задача не найдена')
    return job.to_dict()


@app.delete('/api/jobs/{job_id}')
def cancel_job(job_id: str) -> dict:
    if not queue.cancel_job(job_id):
        raise HTTPException(400, 'Не удалось отменить задачу')
    job = queue.get_job(job_id)
    return job.to_dict() if job else {'id': job_id, 'status': 'cancelled'}


@app.get('/api/jobs/{job_id}/download')
def download_result(job_id: str) -> FileResponse:
    job = queue.get_job(job_id)
    if not job or job.status != JobStatus.COMPLETED:
        raise HTTPException(404, 'Готовый файл недоступен')
    path = Path(job.output_path)
    if not path.is_file():
        raise HTTPException(404, 'Файл не найден на диске')
    return FileResponse(path, filename=path.name, media_type='application/octet-stream')


if FRONTEND.is_dir():
    app.mount('/', StaticFiles(directory=str(FRONTEND), html=True), name='frontend')
