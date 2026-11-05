# Navigation A30 — correction du 20 octobre 2026

Le NavMesh existait, mais son volume ne couvrait que le départ du niveau.
Ses dimensions complètes étaient de 600 × 600 × 160 mètres, centrées près
du point de départ. Sa limite sud était à Y = +1 533 cm, alors que le
premier combat avec les Marines se déroule vers Y = −10 000 à −16 654 cm.
Les IA recevaient les ordres de combat sans pouvoir demander un chemin.
Les précédents essais au débarquement initial n'exerçaient pas cette zone.

Les volumes sont désormais calculés à partir des positions originales des
rencontres, des départs joueur et des points des listes de commandes.
Les dimensions passées à `UCubeBuilder` sont les dimensions complètes.
Les décors lointains du ciel et de l'anneau ne participent pas au calcul.
La génération et la sauvegarde ont été effectuées dans les deux niveaux :

| Niveau | Positions source | Dimensions complètes, en mètres |
| --- | ---: | --- |
| A10 | 568 | 402,97 × 416,58 × 49,14 |
| A30 | 398 | 2 213,04 × 1 186,22 × 274,06 |

L'importateur applique aussi ce calcul aux prochaines générations du projet.
Les meshes, matériaux, UV et textures Anniversary n'ont pas été réimportés.

## Vérification dans le jeu

`validate-navigation` exécute la campagne normale d'A30, sans `CySmoke`.
Le test déplace uniquement le joueur vers les volumes de scénario, puis vers
la position du problème signalé : (−4 604,78 ; −13 228,10 ; 18 764,36) cm.
Les scripts source activent les six Marines et font débarquer les sept
ennemis de la première vague. Le test ne déplace aucun PNJ et ne force
ni leurs cibles ni l'activation des rencontres.

Les 14 contrôles passent : couverture des unités, projection sur le NavMesh,
chemins complets entre adversaires, demandes de déplacement, mouvement réel,
tirs et invincibilité du joueur. Pendant les 12 secondes d'observation,
les **13 unités se sont déplacées**. Leur distance maximale en XY par rapport
à leur position au début de l'observation est comprise entre 3,35 et 13,70 m
pour les ennemis, et entre 12,39 et 33,05 m pour les Marines. Il s'agit d'une
mesure de déplacement, pas de la longueur totale de leurs trajets.

Cette vérification couvre ce premier combat ; elle ne prouve pas que toutes
les rencontres ultérieures de la campagne sont jouables.

Les résultats sont conservés dans :

- `work/a10/navigation-fixed.json` : dimensions et confirmation de sauvegarde.
- `work/a10/missions/a30/navigation-validation.json` : assertions et déplacements.
- `work/a10/missions/a30/navigation-proof.json` : empreintes du projet et des preuves.
- `work/a10/HaloA10/Saved/Validation/Navigation/` : deux images de la zone testée.

## Reproduction

Depuis le dossier du module, avec le Python du dépôt :

```powershell
..\..\runtime\python\Scripts\python.exe -m unreal_reconstruction navigation --work work/a10 --engine G:/UnrealEngine/UE_5.8
..\..\runtime\python\Scripts\python.exe -m unreal_reconstruction validate-navigation --work work/a10 --map a30 --engine G:/UnrealEngine/UE_5.8
```

La première commande reconstruit et sauvegarde la navigation des deux cartes.
La seconde contrôle la campagne normale d'A30 et écrit ses checkpoints dans
le dossier de validation, en préservant les sauvegardes utilisateur.
Relancer `Play-HaloA30.cmd` pour charger le niveau corrigé.
