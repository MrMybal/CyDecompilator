# Reprise des armes et portage C++ Unreal

Architecture explicitement choisie : toute la logique de jeu reste dans Unreal.
Le runtime Halo recompilé n'est pas chargé. Les fonctions récupérées servent de
référence pour des ports C++ avec des entrées et des services Unreal explicites.
Le module reste indépendant de CyDecompilator. Les fichiers du jeu sont lus
uniquement ; les modèles et textures de rendu sont ceux d'Anniversary.

La continuation est suivie dans [COMBAT_ACTIONS.md](COMBAT_ACTIONS.md) : lancer de
grenades IA/joueur, transitions de surchauffe et reprise des ordres au débarquement.
Les nombres ci-dessous décrivent la première preuve ; la nouvelle preuve est
isolée dans `work/combat-actions`.

## Armes et animations

`weapon-parity.json` surcharge l'arsenal existant avec les données des quatorze
armes, leurs déclencheurs, consommation, dispersion et paramètres de projectile.
Les anciens assets restent disponibles. Les nouveaux assets sont isolés sous
`/Game/Recovered/WeaponParity`.

- Les restrictions de prise en main « PNJ uniquement » sont levées. Un changement
  d'arme efface la présentation et l'état de mêlée précédents.
- Huit armes ont leur modèle Anniversary et **107 clips source** importés :
  fusil d'assaut, pistolet, fusil et pistolet à plasma, sniper, Needler,
  shotgun et lance-roquettes. Les indices de la table de première personne
  récupérée déterminent les actions lorsqu'ils sont présents.
- Les morceaux `$p0/$p1/$p2` sont conservés ; les vrais LOD sont exclus par
  leurs noms source. La hiérarchie des parents source détermine les os des
  pièces, notamment pompe, magasin, tubes et poignée.
- **65 actions PNJ** de tir, rechargement et lancer ont été récupérées, avec
  62 poses d'attente nécessaires à l'adaptation des overlays. Les 127 clips
  sont importés sur les squelettes Anniversary existants. Les animations de
  rechargement sont utilisées dans la couche supérieure du corps.
- Le shotgun insère les cartouches une à une et utilise ses clips d'entrée,
  d'insertion et de sortie. Le rechargement conserve les munitions.
- Les armes à batterie consomment une quantité fractionnaire issue du tag.
  Le pistolet à plasma charge sur maintien, tire au relâchement et utilise
  le second déclencheur pour le tir chargé. La prise en main respecte la
  durée du clip source ; cadence progressive et refroidissement sont repris.
- Les billboards d'effets conservent une référence verticale explicite et
  le roulis caméra ; les projectiles disposent d'un repère local explicite.
  Des tests couvrent les directions verticales et les changements d'axes.
- 24 textures de surface supplémentaires ont été récupérées pour les nouvelles
  armes : normales, spéculaire, émission et masques. Le rendu en damier détecté
  sur le fusil à plasma a été corrigé et contrôlé dans Unreal.

## Fonctions d'IA et tests de référence

`RecoveredSourceRules.h` contient les règles indépendantes du monde. Le test
`scripts/test_source_rules.py` compile les corps C récupérés sans les modifier,
avec des doublures de recherche de tags, données et services. Il compare les
sorties, mutations et l'ordre des appels pour **200 000 cas sur dix fonctions**.
Cela valide les règles de valeur ; cela ne valide pas les structures binaires
reconstruites ni l'équivalence complète avec le jeu commercial.

Huit règles d'IA sont raccordées aux adaptateurs Unreal : les deux distances de
vision, quatre déclenchements de berserk, la panique après dégâts, le délai de
première rafale et le contrôle de direction de visée. La règle de décision de
grenade est testée séparément ; ses services de monde ne sont pas encore portés.
La dixième fonction comparée calcule la fraction de charge de l'arme.

`scripts/report_native_port_coverage.py` produit
`work/weapon-ai-parity/ai-port-coverage.json` : 908 fichiers de fonctions de la
référence sont inventoriés avec leurs empreintes et leur état. L'import d'un
paramètre ne suffit pas à déclarer une fonction portée.

La référence lisible locale est une reconstruction best effort d'un prototype
de juin 2011. Elle ne constitue pas une source complète et certifiée du runtime
commercial installé. Les adaptateurs de mémoire, recherche, navmesh, cibles et
rafales Unreal restent distincts des règles comparées.

## Limites encore concrètes

Le résultat n'est **pas un portage à 100 % des armes ni de l'IA**.

- Les cinq interfaces source épée, canon de Hunter, rayon de Sentinelle,
  tourelle et fuel rod n'ont pas de graphe joueur. L'épée et le fuel rod
  utilisent une présentation statique adaptée ; les émetteurs intégrés n'ont
  pas encore de modèle joueur autonome.
- Le lance-flammes possède des animations source, mais aucun modèle Anniversary
  n'a été trouvé dans les dix archives de mission ni dans les inventaires partagés
  `initial_tpls` et `pak_stream`. Son rendu joueur manque.
- Les 132 dépendances d'effets récupérées ne sont pas un interpréteur complet
  des effets Saber/Blam. Plusieurs projectiles, impacts et explosions restent
  des présentations génériques ; la géométrie source `rl_projectile` est vide.
- Certaines transitions secondaires, notamment la séquence complète de surchauffe
  et l'ordonnancement du lancer de grenade PNJ, restent à raccorder.
- Le graphe complet de connaissances, la sélection et notation des cibles,
  les tactiques d'escouade, les trajectoires de grenade, les véhicules,
  les esquives, la réanimation Flood et les services de difficulté restent
  à porter. Les fonctions correspondantes sont explicitement marquées absentes.

## Vérifications et reprise

Les rapports sont dans `work/weapon-ai-parity`. La nouvelle preuve n'est valable
qu'après réussite de `scripts/final_weapon_parity_checks.py` et production de
`delivery-proof.json`, liée au manifeste `tested-project.json`.

`scripts/upgrade_weapon_cpp.py` regroupe récupération, conversions Blender,
imports, shaders, compilation et validations pour reproduire cette étape sur le
projet dix missions déjà préparé. Il nécessite les récupérations antérieures
et la copie de référence présente dans `work/weapon-ai-parity/before`.

```powershell
$taskPython = '..\..\runtime\python\Scripts\python.exe'
& $taskPython scripts/test_source_rules.py
& $taskPython scripts/report_native_port_coverage.py
& $taskPython scripts/check_weapon_parity.py weapons
& $taskPython scripts/check_weapon_parity.py ai
& $taskPython scripts/final_weapon_parity_checks.py
```

Les tests en jeu couvrent l'arsenal, les matériaux rendus, le chargement,
les munitions, les PNJ et leur combat dans des scènes bornées. Ils ne démontrent
pas que toutes les campagnes se terminent ni que tous les effets sont identiques.
La sauvegarde A30 est protégée pendant les tests ; la preuve contrôle également
les trois sauvegardes antérieures, les entrées originales et tout le contenu
préexistant du projet, y compris les dix cartes.

Dernière validation : **516 contrôles Unreal** réussis (105 arsenal, 35 IA,
159 combat partagé, 217 familles de PNJ), **56 tests Python** et les 200 000
comparaisons de référence. Les **59 283 fichiers de contenu préexistants**,
les 23 entrées originales et les trois sauvegardes contrôlées sont inchangés.
Ces nombres certifient cette étape bornée, pas le portage complet demandé.
