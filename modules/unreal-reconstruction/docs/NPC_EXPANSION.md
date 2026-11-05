# Personnages de campagne supplémentaires

Ce document décrit l'étape PNJ initiale. La reprise ultérieure des armes et
des fonctions C++ Unreal est suivie dans [WEAPON_CPP_PORT.md](WEAPON_CPP_PORT.md),
avec sa propre preuve de validation.

Les quinze familles ou personnages absents du premier portage sont récupérés
dans les archives Anniversary du jeu local : Hunter, Flood de combat humain et
élite, Flood porteur, infection Flood, Sentinel, Monitor, Keyes (trois tenues),
Marine suicidaire, Cortana, Keyes infecté, équipage et Johnson. Les modèles et
textures Classic ne remplacent pas les ressources Anniversary.

Les ressources supplémentaires se trouvent dans `/Game/Recovered/NPCExpansion`.
Les décors déjà importés sont conservés. Les fichiers `.umap` reçoivent les PNJ,
leurs références source et les navmeshes adaptés à leurs capsules.

## Couverture

L'import ajoute 3 254 acteurs et remplace 67 anciennes substitutions par le
modèle Marine. Le contrôle utilise les positions de départ des rencontres en
difficulté normale et les bipèdes nommés du scénario. Ce sont des positions
possibles de création par les scripts, pas autant d'ennemis simultanés.

| Niveau | Positions source de PNJ contrôlées |
| --- | ---: |
| A10 | 317 |
| A30 | 221 |
| A50 | 520 |
| B30 | 192 |
| B40 | 573 |
| C10 | 1 183 |
| C20 | 628 |
| C40 | 626 |
| D20 | 554 |
| D40 | 865 |
| Total | 5 679 |

Huit détecteurs de dégâts invisibles de D40 sont exclus explicitement : ils ne
représentent pas des personnages visibles. Les palettes inutilisées ne créent
pas de PNJ supplémentaires. Les identifiants de placement utilisent les indices
de rencontre, escouade et position : plusieurs rencontres peuvent avoir le même
nom dans les données source sans produire de doublons.

## Animation et comportement

Les graphes d'animation runtime de l'édition Anniversary sont décodés, puis
adaptés aux squelettes Anniversary. Les Flood gardent une permutation de membre
cohérente ; les membres intacts et endommagés ne sont pas superposés. Les rigs
rigides du Sentinel et du Monitor utilisent leurs matrices de nœuds source.
Le Marine particulier de C10 conserve une seule tête et une seule variante
de manches, comme le Marine partagé, même si son graphe d'animation est distinct.
Les appendices Flood utilisent la couverture alpha de leur atlas, et la couche
lumineuse utilise son masque couleur : leurs cartes ne forment plus de plans
noirs opaques.

Les directions de locomotion disponibles alimentent les blend spaces ; les
postures fusil/pistolet sélectionnent leurs clips et repères de main. Certains
personnages cinématiques n'ont pas quatre déplacements source : les directions
absentes restent consignées dans les données de présentation.

Les profils d'acteur fournissent les paramètres de combat, vitalités, équipes,
armes, attaques de contact et descendants du Flood porteur. Les ordres de vol
utilisent trois dimensions ; les unités au sol ont trois agents de navigation
sauvegardés par carte (humanoïde, Hunter, infection). Les alliances suivent les
appels de scénario, dont l'alliance Sentinel/joueur de C20. Les animations de
mort disponibles précèdent le ragdoll ; les voix utilisent les références de
dialogue source disponibles.

Les nouvelles armes des PNJ incluent shotgun, lance-roquettes, fuel rod et
épée à énergie, ainsi que les armes intégrées au Hunter/Sentinel. Leurs données
de tir sont récupérées ; les six armes jouables de première personne restent
celles du portage précédent. Le template source du projectile de roquette ne
contient aucune géométrie exploitable : son apparence reste générique.

## Validation et limites

`work/npc-expansion/delivery-proof.json` lie les résultats finaux aux empreintes
du projet et du code. Il vérifie les quinze modèles en jeu, le déplacement sur
la carte source, les profils, armes et morts, puis recharge les dix niveaux
pour comparer leurs PNJ aux emplacements source. Les tests du joueur A10/A30,
des huit autres démarrages de mission et du combat existant sont rejoués.
Les captures sont dans `work/a10/HaloA10/Saved/Validation/NPCExpansion`.

Résultat final : **606 contrôles en jeu et 56 tests Python passent**. Les
contrôles en jeu comprennent 217 assertions sur les quinze nouveaux types,
160 sur les huit cartes supplémentaires et leurs démarrages, 70 sur le joueur
A10/A30 et 159 sur le combat partagé. Les 45 captures ont été examinées ; un
contrôle des pixels vérifie aussi la présence effective de Cortana à l'image.
Les dix niveaux rechargés couvrent les 5 679 positions source sans doublon.

Les empreintes confirment que 58 500 fichiers de contenu préexistants hors
cartes, les 23 entrées source du jeu et les trois sauvegardes présentes avant
l'import sont inchangés. Les cartes ont été modifiées pour les PNJ et navmeshes.

Cette couverture ne constitue pas une réimplémentation complète de Blam.
La réanimation des Flood, le démembrement, les sauts tactiques, les particules
Saber exactes et les comportements propres aux cinématiques restent partiels.
La campagne complète n'est pas encore validée jusqu'à sa fin. Le rendu
holographique est une adaptation Unreal des atlas source.

## Reproduction

Depuis la racine du module, après la récupération et conversion des données :

```powershell
$taskPython = '..\..\runtime\python\Scripts\python.exe'
& $taskPython scripts/recover_missing_npcs.py
& $taskPython scripts/recover_npc_combat.py
& $taskPython scripts/recover_npc_weapon_models.py
# Conversion Blender, import, affinage, placement et reconstruction des navmeshes
# utilisent les scripts *_missing_npcs_unreal.py et build_npc_navigation_unreal.py.
& $taskPython scripts/check_missing_npcs.py
& $taskPython scripts/report_missing_npcs.py
```

Les reçus intermédiaires, les échecs initiaux et les copies de sauvegarde sont
conservés dans `work/npc-expansion`. Le rapport final vérifie les fichiers du jeu
original et les sauvegardes présentes avant l'import.
