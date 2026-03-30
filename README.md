# MVS Audiobook Pipeline

Pipeline complet pour générer l'audiobook de "My Vampire System" (2545 chapitres FR)
via Qwen3-TTS 1.7B sur Vast.ai + dashboard de contrôle.

---

## Structure du projet

```
mvs_pipeline/
├── chunker.py        # Découpe les chapitres en segments TTS
├── pipeline.py       # Orchestrateur asyncio (envoie au TTS)
├── dashboard.py      # Interface web de contrôle
├── requirements.txt  # Dépendances Python
└── data/
    ├── chapitres/    # Tes .txt source (Chapitre_0001.txt, etc.)
    ├── audio/
    │   ├── wav/      # .wav intermédiaires par chunk
    │   └── mp3/      # .mp3 finaux par chapitre
    ├── chunks_cache/ # Chunks JSON pré-calculés (évite re-chunking)
    └── state.json    # État du pipeline (lu par le dashboard)
```

---

## Étape 1 : Préparer ton environnement local

```bash
# Créer un dossier de travail
mkdir mvs_pipeline && cd mvs_pipeline

# Installer les dépendances
pip install -r requirements.txt

# Installer FFmpeg (pour assembler les .mp3)
sudo apt install ffmpeg          # Linux/Vast
brew install ffmpeg              # macOS
```

---

## Étape 2 : Mettre tes chapitres

```bash
mkdir -p data/chapitres
# Copier tous tes .txt dans data/chapitres/
# Les fichiers doivent s'appeler Chapitre_XXXX.txt
```

---

## Étape 3 : Configurer le serveur Vast.ai

### 3a. Choisir une instance sur Vast.ai

Sur vast.ai, filtre par :
- GPU : RTX 4090
- VRAM : 24 GB
- Image Docker : `pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime`

### 3b. Se connecter via SSH

```bash
# Vast te donne une commande SSH type :
ssh -p 29497 root@vast-instance-ip

# Créer le tunnel pour le dashboard TTS
ssh -L 7860:localhost:7860 -p 29497 root@vast-instance-ip -N &
```

### 3c. Installer vLLM-Omni + Qwen3-TTS sur Vast

```bash
# Sur la machine Vast (via SSH)
pip install vllm-omni
pip install flash-attn --no-build-isolation

# Télécharger le modèle
huggingface-cli download Qwen/Qwen3-TTS-12Hz-1.7B-Base

# Télécharger tes LoRA depuis HuggingFace (dépôt privé)
huggingface-cli download Helltrucker/audiobook-lora-models \
  --token TON_TOKEN_HF \
  --local-dir ./lora_models

# Lancer le serveur TTS (reste actif en arrière-plan)
# (le script server.py sera fourni dans la prochaine étape)
python server.py --port 7860
```

---

## Étape 4 : Lancer le dashboard

```bash
# Sur ta machine locale
python dashboard.py
# → http://localhost:8000
```

---

## Étape 5 : Lancer le pipeline

**Option A : via le dashboard** (recommandé)
- Ouvre http://localhost:8000
- Clique "▶ Démarrer"

**Option B : en ligne de commande**
```bash
# Un seul chapitre (pour tester)
python pipeline.py --chapter data/chapitres/Chapitre_0509.txt

# Tous les chapitres
python pipeline.py --chapters data/chapitres/ --workers 2
```

---

## Paramètres importants

Dans `pipeline.py`, section `CONFIG` :

| Paramètre | Défaut | Explication |
|---|---|---|
| `num_workers` | `2` | Workers TTS parallèles. Commence à 2, monte si stable. |
| `tts_url` | `http://127.0.0.1:7860` | URL du serveur (via tunnel SSH) |
| `max_retries` | `3` | Tentatives avant d'abandonner un chunk |

---

## Reprise après interruption

Le pipeline est **idempotent** : si tu l'arrêtes et le relances,
il reprend exactement où il s'est arrêté (les .wav existants sont skippés).

---

## Prochaine étape

La prochaine étape est `server.py` : le serveur FastAPI qui tourne
sur Vast.ai et expose l'endpoint `/generate` pour Qwen3-TTS.
