# Charte des images — chaîne « littéral »

Écrite le 9 octobre 2026 d'après les chaînes qui marchent dans la niche (OptimalHealth, Clip Storm ; étude
`output/_stepup/etude2/references/`). Lue par la chaîne « littéral » (broll_litteral.py, plus.BROLL "chain"
= "litteral") : le directeur la lit à chaque appel, la modifier change la chaîne. L'ancienne charte des dessins est
gardée dans `charte-dessin.md` pour la chaîne « dessin ».

## Une seule patte pour toutes les images

Photo réaliste, plan de cinéma ou rendu 3D médical : couleurs franches, très contrasté, net. Jamais de dessin, jamais
d'aquarelle, jamais de dessin animé. Le prompt de chaque image commence par cette phrase, mot pour mot, ajoutée par
le code (le directeur n'écrit aucun mot de style ni d'appareil photo) :

> Photorealistic cinematic photograph set in the United States, vivid saturated colours, strong contrast, crisp sharp focus, one clear subject filling the frame, no writing, no letters and no logos anywhere.

(9 octobre 2026, au banc : « every label, sign and screen left blank » faisait des rectangles blancs partout et
laissait passer des panneaux en chinois ; sans lieu dit, Z-Image met des Asiatiques et des enseignes chinoises
partout, alors que les podcasts sont américains.)

Pour une séquence d'explication (plus bas), la figure 3D suit cette phrase-là, mot pour mot, ajoutée par le code :

> High-end 3D medical visualization, vivid saturated colours, strong contrast, crisp sharp focus, one clear figure centred in the frame on a plain dark background with space around it, nothing written anywhere.

## Les formats, choisis par le directeur

(Règles du décodage de 12 Shorts d'OptimalHealth, `output/_stepup/etude2/decodage/rapport.md` § 4 : un objet qu'on
tient → carte en bas ; une matière, une action, un lieu, un état vécu → plein écran ; un mécanisme invisible → 3D ;
un geste pas à pas → une seule figure 3D qui évolue. Les 3 premières secondes restent sur le visage, au plus une
carte ; le clip finit sur un visage ; ≈ 40 % du temps hors visage.)

- **Écran coupé en deux** : l'invité dans la moitié haute, la matière ou les petites choses nombreuses (un tapis de
  comprimés, des grains de café) remplissent la moitié basse ; le sous-titre tombe sur la ligne de séparation.
- **Intérieur du corps** : un nerf, une cellule, un organe, une inflammation, en rendu 3D médical plein écran (la
  phrase de style des séquences).

- **Scène** : plein écran, 9:16. Un lieu (une salle des urgences, un bloc opératoire), une personne générique qui
  fait quelque chose (un médecin épuisé au bout d'une garde), un geste, l'intérieur du corps (en rendu 3D médical
  propre, l'organe entier).
- **Objet** : la chose seule, centrée, sur un fond uni coloré qui tranche avec elle (un flacon de comprimés sur fond
  bleu ciel, des clés de voiture sur fond jaune). Affichée en grande carte (≈ 60 % de la largeur, coins arrondis,
  légère ombre) dans la moitié basse de l'écran, par-dessus le bas du visage. Pour ce qu'on tient dans la main ou
  qu'on pose sur une table.
- **Séquence d'explication** (ajoutée le 9 octobre 2026, d'après « The Eye Trick », 1,6 M, et le cordon ombilical,
  1,4 M, d'OptimalHealth) : quand l'invité décrit un geste, une technique ou un mécanisme, on reste 5 à 10 s sur une
  même figure 3D plein écran — une tête ou un corps humain en hologramme anatomique bleu lumineux sur fond sombre,
  ou un organe en rendu 3D anatomique réaliste — et elle évolue mot à mot : une flèche, un cercle de rotation, une
  zone qui s'allume, dessinés par le code en blanc lumineux (exacts, jamais demandés au modèle d'image). Même figure,
  même cadrage d'un plan à l'autre : seule l'indication change, sur le mot qui la dit.

## Jamais de texte

Aucun mot, aucun chiffre, aucune étiquette lisible dans l'image : le modèle d'image écrit faux. Une boîte, un flacon,
un écran restent unis.

## Les gens

Des inconnus génériques (un médecin, une patiente, un interne fatigué), habillés de la tête aux genoux. Jamais une
vraie personne, jamais l'invité ni l'animateur, jamais une personne nommée dans le clip.
