# Contexte pour Claude (passation PC portable → PC fixe)

> À lire en premier par Claude au démarrage d'une session sur ce dépôt.
> Résumé d'une longue conversation (sept. 2026) sur le PC portable. Ensuite,
> enregistrer les points "Préférences" et "En attente" dans la mémoire.

## Qui / comment travailler

- L'utilisateur écrit en **français** : toujours répondre en français, simplement.
- Chaîne YouTube : **The Synapse Cut** (@TheSynapseCut, ex-@HistoireVraiReddit),
  clips de podcasts en anglais (Joe Rogan / Huberman : science, santé,
  psychologie, psychédéliques). 4 anciennes histoires Reddit FR passées en
  non répertorié. Pas de "Joe Rogan"/"JRE" dans le nom ou l'avatar de la chaîne.
- Compte GitHub : SimonNieto — dépôt privé `openshorts-synapse`
  (remote `synapse`) ; `origin` = projet OpenShorts d'origine (mutonby).

## Règles permanentes (données par l'utilisateur)

1. **Ne jamais casser le Clip Generator classique.** Les nouveautés vont dans
   **Clip Generator++** (profils `plus.py` / `clip_profiles.json`,
   `PlusPanel.jsx`, `PlusProfileEditor.jsx`). Tout ce qui change ce que l'IA
   choisit (prompts, sélection, titres) = case **beta**, désactivée par défaut.
2. **Avant `docker compose restart backend`**, vérifier qu'aucun job ne tourne :
   `docker exec openshorts-backend python -c "import os;me=str(os.getpid());print(sum(1 for p in os.listdir('/proc') if p.isdigit() and p!=me and any(k in open(f'/proc/{p}/cmdline','rb').read() for k in (b'main.py',b'story.py',b'ffmpeg'))))"`
   → ne redémarrer que si 0. (`ps` n'existe pas dans le conteneur.)
   `app.py` / `plus.py` / `rework.py` chargés par le serveur → redémarrage
   nécessaire ; `main.py`, `viral_fx.py`, `broll.py`, `hooks.py` tournent dans
   le sous-processus du job → pris en compte au job suivant.
3. **Demander avant tout téléchargement** (modèles, paquets…).
4. Ne jamais saisir / manipuler les clés ou mots de passe de l'utilisateur ;
   les vraies publications (Upload-Post) : c'est lui qui clique.
5. Ne pas toucher `CLIP_WORKERS` / `MAX_CONCURRENT_JOBS` sans qu'il le demande.
6. Lint frontend : `docker exec openshorts-frontend sh -c "cd /app && npx eslint <fichiers> --max-warnings 0"`.

## Ce qui a été construit (tout est dans ce dépôt)

- **Clip Generator++** : profils de chaîne ; styles `natural` (défaut, calibré
  sur 15 shorts de podcasts à succès), `punchy`, `clean` (`viral_fx.py`) ;
  cadrage intelligent sur le visage, spotlight, look, traits lumineux ;
  **plans de réaction** (`reactions.py`, bouche fermée obligatoire) ; musique
  ducker + niveau fixe (`mix_music`) ; watermark (nom de chaîne sous les
  sous-titres, une seule fois) ; **hook "bold"** (Anton, 1-2 mots en jaune,
  halo sombre, fondu, 4 s — `hooks.py`) ; **fin sur phrase complète**
  (`end_on_sentence` dans `main.py`, env `CLEAN_END=1`) ; **mots clés colorés**
  (mots du titre/hook + 1 sous-titre sur 2) ; sélection v2 et titres de série
  (beta) ; stats.
- **Images B-roll (beta)** — `broll.py` : Gemini choisit 2-4 moments concrets ;
  images Gemini (payant) ou **photos Wikimedia Commons gratuites** (CC0/PD/CC BY,
  crédit ajouté aux descriptions) ; présentation en carte (coins arrondis,
  ombre, pop, podcast flouté derrière) ; filtres qualité/esthétique.
  ⚠️ La clé Gemini de l'utilisateur est en **offre gratuite : Google refuse les
  images** (429) → le mode "auto" passe aux photos gratuites.
- **Viral Clip Reworker** : effaceur "smart" (`text_eraser.py`, flux optique,
  masque lettres + halo mesuré), détection auto des sous-titres/hooks,
  aperçu avant/après (`/api/rework/detect`, `/api/rework/preview`).
- **Publication** : ScheduleComposer (créneaux libres, "now"), publication auto
  des 3 meilleurs clips sans doublon d'horaire, **hashtags propres** (3-5, aucun
  dans le titre — `_pick_clip_hashtags`), **tags YouTube + langue** envoyés à
  Upload-Post (`tags[]`, `defaultLanguage`), tags de base par niche dans
  Settings (`publish_settings.json`).
- **Story Channel** (`story.py`, personnages SVG), Viral Finder, planning.

## Mesures utiles (PC portable, CPU)

- Transcription Whisper small int8 : ~3,4× le temps réel (1 min pour ~3 min).
- Effaceur Reworker : ~40 s pour 8 s de vidéo 1080p60.
- Coût images Gemini (payant) : 0,067 $/image (Flash Image), 0,034 $ (Flash Lite Image).

## En attente / prochaines étapes

1. **Activer la RTX 3060** sur le PC fixe : Whisper sur GPU
   (`WHISPER_DEVICE=cuda`, `WHISPER_COMPUTE=float16`, GPU exposé à Docker),
   génération d'images B-roll **en local** (Flux / SDXL) → téléchargement de
   modèle (10-25 Go) : **demander l'accord**.
2. **Kokoro TTS** pour Story Channel (kokoro-onnx + ~115 Mo de modèles) : en attente d'accord.
3. **Reworker "vraiment invisible"** : inpainting vidéo IA (ProPainter / LaMa) sur GPU : en attente d'accord.
4. Proposé, pas encore fait : bouton "ajouter des images" sur un clip déjà
   fini ; hooks ≤ 6 mots (beta) ; clé Gemini séparée pour les images ; passer
   sur Flash Lite Image si facturation activée ; durée des clips 30-60 s
   (profil actuel 15-90 s, le meilleur short fait 55 s).
