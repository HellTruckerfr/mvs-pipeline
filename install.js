module.exports = {
  run: [{
    method: "shell.run",
    params: {
      message: "python -m venv venv"
    }
  }, {
    method: "shell.run",
    params: {
      venv: "venv",
      message: "pip install -r requirements.txt"
    }
  }, {
    method: "shell.run",
    params: {
      message: "mkdir -p data/chapitres data/audio/wav data/audio/mp3 data/chunks_cache"
    }
  }, {
    method: "notify",
    params: {
      html: "Installation terminée ! Clique sur <b>Démarrer</b>."
    }
  }]
}
