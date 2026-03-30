module.exports = {
  title: "Arrêt MVS Pipeline",
  steps: [
    {
      method: "shell.stop",
      params: {
        // Arrête le process lancé par start.js
        file: "start.js",
      }
    },
  ]
}
