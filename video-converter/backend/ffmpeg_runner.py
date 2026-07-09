"""Обёртка FFmpeg / FFprobe: поиск бинарников, probe, конвертация с прогрессом."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from uuid import uuid4

from backend.presets import Preset, get_preset, is_supported_input


class JobStatus(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


@dataclass
class Job:
    id: str
    input_path: str
    output_path: str
    preset_id: str
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    error: str = ''
    log_lines: list[str] = field(default_factory=list)
    probe: dict | None = None
    duration_sec: float | None = None
    _process: subprocess.Popen | None = field(default=None, repr=False)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'input_path': self.input_path,
            'input_name': Path(self.input_path).name,
            'output_path': self.output_path,
            'output_name': Path(self.output_path).name,
            'preset_id': self.preset_id,
            'status': self.status.value,
            'progress': round(self.progress, 1),
            'error': self.error,
            'probe': self.probe,
            'duration_sec': self.duration_sec,
            'log_tail': self.log_lines[-20:],
        }


ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / 'bin'
WORKSPACE = ROOT / 'workspace'
UPLOADS = WORKSPACE / 'uploads'
OUTPUT = WORKSPACE / 'output'

_TIME_RE = re.compile(r'time=(\d{2}):(\d{2}):(\d{2}\.\d+)')
_DURATION_RE = re.compile(r'Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)')
_FFMPEG: str | None = None
_FFPROBE: str | None = None


def ensure_dirs() -> None:
    UPLOADS.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)


def _resolve_binary(name: str) -> str:
    """ffmpeg или ffprobe: bin/ → PATH."""
    global _FFMPEG, _FFPROBE
    cached = _FFMPEG if name == 'ffmpeg' else _FFPROBE
    if cached:
        return cached

    local = BIN_DIR / f'{name}.exe'
    if local.is_file():
        resolved = str(local)
    else:
        resolved = shutil.which(name) or ''
        if not resolved and name == 'ffmpeg':
            resolved = shutil.which('ffmpeg.exe') or ''
        if not resolved and name == 'ffprobe':
            resolved = shutil.which('ffprobe.exe') or ''

    if not resolved:
        raise FileNotFoundError(
            f'{name} не найден. Установите FFmpeg и добавьте в PATH '
            f'или положите {name}.exe в video-converter/bin/'
        )

    if name == 'ffmpeg':
        _FFMPEG = resolved
    else:
        _FFPROBE = resolved
    return resolved


def ffmpeg_path() -> str:
    return _resolve_binary('ffmpeg')


def ffprobe_path() -> str:
    return _resolve_binary('ffprobe')


def ffmpeg_version() -> str:
    try:
        proc = subprocess.run(
            [ffmpeg_path(), '-version'],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        line = (proc.stdout or proc.stderr or '').splitlines()
        return line[0] if line else 'unknown'
    except FileNotFoundError as exc:
        return str(exc)


def _hms_to_seconds(h: str, m: str, s: str) -> float:
    return int(h) * 3600 + int(m) * 60 + float(s)


def probe_media(path: str) -> dict:
    """Метаданные файла через ffprobe."""
    cmd = [
        ffprobe_path(),
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        '-show_streams',
        path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or 'ffprobe failed')
    data = json.loads(proc.stdout)
    fmt = data.get('format', {})
    streams = data.get('streams', [])
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    duration = float(fmt.get('duration') or 0) or None
    return {
        'filename': Path(path).name,
        'format': fmt.get('format_name', ''),
        'duration_sec': duration,
        'size_bytes': int(fmt.get('size') or 0),
        'video_codec': video.get('codec_name') if video else None,
        'width': video.get('width') if video else None,
        'height': video.get('height') if video else None,
        'audio_codec': audio.get('codec_name') if audio else None,
    }


def build_output_path(input_path: str, preset: Preset, output_dir: Path | None) -> Path:
    stem = Path(input_path).stem
    out_dir = output_dir or OUTPUT
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate = out_dir / f'{stem}{preset.extension}'
    n = 1
    while candidate.exists():
        candidate = out_dir / f'{stem}_{n}{preset.extension}'
        n += 1
    return candidate


def _build_ffmpeg_cmd(input_path: str, output_path: str, preset: Preset) -> list[str]:
    return [
        ffmpeg_path(),
        '-hide_banner', '-y',
        '-i', input_path,
        *preset.ffmpeg_args,
        output_path,
    ]


def _parse_progress_line(line: str, duration_sec: float | None) -> float | None:
    if duration_sec and duration_sec > 0:
        m = _TIME_RE.search(line)
        if m:
            current = _hms_to_seconds(m.group(1), m.group(2), m.group(3))
            return min(99.0, (current / duration_sec) * 100)
    m = _DURATION_RE.search(line)
    if m and not duration_sec:
        return None
    return None


class JobQueue:
    """Один worker-поток для последовательной конвертации."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._queue: list[str] = []
        self._worker_started = False
        self._current_id: str | None = None

    def add_job(
        self,
        input_path: str,
        preset_id: str,
        output_dir: str | None = None,
    ) -> Job:
        if not is_supported_input(input_path):
            ext = Path(input_path).suffix.lower()
            raise ValueError(f'Неподдерживаемое расширение: {ext or "(нет)"}')

        preset = get_preset(preset_id)
        out_dir = Path(output_dir) if output_dir else None
        output_path = str(build_output_path(input_path, preset, out_dir))

        job = Job(
            id=str(uuid4()),
            input_path=input_path,
            output_path=output_path,
            preset_id=preset_id,
        )
        try:
            job.probe = probe_media(input_path)
            job.duration_sec = job.probe.get('duration_sec')
        except Exception as exc:  # noqa: BLE001 — probe optional at create
            job.log_lines.append(f'probe warning: {exc}')

        with self._lock:
            self._jobs[job.id] = job
            self._queue.append(job.id)
        self._ensure_worker()
        return job

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs]

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status == JobStatus.PENDING:
                job.status = JobStatus.CANCELLED
                if job_id in self._queue:
                    self._queue.remove(job_id)
                return True
            if job.status == JobStatus.RUNNING and job._process:
                job.status = JobStatus.CANCELLED
                try:
                    job._process.terminate()
                except OSError:
                    pass
                return True
        return False

    def _ensure_worker(self) -> None:
        if self._worker_started:
            return
        self._worker_started = True
        thread = threading.Thread(target=self._worker_loop, daemon=True)
        thread.start()

    def _worker_loop(self) -> None:
        while True:
            job_id = None
            with self._lock:
                while self._queue:
                    candidate = self._queue.pop(0)
                    job = self._jobs.get(candidate)
                    if job and job.status == JobStatus.PENDING:
                        job_id = candidate
                        break
            if not job_id:
                time.sleep(0.3)
                continue
            self._run_job(job_id)

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = JobStatus.RUNNING
            self._current_id = job_id

        preset = get_preset(job.preset_id)
        success = self._execute(job, preset)
        if not success and preset.try_copy_first and job.status != JobStatus.CANCELLED:
            job.log_lines.append('Remux не удался, перекодирование H.264…')
            job.status = JobStatus.RUNNING
            job.progress = 0
            job.error = ''
            fallback = get_preset('mp4_h264')
            job.output_path = str(build_output_path(
                job.input_path, fallback, Path(job.output_path).parent,
            ))
            success = self._execute(job, fallback)

        with self._lock:
            if job.status == JobStatus.RUNNING:
                job.status = JobStatus.COMPLETED if success else JobStatus.FAILED
                if job.status == JobStatus.COMPLETED:
                    job.progress = 100.0
            self._current_id = None

    def _execute(self, job: Job, preset: Preset) -> bool:
        cmd = _build_ffmpeg_cmd(job.input_path, job.output_path, preset)
        job.log_lines.append(' '.join(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
            )
            job._process = proc
            assert proc.stderr is not None
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    job.log_lines.append(line)
                    if len(job.log_lines) > 200:
                        job.log_lines = job.log_lines[-200:]
                if not job.duration_sec:
                    dm = _DURATION_RE.search(line)
                    if dm:
                        job.duration_sec = _hms_to_seconds(dm.group(1), dm.group(2), dm.group(3))
                pct = _parse_progress_line(line, job.duration_sec)
                if pct is not None:
                    job.progress = pct

            proc.wait()
            job._process = None
            if job.status == JobStatus.CANCELLED:
                return False
            if proc.returncode != 0:
                job.error = job.log_lines[-1] if job.log_lines else f'ffmpeg exit {proc.returncode}'
                return False
            if not Path(job.output_path).is_file():
                job.error = 'Выходной файл не создан'
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            job.error = str(exc)
            job._process = None
            return False


queue = JobQueue()
