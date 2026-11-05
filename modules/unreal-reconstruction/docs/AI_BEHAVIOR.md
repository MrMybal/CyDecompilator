# IA de combat inspirée des règles récupérées

Cette étape utilise les tags `actr` et `actv` présents dans les caches de
**Halo Anniversary**, ainsi que certaines règles du code reconstruit du runtime.
Le moteur d'IA Blam n'est pas exécuté dans Unreal et l'équivalence complète avec
Halo n'est pas revendiquée.

Depuis le 21 octobre, l'architecture retenue est un portage des fonctions en
C++ Unreal, sans exécuter le runtime recompilé. Le suivi actuel et les essais
comparant les règles C++ au C récupéré sont dans
[WEAPON_CPP_PORT.md](WEAPON_CPP_PORT.md). Les paragraphes ci-dessous décrivent
la première étape ; l'inventaire détaillé distingue les règles portées des
services de perception, navigation et tactique encore adaptés.

## Données et décisions

`scripts/ai_data.py` récupère 16 variantes / 9 définitions dans A10 et
21 variantes / 13 définitions dans A30. Les 207 placements d'A10 et les
200 placements d'A30 sont associés à leur variante exacte, y compris les
exceptions choisies par les positions individuelles. Cette association est
enregistrée dans les niveaux existants par `bind_ai_unreal.py`.
Les modèles, UV, matériaux et meshes de la carte ne sont pas réimportés.

| Comportement | Données utilisées | Adaptation Unreal |
| --- | --- | --- |
| Vision | Distances et angles central, maximum, périphérique du tag acteur | Seuil extérieur interpolé selon `actor_get_vision_distances`, puis trace physique ; délai d'acquisition cumulatif |
| Bruit de tir | Distance d'audition | Un tir réellement exécuté transmet un stimulus ; sa position devient un point d'enquête, sans vision à travers les murs |
| Tir | Cadence de base, délai de première rafale, durée/séparation des rafales, portée, erreur angulaire, multiplicateur de dégâts de la variante | Ordonnanceur de rafales et dispersion sur l'arme à rayon existante |
| Alerte entre alliés | Règle récupérée de réaction aux tirs amis | Un allié qui combat transmet son dernier point observé aux IA à portée d'audition ; elles se tournent et vérifient leur propre visibilité avant de tirer |
| Position de combat | Plage de distance désirée et durée d'une position | Déplacement par navigation et positions latérales ; rapprochement ou recul selon la distance |
| Perte de cible | Durée de recherche | Poursuite du dernier point vu/entendu ; la position cachée de l'acteur ne met pas ce point à jour ; oubli après expiration |
| Repli | Seuils de bouclier et temps d'abri | Recherche de positions navigables masquées par une géométrie bloquante ; recul si aucun abri n'est trouvé ; reprise après récupération |
| Panique | Type du chef, chances après mort alliée, seuil de dégâts corporels et durée | Réaction à une mort alliée visible ou aux dégâts récents ; déplacement de fuite sans tir, puis retour au combat |
| Scénario | Ordres HSC déjà récupérés | Les unités passives, embarquées ou contrôlées par un ordre de déplacement gardent la priorité sur le combat |

Les nouvelles données sont dans `Content/Recovered/Data/a10-ai.json` et
`a30-ai.json`. Les diagnostics de campagne indiquent `ai_source_variant`,
`ai_source_profile`, `ai_state`, `ai_last_known`, rafales, recherches d'abri
et réactions de panique. Les personnages nommés sans variante de rencontre
conservent des paramètres de secours ; les pilotes/corps cinématiques restent
contrôlés par le scénario.

## Provenance et limites

Référence locale : `tools/cea-runtime-reference`, dépôt
[halocea](https://github.com/surreptitiousresearch/halocea), commit
`570c83fd9c365dad6f2a3e7041705d5b84c7847c`.

- `actor_get_vision_distances.c`, adresse `0x837D5598` : interpolation du
  seuil de vision extérieur selon l'angle. Le second seuil et tous les services
  d'attention/perception de Blam ne sont pas reproduits.
- `actor_action_handle_panic_from_damage.c`, adresse `0x837F1DA8` : comparaison
  des dégâts corporels récents au seuil de panique. La fenêtre d'accumulation
  d'une seconde de l'adaptateur est une approximation.
- `actor_stimulus_heard_shooting.c`, adresse `0x837D4C38` : une IA entend un
  ami combattre et dérive les informations de sa cible. La branche de
  désignation de cible par l’aide à la visée du joueur reste à porter.
- `actor_stimulus_prop_just_killed.c`, adresse `0x837D4E10` : distinction du type
  du chef et des chances de réaction aux morts alliées. Le graphe de connaissances,
  les émotions et leur propagation entre groupes restent simplifiés.

La sélection d'abri, la recherche et la navigation sont écrites pour Unreal.
Les modificateurs de difficulté, les motifs de visée spéciaux, les ordres de
groupe, les grenades, la mêlée tactique, les esquives et les comportements
de véhicules ne sont pas intégralement portés. Il n'y a pas encore d'animation
spécifique de panique ou d'accroupissement derrière l'abri : les clips récupérés
de course, attente et tir existants restent utilisés.

L'arsenal utilise maintenant des projectiles physiques avec traces de déplacement,
impact, guidage et dégâts ; certaines présentations d'effets restent génériques.
L'invincibilité du joueur reste activée par défaut et F10 la bascule.

## Reproduction des essais

Depuis le dossier du module :

```powershell
$python = '..\..\runtime\python\Scripts\python.exe'
& $python -m unreal_reconstruction recover-ai --map a10
& $python -m unreal_reconstruction recover-ai --map a30
& $python -m unreal_reconstruction prepare
& $python -m unreal_reconstruction build --engine G:/UnrealEngine/UE_5.8
& $python -m unreal_reconstruction bind-ai --engine G:/UnrealEngine/UE_5.8
& $python -m unreal_reconstruction validate-ai --map a30 --engine G:/UnrealEngine/UE_5.8
```

`-CyAICheck -CySmoke` exécute un scénario contrôlé : dos de l'IA, obstacle réel,
délai, rafales, perte de cible, oubli, bruit d'un vrai tir, mort d'un Élite,
panique temporaire, bouclier bas, récupération, priorité du scénario puis
déplacement vers un abri sur la navigation réelle d'A30. Les personnages du
scénario d'essai et son obstacle existent uniquement dans cette exécution,
sans ajout d'ennemis ou de géométrie aux cartes sauvegardées.

Résultats et empreintes : `work/a10/missions/a30/ai-validation.json` et
`ai-proof.json`. Le reçu inclut l'identité du projet pour refuser des résultats
associés à une ancienne DLL ou à des niveaux modifiés.

## Résultats de cette étape

- Compilation UE 5.8 réussie.
- 35/35 contrôles IA dans le moteur : 27 tirs répartis en dix rafales,
  quatre alertes alliées dans le scénario contrôlé, une réaction de panique,
  deux recherches d'abri ; repli mesuré de 4,09 mètres sur A30 avec occultation
  de la ligne de tir vérifiée.
- Gameplay : 35/35 contrôles sur chacune des cartes A10 et A30.
- Campagne/audio/checkpoint : 13/13 sur A10 et 15/15 sur A30.
- Audits des surfaces A10 et A30 réussis.
- Arrivée A30 : 28/28. Les sept passagers source ont tiré et se sont déplacés
  de 0,82 à 7,32 mètres en huit secondes après leur débarquement.
- Les quatre Grunts initialement tournés de dos reçoivent les alertes des alliés
  et rejoignent le combat ; aucune unité supplémentaire n'est ajoutée au niveau.
- 38 tests Python réussis.
- 21 643 fichiers de contenu préexistants hors niveaux conservés à l'octet près.

Le test d'arme isole les PNJ après vérification de leur import. Sans les scripts
normalement chargés, `CySmoke` activait auparavant les 317 personnages de toute
la mission A10 simultanément, provoquant une surcharge sans rapport avec le
combat local testé. Le test IA dédié et celui du débarquement vérifient les PNJ
séparément, avec leur navigation et leurs scripts.

Preuve consolidée : `work/ai-behavior/delivery-proof.json`.

La suite C++ du 21 octobre raccorde aussi le lancer de grenades (règles de
variante, trajectoire, dégâts collatéraux, animation et réévaluation au lâcher)
et restaure les ordres de combat au débarquement. Voir
[COMBAT_ACTIONS.md](COMBAT_ACTIONS.md) et sa preuve distincte.

La suite [AI_KNOWLEDGE.md](AI_KNOWLEDGE.md) remplace la cible unique par une mémoire
par adversaire, raccorde le calcul source de priorité et les commandes scalaires
des enregistrements de véhicules. La perception et le pilotage complets restent
des services à porter.
