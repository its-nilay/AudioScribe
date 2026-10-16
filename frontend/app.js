/**
 * AudioScribe — app.js
 * Handles all UI state, API calls, polling, and interactions.
 */

const API = 'http://127.0.0.1:8000';
const POLL_INTERVAL = 3000; // ms

/* ── DOM refs ────────────────────────────────────────────── */
const $ = id => document.getElementById(id);
const apiStatus      = $('apiStatus');
const dropZone       = $('dropZone');
const fileInput      = $('fileInput');
const fileInfo       = $('fileInfo');
const fileName       = $('fileName');
const fileSize       = $('fileSize');
const clearFile      = $('clearFile');
const submitBtn      = $('submitBtn');
const uploadCard     = $('uploadCard');
const processCard    = $('processCard');
const processStatus  = $('processStatus');
const progressBar    = $('progressBar');
const jobIdDisplay   = $('jobIdDisplay');
const resultCard     = $('resultCard');
const langBadge      = $('langBadge');
const chunkBadge     = $('chunkBadge');
const copyBtn        = $('copyBtn');
const downloadBtn    = $('downloadBtn');
const newBtn         = $('newTranscriptionBtn');
const transcriptText = $('transcriptText');
const transcriptEmpty= $('transcriptEmpty');
const segmentsList   = $('segmentsList');
const audioPlayer    = $('audioPlayer');
const audioFilenameBadge = $('audioFilenameBadge');
const errorCard      = $('errorCard');
const errorMsg       = $('errorMsg');
const retryBtn       = $('retryBtn');

let selectedFile = null;
let pollTimer    = null;
let lastJobData  = null;

/* ── Health check ────────────────────────────────────────── */
// Use AbortController with setTimeout for broad browser compatibility
// (AbortSignal.timeout() is not available in older browsers)
async function checkHealth() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 3000);
  try {
    const r = await fetch(`${API}/health`, { signal: controller.signal });
    clearTimeout(timer);
    if (r.ok) {
      apiStatus.className = 'api-status online';
      apiStatus.innerHTML = '<span class="dot"></span> API online';
    } else {
      throw new Error('non-200');
    }
  } catch {
    clearTimeout(timer);
    apiStatus.className = 'api-status offline';
    apiStatus.innerHTML = '<span class="dot"></span> API offline';
  }
}
checkHealth();
setInterval(checkHealth, 10000);

/* ── Format helpers ──────────────────────────────────────── */
function fmtBytes(n) {
  if (n < 1024)       return `${n} B`;
  if (n < 1024*1024)  return `${(n/1024).toFixed(1)} KB`;
  return `${(n/1024/1024).toFixed(2)} MB`;
}
function fmtTime(sec) {
  const m = Math.floor(sec / 60);
  const s = (sec % 60).toFixed(1).padStart(4, '0');
  return `${String(m).padStart(2,'0')}:${s}`;
}

/* ── File selection ──────────────────────────────────────── */
function selectFile(file) {
  if (!file) return;
  const allowed = ['.wav', '.mp3', '.m4a', '.ogg', '.flac', '.webm'];
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  if (!allowed.includes(ext)) {
    showToast(`⚠ Unsupported format: ${ext}`);
    return;
  }
  selectedFile = file;
  fileName.textContent = file.name;
  fileSize.textContent = fmtBytes(file.size);
  fileInfo.classList.remove('hidden');
  submitBtn.disabled = false;
}

function clearSelection() {
  selectedFile = null;
  fileInput.value = '';
  fileInfo.classList.add('hidden');
  submitBtn.disabled = true;
}

/* ── Drag & drop ─────────────────────────────────────────── */
// FIX: clicking the drop-zone shouldn't bubble when the click
// originates from the <label> inside it (which already opens the picker)
dropZone.addEventListener('click', (e) => {
  if (e.target.tagName === 'LABEL' || e.target.closest('label')) return;
  fileInput.click();
});
dropZone.addEventListener('keydown', e => {
  if (e.key === 'Enter' || e.key === ' ') fileInput.click();
});
fileInput.addEventListener('change', () => selectFile(fileInput.files[0]));

dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});
dropZone.addEventListener('dragleave', e => {
  // Only remove if the pointer truly left the drop zone (not just moved to a child)
  if (!dropZone.contains(e.relatedTarget)) {
    dropZone.classList.remove('drag-over');
  }
});
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  selectFile(e.dataTransfer.files[0]);
});

clearFile.addEventListener('click', e => {
  e.stopPropagation(); // don't trigger dropZone click
  clearSelection();
});

/* ── Submit ──────────────────────────────────────────────── */
submitBtn.addEventListener('click', startTranscription);

async function startTranscription() {
  if (!selectedFile) return;

  // Switch to processing view
  uploadCard.classList.add('hidden');
  errorCard.classList.add('hidden');
  resultCard.classList.add('hidden');
  processCard.classList.remove('hidden');
  processStatus.textContent = 'Uploading audio file…';
  setProgress(10);
  jobIdDisplay.textContent = '—';
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }

  const form = new FormData();
  form.append('file', selectedFile);

  let jobId;
  try {
    const r = await fetch(`${API}/transcriptions`, { method: 'POST', body: form });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || `HTTP ${r.status}`);
    }
    const data = await r.json();
    jobId = data.job_id;
  } catch (err) {
    // FIX: show upload card again so user isn't stuck with blank screen
    showError(err.message);
    return;
  }

  jobIdDisplay.textContent = jobId;
  processStatus.textContent = 'Queued — Whisper model loading…';
  setProgress(30);

  // Poll for result
  let attempts = 0;
  pollTimer = setInterval(async () => {
    attempts++;
    try {
      const r2 = await fetch(`${API}/transcriptions/${jobId}`);
      if (!r2.ok) return; // transient network issue — keep polling
      const data = await r2.json();

      if (data.status === 'processing') {
        processStatus.textContent = 'Running speech recognition…';
        setProgress(Math.min(30 + attempts * 5, 85));
      } else if (data.status === 'completed') {
        clearInterval(pollTimer);
        pollTimer = null;
        setProgress(100);
        processStatus.textContent = 'Done!';
        setTimeout(() => showResult(data), 400);
      } else if (data.status === 'failed') {
        clearInterval(pollTimer);
        pollTimer = null;
        showError(data.error || 'Unknown error from server.');
      }
      // 'pending' — keep polling silently
    } catch {
      // network blip — keep polling
    }
  }, POLL_INTERVAL);
}

/* ── Progress ────────────────────────────────────────────── */
function setProgress(pct) {
  progressBar.style.width = pct + '%';
}

/* ── Show result ─────────────────────────────────────────── */
function showResult(data) {
  processCard.classList.add('hidden');
  resultCard.classList.remove('hidden');
  lastJobData = data;

  // Language badge — always reset classes first
  langBadge.textContent = '';
  langBadge.classList.add('hidden');
  if (data.language) {
    langBadge.textContent = `🌐 ${data.language.toUpperCase()}`;
    langBadge.classList.remove('hidden');
  }

  // Chunk badge — only show when more than one chunk was used
  chunkBadge.textContent = '';
  chunkBadge.classList.add('hidden');
  if (data.chunk_count && data.chunk_count > 1) {
    chunkBadge.textContent = `${data.chunk_count} chunks`;
    chunkBadge.classList.remove('hidden');
  }

  // Transcript text
  if (data.text && data.text.trim()) {
    transcriptText.textContent = data.text.trim();
    transcriptText.classList.remove('hidden');
    transcriptEmpty.classList.add('hidden');
  } else {
    transcriptText.classList.add('hidden');
    transcriptEmpty.classList.remove('hidden');
  }

  // Audio player setup
  const originalFileName = (selectedFile && selectedFile.name) || data.filename || 'audio.wav';
  if (audioFilenameBadge) {
    audioFilenameBadge.textContent = originalFileName;
  }
  if (selectedFile) {
    audioPlayer.src = URL.createObjectURL(selectedFile);
  } else if (data.audio_url) {
    audioPlayer.src = `${API}${data.audio_url}`;
  } else if (data.job_id) {
    audioPlayer.src = `${API}/transcriptions/${data.job_id}/audio`;
  }
  audioPlayer.load();

  // Segments timeline
  segmentsList.innerHTML = '';
  if (data.segments && data.segments.length > 0) {
    data.segments.forEach((seg, i) => {
      const item = document.createElement('div');
      item.className = 'segment-item';
      item.dataset.start = seg.start;
      item.dataset.end = seg.end;
      item.style.animationDelay = `${i * 40}ms`;
      item.title = 'Click to listen to this segment';
      item.innerHTML = `
        <span class="segment-time">${fmtTime(seg.start)} → ${fmtTime(seg.end)}</span>
        <span class="segment-text">${escHtml(seg.text)}</span>
        <span class="segment-play-hint">▶ Listen</span>
      `;

      // Click segment to jump audio and play
      item.addEventListener('click', () => {
        audioPlayer.currentTime = seg.start;
        audioPlayer.play();
        highlightActiveSegment(seg.start);
      });

      segmentsList.appendChild(item);
    });
  } else {
    segmentsList.innerHTML = '<p class="no-segments">No timestamped segments detected.</p>';
  }
}

/* ── Audio sync highlighting ─────────────────────────────── */
audioPlayer.addEventListener('timeupdate', () => {
  highlightActiveSegment(audioPlayer.currentTime);
});

function highlightActiveSegment(time) {
  const items = segmentsList.querySelectorAll('.segment-item');
  items.forEach(item => {
    const start = parseFloat(item.dataset.start);
    const end = parseFloat(item.dataset.end);
    if (!isNaN(start) && !isNaN(end) && time >= start && time <= end) {
      if (!item.classList.contains('active')) {
        item.classList.add('active');
        item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    } else {
      item.classList.remove('active');
    }
  });
}

/* ── Show error ──────────────────────────────────────────── */
function showError(msg) {
  processCard.classList.add('hidden');
  uploadCard.classList.add('hidden');
  resultCard.classList.add('hidden');
  errorCard.classList.remove('hidden');
  errorMsg.textContent = msg;
}

/* ── Copy / Download / New ───────────────────────────────── */
copyBtn.addEventListener('click', async () => {
  const text = lastJobData && lastJobData.text ? lastJobData.text.trim() : '';
  if (!text) { showToast('Nothing to copy — transcript is empty.'); return; }
  try {
    await navigator.clipboard.writeText(text);
    showToast('✓ Transcript copied to clipboard');
  } catch {
    showToast('⚠ Could not access clipboard');
  }
});

downloadBtn.addEventListener('click', () => {
  if (!lastJobData) return;
  const blob = new Blob([JSON.stringify(lastJobData, null, 2)], { type: 'application/json' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `transcript-${(lastJobData.job_id || 'result').slice(0, 8)}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast('📥 JSON downloaded');
});

function resetToUpload() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  clearSelection();
  if (audioPlayer) {
    audioPlayer.pause();
    audioPlayer.removeAttribute('src');
    audioPlayer.load();
  }
  resultCard.classList.add('hidden');
  errorCard.classList.add('hidden');
  processCard.classList.add('hidden');
  uploadCard.classList.remove('hidden');
  setProgress(0);
  lastJobData = null;
}
newBtn.addEventListener('click', resetToUpload);
retryBtn.addEventListener('click', resetToUpload);

/* ── Toast ───────────────────────────────────────────────── */
let toastEl    = null;
let toastTimer = null;
function showToast(msg, duration = 2800) {
  if (!toastEl) {
    toastEl = document.createElement('div');
    toastEl.className = 'toast';
    document.body.appendChild(toastEl);
  }
  toastEl.textContent = msg;
  toastEl.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove('show'), duration);
}

/* ── Utils ───────────────────────────────────────────────── */
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
