# Combat A30 et mode de test

Les réactions fondées sur les paramètres source et l’alerte entre alliés sont
décrites dans [AI_BEHAVIOR.md](AI_BEHAVIOR.md). Les chiffres de ce document
correspondent à l’étape précédente.


Correction du 20 octobre 2026, après le signalement d'IA statiques et de tirs
sans effets visibles. La carte et ses matériaux ne sont pas réimportés.
Sauvegarde : `work/a10/backups/20261020-1819-combat`.

## Joueur invincible

`Invincible` est activé par défaut sur le joueur. Les dégâts d'armes ne
retirent ni santé ni bouclier. F10 permet de basculer ce mode, avec une
indication dans le HUD. Une réapparition revient au réglage de test activé.
Les ennemis restent vulnérables. Le test automatisé désactive explicitement
ce mode pour les contrôles de dégâts et de mort, puis vérifie la réapparition.

## Déplacement

L'ancien contrôleur s'arrêtait à 600 cm de sa cible et ne changeait plus de
position à portée. Le contrôleur de prototype demande maintenant des
repositionnements latéraux sur la navigation, espacés de 1,6 à 2,6 secondes,
et rejoint une cible trop éloignée. Les destinations proches sont projetées
sur la navigation ; les mouvements latéraux refusent les chemins partiels.
Les pauses et ordres du scénario gardent la priorité. Aucun ennemi n'est ajouté.

Le test d'arrivée relève les positions des sept passagers APRÈS leur
débarquement, puis vérifie leur déplacement réel au bout de huit secondes.
Un chemin existant près du joueur ne suffit plus à valider ce comportement.
Les états de contrôleur, mouvement, chemin et tirs sont consignés dans
`npc_diagnostics` des rapports du scénario, y compris en partie normale.

## Effets de tirs

Le flash reste visible pendant 85 ms à partir du tir effectif, indépendamment
du compteur qui régule la cadence. Il est réinitialisé à chaque tir et masqué
à la mort/désactivation. Le flash et la lumière sont déclenchés aussi pour
les ennemis. Des sprites de trajectoire ambre ou cyan rendent les tirs
visibles dans le monde ; ils n'ont ni collision ni influence sur la navigation.
Les tirs utilisent toujours le calcul d'impact instantané du prototype : ces
trajectoires sont des effets visuels, pas une reproduction des projectiles Blam.

Les anciens billboards pouvaient être déclarés visibles sans apparaître
dans le rendu de ce moteur. Les sprites utilisent désormais un mesh orienté
vers la caméra et rendu dans la passe principale, sans collision.
Les textures utilisées viennent des effets Anniversary déjà importés. La
capture `enemy-fire.png` complète les vues de l'introduction, du HUD, du
transport et du débarquement. La validation de pixels du flash du joueur est
conservée ; les effets des ennemis sont aussi relus dans le rendu réel.

Cette correction améliore le contrôleur Unreal existant. Elle ne constitue
pas la récupération de toute l'intelligence tactique d'origine.

## Contrôles de la livraison

- 38 tests Python.
- 35 contrôles de gameplay sur chaque carte, dont F10, dégâts ignorés en mode
  invincible et retour à ce réglage lors de la réapparition.
- 28 contrôles d'arrivée A30. Les sept unités source se sont déplacées de
  2,4 à 7,7 mètres dans les huit secondes suivant le débarquement.
- Rafale avec le véritable bouton de souris à 30 images/s : 8 tirs,
  flash visible, puis extinction après relâchement.
- Capture des tirs ennemis : 115 pixels cyan d'effet détectés, en excluant
  l'anneau du réticule. Les captures du joueur montrent aussi le flash.

Les rapports de scénario et de surfaces A10/A30 sont renouvelés sur le
même projet final. `work/arrival-audit/final-delivery-proof.json` consolide
les empreintes et les états ; ses limites A10 restent explicites.

Le test de cadence mesure la rafale à partir du premier tir émis après
traitement de l'entrée. Les captures vérifient aussi que le flash est encore
actif pendant l'image demandée, pour éviter de capturer son extinction.
