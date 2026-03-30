"""
pipeline.py — Orchestrateur principal du pipeline audiobook MVS

Ce fichier coordonne tout :
  1. Lecture des chapitres .txt
  2. Chunking via chunker.py
  3. (Optionnel) Annotation Claude Haiku
  4. Envoi async au serveur TTS Vast.ai
  5. Assemblage des .wav en .mp3 via FFmpeg
  6. Mise à jour de l'état dans state.json (suivi dashboard)

Usage :
  python pipeline.py --chapters data/chapitres/ --output data/audio/
  python pipeline.py --chapter data/chapitres/Chapitre_0509.txt
"""

import asyncio
import aiohttp
import aiofiles
import json
import time
import subprocess
import sys
from pathlib import Path
from datetime import datetime

from chunker import chunk_chapter


# ─── Configuration ─────────────────────────────────────────────────────────────

CONFIG = {
    # URL du serveur TTS (tunnel SSH ou direct sur Vast)
    "tts_url":          "http://127.0.0.1:7860",

    # Nombre de workers TTS parallèles (commence à 2, augmente si stable)
    "num_workers":      2,

    # Mapping voix → LoRA / voice_id sur le serveur
    "voice_map": {
        "narrator":  "narrator_fr_v2",
        "dialogue":  "narrator_fr_v2",   # même voix, paramètres différents
        "thought":   "feminine_fr",
    },

    # Paramètres expressivité par type (passés au serveur en JSON)
    "voice_params": {
        "narrator":  {"speed": 1.0, "style": "narration calme"},
        "dialogue":  {"speed": 1.05, "style": "dialogue expressif"},
        "thought":   {"speed": 0.95, "style": "pensée intérieure, douce"},
    },

    # Répertoires
    "chapters_dir":     "data/chapitres",
    "output_dir":       "data/audio",
    "state_file":       "data/state.json",
    "chunks_cache_dir": "data/chunks_cache",

    # Retry en cas d'erreur TTS
    "max_retries":      3,
    "retry_delay":      2.0,   # secondes entre retries
}


# ─── Gestion de l'état (pour le dashboard) ─────────────────────────────────────

class PipelineState:
    """
    Sauvegarde l'état du pipeline dans un fichier JSON.
    Le dashboard le lit en temps réel via SSE.
    """

    def __init__(self, state_file: str):
        self.path = Path(state_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {
            "status":    "idle",       # idle | running | paused | done | error
            "chapters":  {},           # chapitre_id → {status, chunks_total, chunks_done, ...}
            "workers":   [],           # état de chaque worker
            "logs":      [],           # derniers logs (max 200)
            "started_at": None,
            "updated_at": None,
        }

    def save(self):
        self._data["updated_at"] = datetime.now().isoformat()
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2))

    def set_status(self, status: str):
        self._data["status"] = status
        self.save()

    def init_chapter(self, chapter_id: str, total_chunks: int):
        self._data["chapters"][chapter_id] = {
            "status":       "pending",   # pending | running | done | error
            "chunks_total": total_chunks,
            "chunks_done":  0,
            "chunks_error": 0,
            "started_at":   None,
            "finished_at":  None,
        }
        self.save()

    def update_chapter(self, chapter_id: str, **kwargs):
        if chapter_id in self._data["chapters"]:
            self._data["chapters"][chapter_id].update(kwargs)
            self.save()

    def chunk_done(self, chapter_id: str, success: bool = True):
        ch = self._data["chapters"].get(chapter_id, {})
        if success:
            ch["chunks_done"] = ch.get("chunks_done", 0) + 1
        else:
            ch["chunks_error"] = ch.get("chunks_error", 0) + 1
        self._data["chapters"][chapter_id] = ch
        self.save()

    def log(self, message: str, level: str = "info"):
        entry = {
            "ts":      datetime.now().strftime("%H:%M:%S"),
            "level":   level,   # info | warn | error
            "message": message,
        }
        self._data["logs"].append(entry)
        # Garder seulement les 200 derniers logs
        if len(self._data["logs"]) > 200:
            self._data["logs"] = self._data["logs"][-200:]
        self.save()
        print(f"[{entry['ts']}] [{level.upper()}] {message}")

    @property
    def is_paused(self) -> bool:
        return self._data.get("status") == "paused"

    @property
    def chapters(self) -> dict:
        return self._data["chapters"]


# ─── Client TTS ────────────────────────────────────────────────────────────────

async def call_tts(
    session: aiohttp.ClientSession,
    chunk: dict,
    output_path: Path,
    config: dict,
    retries: int = 0,
) -> bool:
    """
    Envoie un chunk au serveur Qwen3-TTS et sauvegarde le .wav résultant.
    Retourne True si succès, False sinon.
    """
    voice_id = config["voice_map"].get(chunk["voice"], "narrator_fr_v2")
    params   = config["voice_params"].get(chunk["voice"], {})

    payload = {
        "text":     chunk["text"],
        "voice_id": voice_id,
        "params":   params,
    }

    try:
        async with session.post(
            f"{config['tts_url']}/generate",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            if resp.status == 200:
                audio_data = await resp.read()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                async with aiofiles.open(output_path, "wb") as f:
                    await f.write(audio_data)
                return True
            else:
                error_text = await resp.text()
                raise Exception(f"HTTP {resp.status}: {error_text[:200]}")

    except Exception as e:
        if retries < config["max_retries"]:
            await asyncio.sleep(config["retry_delay"])
            return await call_tts(session, chunk, output_path, config, retries + 1)
        return False


# ─── Worker TTS ────────────────────────────────────────────────────────────────

async def tts_worker(
    worker_id: int,
    queue: asyncio.Queue,
    session: aiohttp.ClientSession,
    state: PipelineState,
    config: dict,
    pause_event: asyncio.Event,
):
    """
    Worker qui consomme la queue de chunks et appelle le TTS.
    S'arrête quand il reçoit None dans la queue.
    """
    while True:
        # Attendre si en pause
        await pause_event.wait()

        item = await queue.get()

        # Signal d'arrêt
        if item is None:
            queue.task_done()
            break

        chunk, output_path, chapter_id = item

        start = time.time()
        success = await call_tts(session, chunk, output_path, config)
        elapsed = time.time() - start

        state.chunk_done(chapter_id, success=success)

        if success:
            state.log(
                f"[worker-{worker_id}] chunk {chunk['id']} OK ({elapsed:.1f}s, {chunk['char_count']}c)",
                "info"
            )
        else:
            state.log(
                f"[worker-{worker_id}] chunk {chunk['id']} ERREUR après {config['max_retries']} retries",
                "error"
            )

        queue.task_done()


# ─── Assemblage audio ──────────────────────────────────────────────────────────

def assemble_chapter(wav_dir: Path, output_mp3: Path) -> bool:
    """
    Assemble tous les .wav d'un chapitre en un seul .mp3 via FFmpeg.
    Les fichiers sont triés par index de chunk.
    """
    wav_files = sorted(wav_dir.glob("*.wav"), key=lambda p: p.stem)

    if not wav_files:
        return False

    # Créer un fichier de liste pour FFmpeg
    list_file = wav_dir / "_concat_list.txt"
    with open(list_file, "w") as f:
        for wav in wav_files:
            f.write(f"file '{wav.resolve()}'\n")

    output_mp3.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-codec:a", "libmp3lame",
        "-qscale:a", "2",      # Qualité ~190kbps VBR
        str(output_mp3)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    list_file.unlink(missing_ok=True)

    return result.returncode == 0


# ─── Traitement d'un chapitre ──────────────────────────────────────────────────

async def process_chapter(
    chapter_path: Path,
    queue: asyncio.Queue,
    state: PipelineState,
    config: dict,
):
    """
    Lit un chapitre, le découpe en chunks, et les pousse dans la queue.
    """
    chapter_id = chapter_path.stem.replace("Chapitre_", "").replace("chapitre_", "")

    # Vérifier si déjà traité
    existing = state.chapters.get(chapter_id, {})
    if existing.get("status") == "done":
        state.log(f"Chapitre {chapter_id} déjà traité, on passe.", "info")
        return

    # Cache chunks JSON (évite de re-chunker à chaque run)
    cache_path = Path(config["chunks_cache_dir"]) / f"{chapter_id}.json"
    if cache_path.exists():
        chunks = json.loads(cache_path.read_text())
    else:
        text   = chapter_path.read_text(encoding="utf-8")
        chunks = chunk_chapter(text, chapter_id)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(chunks, ensure_ascii=False))

    state.init_chapter(chapter_id, total_chunks=len(chunks))
    state.update_chapter(chapter_id, status="running", started_at=datetime.now().isoformat())
    state.log(f"Chapitre {chapter_id} : {len(chunks)} chunks en queue")

    wav_dir = Path(config["output_dir"]) / "wav" / chapter_id

    for chunk in chunks:
        output_wav = wav_dir / f"{chunk['id']}.wav"

        # Skip si le wav existe déjà (reprise après crash)
        if output_wav.exists():
            state.chunk_done(chapter_id, success=True)
            continue

        await queue.put((chunk, output_wav, chapter_id))


# ─── Fonction principale ───────────────────────────────────────────────────────

async def run_pipeline(
    chapters: list[Path],
    config: dict,
    state: PipelineState,
):
    """
    Lance le pipeline complet sur une liste de chapitres.
    """
    state.set_status("running")
    state._data["started_at"] = datetime.now().isoformat()
    state.save()

    queue       = asyncio.Queue(maxsize=500)
    pause_event = asyncio.Event()
    pause_event.set()   # Démarré non-pausé

    # Exposer pause_event au dashboard via state (hack simple)
    state._pause_event = pause_event

    async with aiohttp.ClientSession() as session:
        # Lancer les workers
        workers = [
            asyncio.create_task(
                tts_worker(i, queue, session, state, config, pause_event)
            )
            for i in range(config["num_workers"])
        ]

        # Pousser les chapitres dans la queue
        for chap_path in chapters:
            await process_chapter(chap_path, queue, state, config)

        # Signaux d'arrêt pour les workers
        for _ in workers:
            await queue.put(None)

        # Attendre la fin de tous les workers
        await asyncio.gather(*workers)

    # Assemblage des chapitres terminés
    state.log("Assemblage des chapitres en .mp3...")
    for chap_path in chapters:
        chapter_id = chap_path.stem.replace("Chapitre_", "").replace("chapitre_", "")
        wav_dir    = Path(config["output_dir"]) / "wav" / chapter_id
        mp3_out    = Path(config["output_dir"]) / "mp3" / f"Chapitre_{chapter_id}.mp3"

        if assemble_chapter(wav_dir, mp3_out):
            state.update_chapter(chapter_id, status="done", finished_at=datetime.now().isoformat())
            state.log(f"Chapitre {chapter_id} assemblé → {mp3_out}")
        else:
            state.update_chapter(chapter_id, status="error")
            state.log(f"Échec assemblage chapitre {chapter_id}", "error")

    state.set_status("done")
    state.log("Pipeline terminé.")


# ─── Entrée CLI ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pipeline audiobook MVS")
    parser.add_argument("--chapter",  help="Traiter un seul chapitre .txt")
    parser.add_argument("--chapters", help="Répertoire de chapitres .txt")
    parser.add_argument("--workers",  type=int, default=CONFIG["num_workers"])
    args = parser.parse_args()

    CONFIG["num_workers"] = args.workers

    state = PipelineState(CONFIG["state_file"])

    if args.chapter:
        chapters = [Path(args.chapter)]
    elif args.chapters:
        chapters = sorted(Path(args.chapters).glob("Chapitre_*.txt"))
    else:
        print("Spécifier --chapter ou --chapters")
        sys.exit(1)

    state.log(f"Démarrage : {len(chapters)} chapitre(s), {CONFIG['num_workers']} worker(s)")
    asyncio.run(run_pipeline(chapters, CONFIG, state))
