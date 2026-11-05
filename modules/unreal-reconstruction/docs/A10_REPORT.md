# Bilan du prototype A10 — 20 octobre 2026

Ce bilan décrit la première livraison. Les corrections et l'ajout de la deuxième carte
sont décrits dans [A10_A30_CORRECTIONS.md](A10_A30_CORRECTIONS.md).

La première carte de Halo: Combat Evolved Anniversary, **The Pillar of Autumn**, est
reconstruite dans un projet Unreal éditable. Le module reste indépendant de CyDecompilator,
dans `modules/unreal-reconstruction`. Les données de `modules/xbox-native` sont uniquement lues.

## Ouvrir et jouer

- `../Open-HaloA10.cmd` ouvre le projet dans l'éditeur.
- `../Play-HaloA10.cmd` lance directement la carte dans une fenêtre de jeu.
- Projet : `../work/a10/HaloA10/HaloA10.uproject` ; niveau : `/Game/Maps/A10`.
- Installation validée : `G:\UnrealEngine\UE_5.8`, version 5.8.3.
- Commandes : WASD/ZQSD, souris pour regarder et tirer, clic droit pour viser,
  Espace pour sauter, Ctrl pour s'accroupir, R pour recharger.

Les binaires actuels sont construits pour cette installation. Pour utiliser les sources
CyAtlas locales, reconstruire le module avec `build --engine <installation CyAtlas>`.
La validation finale décrite ici a été faite avec l'installation sur `G:`.

## Contenu récupéré et adapté

| Élément | Résultat |
| --- | --- |
| Géométrie Anniversary A10 | 246 morceaux, 2 426 394 sommets, 1 600 412 triangles |
| Décor et dispositifs | 383 objets placés, dont des portes de proximité |
| Personnages | 210 PNJ placés depuis les rencontres et positions de difficulté normale |
| Modèles de personnages | Cyborg, Marine, Élite, Grunt, bras de première personne |
| Animations distinctes converties et importées | 40 : Marine 9, Élite 9, Grunt 7, Cyborg 10, première personne 5 |
| Affectation des matériaux | 1 200 emplacements affectés sur 278 meshes ; 21 restent sans correspondance |

Les animations sont décodées depuis les données originales, puis adaptées aux squelettes
Anniversary. La prise en main et les poses restent à affiner. Des humains sans modèle dédié
utilisent le Marine. Les PNJ reprennent les positions sources ; les scripts de déclenchement
et de progression des rencontres ne sont pas exécutés.

Le déplacement, le saut, l'accroupissement, la visée, le tir à rayon, les munitions,
le rechargement, les dégâts et le bouclier sont une nouvelle implémentation Unreal.
L'IA utilise des équipes, la visibilité, la navigation et un combat élémentaire.
Le code PowerPC recompilé n'est pas exécuté dans Unreal.

## Validation exécutée

La construction C++ et la création du niveau ont réussi. **7 tests unitaires passent**.
Le test dans un véritable processus Unreal charge `/Game/Maps/A10` avec rendu et vérifie
**16 assertions, toutes réussies** :

1. Apparition du joueur.
2. Présence de son modèle.
3. Animations de première personne disponibles.
4. Collision avec le sol de la carte.
5. Présence des personnages des rencontres.
6. Déplacement du joueur.
7. Maintien du joueur sur la carte après déplacement.
8. Tir touchant un personnage.
9. Consommation de munitions.
10. Conservation des munitions au rechargement.
11. Navigation disponible.
12. Chemin de navigation calculé sur la carte.
13. Tir d'une IA sur le joueur.
14. Séquence animée affectée.
15. Évolution réelle d'une pose animée.
16. Dégâts et mort.

Le combat et les dégâts utilisent une situation de test isolée et bornée. Le sol,
le déplacement et le chemin de navigation sont contrôlés séparément sur la carte importée.
Ces vérifications ne démontrent pas que toute la mission est traversable ou fidèle.

Preuves locales conservées :

- `../work/a10/conversion-report.json` : état, métriques, omissions et résultats d'import.
- `../work/a10/runtime-proof.json` : empreintes des sources, assets, DLL et preuves.
- `../work/a10/HaloA10/Saved/Validation/runtime.json` : assertions du test Unreal.
- `../work/a10/HaloA10/Saved/Validation/a10-start.png` : capture réelle du niveau rendu.
- `../work/a10/logs/` : journaux et reçus des processus.

La preuve est invalidée si les sources, assets, DLL ou résultats concernés changent.

## Limites de cette livraison

Le résultat est un **prototype jouable**, sans conversion des scripts de campagne,
des vagues conditionnelles, des ordres originaux des IA, des sauvegardes, de l'audio ou
de la fin de mission. Les cinématiques restent hors de ce premier essai.

L'éclairage et les matériaux sont approximatifs. Certains effets et surfaces transparentes
restent opaques et produisent des artefacts visibles. Les objets non pris en charge sont
énumérés dans le rapport JSON. Les neuf secteurs graphiques sont chargés ensemble ; le
streaming et les transitions BSP originaux ne sont pas reproduits.

Cet adaptateur cible les données Halo inspectées. Il ne permet pas encore de convertir
automatiquement n'importe quel jeu décompilé en projet Unreal.
