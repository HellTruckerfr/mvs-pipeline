#!/bin/bash
# setup_vast.sh — Installation complète sur une instance Vast.ai RTX 4090
# Copier ce fichier sur Vast et l'exécuter : bash setup_vast.sh TON_TOKEN_HF

set -e   # Arrêter si une commande échoue

HF_TOKEN="${1:-}"

echo "======================================================"
echo " MVS Audiobook — Setup Vast.ai"
echo "======================================================"

if [ -z "$HF_TOKEN" ]; then
  echo "Usage : bash setup_vast.sh TON_TOKEN_HUGGINGFACE"
  echo "Ton token HF se trouve sur : https://huggingface.co/settings/tokens"
  exit 1
fi

# ─── 1. Dépendances système ───────────────────────────────────────────────────
echo ""
echo "[1/6] Installation des dépendances système..."
apt-get update -qq
apt-get install -y -qq ffmpeg sox git curl

# ─── 2. Python et pip ─────────────────────────────────────────────────────────
echo ""
echo "[2/6] Mise à jour pip..."
pip install --upgrade pip --quiet

# ─── 3. vLLM-Omni ─────────────────────────────────────────────────────────────
echo ""
echo "[3/6] Installation de vLLM-Omni..."
# Note : vLLM-Omni nécessite Python 3.12 et CUDA 12.x
# L'image Vast pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime convient

pip install vllm-omni --quiet
pip install flash-attn --no-build-isolation --quiet || echo "FlashAttn optionnel, ignoré"

# Dépendances audio
pip install soundfile httpx fastapi uvicorn --quiet

# ─── 4. Téléchargement du modèle Qwen3-TTS ───────────────────────────────────
echo ""
echo "[4/6] Téléchargement du modèle Qwen3-TTS 1.7B..."
pip install huggingface_hub --quiet

python3 -c "
from huggingface_hub import snapshot_download
print('  Téléchargement CustomVoice...')
snapshot_download(
    'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice',
    cache_dir='/root/.cache/huggingface'
)
print('  OK')
"

# ─── 5. Téléchargement des LoRA privées ───────────────────────────────────────
echo ""
echo "[5/6] Téléchargement des LoRA privées (Helltrucker/audiobook-lora-models)..."
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(
    'Helltrucker/audiobook-lora-models',
    token='$HF_TOKEN',
    local_dir='./lora_models'
)
print('  LoRA téléchargées dans ./lora_models')
"

# ─── 6. Copie des fichiers du pipeline ────────────────────────────────────────
echo ""
echo "[6/6] Vérification des fichiers du pipeline..."

REQUIRED_FILES="server.py chunker.py pipeline.py dashboard.py annotator.py"
MISSING=0
for f in $REQUIRED_FILES; do
  if [ ! -f "$f" ]; then
    echo "  MANQUANT : $f"
    MISSING=1
  else
    echo "  OK : $f"
  fi
done

if [ $MISSING -eq 1 ]; then
  echo ""
  echo "Copie tes fichiers Python sur Vast avec :"
  echo "  scp -P PORT *.py root@IP_VAST:/root/"
fi

# ─── Résumé ───────────────────────────────────────────────────────────────────
echo ""
echo "======================================================"
echo " Setup terminé !"
echo "======================================================"
echo ""
echo "Pour démarrer le serveur TTS :"
echo "  python server.py"
echo ""
echo "Le serveur sera accessible sur le port 7860."
echo ""
echo "Sur ta machine locale, crée le tunnel SSH :"
echo "  ssh -L 7860:localhost:7860 -p PORT root@IP_VAST -N"
echo ""
echo "Puis lance le dashboard :"
echo "  python dashboard.py"
echo "  → http://localhost:8000"
