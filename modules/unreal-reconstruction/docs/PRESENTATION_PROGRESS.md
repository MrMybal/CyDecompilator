# Navigation du premier combat — correction du 20 octobre 2026

Le NavMesh précédent ne couvrait que le départ et excluait le premier combat
avec les Marines. Les deux niveaux ont maintenant un volume calculé à partir
des positions et routes source, avec une navigation reconstruite et sauvegardée.
Sur A30, un essai en campagne normale, dans la zone signalée, passe 14/14 contrôles :
les sept ennemis et les six Marines se déplacent réellement. Les déplacements
maximaux sur 12 secondes sont de 3,35 à 13,70 m pour les ennemis et de 12,39 à
33,05 m pour les Marines. L'invincibilité reste activée par défaut.

Preuve : `work/a10/missions/a30/navigation-proof.json`.
Cause, limites et reproduction : [NAVIGATION_FIX.md](NAVIGATION_FIX.md).

Après cette correction : compilation UE 5.8 réussie, 41 tests Python réussis,
35/35 contrôles de gameplay sur chaque carte, 35/35 contrôles IA sur A30,
campagne A10 13/13 et A30 15/15, audits des surfaces réussis et arrivée A30
28/28. Les checkpoints utilisateur d'avant test sont restaurés et leurs
empreintes vérifiées.
Les neuf reçus de validation correspondent aux mêmes 21 671 fichiers du
projet final. La vérification consolidée est réussie dans
`work/ai-behavior/delivery-proof.json` ; les 21 643 assets préexistants hors
niveaux et le `default.xex` original restent identiques.

## IA de combat — livraison précédente du 20 octobre 2026

Réactions fondées sur les paramètres `actr`/`actv` Anniversary : vision et délai,
rafales, recherche à la dernière position connue, alerte entre alliés, panique
après mort d’un chef et repli de l’Élite selon son bouclier.
Le joueur reste invincible par défaut ; F10 active/désactive ce mode.
La carte et ses assets Anniversary sont conservés.

- Compilation UE 5.8 réussie ; 38 tests Python réussis.
- IA : 35/35 contrôles dans le moteur, dont alerte derrière un mur sans tir
  à travers l’obstacle, engagement après retrait du mur et déplacement réel
  vers un abri sur A30 (4,09 mètres).
- Gameplay A10 et A30 : 35/35 par carte.
- Campagne/audio/checkpoints : A10 13/13, A30 15/15.
- Audits des surfaces des deux cartes réussis.
- Introduction et arrivée A30 : 28/28 ; sept passagers source débarqués.
  Les sept ont tiré et se sont déplacés de 0,82 à 7,32 mètres en huit secondes.
  Les quatre Grunts auparavant immobiles sont alertés par les alliés.
- Effets de tir vérifiés à l’image : 486 pixels clairs nouveaux au canon
  du joueur et 54 pixels cyan d’effet ennemi, réticule exclu.
- 21 643 fichiers de contenu préexistants hors niveaux identiques à la
  livraison précédente ; 407 placements associés à leur variante source.
- Huit reçus vérifiés sur les mêmes 21 670 fichiers du projet final.
- `default.xex` original inchangé.

Preuve : `work/ai-behavior/delivery-proof.json`.
Détails et reproduction : [AI_BEHAVIOR.md](AI_BEHAVIOR.md).
Relancer `Play-HaloA30.cmd` pour charger la DLL et les niveaux mis à jour.

L’IA reste une adaptation Unreal. Grenades, coordination tactique complète,
modificateurs de difficulté, animations de panique et combat de véhicules
ne sont pas intégralement portés. Les limites de campagne précédentes,
dont les objets cinématiques A10 encore manquants, restent présentes.


## 20 octobre 2026 — arsenal et présentation du combat

Les objets des scénarios A10/A30, l’inventaire à deux armes, les six armes,
les boucliers, les voix des unités et les animations directionnelles/morts
sont reliés à leurs données source. Les ragdolls utilisent un adaptateur de
pose pour les racines FBX à échelle 100 ; les modèles visibles suivent bien
les corps physiques. Le vol garde les commandes enregistrées, des attitudes
bornées et une garde au sol.

La livraison passe 159 contrôles de combat et 45 tests Python, ainsi que
les contrôles de gameplay, IA, campagne/audio, arrivée, navigation et
surfaces. Dix reçus portent sur les mêmes 21 931 fichiers du projet.
Les deux maps et leur géométrie sont conservées ; 251 assets sont ajoutés.
Les sauvegardes utilisateur sont restaurées et vérifiées.

Voir [COMBAT_PRESENTATION.md](COMBAT_PRESENTATION.md) pour les commandes,
les preuves, les raccourcis et les limites du portage. La physique de vol,
le comportement des IA et les particules restent des adaptations Unreal.
