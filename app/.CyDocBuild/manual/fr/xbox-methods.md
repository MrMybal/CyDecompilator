---
id: xbox-methods
title: Rendu, commandes et cadence Xbox
description: Diagnostiquer les commandes, le rendu, la cadence et la compatibilité d’un projet natif.
section: Parcours consoles
parent: xbox
order: 17
sourceRevision: 2
---

Consulter ce guide après préparation ou rattachement d’un [projet Xbox natif](doc:xbox).
Choisir l’exécutable exact et son reçu de compilation avant de modifier un profil. Le
nom du fichier ne suffit pas : les identités de l’exécutable et du module GPU sont
vérifiées par empreinte.

## Lancer la compilation enregistrée {#start-the-recorded-build}

1. Dans les **outils natifs Xbox**, sélectionner le SDK séparé et, si nécessaire, un
   module GPU natif existant. Ce module est facultatif ; ses capacités dépendent de
   la compilation choisie.
2. Créer ou rattacher le projet natif. Recompiler après modification des sources ou
   du module GPU.
3. Choisir le **plein écran au lancement** si souhaité, puis **lancer le jeu Xbox natif**.
   Les réglages enregistrés dans le jeu peuvent remplacer ce choix d’affichage.
4. Lire la sortie de la tâche en cours. Annuler cette tâche pour arrêter les processus du jeu.

Le rattachement réutilise le projet natif choisi, sans importer une seconde copie de
ses ressources. Conserver son dossier original et son SDK.

## Cadence et animation {#cadence-and-animation}

Fréquence de présentation, pas de simulation et interpolation des animations sont
distincts. Débloquer la présentation n’accélère pas automatiquement la mise à jour de
la physique, de l’IA ou des scripts. Lors du remplacement d’un sous-système, comparer
une scène représentative et les actions du joueur ; contrôler séparément les bras,
ennemis, véhicules et caméras. Un compteur d’images ne prouve ni la bonne vitesse de
simulation ni la compatibilité de tout le jeu.

## Clavier, souris et joueurs locaux {#keyboard-mouse-and-local-players}

Contrôler le focus clavier, la pause et les menus avant le jeu. Chaque déplacement de
souris doit être consommé une seule fois ; les anciennes valeurs doivent être effacées
après perte de focus ou pause. Les menus et le jeu peuvent emprunter des chemins
d’entrée différents dans le programme d’origine.

L’option de **coopération locale de campagne du profil Halo** réserve clavier et souris
au joueur 1 et la première manette au joueur 2 sur le profil pris en charge. Ce parcours
expérimental est propre à ce jeu. Il n’ajoute pas un écran partagé générique ni une
seconde campagne sauvegardée indépendamment à tous les jeux Xbox.

## Limites du rendu et du réseau {#rendering-and-network-limits}

Une image noire peut venir des copies de rendu, de l’exposition HDR ou des requêtes
d’occlusion ; changer uniquement le mode de rendu peut ne pas suffire. Comparer la
scène visible attendue : l’initialisation du GPU ne garantit pas un rendu correct.
Les solutions de repli d’occlusion peuvent créer des artefacts, par exemple des
lumières visibles à travers les murs.

Les travaux facultatifs de lancer de rayons ne reconstruisent pas un moteur complet
de matériaux et d’éclairage, ni un débruiteur temporel achevé. Leurs hypothèses de
capture limitent aussi les vues multiples. Un transport par IP directe ne crée pas
à lui seul une campagne synchronisée. Xbox Live n’est pas fourni et le multijoueur
compétitif est exclu de ce parcours.

Pour les paramètres, voir [`xbox_tools`](doc:op-xbox-tools),
[`xbox_build`](doc:op-xbox-build) et [`xbox_run`](doc:op-xbox-run).
