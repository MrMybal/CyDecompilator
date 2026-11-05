# Présentation du combat et arsenal récupéré

Étape du 20 octobre 2026. Travail limité au module indépendant
`modules/unreal-reconstruction`. Les rendus restent Anniversary. Les cartes,
UV et feuillages approuvés sont conservés. Sauvegarde préalable :
`work/a10/backups/20261020-combat-presentation`.

## Données récupérées

- Quatre espèces : Marine, Elite, Grunt et Jackal. Les séquences source
  directionnelles alimentent de vrais Blend Spaces direction/vitesse ; les
  tirs se superposent au haut du corps. La vitesse vient du déplacement
  racine source, tandis qu’Unreal déplace la capsule sur la navigation.
- Les noms complets `h-kill front gut`, etc. remplacent l’ancien filtre de
  mort incomplet. Animations de mort suivies de corps physiques.
- Dialogues français issus des variantes `udlg`, déclenchés par l’alerte,
  le tir, les blessures, la mort, la retraite et la mort d’un allié.
- Six armes : fusil d’assaut, pistolet, fusil à plasma, pistolet à plasma,
  Needler et sniper. Maillages, poses à la première personne, cadence,
  vitesse des projectiles, gravité, portée, dégâts et sons viennent des
  données récupérées. L’arme à la troisième personne suit son marqueur
  source. Les armes sans os gardent leur échelle de template.
- Placements source : 61 objets A10 et 80 A30, avec drapeaux de placement,
  noms de scénario, chargeur et réserve. Inventaire de deux armes avec
  ramassage, échange, abandon et sauvegarde des munitions.
- Santé, munitions, grenades et surbouclier ramassables. Absorption puis
  débordement des dégâts, recharge du bouclier et effet sur le corps et
  les bras du joueur. Le bouclier du Jackal est séparé du corps ; il bloque
  les balles et peut être épuisé par le plasma.
- Projectiles balayés entre deux positions pour éviter de traverser les
  objets à haute vitesse. Needles visibles, guidage, attachement, détonation
  différée et supercombinaison. Impacts plasma bleus/verts et Needler roses
  avec textures Saber récupérées, sons et lumières temporaires.

## Reproduction

Les marqueurs de tir des modèles source sont calibrés sur les poses importées.
Les flashes de la vue subjective ont leur propre matériau ; les projectiles
et impacts dans le monde conservent leur test de profondeur. Chaque flash est
contrôlé par comparaison des pixels avec et sans effet dans sa zone projetée,
à pose identique. Le test suspend la pose et maintient brièvement le flash
pour laisser les captures se terminer ; la partie normale conserve une
impulsion de 85 ms.

Le projet doit déjà contenir les extractions A10/A30, l’audio et les imports
Anniversary des étapes précédentes. Depuis le dossier du module :

```powershell
$py = '..\..\runtime\python\Scripts\python.exe'
$ue = 'G:/UnrealEngine/UE_5.8'
$images = '%USERPROFILE%/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
& $py -m unreal_reconstruction recover-combat
& $py -m unreal_reconstruction convert-combat
& $py -m unreal_reconstruction prepare
& $py -m unreal_reconstruction build --engine $ue
& $py -m unreal_reconstruction combat-assets --engine $ue
& $py -m unreal_reconstruction validate-combat --map a30 --engine $ue --image-python $images
```

`validate-combat` produit les assertions natives, les captures et un WAV
de voix sous `HaloA10/Saved/Validation/Combat`. La preuve associe ces fichiers
aux empreintes du code, de la DLL et des assets. Une exécution incomplète ne
peut pas réutiliser les captures de la précédente.

## Limites du portage

Le comportement des IA adapte les paramètres et ordres du scénario à Unreal ;
il ne réexécute pas tout le moteur Blam. Les vaisseaux rejouent les commandes
source à 30 Hz avec interpolation, attitudes bornées et garde au sol ;
l’ajustement des points d’arrivée reste une adaptation cinématique.

Les systèmes de particules Saber ne sont pas exécutés directement : textures,
couleurs et données de tir récupérées sont rendues par des effets Unreal
reconstruits. Le surbouclier utilise un support procédural, faute de modèle
Anniversary trouvé. Le tir chargé du pistolet plasma, la consommation
fractionnaire exacte des batteries, les réponses physiques détaillées de
tous les matériaux et les HUD spécifiques à chaque arme restent incomplets.
L’interface affiche le nom, le chargeur, la réserve et la chaleur réels.


## Résultats vérifiés sur la livraison

- 159/159 contrôles natifs de combat : quatre espèces, dix échantillons par
  Blend Space, déplacement réel et mouvement des pieds dans les quatre
  directions, armes, dialogues, morts, physique, inventaire et boucliers.
- 45 tests Python réussis, dont la restauration d’un checkpoint après échec
  d’un test et la préservation d’une sauvegarde initialement absente.
- Gameplay A10/A30 : 35/35 par carte ; comportement IA : 35/35.
- Campagne et audio : A10 13/13, A30 15/15. Navigation du premier combat
  A30 en partie normale : 14/14, treize personnages réellement déplacés.
- Introduction et dropship : 28/28 ; sept passagers source débarqués,
  tous déplacés de plus d’un mètre dans la fenêtre de huit secondes.
- Flashes : les six armes passent la comparaison à pose identique. Le test
  d’arrivée confirme également 486 nouveaux pixels blancs au canon du
  joueur et 30 pixels cyan d’effet ennemi, réticule exclu. Ce dernier test
  utilise un pas de simulation fixe de 1/60 s pour les flashes de 85 ms.
- Audits des surfaces des deux cartes réussis. Les deux niveaux et tous les
  assets de géométrie d’environnement préexistants ont les mêmes empreintes.
  251 assets de contenu sont ajoutés. 22 matériaux/textures partagés sont
  réenregistrés pour les personnages, armes, objets et effets ; la liste
  exacte figure dans la preuve de livraison.
- Dix reçus concordants sur les 21 931 fichiers de la même version Unreal.
  Les sauvegardes utilisateur initiales et le `default.xex` sont inchangés.

Preuve complète : `work/combat-presentation/delivery-proof.json`.
Captures, WAV et vidéo : `work/a10/HaloA10/Saved/Validation/Combat/`.
Les tests de navigation et d’arrivée préservent maintenant leurs checkpoints
antérieurs et archivent ceux de l’essai, afin de ne pas remplacer une
sauvegarde utilisateur ou la preuve d’un autre test.
