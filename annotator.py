"""
annotator.py — Annotation optionnelle des chunks via Claude Haiku

Ce module est OPTIONNEL. Il enrichit les chunks avec des instructions
de style plus précises avant de les envoyer au TTS.

Sans annotation  : le serveur TTS utilise les instructions génériques
                   (narrateur posé, voix féminine douce, etc.)

Avec annotation  : Claude Haiku analyse le contexte de chaque phrase
                   et génère une instruction sur mesure :
                   "voix tendue, légèrement tremblante, débit rapide"

Quand l'utiliser :
  - Pour les scènes importantes (combats, révélations, émotions fortes)
  - Sur un sous-ensemble de chapitres (pas forcément tous les 2545)
  - En post-traitement si la qualité audio semble trop monotone

Usage :
  from annotator import annotate_chunks
  chunks = annotate_chunks(chunks, batch_size=20)

Coût estimé :
  ~20 chunks / appel API → 2545 chapitres × ~77 chunks ÷ 20 = ~9800 appels
  Claude Haiku : ~$0.0004 / appel ≈ $4 total pour TOUS les chapitres
"""

import anthropic
import json
import time
from pathlib import Path


# ─── Client Anthropic ──────────────────────────────────────────────────────────

def get_client() -> anthropic.Anthropic:
    """Retourne le client Anthropic (lit ANTHROPIC_API_KEY dans l'env)."""
    return anthropic.Anthropic()


# ─── Prompt système ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es un expert en direction de doublage pour audiobooks.
Tu analyses des segments de texte et tu génères des instructions de style
courtes pour un système TTS (text-to-speech).

Règles :
- Maximum 15 mots par instruction
- En français uniquement
- Décris le ton, le rythme, l'émotion — pas le contenu
- Sois précis et concret : "voix grave, débit lent, ton solennel"
  plutôt que "voix dramatique"
- Pour la narration neutre, réponds juste "narration neutre, débit régulier"

Réponds UNIQUEMENT en JSON valide, sans texte avant ou après :
[
  {"index": 0, "instruction": "..."},
  {"index": 1, "instruction": "..."},
  ...
]"""


# ─── Annotation d'un batch de chunks ──────────────────────────────────────────

def annotate_batch(
    client: anthropic.Anthropic,
    chunks: list[dict],
    chapter_context: str = "",
) -> list[dict]:
    """
    Envoie un batch de chunks à Claude Haiku pour annotation.
    Retourne les chunks enrichis avec un champ "tts_instruction".

    chunks      : liste de dicts avec au moins "text" et "voice"
    chapter_context : résumé du chapitre pour aider Claude à contextualiser
    """

    # Préparer le contenu pour Claude
    chunks_text = []
    for i, chunk in enumerate(chunks):
        chunks_text.append(f'{i}. [{chunk["voice"]}] {chunk["text"]}')

    user_message = ""
    if chapter_context:
        user_message += f"Contexte du chapitre : {chapter_context}\n\n"
    user_message += "Segments à annoter :\n" + "\n".join(chunks_text)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        # Parser le JSON retourné
        raw = response.content[0].text.strip()

        # Nettoyer si Claude a ajouté des backticks
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        annotations = json.loads(raw)

        # Enrichir les chunks
        annotated = list(chunks)
        for ann in annotations:
            idx = ann.get("index")
            if idx is not None and 0 <= idx < len(annotated):
                annotated[idx]["tts_instruction"] = ann.get("instruction", "")

        return annotated

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        # En cas d'erreur de parsing, retourner les chunks sans annotation
        print(f"[annotator] Erreur parsing JSON : {e}")
        return chunks

    except anthropic.APIError as e:
        print(f"[annotator] Erreur API Anthropic : {e}")
        return chunks


# ─── Annotation complète d'une liste de chunks ────────────────────────────────

def annotate_chunks(
    chunks: list[dict],
    batch_size: int = 20,
    chapter_context: str = "",
    cache_path: str | None = None,
) -> list[dict]:
    """
    Annote tous les chunks d'un chapitre en les envoyant par batches.

    batch_size     : nombre de chunks par appel API (20 = bon équilibre)
    chapter_context: résumé du chapitre (optionnel, améliore la précision)
    cache_path     : si fourni, sauvegarde le résultat annoté en JSON
                     pour éviter de re-annoter si on relance

    Retourne la liste enrichie avec "tts_instruction" sur chaque chunk.
    """

    # Charger depuis le cache si disponible
    if cache_path and Path(cache_path).exists():
        print(f"[annotator] Cache trouvé : {cache_path}")
        return json.loads(Path(cache_path).read_text())

    client     = get_client()
    annotated  = []
    total      = len(chunks)
    n_batches  = (total + batch_size - 1) // batch_size

    print(f"[annotator] {total} chunks → {n_batches} batches")

    for i in range(0, total, batch_size):
        batch      = chunks[i : i + batch_size]
        batch_num  = i // batch_size + 1

        print(f"[annotator] Batch {batch_num}/{n_batches}...", end=" ", flush=True)
        t0 = time.time()

        result = annotate_batch(client, batch, chapter_context)
        annotated.extend(result)

        elapsed = time.time() - t0
        print(f"OK ({elapsed:.1f}s)")

        # Petite pause pour ne pas saturer l'API sur de gros volumes
        if batch_num < n_batches:
            time.sleep(0.2)

    # Sauvegarder en cache
    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_path).write_text(
            json.dumps(annotated, ensure_ascii=False, indent=2)
        )
        print(f"[annotator] Sauvegardé : {cache_path}")

    return annotated


# ─── Intégration dans le serveur TTS ──────────────────────────────────────────

def build_tts_prompt(chunk: dict) -> str:
    """
    Construit le prompt final pour le TTS à partir d'un chunk annoté.

    Si le chunk a une instruction fine (via annotator), elle prend le dessus.
    Sinon, on utilise l'instruction générique du voice_map.
    """
    instruction = chunk.get("tts_instruction", "").strip()

    if instruction:
        return f"[{instruction}] {chunk['text']}"
    else:
        return chunk["text"]


# ─── Test rapide ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from chunker import process_file

    if len(sys.argv) < 2:
        print("Usage: python annotator.py <chapitre.txt>")
        sys.exit(1)

    chunks = process_file(sys.argv[1])

    print(f"\nAnnotation de {len(chunks)} chunks...")
    annotated = annotate_chunks(
        chunks[:10],    # Tester sur les 10 premiers seulement
        batch_size=10,
        chapter_context="Vincent, ancien vampire devenu humain, réfléchit à comment former son successeur.",
    )

    print("\n=== Résultats ===")
    for c in annotated:
        instr = c.get("tts_instruction", "(aucune)")
        print(f"[{c['voice']:9s}] {instr}")
        print(f"           → {c['text'][:70]}...")
        print()
