module.exports = {
  title: "Mise à jour depuis GitHub",
  steps: [
    // Arrêter le dashboard si actif
    {
      method: "shell.stop",
      params: { file: "start.js" }
    },
    // Pull les dernières modifications
    {
      method: "shell.run",
      params: {
        message: "git pull origin main",
        on: [{
          event: "/Already up to date|mise à jour/",
          done: true,
        }, {
          event: "/error/i",
          done: true,
        }]
      }
    },
    // Réinstaller les dépendances si requirements.txt a changé
    {
      method: "shell.run",
      params: {
        venv: "venv",
        message: "pip install -r requirements.txt --quiet",
      }
    },
    {
      method: "notify",
      params: {
        html: "Mise à jour terminée. Clique sur <b>Démarrer</b> pour relancer.",
      }
    },
  ]
}
