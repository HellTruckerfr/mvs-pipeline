const fs = require('fs')
const path = require('path')

module.exports = {
  version: "5.0",
  title: "MVS Audiobook Pipeline",
  description: "Pipeline audiobook My Vampire System — Qwen3-TTS + Dashboard de contrôle",
  icon: "icon.png",
  menu: async (kernel, info) => {

    let running = {
      install: info.running("install.js"),
      start:   info.running("start.js"),
      update:  info.running("update.js")
    }

    let installed = info.exists("venv")

    if (running.install) {
      return [{
        default: true,
        icon: "fa-solid fa-plug",
        text: "Installation en cours...",
        href: "install.js"
      }]
    }

    if (running.start) {
      return [{
        default: true,
        icon: "fa-solid fa-rocket",
        text: "Ouvrir Dashboard",
        href: "http://localhost:8000",
      }, {
        icon: "fa-solid fa-terminal",
        text: "Terminal",
        href: "start.js",
      }]
    }

    if (running.update) {
      return [{
        default: true,
        icon: "fa-solid fa-arrows-rotate",
        text: "Mise à jour en cours...",
        href: "update.js"
      }]
    }

    if (!installed) {
      return [{
        default: true,
        icon: "fa-solid fa-plug",
        text: "Installer",
        href: "install.js"
      }]
    }

    return [{
      default: true,
      icon: "fa-solid fa-power-off",
      text: "Démarrer",
      href: "start.js"
    }, {
      icon: "fa-solid fa-arrows-rotate",
      text: "Mettre à jour",
      href: "update.js"
    }, {
      icon: "fa-solid fa-plug",
      text: "Réinstaller",
      href: "install.js"
    }]
  }
}
