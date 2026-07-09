"""Профили конвертации FFmpeg."""

from __future__ import annotations

from dataclasses import dataclass


INPUT_EXTENSIONS = frozenset({
    '.vob', '.avi', '.mpg', '.mpeg', '.wmv', '.flv', '.mov', '.mkv',
    '.3gp', '.ts', '.m2ts', '.mp4', '.webm', '.m4v', '.asf', '.ogv',
})

OUTPUT_EXTENSIONS = frozenset({
    '.mp4', '.mkv', '.webm', '.mp3', '.aac', '.m4a',
})


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    description: str
    extension: str
    ffmpeg_args: tuple[str, ...]
    try_copy_first: bool = False


PRESETS: dict[str, Preset] = {
    'mp4_h264': Preset(
        id='mp4_h264',
        label='Универсальный MP4 (H.264 + AAC)',
        description='Подходит для телевизора, телефона и архива.',
        extension='.mp4',
        ffmpeg_args=(
            '-c:v', 'libx264', '-crf', '23', '-preset', 'medium',
            '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
        ),
    ),
    'mp4_h265': Preset(
        id='mp4_h265',
        label='Компактный MP4 (H.265 + AAC)',
        description='Меньший размер файла, кодирование дольше.',
        extension='.mp4',
        ffmpeg_args=(
            '-c:v', 'libx265', '-crf', '28', '-preset', 'medium',
            '-tag:v', 'hvc1',
            '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
        ),
    ),
    'mobile_720p': Preset(
        id='mobile_720p',
        label='Для телефона (720p, H.264)',
        description='Ограничение по высоте 720p, AAC 128 kbps.',
        extension='.mp4',
        ffmpeg_args=(
            '-vf', "scale='min(1280,iw)':min(720\\,ih):force_original_aspect_ratio=decrease",
            '-c:v', 'libx264', '-crf', '23', '-preset', 'medium',
            '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart',
        ),
    ),
    'mkv_h264': Preset(
        id='mkv_h264',
        label='MKV (H.264 + AAC)',
        description='Гибкий контейнер MKV.',
        extension='.mkv',
        ffmpeg_args=(
            '-c:v', 'libx264', '-crf', '23', '-preset', 'medium',
            '-c:a', 'aac', '-b:a', '192k',
        ),
    ),
    'webm_vp9': Preset(
        id='webm_vp9',
        label='WebM (VP9 + Opus)',
        description='Для браузера и веб-публикации.',
        extension='.webm',
        ffmpeg_args=(
            '-c:v', 'libvpx-vp9', '-crf', '31', '-b:v', '0',
            '-c:a', 'libopus', '-b:a', '128k',
        ),
    ),
    'mp3_audio': Preset(
        id='mp3_audio',
        label='Только аудио MP3',
        description='Извлечь звуковую дорожку.',
        extension='.mp3',
        ffmpeg_args=('-vn', '-c:a', 'libmp3lame', '-q:a', '2'),
    ),
    'aac_audio': Preset(
        id='aac_audio',
        label='Только аудио AAC',
        description='Извлечь звук в AAC (.m4a).',
        extension='.m4a',
        ffmpeg_args=('-vn', '-c:a', 'aac', '-b:a', '192k'),
    ),
    'copy_mp4': Preset(
        id='copy_mp4',
        label='Быстро — смена контейнера (MP4)',
        description='Без перекодирования, если кодеки совместимы с MP4.',
        extension='.mp4',
        ffmpeg_args=('-c', 'copy', '-movflags', '+faststart'),
        try_copy_first=True,
    ),
}


def get_preset(preset_id: str) -> Preset:
    if preset_id not in PRESETS:
        raise KeyError(f'Unknown preset: {preset_id}')
    return PRESETS[preset_id]


def list_presets() -> list[dict]:
    return [
        {
            'id': p.id,
            'label': p.label,
            'description': p.description,
            'extension': p.extension,
        }
        for p in PRESETS.values()
    ]


def is_supported_input(path: str) -> bool:
    from pathlib import Path
    return Path(path).suffix.lower() in INPUT_EXTENSIONS
