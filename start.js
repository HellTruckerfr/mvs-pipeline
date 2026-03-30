module.exports = {
  title: "MVS Dashboard",
  // daemon: true garde le process actif en arrière-plan
  // (le dashboard reste accessible même si on ferme la fenêtre Pinokio)
  daemon: true,
  steps: [
    {
      method: "shell.run",
      params: {
        venv: "venv",
        message: "python dashboard.py",
        on: [{
          // Attend que le serveur soit prêt avant d'ouvrir le navigateur
          event: "/Dashboard MVS démarré/",
          done: true,
        }]
      }
    },
    // Ouvrir automatiquement le dashboard dans le navigateur
    {
      method: "browser.open",
      params: {
        url: "http://localhost:8000",
      }
    },
  ]
}
