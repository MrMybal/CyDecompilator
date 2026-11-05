# Suite du portage C++ : grenades, surchauffe et débarquement

Cette étape prolonge `WEAPON_CPP_PORT.md`. Elle reste dans le module indépendant,
avec du gameplay C++ Unreal et des assets de rendu Anniversary. Les cartes ne
sont pas réimportées. La copie de référence et les nouveaux rapports sont dans
`work/combat-actions`, distincts de la preuve de l'étape précédente.

## Comportements raccordés

- Les IA peuvent décider puis exécuter un lancer selon leur variante : type,
  stimulus (dont les pauses de rafale du Grunt), chance, délai de contrôle,
  distance, quantité de grenades, nombre
  d'ennemis requis et temporisation partagée par rencontre. Le mode passif et
  le rechargement gardent leur priorité.
- Le planificateur refuse une cible trop proche/lointaine, des alliés dans le
  rayon de dommage collatéral et un obstacle sur l'arc. Il réévalue la situation
  au lâcher ; un allié arrivé entre-temps annule le lancer sans consommer de grenade.
- Le joueur et les PNJ utilisent les clips de lancer récupérés. Dix-neuf correspondances de
  lâcher sont récupérées. Les clips joueur utilisent la keyframe du graphe
  cyborg, qui pilote le départ dans le code source ; leur keyframe FP à zéro
  ne constitue pas un événement de lâcher. Les autres clips ont une
  temporisation d'adaptation explicite. Le lancer bloque le tir et le rechargement.
- Le joueur utilise **G** pour lancer et **V** pour sélectionner frag/plasma.
  Le HUD affiche le type sélectionné. La grenade est attachée à la main gauche
  pendant le geste, puis masquée au lâcher ; le départ joueur utilise le décalage
  source et la direction de visée. Les deux stocks et la sélection sont sauvegardés ; les anciens checkpoints
  qui ne contiennent que des frags restent lisibles. Les pickups plasma fonctionnent.
- La frag rebondit et respecte armement/décompte source ; la plasma s'attache à
  une unité touchée et compte deux secondes, ou s'arme au repos. Les dégâts,
  rayons et coefficients de matériau viennent des tags. Le modèle plasma applique son unité source de 0,03048 m, sans mélanger
  ses LOD. Les explosions utilisent
  encore une présentation adaptée, pas le graphe VFX original complet.
- La surchauffe utilise les clips source d'entrée, maintien et sortie. Le tir
  reste verrouillé pendant le refroidissement puis la sortie. Une pression de
  détente pendant la surchauffe ne remplace plus l'animation par une charge.
- Les transports mémorisent l'ordre passif d'un passager à l'embarquement et
  le restaurent au débarquement. Un combattant ne reste plus artificiellement
  passif. Un personnage explicitement passif le reste. Une double réservation
  du même personnage ou un siège sans marqueur valide est refusé.

La cadence de tir ne rattrape plus un ralentissement par des tirs trop rapprochés.
Le contrôle mesure les instants réels d’émission, sans dépendre du frame où
le scénario de test observe le compteur.

Le bouclier du Jackal utilise maintenant un os présent dans le squelette
Anniversary (`Bip01_L_Forearm`) et une boîte ajustée sur sa géométrie skinnée.
L'ancien `frame_shield` était présent dans le graphe d'animation source, mais
absent du corps Anniversary : le collider pouvait rester à la racine du PNJ.
Le test vérifie l'ajustement, le blocage des balles et les dégâts plasma sur le
bouclier. Sa phase isolée utilise une trajectoire sans dispersion aléatoire.
La touche de sélection de grenade est V pour conserver Q au déplacement AZERTY.

## Référence et limites

La règle `actor_action_consider_grenade` est maintenant raccordée au monde.
Les conditions de cible, de délai de rencontre et d'orientation sont portées
depuis les fonctions récupérées. `RecoveredGrenadeRules.h` contient aussi le cas
balistique utilisé par le planificateur : arc bas, sans paramètres optionnels.
Le test compare ces règles aux corps C non modifiés avec des services simulés.

Ce sont des ports de règles et des adaptateurs explicites. La perception
utilisée est encore celle du module Unreal ; le graphe complet des props n'est
pas réimplémenté. Le contrôle de dégâts collatéraux adapte les acteurs visibles
et leurs rencontres, sans compter une deuxième fois la même unité. La gravité
vient du monde Unreal, commune au plan et au projectile. La difficulté est
actuellement le facteur neutre 1 ; les ordres de playfighting ne sont pas portés.

Les quantités de grenades sont finies et issues des variantes du cache. La
référence prototype contient un stub qui accorde des grenades illimitées aux IA :
ce stub n'est pas considéré comme une preuve du comportement commercial.
La physique précise de chaque matériau de rebond, les effets complets, les
esquives, les tactiques d'escouade et le pilotage de combat restent à porter.
La correction des transports concerne les ordres des passagers ; elle ne
remplace pas l'adaptateur cinématique actuel par la physique d'origine.

## Reproduction et preuves

```powershell
$env:PYTHONUTF8='1'
$taskPython='..\..\runtime\python\Scripts\python.exe'
& $taskPython scripts/recover_grenade_rules.py
& $taskPython scripts/update_fp_action_slots.py
& $taskPython scripts/test_grenade_rules.py
& $taskPython -m unreal_reconstruction prepare
& $taskPython -m unreal_reconstruction build --engine G:/UnrealEngine/UE_5.8
& $taskPython scripts/verify_combat_actions.py
```

L'import du modèle plasma passe par `stage_grenade_assets.py`, la conversion
Blender `convert_blender.py`, puis `import_grenade_assets_unreal.py` exécuté dans
Unreal. Il est isolé dans `/Game/Recovered/CombatActions`.

`verify_combat_actions.py` contrôle les nouvelles actions, puis les quatre suites
précédentes : arsenal, comportement IA, combat partagé et quinze familles de PNJ.
Il vérifie les sauvegardes, les entrées originales et les empreintes du contenu
préexistant, en autorisant uniquement trois nouvelles correspondances de clips
dans `weapon-parity.json`. Il produit `delivery-proof.json` et le manifeste du
projet testé. Ces tests bornés ne prouvent pas l'équivalence totale des dix campagnes.

Dernière preuve complète : **566 contrôles Unreal** réussis (49 nouvelles actions,
105 arsenal, 35 IA, 160 combat, 217 familles de PNJ), **56 tests Python** et
**91 355 comparaisons** contre quatre corps C de référence. Les dix cartes et
59 717 fichiers de contenu préexistants sont inchangés ; seuls trois raccords
de clips sont ajoutés dans les données d’armes. Les 23 entrées originales, le
XEX et les trois sauvegardes contrôlées sont préservés.
