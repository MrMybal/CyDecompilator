# Campagne Anniversary dans Unreal 5.8

Les huit missions supplémentaires rejoignent A10/A30 dans le projet
`work/a10/HaloA10/HaloA10.uproject`. Les huit niveaux passent chacun 13 contrôles en jeu et 7 contrôles de démarrage avec les scripts actifs. Les audits de géométrie, de collision et de surfaces sont validés. Les régressions du joueur A10/A30 passent également. La preuve de l'assemblage initial reste dans `work/campaign-expansion/delivery-proof.json`. L'état du projet après l'ajout des PNJ est lié à ses nouvelles empreintes dans `work/npc-expansion/delivery-proof.json`.

| Map | Mission |
| --- | --- |
| A50 | The Truth and Reconciliation |
| B30 | The Silent Cartographer |
| B40 | Assault on the Control Room |
| C10 | 343 Guilty Spark |
| C20 | The Library |
| C40 | Two Betrayals |
| D20 | Keyes |
| D40 | The Maw |

Lancer `Play-HaloCampaign.cmd` pour choisir une mission, ou son lanceur
`Play-Halo<MAP>.cmd`. L'invincibilité reste activée ; F10 permet de la basculer.
Le menu accepte aussi `-Map C20 -Editor` pour ouvrir un niveau dans l'éditeur.

## Import

Chaque nouvelle mission dispose de ses meshes, matériaux et textures dans
`/Game/Recovered/Missions/<MAP>`. Les Blueprints du joueur et les ressources
de combat validées sur A10/A30 restent partagés.

La table ANIS des scènes Anniversary fournit les modèles de décor et leurs
matrices de placement, y compris les substitutions de modèles dont le nom
diffère du nom Classic. Les huit canaux UV, les couleurs de sommets, les
normales et les partitions de collision sont conservés dans les conversions.
Les surfaces transparentes et les cartes d'effets suivent les règles déjà
utilisées par A10/A30. Les objets prévus pour une création par les scripts
commencent cachés, avec leur collision désactivée.

Les lumières, paramètres d'ambiance, brouillards et panoramas de ciel viennent
des scènes Anniversary. Les sons des dix missions sont référencés dans les
manifestes audio ; les dialogues français sont prioritaires. Les deux modèles
de porte endommagée de D40 ont nécessité une correction de la lecture des
indices d'objets sur les templates sans squelette.

Les positions de départ utilisées pour les essais sont projetées sur le
navmesh avec un contrôle de capsule. Quand un départ de cinématique est
impraticable, le rapport conserve la position source choisie à proximité.

## Portée

Cette étape porte les niveaux et réutilise le prototype de gameplay existant.
Les cinématiques des nouvelles missions restent désactivées. La machine de
scripts adapte les fonctions déjà prises en charge ; une campagne terminable
de bout en bout n'est pas encore validée. Les transports, ascenseurs et autres
comportements propres à chaque mission peuvent demander des adaptations.

L'import complémentaire des Hunters, Flood, Sentinels, Monitor et personnages
particuliers est décrit dans [NPC_EXPANSION.md](NPC_EXPANSION.md). Les anciens
rapports d'import de décor conservent leur inventaire historique des omissions ;
le nouvel audit des dix niveaux sauvegardés fournit la couverture actuelle des
personnages. L'arsenal jouable reste celui des six armes de première personne ;
les armes supplémentaires de cette étape sont réservées aux PNJ.

Les shaders, l'eau, les particules et la réponse de l'éclairage restent des
approximations du rendu Saber. Les rapports distinguent les palettes inutilisées,
les objets réellement omis et les templates sans géométrie exploitable.

## Reproduction depuis la base A10/A30

Depuis le dossier du module, avec le Python du dépôt et l'UE 5.8 installé :

```powershell
$taskPython = '..\..\runtime\python\Scripts\python.exe'
& $taskPython -m unreal_reconstruction tools
& $taskPython scripts/recover_campaign_maps.py
& $taskPython scripts/convert_campaign_maps.py
& $taskPython scripts/recover_campaign_sky.py
& $taskPython scripts/extract_audio.py '..\xbox-native\work\halo-rex\game' 'work/a10'
& $taskPython -m unreal_reconstruction audio --engine 'G:\UnrealEngine\UE_5.8'
& $taskPython scripts/port_campaign_maps.py
& $taskPython scripts/finish_campaign_maps.py
```

Les étapes conservent leurs journaux et reçus dans chaque dossier de mission.
Les tests archivent leurs checkpoints temporaires et restaurent les sauvegardes
présentes avant leur exécution.


## Résultats finaux

| Map | Mission | Chunks | Triangles UE | Contrôles map + démarrage |
| --- | --- | ---: | ---: | --- |
| A50 | The Truth and Reconciliation | 2609 | 1,406,061 | 13/13 + 7/7 |
| B30 | The Silent Cartographer | 261 | 1,110,259 | 13/13 + 7/7 |
| B40 | Assault on the Control Room | 615 | 1,606,784 | 13/13 + 7/7 |
| C10 | 343 Guilty Spark | 129 | 1,301,266 | 13/13 + 7/7 |
| C20 | The Library | 110 | 1,111,184 | 13/13 + 7/7 |
| C40 | Two Betrayals | 615 | 1,607,491 | 13/13 + 7/7 |
| D20 | Keyes | 1132 | 1,317,578 | 13/13 + 7/7 |
| D40 | The Maw | 7469 | 1,679,716 | 13/13 + 7/7 |

Les ressources Content présentes avant cette étape sont conservées octet pour octet. Les deux sauvegardes de campagne préexistantes et le fichier original `default.xex` ont gardé leurs empreintes. Les captures finales se trouvent dans `work/a10/HaloA10/Saved/Validation/Maps/<map>`.
