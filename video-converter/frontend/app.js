(() => {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const dropzone = $('#dropzone');
  const fileInput = $('#file-input');
  const presetSelect = $('#preset-select');
  const outputDir = $('#output-dir');
  const btnUpload = $('#btn-upload');
  const btnPath = $('#btn-path');
  const btnConcat = $('#btn-concat');
  const btnRefresh = $('#btn-refresh');
  const pickFolder = $('#pick-folder');
  const queueList = $('#queue-list');
  const queueEmpty = $('#queue-empty');
  const queueCount = $('#queue-count');
  const ffmpegStatus = $('#ffmpeg-status');
  const logBox = $('#log-box');
  const logToggle = $('#log-toggle');

  let selectedFiles = [];
  let pathQueue = [];
  let pollTimer = null;

  function log(msg) {
    const ts = new Date().toLocaleTimeString('ru-RU');
    logBox.textContent += `[${ts}] ${msg}\n`;
    logBox.scrollTop = logBox.scrollHeight;
  }

  async function api(path, options = {}) {
    const res = await fetch(path, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || data.message || res.statusText);
    }
    return data;
  }

  async function loadHealth() {
    try {
      const h = await api('/api/health');
      if (h.status === 'ok') {
        ffmpegStatus.textContent = 'FFmpeg OK';
        ffmpegStatus.className = 'status-badge ok';
      } else {
        ffmpegStatus.textContent = 'FFmpeg не найден';
        ffmpegStatus.className = 'status-badge bad';
        log('Установите FFmpeg или положите ffmpeg.exe в video-converter/bin/');
      }
      if (h.output_dir && !outputDir.value) {
        outputDir.placeholder = h.output_dir;
      }
    } catch (e) {
      ffmpegStatus.textContent = 'Сервер недоступен';
      ffmpegStatus.className = 'status-badge bad';
      log(`Ошибка health: ${e.message}`);
    }
  }

  async function loadPresets() {
    const presets = await api('/api/presets');
    presetSelect.innerHTML = presets
      .map((p) => `<option value="${p.id}">${p.label}</option>`)
      .join('');
  }

  function updateSelectedUI() {
    const total = selectedFiles.length + pathQueue.length;
    btnUpload.disabled = selectedFiles.length === 0;
    btnConcat.disabled = pathQueue.length < 2 && selectedFiles.length < 2;

    let el = dropzone.querySelector('.selected-files');
    if (!el) {
      el = document.createElement('div');
      el.className = 'selected-files';
      dropzone.querySelector('.dropzone-inner').appendChild(el);
    }
    if (total === 0) {
      el.textContent = '';
      return;
    }
    const names = [
      ...selectedFiles.map((f) => f.name),
      ...pathQueue.map((p) => p.split(/[/\\]/).pop()),
    ];
    el.textContent = `Выбрано: ${names.join(', ')}`;
  }

  function statusLabel(st) {
    const map = {
      pending: 'В очереди',
      running: 'Конвертация…',
      completed: 'Готово',
      failed: 'Ошибка',
      cancelled: 'Отменено',
    };
    return map[st] || st;
  }

  function renderJob(job) {
    const pct = job.progress || 0;
    let barClass = '';
    if (job.status === 'completed') barClass = 'done';
    if (job.status === 'failed') barClass = 'fail';

    const meta = job.probe
      ? `${job.probe.width || '?'}×${job.probe.height || '?'} · ${formatDuration(job.probe.duration_sec)}`
      : '';

    const actions = [];
    if (job.status === 'completed') {
      actions.push(
        `<a class="btn secondary small" href="/api/jobs/${job.id}/download" download>Скачать</a>`,
      );
    }
    if (job.status === 'pending' || job.status === 'running') {
      actions.push(
        `<button type="button" class="btn ghost small" data-cancel="${job.id}">Отмена</button>`,
      );
    }
    if (job.error) {
      actions.push(`<span class="muted" style="font-size:0.75rem">${escapeHtml(job.error)}</span>`);
    }

    return `
      <div class="job-card" data-id="${job.id}">
        <div class="job-head">
          <div>
            <div class="job-name">${escapeHtml(job.input_name)}</div>
            <div class="job-meta">→ ${escapeHtml(job.output_name)} ${meta ? '· ' + meta : ''}</div>
          </div>
          <span class="status-pill ${job.status}">${statusLabel(job.status)}</span>
        </div>
        <div class="progress-wrap">
          <div class="progress-bar ${barClass}" style="width:${pct}%"></div>
        </div>
        <div class="job-meta">${pct.toFixed(0)}%</div>
        <div class="job-actions">${actions.join('')}</div>
      </div>`;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function formatDuration(sec) {
    if (!sec) return '';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  async function refreshQueue() {
    try {
      const { jobs } = await api('/api/jobs');
      queueCount.textContent = `${jobs.length} задач`;
      queueEmpty.classList.toggle('hidden', jobs.length > 0);
      queueList.innerHTML = jobs.map(renderJob).join('');

      queueList.querySelectorAll('[data-cancel]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const id = btn.getAttribute('data-cancel');
          try {
            await api(`/api/jobs/${id}`, { method: 'DELETE' });
            log(`Отменено: ${id}`);
            refreshQueue();
          } catch (e) {
            log(`Отмена: ${e.message}`);
          }
        });
      });

      const active = jobs.some((j) => j.status === 'pending' || j.status === 'running');
      if (active && !pollTimer) {
        pollTimer = setInterval(refreshQueue, 1500);
      } else if (!active && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    } catch (e) {
      log(`Очередь: ${e.message}`);
    }
  }

  async function uploadFiles() {
    if (!selectedFiles.length) return;
    const fd = new FormData();
    selectedFiles.forEach((f) => fd.append('files', f));
    fd.append('preset_id', presetSelect.value);
    if (outputDir.value.trim()) {
      fd.append('output_dir', outputDir.value.trim());
    }
    btnUpload.disabled = true;
    try {
      const res = await api('/api/jobs/upload', { method: 'POST', body: fd });
      log(`Добавлено ${res.jobs.length} задач (upload)`);
      selectedFiles = [];
      fileInput.value = '';
      updateSelectedUI();
      refreshQueue();
    } catch (e) {
      log(`Upload: ${e.message}`);
      alert(e.message);
    } finally {
      btnUpload.disabled = selectedFiles.length === 0;
    }
  }

  async function submitPaths(paths) {
    const body = {
      paths,
      preset_id: presetSelect.value,
      output_dir: outputDir.value.trim() || null,
    };
    const res = await api('/api/jobs/path', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    log(`Добавлено ${res.jobs.length} задач (path)`);
    pathQueue = [];
    updateSelectedUI();
    refreshQueue();
  }

  async function concatPaths(paths) {
    const body = {
      paths,
      preset_id: presetSelect.value,
      output_dir: outputDir.value.trim() || null,
    };
    const res = await api('/api/jobs/concat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    log(`Склейка → ${res.jobs.length} задач`);
    pathQueue = [];
    selectedFiles = [];
    updateSelectedUI();
    refreshQueue();
  }

  // Events
  dropzone.addEventListener('click', () => fileInput.click());
  dropzone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      fileInput.click();
    }
  });

  ['dragenter', 'dragover'].forEach((ev) => {
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
  });
  ['dragleave', 'drop'].forEach((ev) => {
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
    });
  });

  dropzone.addEventListener('drop', (e) => {
    const files = [...(e.dataTransfer?.files || [])];
    if (files.length) {
      selectedFiles = files;
      updateSelectedUI();
    }
  });

  fileInput.addEventListener('change', () => {
    selectedFiles = [...fileInput.files];
    updateSelectedUI();
  });

  btnUpload.addEventListener('click', uploadFiles);

  btnPath.addEventListener('click', () => {
    const raw = prompt(
      'Полный путь к файлу (можно несколько через ;):\nПример: D:\\Videos\\movie.vob',
    );
    if (!raw) return;
    const paths = raw.split(';').map((s) => s.trim()).filter(Boolean);
    pathQueue.push(...paths);
    updateSelectedUI();
    submitPaths(paths).catch((e) => {
      alert(e.message);
      log(`Path: ${e.message}`);
    });
  });

  btnConcat.addEventListener('click', () => {
    const paths = pathQueue.length >= 2
      ? pathQueue
      : null;
    if (!paths) {
      const raw = prompt(
        'Пути к частям для склейки (через ;):\nПример: D:\\DVD\\VTS_01_1.VOB;D:\\DVD\\VTS_01_2.VOB',
      );
      if (!raw) return;
      const parsed = raw.split(';').map((s) => s.trim()).filter(Boolean);
      if (parsed.length < 2) {
        alert('Нужно минимум 2 файла');
        return;
      }
      concatPaths(parsed).catch((e) => {
        alert(e.message);
        log(`Concat: ${e.message}`);
      });
      return;
    }
    concatPaths(paths).catch((e) => {
      alert(e.message);
      log(`Concat: ${e.message}`);
    });
  });

  btnRefresh.addEventListener('click', refreshQueue);

  pickFolder.addEventListener('click', async () => {
    if (window.showDirectoryPicker) {
      try {
        const handle = await window.showDirectoryPicker();
        outputDir.value = handle.name + ' (выберите полный путь вручную при необходимости)';
        log('Для надёжности укажите полный путь к папке в поле ввода, например C:\\Videos\\output');
      } catch {
        /* cancelled */
      }
    } else {
      alert('Укажите полный путь к папке в поле ввода, например:\nC:\\Users\\Имя\\Videos\\output');
    }
  });

  logToggle.addEventListener('click', () => {
    logBox.classList.toggle('hidden');
    logToggle.textContent = logBox.classList.contains('hidden') ? 'Журнал ▸' : 'Журнал ▾';
  });

  // Init
  (async () => {
    await loadPresets();
    await loadHealth();
    await refreshQueue();
    log('Video Converter готов');
  })();
})();
