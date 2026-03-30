module.exports = {
  daemon: true,
  run: [{
    method: "shell.run",
    params: {
      venv: "venv",
      message: "python dashboard.py",
      on: [{
        event: "/Dashboard MVS démarré/",
        done: true
      }]
    }
  }]
}
