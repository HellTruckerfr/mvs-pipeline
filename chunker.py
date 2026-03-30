"""
chunker.py — Découpe intelligente de chapitres en segments TTS

Rôle : transformer un chapitre .txt brut en liste de chunks JSON
annotés, prêts à être envoyés au serveur Qwen3-TTS.

Règles de découpe :
  - Max 200 caractères par chunk (sweet spot Qwen3-TTS)
  - On ne coupe jamais en milieu de mot
  - Les dialogues « » sont gardés entiers si possible
  - Les pensées intérieures (entre guillemets simples ou italiques) 
    reçoivent un tag voix différent
  - Chaque chunk reçoit un champ "voice" (narrator / dialogue / thought)
"""

import re
import json
from pathlib import Path


# ─── Constantes ────────────────────────────────────────────────────────────────

MAX_CHARS = 200          # Longueur max d'un chunk
MIN_CHARS = 40           # En dessous, on fusionne avec le suivant


# ─── Détection du type de segment ──────────────────────────────────────────────

def detect_voice(text: str) -> str:
    """
    Retourne le type de voix pour un segment de texte.
    
    - "dialogue"  : texte entre « »
    - "thought"   : texte entre " " (pensées intérieures style web novel)
    - "narrator"  : tout le reste (narration pure)
    """
    stripped = text.strip()
    
    # Dialogue français : commence par « et finit par »
    if stripped.startswith("«") and "»" in stripped:
        return "dialogue"
    
    # Pensées entre guillemets doubles droits (style traduction web novel FR)
    if stripped.startswith('"') and stripped.endswith('"'):
        return "thought"
    
    return "narrator"


# ─── Découpe d'un paragraphe en chunks ─────────────────────────────────────────

def split_paragraph(paragraph: str) -> list[str]:
    """
    Découpe un paragraphe en segments de max MAX_CHARS caractères.
    
    Stratégie :
    1. On découpe d'abord sur les séparateurs naturels (. ! ? …)
    2. Si un segment est encore trop long, on découpe sur les virgules/;/:
    3. En dernier recours, on coupe sur les espaces (jamais en milieu de mot)
    """
    paragraph = paragraph.strip()
    if not paragraph:
        return []

    # Étape 1 : découpe sur les fins de phrases
    # Le lookbehind garde le signe de ponctuation dans le segment
    sentences = re.split(r'(?<=[.!?…»])\s+', paragraph)

    chunks = []
    buffer = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Le segment tient seul dans la limite
        if len(sentence) <= MAX_CHARS:
            if buffer:
                # On essaie d'abord de fusionner avec le buffer
                if len(buffer) + 1 + len(sentence) <= MAX_CHARS:
                    buffer += " " + sentence
                else:
                    # Buffer plein : on le valide et on repart
                    chunks.append(buffer)
                    buffer = sentence
            else:
                buffer = sentence

        else:
            # La phrase est trop longue → on découpe sur virgules / points-virgules
            if buffer:
                chunks.append(buffer)
                buffer = ""

            sub_parts = re.split(r'(?<=[,;:])\s+', sentence)
            sub_buffer = ""
            for part in sub_parts:
                if len(sub_buffer) + 1 + len(part) <= MAX_CHARS:
                    sub_buffer = (sub_buffer + " " + part).strip()
                else:
                    if sub_buffer:
                        chunks.append(sub_buffer)
                    # Si le part lui-même dépasse MAX_CHARS, découpe sur espaces
                    if len(part) > MAX_CHARS:
                        words = part.split()
                        word_buf = ""
                        for word in words:
                            if len(word_buf) + 1 + len(word) <= MAX_CHARS:
                                word_buf = (word_buf + " " + word).strip()
                            else:
                                if word_buf:
                                    chunks.append(word_buf)
                                word_buf = word
                        if word_buf:
                            sub_buffer = word_buf
                        else:
                            sub_buffer = ""
                    else:
                        sub_buffer = part
            if sub_buffer:
                chunks.append(sub_buffer)

    if buffer:
        chunks.append(buffer)

    # Fusion des chunks trop courts avec le suivant
    merged = []
    i = 0
    while i < len(chunks):
        current = chunks[i]
        if len(current) < MIN_CHARS and i + 1 < len(chunks):
            next_chunk = chunks[i + 1]
            if len(current) + 1 + len(next_chunk) <= MAX_CHARS:
                merged.append(current + " " + next_chunk)
                i += 2
                continue
        merged.append(current)
        i += 1

    return merged


# ─── Traitement d'un chapitre complet ──────────────────────────────────────────

def chunk_chapter(text: str, chapter_id: str) -> list[dict]:
    """
    Prend le texte brut d'un chapitre et retourne une liste de chunks JSON.

    Format d'un chunk :
    {
        "id":         "0509_042",       # chapitre + index du chunk
        "chapter":    "0509",           # numéro de chapitre
        "index":      42,               # position dans le chapitre
        "text":       "...",            # texte à synthétiser
        "voice":      "narrator",       # narrator | dialogue | thought
        "char_count": 147               # longueur en caractères
    }
    """
    chunks = []
    chunk_index = 0

    # On découpe le texte en paragraphes (lignes séparées par lignes vides)
    # On ignore aussi la ligne de titre "# Chapitre XXX"
    raw_paragraphs = re.split(r'\n\s*\n', text)

    for para in raw_paragraphs:
        para = para.strip()

        # Ignorer les lignes de titre markdown et les lignes BOM/vides
        if para.startswith('#') or para.startswith('\ufeff'):
            continue

        if not para:
            continue

        # Découper le paragraphe en segments
        segments = split_paragraph(para)

        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue

            voice = detect_voice(seg)

            chunks.append({
                "id":         f"{chapter_id}_{chunk_index:04d}",
                "chapter":    chapter_id,
                "index":      chunk_index,
                "text":       seg,
                "voice":      voice,
                "char_count": len(seg),
            })
            chunk_index += 1

    return chunks


# ─── Interface en ligne de commande ────────────────────────────────────────────

def process_file(input_path: str, output_path: str | None = None) -> list[dict]:
    """
    Lit un fichier .txt et retourne les chunks.
    Si output_path est fourni, sauvegarde aussi en JSON.
    """
    path = Path(input_path)
    chapter_id = path.stem.replace("Chapitre_", "").replace("chapitre_", "")

    text = path.read_text(encoding="utf-8")
    chunks = chunk_chapter(text, chapter_id)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(chunks, ensure_ascii=False, indent=2))
        print(f"[chunker] {len(chunks)} chunks → {out}")

    return chunks


# ─── Test rapide ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python chunker.py <chapitre.txt> [output.json]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    result = process_file(input_file, output_file)

    # Affichage d'un résumé
    voices = {}
    for c in result:
        voices[c["voice"]] = voices.get(c["voice"], 0) + 1

    print(f"\n=== Résumé ===")
    print(f"Total chunks     : {len(result)}")
    print(f"Répartition voix : {voices}")
    print(f"Chars moy/chunk  : {sum(c['char_count'] for c in result) // len(result)}")
    print(f"\nPremiers chunks :")
    for c in result[:5]:
        print(f"  [{c['id']}] ({c['voice']:9s}) {c['char_count']:3d}c → {c['text'][:80]}...")
