# Escouades, pilote embarqué et flashes de tir

Cette étape conserve le gameplay en C++ Unreal et les assets de rendu
Anniversary. Les preuves précédentes restent dans leurs dossiers historiques ;
la copie de référence et les résultats de cette passe sont dans `work/squad-vfx`.

## Déplacements d'escouade

Les personnages utilisent les positions de combat et les groupes de leur
rencontre/squad d'origine. Le sélectionneur vérifie la navigation et la visibilité,
évalue la portée et les lignes de tir amies, puis réserve une position par acteur.
Un autre combattant de la rencontre choisit une position libre. Les réservations
sont libérées lors de la réinitialisation, de l'attente ou des ordres passifs.
Le repli peut choisir un point réellement masqué par le décor. Le déplacement
générique reste disponible lorsqu'aucun point source ne convient.

Les règles de groupe, classement, garde, attaque, mouvement de combat et blocage
de visée sont portées depuis les fonctions récupérées. Les requêtes de chemin,
la couverture et l'attribution des positions restent des services Unreal. Les
états et manœuvres complets des pelotons ne sont pas encore reproduits.

L'IA suspend aussi le tir lorsqu'un allié coupe sa ligne, puis reprend une fois
le passage dégagé. L'ordre `ai_defend` sélectionne les groupes défensifs.

Les **47 172 positions** et **2 988 squads** des dix caches source sont vérifiés.
L'ancien `a10-campaign.json` n'avait pas la table `encounters` : ce champ seul
est ajouté depuis A10. Les neuf autres tables sont identiques à la source.
Aucun fichier de niveau ni modèle n'est réimporté.

## Pilotage par points

Un personnage réellement installé au siège conducteur d'un Pelican ou Banshee
peut piloter vers un point. Les commandes `goto` des listes de campagne utilisent
ce service lorsqu'elles concernent un conducteur embarqué. Les axes de commande
libre et leurs bases de vol viennent du code récupéré ; les vitesses et glissements
utilisent les intégrateurs déjà portés. L'actualisation fonctionne à 30 Hz.

Le véhicule ralentit et s'arrête au point. Une requête de collision arrête le
déplacement devant un obstacle statique. Le déplacement cinématique enregistré
garde la priorité et annule le pilote par points.

Il s'agit d'un premier suivi de points en vol. Les virages et la tolérance
d'arrivée sont une adaptation Unreal. Le contournement autonome d'obstacles,
les manœuvres de combat, les véhicules terrestres, la suspension et la dynamique
complète du châssis restent à porter. La requête sphérique ne reproduit pas
exactement les contacts de toute la coque.

## Flashes de tir

Un relevé des 14 armes conserve **143 enregistrements d'émetteurs**, avec toutes
leurs définitions de particules référencées. Le rendu utilise un flash composite Anniversary par décharge, sélectionné
parmi les événements compatibles avec la caméra. Le fusil d'assaut utilise sa
véritable géométrie de flamme et ses UV importés. Les autres armes conservent
leur présentation déjà calibrée (volume lumineux ou sprite). La variation du
rayon source est normalisée autour de cette échelle Anniversary, plutôt que de
plaquer des dimensions Classic sur une autre géométrie.

Les retards, durées de vie, vitesses et rotations des événements sélectionnés
sont utilisés ; les flashes attachés suivent l'ancrage de l'arme et conservent l'inclinaison réelle du tir des PNJ
lorsque le personnage tourne. Les plans ne
possèdent aucune collision. Une nouvelle décharge réutilise le composite
précédent : les nombreuses particules Classic ne sont pas superposées avec une
même texture Anniversary. Leurs quantités, ainsi que les fumées, bulles et
douilles sans liaison adaptée, restent conservées dans le relevé pour le portage
ultérieur des graphes.

La lecture de `build_sprite_compute_basis` a corrigé une ambiguïté d'axes :
le mode parallèle place **UV X** le long du tir. Le mode perpendiculaire utilise
la référence verticale du monde, avec repli près des pôles ; le mode écran
reste parallèle au plan de caméra. Les matériaux dynamiques utilisent un asset
de matériau comme parent, pour éviter le damier de secours Unreal.

Les shaders, atlas et séquences exacts, les marqueurs secondaires, les pièces
et lumières des graphes, la physique complète des particules et les effets
d'impact/projectile exacts ne sont pas entièrement portés. Cette étape améliore
les flashes ; elle ne constitue pas une reproduction complète des VFX d'origine.

## Vérification

`test_tactical_rules.py` compare **210 000 cas** à huit corps C récupérés non
modifiés. La référence reste la reconstruction d'un prototype de juin 2011,
pas un source retail complet certifié.

La scène `-CySquadCheck` vérifie les réservations distinctes, le mouvement réel
sur le NavMesh, la suspension/reprise du tir, les axes des particules, leurs
matériaux et collisions, puis le vol avec conducteur et l'arrêt devant un mur.
Les suites antérieures et les scènes A30/A10 complètent ces contrôles.

```text
python scripts/recover_tactical_data.py
python scripts/recover_muzzle_particles.py
python scripts/test_tactical_rules.py
python -m unreal_reconstruction prepare
python -m unreal_reconstruction build --engine G:/UnrealEngine/UE_5.8
python scripts/verify_squad_vfx.py --resume
```

Le contrôle visuel utilise les pixels réellement rendus, avec le masque alpha
exact de la texture du viseur et une limite de surexposition. Un contrôle négatif
vérifie qu'un viseur seul ne suffit pas à valider un flash.

Le banc de combat projette désormais le centre des limites rendues du flash,
plutôt que le pivot arbitraire du modèle Anniversary, et capture l'impulsion
avant sa fin. Cette dernière correction touche uniquement le banc de test.
Les huit suites déjà réussies sont conservées avec leur DLL et toutes leurs
empreintes source dans `fixture-only-validation.json` ; le vérificateur refuse
cette réutilisation si un autre fichier source change. Les 160 contrôles de combat
sont relancés sur la dernière compilation.

La preuve consolidée est `work/squad-vfx/delivery-proof.json`, avec les
empreintes du projet dans `tested-project.json`. Le vérificateur refuse toute
autre modification du contenu préexistant et préserve les sauvegardes.
