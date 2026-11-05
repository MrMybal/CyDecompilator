# A30 — ennemis, HUD et arrivée Anniversary

> Mise à jour suivante : [combat, VFX et invincibilité](COMBAT_TEST_FIXES.md).
> Les nombres de contrôles de ce document décrivent l’étape d’arrivée initiale.


Projet : `work/a10/HaloA10/HaloA10.uproject`, UE 5.8.3. La géométrie et les
shaders de la carte approuvée sont conservés. Les entrées du jeu sont lues,
jamais modifiées. Sauvegarde des sources avant intervention :
`work/a10/backups/20261020-160713-arrival`.

## Corrections

- Les références HSC à un peloton sont résolues vers ses escouades. Par exemple,
  `lz_search/cship_toon` contient sept personnages en difficulté normale.
  Les escouades gardent leurs emplacements et quantités issus du scénario.
- Les passagers sont attachés aux marqueurs des sièges du vaisseau. Cachés et
  sans collision pendant le transport, ils ne peuvent ni viser ni tirer. Le
  débarquement réactive leurs meshes, remet leur capsule à la verticale et
  utilise le sol de la carte. Aucun renfort supplémentaire n'est ajouté pour
  remplir le niveau.
- Le pilote utilise son modèle Anniversary et un retarget de 19 articulations.
  Ses animations `idle`, `heads_up`, `death_pose` et les deux poses de mort
  assises des Marines proviennent des graphes cinématiques embarqués. Les
  personnages attachés restent embarqués : le contrôleur de combat ne remplace
  plus leur pose assise par une animation debout à la fin du clip. Le repère
  des marqueurs des lifepods est recalé sur `frame_lifepod` du modèle
  Anniversary ; la translation de repos du modèle classique ne doit pas
  décaler le pilote et la caméra au-dessus de la coque.
- Le HUD utilise les textures `hce_uhb*` de `pak_stream.s3dpak` : bouclier,
  santé, munitions, réticule et radar. Les valeurs réagissent à l'état réel du
  joueur ; le réticule change de couleur sur un adversaire. Le canal alpha des
  textures de jauge encode un seuil, pas la transparence ordinaire.
- La bouche du canon est retrouvée sur les sommets du fusil réellement skinnés
  par Unreal, puis suivie dans le repère de son os animé.
  Son matériau et l'éclat complémentaire utilisent des pixels Anniversary,
  avec une lumière courte et aucune collision.
- Les commandes de caméra, interpolation, fondu, letterbox, verrouillage puis
  restitution des commandes sont exécutées pour l'introduction. Entrée permet
  de passer l'introduction. Les objets d'introduction sont alors nettoyés.
- Les 63 enregistrements A30 sont décodés à 30 Hz, jusqu'à leur terminateur,
  avec les durées d'origine. Les véhicules nommés des scripts sont importés ;
  l'arrivée, le chargement, le débarquement et le départ du dropship de la
  première vallée passent par le script `mission_lz_dropship` récupéré.
- Les journaux d'une partie normale sont séparés des preuves de validation.

## Limites concrètes

Les enregistrements contiennent des **commandes de vol**, pas des positions.
Leur lecture dans Unreal utilise un adaptateur cinématique, pas la physique
rigide Blam. Les deux mouvements du lifepod sont contraints aux points de
passage/crash du scénario pour éviter une trajectoire sous la carte. La
séquence garde ses durées et ses commandes d'origine ; la trajectoire n'est
pas une reproduction physique exacte.

Les airbrakes passent à un état sans les surfaces détachées, au moment prévu
par le script. Les débris animés, les portes mobiles des transports, la
convolution d'écran d'origine, les animations faciales et l'habillage complet
des titres cinématiques restent à adapter. Les Banshees et le Pelican ont
leurs modèles et leurs enregistrements disponibles, mais leur combat aérien,
le Warthog et toutes les missions suivantes ne sont pas validés ici.
Les cinématiques A10 ne sont pas couvertes par cette correction : leurs
objets de cinématique non reconstruits restent consignés dans le rapport
de campagne A10.
Les ennemis utilisent toujours le contrôleur de combat et la navigation du
prototype ; cette intervention ne démontre pas une équivalence complète des IA.

## Validation de cette étape

- 38 tests Python, dont le codec d'enregistrements et le changement de repère
  des marqueurs du lifepod.
- 23 contrôles Unreal pour l'introduction et le premier dropship : clips du
  pilote maintenus, bassin à moins de 8 cm du marqueur du siège, commandes
  rendues au joueur, HUD chargé, tir et flash rendu, absence de vague ajoutée,
  sept passagers, huit demandes de débarquement d'origine et départ terminé.
- Sept captures réelles. Le test de pixels compare le canon au repos et en
  rafale, en plus de contrôler la visibilité des composants et leur collision.

Les preuves de cette étape sont `work/a10/missions/a30/arrival-proof.json`,
`arrival-validation.json` et `arrival-pixels.json`. Les régressions de gameplay,
de campagne/audio et de surfaces des deux cartes ont leurs reçus séparés.
Les rapports `conversion-report.json` signalent explicitement une preuve
absente ou devenue périmée après une modification du projet.

## Reproduction

Un Python muni de Pillow est nécessaire pour les sprites HUD (extra `assets`
du paquet, ou `--image-python` pointant vers un environnement existant).
Fermer l'éditeur de ce projet avant les imports et la reconstruction du module.

```powershell
python -m unreal_reconstruction recover-arrival --map a30 --image-python <python-avec-Pillow>
python -m unreal_reconstruction convert-arrival --map a30
python -m unreal_reconstruction prepare
python -m unreal_reconstruction build --engine G:/UnrealEngine/UE_5.8
python -m unreal_reconstruction arrival --map a30 --engine G:/UnrealEngine/UE_5.8
python -m unreal_reconstruction level --map a30 --engine G:/UnrealEngine/UE_5.8
python -m unreal_reconstruction validate-arrival --map a30 --engine G:/UnrealEngine/UE_5.8 --image-python <python-avec-Pillow>
```

`validate-arrival` exécute l'introduction complète, puis réveille explicitement
le script original du premier dropship pour tester cette séquence sans
attendre le déplacement d'un joueur. En partie normale, les volumes et
conversations du scénario conservent le contrôle de son déclenchement. Il vérifie les personnages transportés, leur visibilité au
débarquement, le départ, le HUD, les commandes et les pixels du flash. Les
captures sont dans `Saved/Validation/Arrival`. Les reçus comportent les
empreintes du projet final et des captures ; aucun test ne valide la campagne
entière.

Le codec est fondé sur les fonctions récupérées du moteur CEA publiées dans
[halocea](https://github.com/surreptitiousresearch/halocea/tree/570c83fd9c365dad6f2a3e7041705d5b84c7847c/src/blam/cutscene),
notamment `recorded_animation_initialize_unit_control`,
`recorded_animation_apply_event_stream` et les handlers de différences de
direction. Aucun binaire de ce dépôt n'est exécuté.
