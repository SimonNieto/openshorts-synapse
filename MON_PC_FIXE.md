# Installer OpenShorts sur le PC fixe

Ce dépôt contient tout le code (Clip Generator++, Reworker, B-roll, Story
Channel, publication auto…). **Il ne contient volontairement pas** :

- `.env` — tes clés et réglages serveur (secret, jamais sur GitHub) ;
- `output/` — tes clips déjà générés (vidéos, trop lourd pour git) ;
- les clés saisies dans l'app (Gemini, Upload-Post, ElevenLabs) : elles vivent
  dans le navigateur, pas dans le projet.

## 1. Installer (une seule fois)

1. **Git for Windows** — https://git-scm.com/download/win
2. **Docker Desktop** (avec WSL 2) — https://www.docker.com/products/docker-desktop/
3. **Pilote NVIDIA à jour** pour la RTX 3060 (servira pour l'accélération GPU plus tard).

## 2. Récupérer le projet

Dans un terminal (PowerShell), dans le dossier Documents :

```
git clone <URL DE TON DÉPÔT GITHUB>
cd <nom du dépôt>
```

## 3. Copier ce qui n'est pas sur GitHub

Depuis le PC portable (clé USB, Google Drive…) :

- le fichier **`.env`** du dossier OpenShorts → à mettre à la racine du dossier cloné ;
- facultatif : le dossier **`output/`** si tu veux retrouver tes anciens clips.

Pas de `.env` sous la main ? Copie `.env.example` en `.env` et remets tes clés.

## 4. Lancer

```
docker compose up --build
```

Puis ouvre **http://localhost:5175** et, dans **Settings**, recolle tes clés
(Gemini, Upload-Post, ElevenLabs) : elles sont propres à chaque navigateur.

## 5. Mettre à jour plus tard

```
git pull
docker compose up --build
```

## Notes

- Tes profils Clip Generator++ (`clip_profiles.json`), réglages de publication
  (`publish_settings.json`), planning (`publish_schedule.json`) et hashtags
  recherchés (`hashtag_research.json`) sont inclus tels qu'ils étaient sur le
  portable.
- `CLIP_WORKERS` / `MAX_CONCURRENT_JOBS` restent à 2 dans le `.env` copié ; avec
  32 Go de RAM tu pourras les augmenter si tu veux, mais rien n'y oblige.
- Étape suivante prévue : activer la RTX 3060 (transcription beaucoup plus
  rapide, images B-roll générées en local et gratuites). Il faudra télécharger
  un modèle d'image (10-25 Go) : à faire ensemble.
