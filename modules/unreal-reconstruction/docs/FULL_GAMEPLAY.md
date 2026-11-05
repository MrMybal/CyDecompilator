# Conduite, combat embarqué, manœuvres et effets Anniversary

Cette étape ajoute la conduite du Warthog, du Ghost, du Scorpion, du Banshee et
du Wraith au projet Unreal 5.8. Les commandes passent par le personnage possédé :
la sortie du véhicule restitue sa caméra, ses armes et ses commandes. Le Wraith
conduisible est une extension du portage, pas une fonctionnalité du Halo CE original.

Le projet reste `work/a10/HaloA10/HaloA10.uproject`. Le module reste indépendant
de CyDecompilator. Aucun runtime Blam n'est embarqué ; les services sont en C++
Unreal. Les fichiers originaux et les dix maps existantes ne sont pas régénérés.

## Commandes

- E près d'une place libre : monter ; E à bord : descendre si un emplacement sûr existe.
- Z/W et S : accélérer et reculer ; Q/A et D : direction/translation ; souris : regarder et viser.
- Espace : frein du Warthog, montée en vol ; Ctrl : descente en vol.
- Clic gauche et droit : détente principale et secondaire des armes de bord.
- Place tireur du Warthog : la souris commande la tourelle, clic gauche tire.
- Place passager : arme personnelle, tir et rechargement ; les munitions de l'arme
  personnelle restent distinctes des armes de bord.
- F10 : invincibilité de test, active par défaut, également appliquée au véhicule occupé.

La place la plus proche est choisie parmi les places libres. Les véhicules qui
jouent un enregistrement cinématique ne peuvent pas être pris pendant sa lecture.
Un PNJ peut conserver la conduite pendant que le joueur occupe la tourelle ou
une place passager. Monter et descendre de ces places préserve sa destination.
La caméra passager vient du `camera_marker_name` de la place source.

## Données et fonctions portées

`recover_vehicle_runtime.py` récupère 23 définitions de véhicule, leurs places,
repères multiples, armes, projectiles, dommages, sons et paramètres de conduite
dans les dix caches. Les valeurs restent en unités source jusqu'à la frontière
Unreal. Les commandes sont intégrées à 30 Hz, avec détection des obstacles et du
sol. Les profils de vitesse, les termes du scout et le paramètre de rotation des
roues proviennent des fonctions originales. Les meshes de coque intacts et leurs
hiérarchies articulées sont des dérivés des modèles Anniversary.

Les pilotes utilisent perception et mémoire, des passes d'attaque, des approches
de destination, des détours aériens ou des chemins au sol, et une récupération
quand la coque est bloquée. Un ordre scripté garde la priorité. Un pilote passif
ne reprend plus une ancienne cible une fois son déplacement scripté terminé.

Le profil de tir de l'arme montée vient de
`weap_attrs.aiming.actor_firing_parameters`, conformément à
`actor_combat_get_firing_variant_definition`. Il ne remplace pas la perception
et les points de vie du personnage. Les détentes ont des horloges distinctes,
la chambre du canon et du fuel rod conserve sa temporisation, et l'IA applique
les portes de situation et de dommages collatéraux du tir secondaire. Le tir
spécial du Banshee respecte aussi le délai et les charges intermédiaires.

`RecoveredPlatoons` utilise les règles de force/effectif des platoons, leurs
transitions attaque/défense, l'autorisation des manœuvres et les destinations de
squad de la campagne. Les unités réservent des positions de tir distinctes et
évitent de tirer dans leurs alliés. Les parcours non combattants conservent les
ordres répétition, boucle, aller-retour et choix pondéré, les séquences, les temps
d'attente et les positions occupées.

Les fonctions de référence sont dans `tools/cea-runtime-reference/src/blam` :
`encounter_test_rule`, `encounter_update_platoons`, `action_alert_next_position`,
`actor_combat_enable_special_fire_situation`,
`actor_combat_allow_special_fire_situation`, `action_charge_begin`,
`actor_action_handle_combat_selection`, `actor_move_calculate_free`,
`update_alien_scout_physics`, `update_human_jeep_physics` et les fonctions
`physics_variable_speed_update*`.

## Graphes d'effets

Le bloc original `initial_ps/ps.CacheBlock.bin` est décompressé en 9 276 entrées
identifiées, puis lu comme données. Aucun SSL ni programme externe provenant
des fichiers du jeu n'est exécuté. Les espaces de noms des particules et des
objets de contrôle sont résolus séparément : une définition d'entité homonyme
ne peut plus écraser le fichier `.sfx` reconnu par son CRC de nom.

Le registre contient 1 348 définitions nommées, dont 422 graphes à émetteurs.
116 références de textures Anniversary ont été résolues. Les rectangles d'atlas
et les feuilles d'animation sont conservés. Le lecteur natif gère les émissions,
durées, courbes de taille/couleur/transparence, vitesses, gravité, frottement,
rebonds simples, lumières et segments de traînées. Tous les plans visuels sont
sans collision et ne modifient pas le NavMesh.

Le pont HCEX de nommage est porté depuis `src/hcex`. Les programmes SML sont
convertis en un arbre limité de conditions d'état et de commandes
Start/Restart/Stop/PauseSfx. Les événements de tir, de charge et de surchauffe
utilisent cet arbre. Les effets suivent les repères animés des armes et des
tourelles ; le tir secondaire et les deux bouches du Banshee restent distincts.
Les réponses d'impact sont celles des tables source des 33 matériaux et de la
détente effective. Un effet récupéré évite le double affichage des particules
génériques antérieures.

Les courbes et vecteurs sans crochets, y compris les listes séparées par des
virgules, sont lus sans interrompre les propriétés suivantes. Les indicateurs
numériques 0/1 sont acceptés au même titre que yes/no et true/false. Un graphe
sans texture rendable ni lumière ne masque pas le chemin visuel de repli.
Le flash et la lumière génériques ne se superposent plus à un graphe de bouche
Anniversary actif ; les projectiles sans modèle récupéré utilisent leur traînée
rendable sans ajouter une sphère générique.

## Validation et limites de la preuve

La preuve de cette étape est `work/full-gameplay/delivery-proof.json` ; les
preuves des étapes précédentes restent historiques. Le vérificateur
`scripts/verify_full_gameplay.py` rejoue les entrées de conduite et les scénarios
natifs, puis les suites d'armes, de combat, de connaissance, de personnages et
le démarrage des dix maps. Les sauvegardes de campagne sont conservées par le
gestionnaire `preserve_checkpoint`. Les captures sont dans
`Saved/Validation/Vehicles` et `Saved/Validation/FullGameplay` du projet.

La preuve distingue les binaires testés. Après la validation complète, les derniers
ajustements des places, caméras, repères et indicateurs VFX ont été vérifiés par
les suites véhicules, pilotage, escouades, armes, combat et arrivée A30. Les autres
suites conservent le binaire archivé de cette même passe ; les sources hors des
fonctions modifiées, les données et la configuration sont comparées explicitement.
Le détail exact figure dans `final-scoped-delta.json` et dans les reçus par suite.

Trois comparaisons avec les corps C originaux non modifiés sont reproductibles :
3 700 000 cas pour les règles de platoon, 300 000 pour le parcours des positions,
181 632 pour les portes du tir spécial. Elles vérifient ces fonctions de valeur,
pas l'équivalence du jeu entier. Les tests natifs vérifient séparément leur
raccordement aux acteurs Unreal.

Une fidélité à 100 % au jeu commercial n'est pas certifiée. La référence C
disponible est une reconstruction du prototype de juin 2011. La physique de
véhicule utilise un adaptateur cinématique Unreal, et ne reproduit pas l'ensemble
du solveur rigide Blam, des suspensions et des contacts. Le choix des matériaux
de surface sur les meshes Anniversary passe encore par un adaptateur de noms
de sections, car leur index de matériau de collision classique n'est pas conservé.

Le registre source contient aussi des références sans ressource résolue :
`anniversary-fx/texture-errors.json` et `anniversary-fx/bindings.json` les listent
explicitement. Ce sont des références rencontrées dans l'ensemble des données,
pas autant d'effets manquants effectivement déclenchés. Les contrôleurs de
palettes, de géométrie d'effet, de flares et certains shaders Saber n'ont pas
d'équivalent exact dans le lecteur actuel. Pour un graphe absent ou non exécutable,
le chemin visuel antérieur sert de repli ; il n'est pas présenté comme exact.
Le rapport d'audit des graphes distingue ces cas des graphes récupérés et rendus.

## Rejouer

Depuis le dossier du module, avec le Python du projet :

```powershell
../../runtime/python/Scripts/python.exe -m unreal_reconstruction prepare
../../runtime/python/Scripts/python.exe -m unreal_reconstruction build --engine G:/UnrealEngine/UE_5.8
../../runtime/python/Scripts/python.exe scripts/verify_full_gameplay.py
../../runtime/python/Scripts/python.exe scripts/test_platoon_rules.py
../../runtime/python/Scripts/python.exe scripts/test_patrol_rules.py
../../runtime/python/Scripts/python.exe scripts/test_special_fire_rules.py
../../runtime/python/Scripts/python.exe -m unittest discover -s tests
```

Vérifier la réussite de la compilation avant de lancer les tests natifs.
