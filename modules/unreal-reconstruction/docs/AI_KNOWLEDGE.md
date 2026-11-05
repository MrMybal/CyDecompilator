# Priorités des cibles et commandes de véhicules

Suite de [COMBAT_ACTIONS.md](COMBAT_ACTIONS.md), dans le module C++ Unreal
indépendant. Les modèles restent Anniversary. Cette étape ajoute deux fichiers
de données ; aucun niveau ni asset existant n'est réimporté.

## IA

`RecoveredTargetRules.h` porte le calcul de poids de
`actor_compute_prop_target_weight @837D6DC8` : bandes de distance, menace,
adversaire qui inflige des dégâts, tir et orientation observés, priorité initiale
du joueur et continuité d'une cible déjà suivie. Le prédicat d'acceptation de
`actor_situation_try_new_target @837D7B38` est aussi repris. Les services de mise
à jour du statut de cette seconde fonction restent des adaptations Unreal.

`RecoveredKnowledge.cpp` remplace la sélection du seul ennemi visible le plus
proche. Chaque adversaire dispose d'un délai de reconnaissance, d'une position
observée, d'une expiration et d'indices de danger propres. Un mur arrête
l'actualisation de sa position ; son déplacement caché ne met pas ce souvenir à
jour. Le choix tient compte des autres adversaires connus. Une cible morte ou
expirée est retirée ; une autre peut prendre sa place. Les ordres passifs et les
délais de première rafale gardent leur priorité. Un ordre de repli déjà engagé
se poursuit jusqu’au temps de protection et à la récupération du bouclier,
même si le dernier souvenir de cible expire entre-temps.

L'absence de connaissance sous-marine, de l'ensemble des états de visibilité et
du graphe original des props reste explicite. La mémoire, sa durée, les traces
de visibilité, les indices récents (une seconde), l'exclusion des morts et
l'estimation de position lors d'un dégât sont des services Unreal. Le code
préserve les branches inhabituelles du prototype dans la fonction de poids,
sans prétendre qu'elles décrivent exactement le retail.

Les portées minimales de ciblage proviennent des 14 définitions d'armes. Les
profils de mêlée et de portée proviennent des variantes déjà récupérées.

## Véhicules

`RecoveredVehicleRules.h` porte intégralement les deux règles scalaires
`physics_variable_speed_update @838106C8` et
`physics_variable_speed_update_seek @838107C8`. Les enregistrements à 30 Hz
utilisent désormais les accélérations, décélérations et limites avant/arrière
et latérales des tags de 23 véhicules. Le relevé vérifie aussi que chaque
occurrence de ces définitions dans les dix caches possède les mêmes commandes
avant de mutualiser les données. Le frein vise une vitesse nulle. Le
changement de sens applique la décélération avant l'accélération opposée.
La conversion de l'axe latéral Halo vers Unreal est appliquée une seule fois.

Cela améliore les commandes des trajectoires enregistrées. Le châssis, la
suspension, les forces aérodynamiques, les collisions de conduite et le pilotage
autonome de combat restent à porter. Le suivi des enregistrements reste une
adaptation cinématique avec correction des points d'arrivée et garde au sol.

## Présentation des armes

La fin du refroidissement ne doit plus remplacer l'animation d'un lancer de
grenade en cours. Le refroidissement continue ; les transitions visuelles de
surchauffe attendent la fin du lancer, puis reprennent. Le clip de lancer
surchauffé et son événement de lâcher sont conservés. Cette correction ne
constitue pas un portage de toute la pile originale des priorités d'animation.

Les graphes VFX exacts, les présentations d'armes encore absentes et les autres
services d'IA restent les limites décrites dans les étapes précédentes.

## Démarrage de campagne et bouclier Jackal

Le test complet A30 a révélé un plantage de `GetCPUSkinnedVertices` : un
Jackal masqué par les scripts pouvait demander un skinning CPU alors que son
objet de rendu était absent. Le calcul de la boîte de collision attend désormais
que l’unité et son maillage soient actifs et prêts au rendu. La collision reste
désactivée tant que cet ajustement n’a pas réussi. Les tirs physiques contre le
bouclier et l’arrivée de la campagne font partie des régressions.

## Reproduction et preuves

Depuis le dossier du module, avec son Python privé et `PYTHONUTF8=1` :

```text
python scripts/recover_control_metadata.py
python scripts/test_target_rules.py
python scripts/test_vehicle_rules.py
python -m unreal_reconstruction prepare
python -m unreal_reconstruction build --engine G:/UnrealEngine/UE_5.8
python scripts/verify_ai_knowledge.py --resume
```

Les deux oracles comparent 400 000 cas aux corps C récupérés non modifiés, avec
des services de test explicites. La référence est une reconstruction du
prototype de juin 2011, pas un source retail complet certifié.

Le test natif `-CyKnowledgeCheck` vérifie plusieurs adversaires, les dégâts
réels, l'occlusion, l'expiration, le remplacement d'une cible morte, les
commandes du Pelican et le conflit grenade/refroidissement. Le vérificateur
relance aussi les suites grenades, armes, IA, combat, espèces et arrivée A30.
Il refuse une modification du contenu préexistant ou des sauvegardes et lie
les rapports à la DLL, aux sources et aux données testées.

La preuve de cette étape est `work/ai-knowledge/delivery-proof.json` ; son
inventaire précis est `tested-project.json`. Les preuves précédentes restent
historiques. `ai-port-coverage.json` distingue règles portées, fragments et
services restants ; ses nombres ne mesurent pas un pourcentage d'IA complète.

Validation finale : **624 contrôles Unreal**, **56 tests Python** et **400 000
comparaisons source** réussis. Les **59 724 fichiers de contenu préexistants**,
les **23 entrées originales** et les **trois sauvegardes** sont préservés.
