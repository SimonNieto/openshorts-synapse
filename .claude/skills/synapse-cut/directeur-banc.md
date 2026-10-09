# Méthode du directeur — chaîne « littéral »

Écrite le 9 octobre 2026. Le directeur de la chaîne « littéral » (broll_litteral.py) la lit à chaque appel : la
modifier change la chaîne. Les principes du directeur des dessins sont gardés dans `directeur-dessin.md`.

**La règle qui la résume : le directeur ne cherche pas une idée. Il relève les noms concrets dits dans le clip et
montre chacun tel quel.**

1. Un nom concret, c'est une chose qu'une caméra peut filmer : un objet (un flacon, des clés, un téléphone), une
   substance (des comprimés, du café, de l'eau), un organe (le cœur, une tumeur, le cerveau), un lieu (les urgences,
   un bloc opératoire, une chambre la nuit), un geste (conduire, prendre la tension), un type de personne (un médecin
   de garde, une patiente, un interne).
2. Ne sont pas concrets : les idées (la valeur, l'ego, la peur), les chiffres et les durées, les noms propres de
   personnes, les figures de style (« une flaque de larmes », « les lumières brillantes »), les mots dits en passant
   qui ne sont pas le propos (« quelqu'un m'a envoyé sur X » : X n'est pas le sujet).
3. L'image est la chose, littéralement, telle qu'on la reconnaît : « mélatonine » → un flacon de comprimés de
   mélatonine ; « urgences » → une salle des urgences ; « médecin » → un médecin en blouse. Pas un détour, pas une
   ambiance, pas un symbole.
4. Le format :
   - **objet** pour ce qu'on tient dans la main ou qu'on pose sur une table : la chose seule, avec la couleur unie du
     fond, choisie pour trancher avec elle ;
   - **scène** pour un lieu, une personne, un geste, l'intérieur du corps (rendu 3D médical propre, l'organe entier).
5. Une description courte (30 mots au plus), au présent, au positif, en mots simples : ce qui remplit l'image, un
   ou deux détails vrais tirés de ce qui est dit (« trois heures du matin », « au bout de quinze heures de garde »).
   « A single » pour ce qui est seul. Aucun mot de style ni d'appareil photo (le code les ajoute), aucun texte à
   lire, aucune comparaison.
6. Une même chose qui revient garde la même clé : son image revient, sans être refaite.
7. Proposer large : un nom concret à chaque fois qu'il est dit. Le code choisit (une image toutes les 3 à 5 s, pile
   sur le mot) ; la priorité dit ce qui compte le plus (3 = la chose dont parle le clip).
8. Quand l'invité explique **comment** faire ou **comment ça marche** (un geste des yeux, une respiration, un nerf
   qui transmet, un cordon qui pulse), une seule séquence d'explication pour ce passage : une figure 3D décrite une
   fois (l'hologramme bleu d'une tête ou d'un corps, ou l'organe en rendu anatomique réaliste), les points de la
   figure où quelque chose se passe, nommés tels qu'on les voit à l'écran (« l'œil à gauche de l'écran »), et 3 à 6
   étapes, chacune sur le mot qui la dit, avec ce qui s'y montre : une flèche (vers où), un cercle qui tourne (dans
   quel sens), une zone qui s'allume. Rien de tout ça dans la description de la figure : le code le dessine.
9. Une vraie personne nommée ne donne jamais d'image, même pas un inconnu qui la remplacerait ; la gravité, la
   sécurité et les faits des principes passent avant tout.
