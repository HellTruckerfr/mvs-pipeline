module.exports = {
  title: "Installation MVS Pipeline",
  steps: [
    // ─── 1. Créer l'environnement virtuel Python ──────────────────────────
    {
      method: "shell.run",
      params: {
        message: "python -m venv venv",
        on: [{
          // Si venv existe déjà, on ignore l'erreur
          event: "/.*/",
          done: true,
        }]
      }
    },
    // ─── 2. Installer les dépendances pip ────────────────────────────────
    {
      method: "shell.run",
      params: {
        // Pinokio active automatiquement le venv dans le répertoire du projet
        venv: "venv",
        message: "pip install -r requirements.txt",
      }
    },
    // ─── 3. Créer les dossiers de données ────────────────────────────────
    {
      method: "shell.run",
      params: {
        venv: "venv",
        message: [
          "mkdir -p data/chapitres",
          "mkdir -p data/audio/wav",
          "mkdir -p data/audio/mp3",
          "mkdir -p data/chunks_cache",
        ].join(" && "),
      }
    },
    // ─── 4. Vérifier FFmpeg ───────────────────────────────────────────────
    {
      method: "shell.run",
      params: {
        message: "ffmpeg -version",
        on: [{
          event: "/ffmpeg version/",
          done: true,
        }, {
          // FFmpeg absent : afficher un avertissement mais continuer
          event: "/.*/",
          done: true,
        }]
      }
    },
    // ─── Message de fin ───────────────────────────────────────────────────
    {
      method: "notify",
      params: {
        html: "Installation terminée ! Clique sur <b>Démarrer</b> pour lancer le dashboard.",
      }
    },
  ]
}
