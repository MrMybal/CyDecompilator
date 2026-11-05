# Corrections Anniversary — 20 octobre 2026

Les cartes, personnages, objets et textures affichés proviennent des archives Saber
de Halo Combat Evolved Anniversary Xbox 360. Aucun modèle ni texture de l'affichage
Classic n'est utilisé. Les positions, paramètres et graphes d'animation du moteur de
jeu sont lus dans les données runtime livrées avec Anniversary.

Les défauts signalés avaient plusieurs causes distinctes :

- La déclaration de sommets de 12 octets était ambiguë. Un sapin à un canal UV et
  une surface à deux canaux UV ne placent pas leurs coordonnées au même endroit.
  La lecture suit désormais la déclaration interleaved de **46 bits** : présence
  et compression de chaque tangent, couleur et UV. Le stride est contrôlé en fin
  de décodage. Les couleurs sont des octets RGBA, sans permutation ARGB.
- Les facteurs de répétition du bloc Saber **0x2F01** n'étaient pas appliqués.
  Chaque canal reçoit maintenant son facteur source, y compris les sapins et le
  terrain. Aucun recalage d'atlas spécifique aux sapins n'est ajouté. Les chaînes
  d'édition `__export_uv_compr_params` ne sont pas appliquées une seconde fois.
  Le contrôle `audit-foliage` compare les **18 912 coins UV** des aiguilles du FBX
  aux données binaires Anniversary et vérifie leur alpha ainsi que leur UCX.
- Le grand sapin contient quatre variantes sous `base00` à `base03`. Les 70
  placements A30 demandent la permutation 0 : seule `base00` est importée. Les LOD
  inférieurs sont exclus séparément. Les quatre variantes ne sont plus superposées.
- Le décor conserve jusqu'à quatre canaux UV et les poids de mélange des couches.
  Les objets conservent aussi ces poids, au lieu des couleurs blanches par défaut.
  Les poids sont exportés en valeurs linéaires. Les connexions des entrées
  UV des matériaux Unreal sont contrôlées ; un échec interrompt l'import.
- Les petites textures BC Xbox conservent un pas physique minimal de 32 blocs
  par ligne. `sc_grey_70` contient 16 blocs utiles puis 16 blocs de padding :
  l'ancien décodeur produisait une ligne noire sur deux, puis des bandes sur les
  rochers. Le padding est maintenant retiré avant écriture PNG. Le contrôle
  vérifie les 4 096 pixels de cette texture grise. L'import Unreal compare aussi
  l'empreinte du PNG, afin de réimporter une texture corrigée déjà présente.
- Les feuilles utilisent leur découpe alpha. Leurs mipmaps conservent la couverture
  de l'alpha pour limiter la disparition des aiguilles à distance. Les plans de
  végétation lointaine et les nuages reçoivent aussi leur transparence.
- Les collisions sont séparées par section et par indicateurs source `cdt_off_*`.
  Un effet partageant un mesh avec un mur ne reçoit plus les triangles de collision
  du mur. Les sapins disposent d'une collision distincte construite sur leur tronc.
- Les os Bip01 Classic/runtime et Anniversary partagent leurs axes locaux, mais
  leurs poses de repos diffèrent. La flexion de repos des bras n'est plus ajoutée
  une deuxième fois. L'audit Unreal compare les directions des membres aux clés
  sources. Une erreur de troisième indice de skinning dans Reclaimer est corrigée.
- Le fusil utilise un affichage de munitions dynamique issu de sa planche de
  chiffres Anniversary. Les tirs déclenchent la séquence récupérée et un flash
  récupéré, avec une cadence de 15 coups par seconde. Les armes attachées aux os
  compensent l'échelle du squelette. Entrée permet de réapparaître au départ du
  niveau ; la caméra ne montre plus l'intérieur du corps du joueur mort.
- La capture de tir attend 150 ms après le tir effectif : une capture demandée
  dans la même frame pouvait montrer les munitions avant la mise à jour des
  paramètres côté rendu. La capture vérifiée montre désormais 59 sur le fusil
  et dans le HUD après un tir à partir de 60.

Les imports actuels utilisent `EnvironmentV3` et `PropsV3`. Les anciens assets sont
conservés. Une sauvegarde des sources, configurations, cartes et Blueprints précédents
se trouve dans `work/a10/backups/20261020-023535`.

Le shader Saber complet, les éclairages d'origine, les effets d'impact, l'audio,
les scripts de campagne, l'activation des vagues et les cinématiques restent à
reconstituer. Le tir utilise encore un rayon Unreal. Les collisions et l'IA sont
celles du prototype. Ces corrections ne prouvent pas une reproduction complète
du gameplay ou du rendu original.

Les rapports effectifs sont `work/a10/unreal-import-audit.json`,
`work/a10/missions/a30/foliage-audit.json` et les fichiers de validation dans
`work/a10/HaloA10/Saved/Validation`. La validation de chaque carte possède une
preuve liée aux empreintes des fichiers du projet ; consulter `runtime-proof.json`
et `conversion-report.json` pour son état courant.

Références de format consultées (lecture seule, sans dépendance de compilation) :

- [LibSaber, révision 1311ab2](https://github.com/Wildenhaus/LibSaber/tree/1311ab287add95771fefd51001836dcfd958ba1c),
  `InterleavedData.cs`, `InterleavedDataFlags.cs` et `UvScalingMap.cs`.
- [IndexV2, révision 28a0ce0](https://github.com/Wildenhaus/IndexV2/tree/28a0ce0f857b650ae5ad9f15cd1052a36b7cbe01),
  profil HaloCEA, `Meshes/MeshBuilder.cs` : facteur UV du mesh hôte pour les
  objets partagés, du compound pour les meshes de skin partagés.
