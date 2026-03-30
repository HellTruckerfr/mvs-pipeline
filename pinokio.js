module.exports = {
  title: "MVS Audiobook Pipeline",
  description: "Pipeline audiobook My Vampire System — Qwen3-TTS + Dashboard",
  icon: "icon.png",

  menu: async (kernel, info) => {

    // Vérifie si le dashboard tourne déjà
    let running = await kernel.running("start.js")

    return [
      // ─── Installer les dépendances ───────────────────────────────────────
      {
        text: "Installer",
        href: "install.js",
      },
      // ─── Démarrer le dashboard ───────────────────────────────────────────
      {
        text: running ? "En cours..." : "Démarrer",
        href: "start.js",
        params: { run: !running },
      },
      // ─── Arrêter ────────────────────────────────────────────────────────
      {
        text: "Arrêter",
        href: "stop.js",
      },
      // ─── Ouvrir le dashboard dans le navigateur ──────────────────────────
      {
        text: "Ouvrir Dashboard",
        href: "http://localhost:8000",
        external: true,
      },
      // ─── Mettre à jour depuis GitHub ─────────────────────────────────────
      {
        text: "Mettre à jour",
        href: "update.js",
      },
    ]
  }
}
