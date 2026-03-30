"""
dashboard.py — Interface web de contrôle du pipeline audiobook MVS

Stack : FastAPI + HTMX + Server-Sent Events
Pas de React, pas de Node, pas de build step.

Démarrage :
  pip install fastapi uvicorn aiofiles
  python dashboard.py

Accès : http://localhost:8000
"""

import asyncio
import json
import os
import subprocess
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn


# ─── Config ────────────────────────────────────────────────────────────────────

STATE_FILE    = "data/state.json"
CHAPTERS_DIR  = "data/chapitres"
OUTPUT_DIR    = "data/audio"

app = FastAPI(title="MVS Audiobook Dashboard")


# ─── Lecture de l'état ─────────────────────────────────────────────────────────

def read_state() -> dict:
    path = Path(STATE_FILE)
    if not path.exists():
        return {
            "status": "idle",
            "chapters": {},
            "workers": [],
            "logs": [],
            "started_at": None,
            "updated_at": None,
        }
    return json.loads(path.read_text())


def write_state(data: dict):
    Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(STATE_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ─── SSE : Server-Sent Events ──────────────────────────────────────────────────

async def state_event_generator():
    """
    Envoie l'état complet toutes les secondes via SSE.
    Le dashboard HTMX écoute ce flux et met à jour l'UI en temps réel.
    """
    last_updated = None
    while True:
        state = read_state()
        updated = state.get("updated_at")

        if updated != last_updated:
            last_updated = updated
            payload = json.dumps(state, ensure_ascii=False)
            yield f"data: {payload}\n\n"

        await asyncio.sleep(1.0)


@app.get("/events")
async def sse_events():
    return StreamingResponse(
        state_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ─── API de contrôle ───────────────────────────────────────────────────────────

@app.post("/api/start")
async def api_start():
    """Lance le pipeline sur tous les chapitres du dossier."""
    state = read_state()
    if state["status"] == "running":
        return JSONResponse({"ok": False, "msg": "Déjà en cours"})

    chapters_dir = Path(CHAPTERS_DIR)
    if not chapters_dir.exists():
        return JSONResponse({"ok": False, "msg": f"Dossier introuvable : {CHAPTERS_DIR}"})

    # Lance pipeline.py en sous-processus pour ne pas bloquer le dashboard
    subprocess.Popen(
        ["python", "pipeline.py", "--chapters", CHAPTERS_DIR],
        cwd=Path(__file__).parent
    )
    return JSONResponse({"ok": True})


@app.post("/api/pause")
async def api_pause():
    state = read_state()
    if state["status"] == "running":
        state["status"] = "paused"
        write_state(state)
    return JSONResponse({"ok": True})


@app.post("/api/resume")
async def api_resume():
    state = read_state()
    if state["status"] == "paused":
        state["status"] = "running"
        write_state(state)
    return JSONResponse({"ok": True})


@app.post("/api/retry/{chapter_id}")
async def api_retry(chapter_id: str):
    """Remet un chapitre en 'pending' pour qu'il soit re-traité."""
    state = read_state()
    if chapter_id in state["chapters"]:
        state["chapters"][chapter_id]["status"] = "pending"
        state["chapters"][chapter_id]["chunks_done"] = 0
        state["chapters"][chapter_id]["chunks_error"] = 0
        write_state(state)
    return JSONResponse({"ok": True})


@app.get("/api/audio/{chapter_id}")
async def api_audio(chapter_id: str):
    """Retourne l'URL du .mp3 d'un chapitre si disponible."""
    mp3 = Path(OUTPUT_DIR) / "mp3" / f"Chapitre_{chapter_id}.mp3"
    if mp3.exists():
        return JSONResponse({"ok": True, "url": f"/audio/mp3/Chapitre_{chapter_id}.mp3"})
    return JSONResponse({"ok": False})


@app.get("/api/state")
async def api_state():
    return JSONResponse(read_state())


# ─── Servir les fichiers audio ─────────────────────────────────────────────────

audio_dir = Path(OUTPUT_DIR)
audio_dir.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(audio_dir)), name="audio")


# ─── Page principale ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(DASHBOARD_HTML)


# ─── HTML du dashboard ─────────────────────────────────────────────────────────
# Tout-en-un : HTML + CSS + JS inline, pas de fichiers externes sauf HTMX

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MVS Audiobook Pipeline</title>
<style>
  :root {
    --bg:       #0f1117;
    --bg2:      #1a1d27;
    --bg3:      #22263a;
    --border:   #2e3350;
    --text:     #e2e4f0;
    --muted:    #6b7099;
    --accent:   #7c6af7;
    --green:    #3ecf8e;
    --amber:    #f5a623;
    --red:      #f04545;
    --blue:     #4a9eff;
    --radius:   8px;
    --font:     'JetBrains Mono', 'Fira Code', monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    font-size: 13px;
    line-height: 1.6;
    min-height: 100vh;
  }

  /* Layout */
  .header {
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: var(--bg2);
  }
  .header h1 {
    font-size: 15px;
    font-weight: 600;
    color: var(--accent);
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .header .version { color: var(--muted); font-size: 11px; }

  .layout {
    display: grid;
    grid-template-columns: 320px 1fr;
    height: calc(100vh - 57px);
  }

  /* Sidebar */
  .sidebar {
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .sidebar-section {
    padding: 16px;
    border-bottom: 1px solid var(--border);
  }
  .sidebar-section h2 {
    font-size: 10px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 12px;
  }

  /* Contrôles */
  .controls { display: flex; gap: 8px; flex-wrap: wrap; }
  .btn {
    border: 1px solid var(--border);
    background: var(--bg3);
    color: var(--text);
    font-family: var(--font);
    font-size: 12px;
    padding: 7px 14px;
    border-radius: var(--radius);
    cursor: pointer;
    transition: all 0.15s;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .btn:hover { border-color: var(--accent); color: var(--accent); }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  .btn.primary:hover { opacity: 0.85; }
  .btn.danger { border-color: var(--red); color: var(--red); }

  /* Status badge */
  .status-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .status-badge::before {
    content: '';
    width: 7px; height: 7px;
    border-radius: 50%;
    background: currentColor;
  }
  .status-idle    { color: var(--muted);  background: rgba(107,112,153,0.12); }
  .status-running { color: var(--green);  background: rgba(62,207,142,0.12); }
  .status-paused  { color: var(--amber);  background: rgba(245,166,35,0.12); }
  .status-done    { color: var(--blue);   background: rgba(74,158,255,0.12); }
  .status-error   { color: var(--red);    background: rgba(240,69,69,0.12); }

  /* Stats bar */
  .stats-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .stat-card {
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px 12px;
  }
  .stat-card .label { color: var(--muted); font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; }
  .stat-card .value { font-size: 20px; font-weight: 700; margin-top: 2px; }

  /* Liste chapitres */
  .chapters-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px;
  }
  .chapter-item {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px 12px;
    margin-bottom: 4px;
    background: var(--bg2);
    cursor: default;
    transition: border-color 0.15s;
  }
  .chapter-item:hover { border-color: var(--accent); }
  .chapter-item .ch-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
  }
  .chapter-item .ch-id { font-weight: 600; color: var(--accent); }
  .progress-bar {
    height: 4px;
    background: var(--bg3);
    border-radius: 2px;
    overflow: hidden;
    margin-top: 4px;
  }
  .progress-fill {
    height: 100%;
    background: var(--green);
    border-radius: 2px;
    transition: width 0.5s ease;
  }
  .progress-fill.error { background: var(--red); }

  .ch-actions { display: flex; gap: 6px; margin-top: 8px; }
  .ch-btn {
    font-family: var(--font);
    font-size: 10px;
    padding: 3px 8px;
    border-radius: 4px;
    border: 1px solid var(--border);
    background: var(--bg3);
    color: var(--muted);
    cursor: pointer;
    transition: all 0.15s;
  }
  .ch-btn:hover { color: var(--text); border-color: var(--text); }
  .ch-btn.play  { color: var(--green); border-color: var(--green); }

  /* Logs */
  .main-panel {
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .log-panel {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    background: var(--bg);
  }
  .log-entry {
    display: flex;
    gap: 10px;
    padding: 3px 0;
    border-bottom: 1px solid rgba(46,51,80,0.4);
    font-size: 12px;
  }
  .log-ts    { color: var(--muted); flex-shrink: 0; }
  .log-level { flex-shrink: 0; width: 36px; text-align: center; font-size: 10px; font-weight: 700; border-radius: 3px; padding: 1px 4px; }
  .log-level.info  { color: var(--blue);  background: rgba(74,158,255,0.1); }
  .log-level.warn  { color: var(--amber); background: rgba(245,166,35,0.1); }
  .log-level.error { color: var(--red);   background: rgba(240,69,69,0.1); }
  .log-msg { color: var(--text); }

  /* Audio player */
  .audio-panel {
    border-top: 1px solid var(--border);
    padding: 12px 16px;
    background: var(--bg2);
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .audio-panel audio { flex: 1; height: 32px; }
  .audio-label { color: var(--muted); font-size: 11px; min-width: 80px; }
  audio { accent-color: var(--accent); }
  audio::-webkit-media-controls-panel { background: var(--bg3); }
</style>
</head>
<body>

<header class="header">
  <h1>MVS Audiobook Pipeline</h1>
  <div style="display:flex;align-items:center;gap:12px">
    <span id="status-badge" class="status-badge status-idle">idle</span>
    <span class="version">Qwen3-TTS 1.7B • vLLM-Omni</span>
  </div>
</header>

<div class="layout">

  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="sidebar-section">
      <h2>Contrôles</h2>
      <div class="controls">
        <button class="btn primary" onclick="startPipeline()">▶ Démarrer</button>
        <button class="btn" id="btn-pause" onclick="togglePause()">⏸ Pause</button>
        <button class="btn danger" onclick="if(confirm('Réinitialiser l\\'état ?')) resetState()">↺ Reset</button>
      </div>
    </div>

    <div class="sidebar-section">
      <h2>Progression globale</h2>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="label">Chapitres terminés</div>
          <div class="value" id="stat-done">0</div>
        </div>
        <div class="stat-card">
          <div class="label">Total chapitres</div>
          <div class="value" id="stat-total">0</div>
        </div>
        <div class="stat-card">
          <div class="label">Chunks traités</div>
          <div class="value" id="stat-chunks">0</div>
        </div>
        <div class="stat-card">
          <div class="label">Erreurs</div>
          <div class="value" id="stat-errors" style="color:var(--red)">0</div>
        </div>
      </div>
    </div>

    <div class="sidebar-section" style="flex:1;overflow:hidden;display:flex;flex-direction:column;padding-bottom:0">
      <h2>Chapitres</h2>
      <div class="chapters-list" id="chapters-list">
        <div style="color:var(--muted);padding:8px 0">En attente de données…</div>
      </div>
    </div>
  </aside>

  <!-- Panel principal -->
  <main class="main-panel">
    <div class="log-panel" id="log-panel">
      <div style="color:var(--muted);text-align:center;padding:40px 0">
        Les logs apparaîtront ici au démarrage du pipeline…
      </div>
    </div>

    <!-- Player audio -->
    <div class="audio-panel">
      <span class="audio-label" id="audio-label">Aucun audio</span>
      <audio id="audio-player" controls></audio>
    </div>
  </main>

</div>

<script>
// ─── SSE : écoute l'état en temps réel ──────────────────────────────────────

let isPaused = false;
const evtSource = new EventSource('/events');

evtSource.onmessage = (e) => {
  const state = JSON.parse(e.data);
  updateUI(state);
};

evtSource.onerror = () => {
  console.warn('SSE déconnecté, reconnexion...');
};

// ─── Mise à jour de l'interface ──────────────────────────────────────────────

function updateUI(state) {
  // Status badge
  const badge = document.getElementById('status-badge');
  badge.className = `status-badge status-${state.status}`;
  badge.textContent = statusLabel(state.status);
  isPaused = state.status === 'paused';
  document.getElementById('btn-pause').textContent = isPaused ? '▶ Reprendre' : '⏸ Pause';

  // Stats globales
  const chapters = Object.values(state.chapters || {});
  const done     = chapters.filter(c => c.status === 'done').length;
  const errors   = chapters.reduce((s, c) => s + (c.chunks_error || 0), 0);
  const chunksOk = chapters.reduce((s, c) => s + (c.chunks_done || 0), 0);

  document.getElementById('stat-done').textContent   = done;
  document.getElementById('stat-total').textContent  = chapters.length;
  document.getElementById('stat-chunks').textContent = chunksOk;
  document.getElementById('stat-errors').textContent = errors;

  // Liste chapitres
  renderChapters(state.chapters || {});

  // Logs
  renderLogs(state.logs || []);
}

function statusLabel(s) {
  const map = { idle:'En attente', running:'En cours', paused:'En pause', done:'Terminé', error:'Erreur' };
  return map[s] || s;
}

// ─── Rendu des chapitres ─────────────────────────────────────────────────────

function renderChapters(chapters) {
  const list = document.getElementById('chapters-list');
  const ids  = Object.keys(chapters).sort();

  if (!ids.length) {
    list.innerHTML = '<div style="color:var(--muted);padding:8px 0">Aucun chapitre chargé</div>';
    return;
  }

  list.innerHTML = ids.map(id => {
    const ch      = chapters[id];
    const pct     = ch.chunks_total > 0 ? Math.round((ch.chunks_done / ch.chunks_total) * 100) : 0;
    const hasError = ch.chunks_error > 0;
    const isDone   = ch.status === 'done';
    const statusC  = isDone ? 'var(--green)' : hasError ? 'var(--amber)' : 'var(--muted)';

    return `
    <div class="chapter-item">
      <div class="ch-header">
        <span class="ch-id">Chap. ${id}</span>
        <span style="color:${statusC};font-size:11px">${pct}% • ${ch.chunks_done}/${ch.chunks_total}</span>
      </div>
      <div class="progress-bar">
        <div class="progress-fill ${hasError ? 'error' : ''}" style="width:${pct}%"></div>
      </div>
      <div class="ch-actions">
        ${isDone ? `<button class="ch-btn play" onclick="playChapter('${id}')">▶ Écouter</button>` : ''}
        ${ch.status === 'error' || ch.chunks_error > 0 ? `<button class="ch-btn" onclick="retryChapter('${id}')">↺ Retry</button>` : ''}
        <span style="color:var(--muted);font-size:10px;margin-left:auto">${ch.chunks_error > 0 ? ch.chunks_error + ' erreur(s)' : ''}</span>
      </div>
    </div>`;
  }).join('');
}

// ─── Rendu des logs ──────────────────────────────────────────────────────────

let lastLogCount = 0;

function renderLogs(logs) {
  if (logs.length === lastLogCount) return;
  lastLogCount = logs.length;

  const panel = document.getElementById('log-panel');
  const isScrolledToBottom = panel.scrollHeight - panel.clientHeight <= panel.scrollTop + 10;

  panel.innerHTML = logs.slice(-150).map(l => `
    <div class="log-entry">
      <span class="log-ts">${l.ts}</span>
      <span class="log-level ${l.level}">${l.level.toUpperCase()}</span>
      <span class="log-msg">${escapeHtml(l.message)}</span>
    </div>`).join('');

  if (isScrolledToBottom) {
    panel.scrollTop = panel.scrollHeight;
  }
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ─── Actions ─────────────────────────────────────────────────────────────────

async function startPipeline() {
  const r = await fetch('/api/start', { method: 'POST' });
  const d = await r.json();
  if (!d.ok) alert('Erreur : ' + d.msg);
}

async function togglePause() {
  const endpoint = isPaused ? '/api/resume' : '/api/pause';
  await fetch(endpoint, { method: 'POST' });
}

async function retryChapter(id) {
  await fetch(`/api/retry/${id}`, { method: 'POST' });
}

async function playChapter(id) {
  const r = await fetch(`/api/audio/${id}`);
  const d = await r.json();
  if (d.ok) {
    const player = document.getElementById('audio-player');
    const label  = document.getElementById('audio-label');
    player.src   = d.url;
    label.textContent = `Chap. ${id}`;
    player.play();
  } else {
    alert('Audio non disponible');
  }
}

async function resetState() {
  await fetch('/api/state/reset', { method: 'POST' });
  location.reload();
}
</script>
</body>
</html>"""


# ─── Route reset ───────────────────────────────────────────────────────────────

@app.post("/api/state/reset")
async def api_reset():
    path = Path(STATE_FILE)
    if path.exists():
        path.unlink()
    return JSONResponse({"ok": True})


# ─── Lancement ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Dashboard MVS démarré → http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
