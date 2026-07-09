# Video Converter

Локальный конвертер видео для **Windows** с интерфейсом в браузере.

- **Backend:** FastAPI + FFmpeg  
- **UI:** HTML/CSS/JS (localhost)  
- **Запуск:** двойной клик по `run.bat`

Часть монорепозитория [KalkulatorRK/projects-](https://github.com/KalkulatorRK/projects-).

## Поддерживаемые форматы

### Вход

VOB, AVI, MPG, MPEG, WMV, FLV, MOV, MKV, 3GP, TS, M2TS, MP4, WebM, M4V, ASF, OGV

### Выход (профили)

| Профиль | Результат |
|---------|-----------|
| Универсальный MP4 | H.264 + AAC |
| Компактный MP4 | H.265 + AAC |
| Для телефона | 720p H.264 |
| MKV | H.264 + AAC |
| WebM | VP9 + Opus |
| Только аудио | MP3 или AAC |
| Быстро | remux в MP4 (с fallback на H.264) |

## Требования

1. **Python 3.11+** — [python.org](https://www.python.org/downloads/)
2. **FFmpeg** — один из вариантов:
   - установить и добавить в PATH;
   - или положить `ffmpeg.exe` и `ffprobe.exe` в папку `bin/`

Сборка FFmpeg для Windows: [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/)

## Быстрый старт

```bat
cd video-converter
run.bat
```

Откроется браузер: `http://127.0.0.1:8765`

## Использование

1. Перетащите файлы в зону загрузки **или** укажите полный путь («Путь к файлу…») — без копирования больших файлов.
2. Выберите профиль конвертации.
3. (Опционально) укажите папку для результата — иначе `workspace/output/`.
4. Для DVD: несколько VOB → «Склеить выбранные» → затем конвертация.

## Разработка

```bat
cd video-converter
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765 --app-dir .
pytest tests/ -q
```

## Структура

```
video-converter/
├── backend/          API, очередь, FFmpeg
├── frontend/         UI в браузере
├── bin/              ffmpeg.exe (опционально)
├── workspace/        uploads + output (создаётся автоматически)
├── run.bat
└── requirements.txt
```

## API

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/health` | Статус FFmpeg |
| GET | `/api/presets` | Профили |
| POST | `/api/jobs/upload` | Загрузка файлов |
| POST | `/api/jobs/path` | Конвертация по локальному пути |
| POST | `/api/jobs/concat` | Склейка частей |
| GET | `/api/jobs` | Очередь |
| GET | `/api/jobs/{id}/download` | Скачать результат |

## Примечания

- Конвертация идёт **локально**, интернет не нужен.
- Очередь обрабатывается **последовательно** (один FFmpeg).
- Проект **не связан** с ndt_web / Карта-НК и не деплоится на Render.
