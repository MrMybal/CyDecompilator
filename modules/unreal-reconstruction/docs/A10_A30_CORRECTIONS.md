# Corrections A10 et ajout d'A30 — 20 octobre 2026

Cette révision traite les captures et la vidéo fournies : plans d'effets opaques,
personnages déformés ou couchés, animations mal appliquées et joueur incomplet.

## Animations

Les os et séquences récupérés sont conservés. L'import FBX supprimait le transform
racine nommé `Armature` pour certains personnages : les translations de leurs séquences
étaient cent fois plus petites que celles du modèle. Tous les exports utilisent désormais
une racine explicite, avec de nouveaux assets sous `/Game/Recovered/CharactersV2`.

Le placement utilisait aussi des arguments positionnels pour `unreal.Rotator`.
Dans cette installation, cela plaçait le lacet dans le tangage : les angles sont
désormais passés par nom. Le contrôle en jeu vérifie que les personnages restent debout.

Les clips de type overlay sont combinés avec l'animation d'attente originale avant
export. Ils ne sont plus joués comme des poses complètes isolées. Les translations
animées sont aussi conservées, notamment celles des bras et du fusil.

Le graph de première personne contient 42 os. Les cinq os manquants du fusil ont été
ajoutés depuis ses références sources. Les pièces du modèle Anniversary sont attachées
aux os de l'arme, du magasin, du levier, de l'affichage et de la sécurité. Le fusil suit
ainsi les séquences de tir, déplacement, rechargement et mêlée avec les bras.

Le modèle source de l'arme a son propre repère de référence. Il ne doit pas hériter
du décalage de référence du modèle des mains : ce décalage reculait le fusil derrière
la caméra. Le nouvel asset de première personne est sous `CharactersV2/cyborg_fp_v3`.

Les assets intermédiaires et le premier import restent disponibles. Les anciens assets
ne sont plus utilisés par les deux niveaux reconstruits.

## Matériaux et placement

Les rayons lumineux utilisent un mélange additif ; le verre et les décals identifiés
utilisent la transparence ; les feuillages identifiés utilisent une découpe alpha.
Ces règles sont explicites dans `scripts/material_policy.py` et restent des approximations
des shaders du jeu. Le canal alpha du terrain sert à d'autres données : il ne découpe
pas le sol. Les plans d'effets sont séparés des surfaces solides et exclus de la collision.
Les pins utilisent la découpe alpha pour leurs branches et une collision de tronc séparée,
afin que leurs grands plans de feuillage ne bloquent pas le joueur.

Les suffixes de doublons de matériaux ajoutés par FBX sont résolus : les 1 224 emplacements
des 316 meshes traités sur A10 ont une affectation. Les angles de tangage et de roulis
des objets sont importés en plus du lacet ; les échelles sources présentes sont appliquées.

## Joueur

Le joueur reprend les valeurs lues dans les tags : vitesses avant/arrière/latérales,
accélération, contrôle en l'air, saut, capsule et hauteurs de caméra debout/accroupi.
La cadence du fusil est de 15 tirs par seconde et son rechargement dure 3,4 secondes.
Le rechargement bloque le tir et transfère les munitions à son terme. Les animations
de déplacement, tir, rechargement et coup de crosse sont affectées au joueur.

La caméra est explicitement activée à la prise de possession du personnage par le
contrôleur du joueur. Le corps de troisième personne est alors masqué pour son propriétaire,
et les bras de première personne sont affichés. Cela évite de garder la configuration
d'un PNJ lorsque la possession arrive après `BeginPlay`.

Il s'agit toujours d'une implémentation Unreal reconstruite. Elle ne reproduit pas encore
tous les comportements, le HUD, la physique et les interactions du jeu de base.

## Deuxième carte

`Play-HaloA30.cmd` lance `/Game/Maps/A30` dans le même projet que `/Game/Maps/A10`.
Ses données intermédiaires sont sous `work/a10/missions/a30`.

Le terrain A30 importé comporte 1 173 036 sommets et 945 987 triangles, répartis en
1 756 morceaux. Les arbres, rochers et dispositifs pris en charge sont placés depuis
le scénario original. La carte comporte 646 objets et 200 PNJ placés. Les 51 Jackals
utilisent leur propre modèle et sept séquences converties, en plus des 40 séquences
des autres personnages et de la première personne. Leur bouclier d'énergie et ses
variantes d'effets ne sont pas encore reconstruits.

Le départ de test est projeté sur une surface navigable à proximité du point source,
à l'extérieur de la capsule prévue pour la cinématique initiale. Les positions avant
et après ajustement sont conservées dans le rapport d'import du niveau.

Les scripts de campagne, événements, objectifs et cinématiques
restent hors de cette conversion. La navigation de cet essai couvre la zone du départ ;
une traversée complète de la mission n'est pas validée.

## Vérifications

Les 11 tests unitaires passent. Un audit dans Unreal évalue les poses d'attente,
déplacement et tir des personnages à deux instants : il vérifie l'échelle et
la hauteur de la tête par rapport aux pieds. Les cinq actions de première personne
sont également évaluées avec leur squelette et les os du fusil.

La validation finale passe **21 contrôles sur A10 et 21 sur A30** : elle couvre notamment
la caméra active du joueur, les personnages debout, le déplacement par entrée clavier,
le sol, un trajet de navigation accessible, le tir, le rechargement temporisé, les dégâts
et l'évolution d'une pose. Les empreintes des deux projets de preuve correspondent aux
mêmes sources, DLL et assets finaux. Le combat est testé dans une situation bornée ;
ce résultat ne prouve pas une campagne complète ou une fidélité parfaite au jeu original.

Captures locales : `pose-idle.png`, `pose-run.png`, `pose-fire.png`, `fp-reload.png`,
`a10-start.png` et `a30-start.png`, dans `work/a10/HaloA10/Saved/Validation`.

Les résultats en jeu sont conservés séparément par carte dans
`work/a10/HaloA10/Saved/Validation`, avec les captures réelles. Les rapports et empreintes
sont dans `work/a10` pour A10 et `work/a10/missions/a30` pour A30.

Le contrôle de navigation recherche un trajet accessible autour du départ. Il ne suppose
pas qu'un point arbitraire à travers un rocher ou un bord de falaise soit accessible.
Les anciennes données Recast sont reconstruites avec un agent correspondant à la capsule
du joueur, et les deux cartes ont leurs propres résultats de test.

Les conventions des animations superposées et de la première frame de référence sont
également documentées dans les guides officiels [Halo 2 : animations de première personne](https://learn.microsoft.com/en-us/halo-master-chief-collection/h2/art/animation/animationsfpanims)
et [Halo 3 : animations de dispositifs](https://learn.microsoft.com/en-us/halo-master-chief-collection/h3/individual/devicemachines).
Le type des clips utilisés ici est lu dans les métadonnées Halo CE, sans déduire leur
type depuis leur seul nom.
