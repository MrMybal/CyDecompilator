---
id: installation
title: Installation et premier lancement
description: Conserver une installation complète et vérifier les prérequis de chaque tâche.
section: Bien démarrer
parent: start
order: 1
sourceRevision: 3
---

## Conserver l’installation complète {#keep-the-complete-installation-together}

Windows x64 propose deux paquets complets, comprenant Python et les bibliothèques nécessaires. Aucun Python système n’est requis.

- **Installateur :** exécutez le fichier EXE de configuration, choisissez sa langue et sa destination, puis lancez depuis le menu Démarrer. L’emplacement par défaut est accessible au compte courant sans droits administrateur. Le raccourci sur le bureau est optionnel.
- **ZIP portable :** extrayez toute l’archive dans un dossier accessible en écriture, puis lancez **CyDecompilator.exe**. Conservez **app/** et **runtime/** à côté de l’exécutable.
- **ZIP de mise à jour applicative :** cette petite archive s’adresse à une installation compatible existante ; conservez ses dossiers **runtime/** et **data/**. L’outil de mise à jour sélectionne cette archive plutôt que le paquet portable complet.

Linux x64 reste expérimental et utilise **CyDecompilator.sh** avec un runtime créé sous Linux. Les paquets Windows ne fonctionnent pas sous Linux. Les moteurs d’analyse et chaînes de compilation optionnels s’installent séparément depuis la page Moteurs.

| Dossier | Rôle |
|---|---|
| app/ | Code, traductions, manuel intégré et notices |
| runtime/python/ | Interpréteur privé et dépendances Python installées |
| runtime/engines/ | Moteurs d’analyse et chaînes d’outils optionnels |
| data/ | Projets, réglages, historique, tâches et rapports |

Ne déplacez pas un environnement virtuel Python en supposant qu’il fonctionnera encore : ses lanceurs peuvent contenir des chemins absolus. Pour une installation de développement neuve, créez-le à son emplacement définitif, puis installez les dépendances de l’application et le SDK CyToolsCore du propriétaire. La procédure développeur figure dans **app/README.md**. L’exécution Linux et chaque moteur ont leurs propres limites de validation ; les résultats Windows ne prouvent pas la compatibilité Linux.

## Vérifier les prérequis selon l’objectif {#check-prerequisites-by-task}

1. Ouvrez [Moteurs](doc:engines). Installez uniquement les outils nécessaires au format ciblé, ou sélectionnez un outil compatible déjà présent.
2. Pour compiler des sources natives, installez la chaîne C/C++ adaptée. Les projets PE Windows utilisent généralement la charge de travail C++ de Visual Studio et le SDK Windows.
3. Pour les projets managés, fournissez un SDK .NET compatible et les références du framework ciblé. Java nécessite l’installation appropriée ; JavaScript/Electron nécessite Node.js et les composants optionnels sélectionnés.
4. Git est nécessaire pour l’historique et les sauvegardes des corrections automatiques.
5. Configurez un [fournisseur IA](doc:ai) uniquement si vous souhaitez cette assistance. La décompilation manuelle n’en nécessite pas.

## Confirmer l’installation {#confirm-the-installation}

Ouvrez **Options**, choisissez une langue et un thème, puis appuyez sur F1. Le manuel doit s’ouvrir même sans projet. Commencez par une petite entrée connue avant une application volumineuse. Un moteur installé et une analyse réussie sont deux états distincts : examinez le résultat de la tâche si le composant existe mais ne produit aucune fonction.

## En cas d’échec au lancement {#when-launch-fails}

Une erreur de runtime manquant signifie que le lanceur ne trouve pas son interpréteur privé. Réextrayez le paquet portable complet ou réinstallez. Les paquets complets utilisent **runtime/python/pythonw.exe** ; les venv de développement existants utilisent **runtime/python/Scripts/pythonw.exe**. Si une bibliothèque native ou un import Python échoue, consultez le **journal de l’application** et les dépendances du runtime correspondant, plutôt que d’installer des paquets dans un autre Python système. Consultez le [dépannage](doc:troubleshooting) et le [stockage](doc:storage) avant toute suppression.


L’application portable conserve ses données dans **data/** à côté d’elle. La désinstallation d’une copie installée préserve les projets, réglages et moteurs créés après installation. Sauvegardez-les avant toute suppression manuelle du dossier restant.
