"""
server.py — Serveur TTS Qwen3-TTS sur Vast.ai
Ce fichier tourne SUR la machine Vast (pas en local).

Architecture :
  - vLLM-Omni tourne en arrière-plan sur le port 8091
  - Ce serveur FastAPI tourne sur le port 7860
  - Il fait le pont entre le pipeline (qui connaît "narrator_fr_v2")
    et vLLM-Omni (qui connaît des voice_ids + instructions NL)

Démarrage sur Vast :
  python server.py

  ou en deux commandes séparées si tu veux voir les logs vLLM à part :
  bash start_vllm.sh &
  python server.py
"""

import asyncio
import io
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import soundfile as sf
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
import uvicorn


# ─── Configuration ─────────────────────────────────────────────────────────────

VLLM_PORT   = 8091
SERVER_PORT = 7860
MODEL_NAME  = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
LORA_DIR    = "./lora_models"   # chemin local sur Vast après huggingface-cli download

# Mapping LoRA → instruction en langage naturel pour Qwen3-TTS VoiceDesign
# Qwen3-TTS comprend les instructions de style directement dans le champ "voice"
# On utilise le modèle CustomVoice pour les voix de base,
# et on enrichit avec des instructions de style passées dans le prompt.
VOICE_INSTRUCTIONS = {
    "narrator_fr_v2": (
        "Voix de narrateur français, grave et posée, "
        "débit régulier, ton neutre légèrement dramatique, "
        "diction claire, style audiobook professionnel"
    ),
    "feminine_fr": (
        "Voix féminine française, douce et introspective, "
        "débit légèrement lent, ton pensif et intérieur, "
        "comme une pensée murmurée"
    ),
}

# Voix de base CustomVoice à utiliser pour chaque LoRA
# (voix natives de Qwen3-TTS qui servent de point de départ)
VOICE_BASE = {
    "narrator_fr_v2": "eric",     # voix masculine posée
    "feminine_fr":    "serena",   # voix féminine douce
}


# ─── Modèles de requête/réponse ────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    text:     str
    voice_id: str = "narrator_fr_v2"
    params:   dict = {}


# ─── Application FastAPI ───────────────────────────────────────────────────────

app = FastAPI(title="MVS TTS Server")

# Client HTTP partagé (réutilise les connexions)
_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=120.0)
    return _http_client


# ─── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Vérifie que le serveur et vLLM-Omni sont opérationnels."""
    try:
        r = await get_http_client().get(f"http://localhost:{VLLM_PORT}/health")
        vllm_ok = r.status_code == 200
    except Exception:
        vllm_ok = False

    return {
        "server": "ok",
        "vllm":   "ok" if vllm_ok else "unavailable",
        "model":  MODEL_NAME,
    }


# ─── Endpoint principal de génération ─────────────────────────────────────────

@app.post("/generate")
async def generate(req: GenerateRequest):
    """
    Génère un fichier WAV à partir d'un chunk de texte.

    Reçoit :
      { "text": "...", "voice_id": "narrator_fr_v2", "params": {} }

    Retourne :
      audio/wav binaire

    Le pipeline local appelle cet endpoint pour chaque chunk.
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Texte vide")

    voice_base  = VOICE_BASE.get(req.voice_id, "eric")
    instruction = VOICE_INSTRUCTIONS.get(req.voice_id, "")

    # Construction du prompt avec instruction de style
    # Qwen3-TTS CustomVoice accepte une instruction optionnelle dans le champ "input"
    # sous la forme : [style_instruction] texte_à_lire
    if instruction:
        prompt_text = f"[{instruction}] {req.text}"
    else:
        prompt_text = req.text

    payload = {
        "model":           MODEL_NAME,
        "input":           prompt_text,
        "voice":           voice_base,
        "language":        "French",
        "response_format": "wav",
    }

    try:
        client = get_http_client()
        response = await client.post(
            f"http://localhost:{VLLM_PORT}/v1/audio/speech",
            json=payload,
        )

        if response.status_code != 200:
            error_text = response.text[:500]
            raise HTTPException(
                status_code=502,
                detail=f"vLLM-Omni erreur {response.status_code}: {error_text}"
            )

        # Retourner le WAV directement
        return Response(
            content=response.content,
            media_type="audio/wav",
        )

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout vLLM-Omni")
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="vLLM-Omni non disponible")


# ─── Endpoint batch (optionnel, pour accélérer encore plus) ───────────────────

class BatchRequest(BaseModel):
    chunks: list[GenerateRequest]


@app.post("/generate_batch")
async def generate_batch(req: BatchRequest):
    """
    Génère plusieurs chunks en parallèle.
    Retourne une liste de résultats {id, ok, size_bytes, error}.

    Utilisé par le pipeline quand num_workers > 1 et qu'on veut
    maximiser l'utilisation GPU.
    """
    tasks = [generate(chunk) for chunk in req.chunks]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            output.append({
                "index": i,
                "ok":    False,
                "error": str(result),
            })
        else:
            output.append({
                "index":      i,
                "ok":         True,
                "size_bytes": len(result.body),
            })

    return output


# ─── Lancement de vLLM-Omni en sous-processus ─────────────────────────────────

def start_vllm():
    """
    Lance vLLM-Omni en arrière-plan si pas déjà actif.
    """
    # Vérifier si déjà actif
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('localhost', VLLM_PORT))
    sock.close()

    if result == 0:
        print(f"[server] vLLM-Omni déjà actif sur le port {VLLM_PORT}")
        return None

    print(f"[server] Démarrage de vLLM-Omni ({MODEL_NAME})...")

    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        # Pour vLLM-Omni : remplacer la ligne ci-dessus par :
        # "vllm", "serve",
        MODEL_NAME,
        "--stage-configs-path", "vllm_omni/model_executor/stage_configs/qwen3_tts.yaml",
        "--omni",
        "--port", str(VLLM_PORT),
        "--host", "0.0.0.0",
        "--trust-remote-code",
        "--enforce-eager",
        "--gpu-memory-utilization", "0.85",
    ]

    log_file = open("vllm.log", "w")
    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=log_file,
    )

    # Attendre que vLLM soit prêt (max 120 secondes)
    print("[server] Attente démarrage vLLM-Omni", end="", flush=True)
    for _ in range(120):
        time.sleep(1)
        print(".", end="", flush=True)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sock.connect_ex(('localhost', VLLM_PORT)) == 0:
            sock.close()
            print(" prêt!")
            return proc
        sock.close()

    print("\n[ERREUR] vLLM-Omni n'a pas démarré en 120s. Voir vllm.log")
    proc.kill()
    sys.exit(1)


# ─── Point d'entrée ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Démarrer vLLM-Omni
    vllm_proc = start_vllm()

    print(f"[server] Serveur TTS démarré sur le port {SERVER_PORT}")
    print(f"[server] Health check : http://localhost:{SERVER_PORT}/health")

    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=SERVER_PORT,
            log_level="warning",
        )
    finally:
        if vllm_proc:
            vllm_proc.terminate()
