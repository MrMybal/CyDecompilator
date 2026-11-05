---
id: installation
title: Installation et premier lancement
description: Installation et lancement
section: Bien démarrer
order: 1
sourceRevision: 1
---

## Conserver l’installation complète {#keep-the-complete-installation-together}

Sous Windows, lancez **CyDecompilator.exe**. Sous Linux, utilisez **CyDecompilator.sh** avec un environnement Python créé pour Linux. Le logiciel utilise un Python privé et des moteurs optionnels installés séparément. Une archive de sources ou de mise à jour ne contient pas nécessairement le runtime complet. Conservez les dossiers **runtime/** et **data/** lors d’une mise à jour de l’application.

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

Une erreur concernant **runtime/python/Scripts/pythonw.exe** signifie que le lanceur Windows ne trouve pas son interpréteur privé. Restaurez ou recréez cet environnement à l’emplacement de l’installation. Si une bibliothèque native ou un import Python échoue, consultez le **journal de l’application** et les dépendances du runtime correspondant, plutôt que d’installer des paquets dans un autre Python système. Consultez le [dépannage](doc:troubleshooting) et le [stockage](doc:storage) avant toute suppression.
