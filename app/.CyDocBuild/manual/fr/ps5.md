---
id: ps5
title: Préparation PS5 et conversion pour ordinateur
description: Préparer des entrées lisibles, configurer AnyPS5/UltraPack et tester la sortie convertie.
section: Consoles et Unreal
parent: consoles
order: 15
sourceRevision: 2
---

Ouvrez [Portage PS5](doc:ps5). CyDecompilator gère entrées préservées, analyse, tâches de conversion, reçus et scénarios. **AnyPS5**, optionnel, fournit conversion d’exécutable et compatibilité API/GPU console ; **UltraPack** fournit l’extraction compatible. Ce sont des backends séparés, pas une réécriture automatique du moteur graphique original en sources PC natives.

```diagram
{"type": "flow", "title": "De l’entrée console à une sortie testée", "nodes": [{"id": "step-0", "label": "1. Préserver les ressources", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Choisir le backend", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Convertir ou générer", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Consigner les identités", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Exécuter avec assertions", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Évaluer la compatibilité", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Préserver les ressources** — Examiner une entrée complète lisible.
2. **Choisir le backend** — Installer l’outil optionnel compatible.
3. **Convertir ou générer** — Lire code et imports incompatibles.
4. **Consigner les identités** — Garder reçu et journaux de sortie.
5. **Exécuter avec assertions** — Tester explicitement le comportement.
6. **Évaluer la compatibilité** — Compiler ne valide pas tout le jeu.


## Préparer et convertir {#prepare-and-convert}

1. Dans les outils de portage, installez/configurez convertisseur et bibliothèques du système cible. Configurez UltraPack pour les PKG/PFS/archives compatibles ; compiler son auxiliaire de paquets nécessite le SDK .NET 9+.
2. Sélectionnez un fichier ou un dossier extrait complet avec entrée, modules et ressources. Choisissez une entrée relative si plusieurs applications sont présentes.
3. Utilisez **Préparer l’entrée**, vérifiez métadonnées et prérequis manquants, puis **Convertir pour ordinateur**. L’original reste séparé. Importer un conteneur ne rend pas disponibles des octets essentiels chiffrés ou opaques.
4. Examinez les diagnostics. L’analyse automatique d’échec peut relier une tentative à des preuves C/désassemblage bornées et aux imports inconnus. L’échec du diagnostic reste distinct de celui de la conversion.
5. Configurez des scénarios avec assertions puis exécutez la sortie vérifiée. Examinez reçus et erreurs avant de réutiliser une conversion.

Le mode homebrew autonome est explicite et impose ses hypothèses sur les modules. Les exécutables racines secondaires diffèrent des modules PRX partagés et exigent un convertisseur adapté. Convertir la seule entrée ne prouve pas une application complète.

## Preuves de test et performances {#test-evidence-and-performance}

Une conversion commence en **converted-unverified**. Exécuter sans assertions reste **executed-unverified**. Définissez sorties/codes attendus depuis le comportement voulu indépendant ; ne copiez pas la nouvelle sortie uniquement pour faire réussir le test. Une assertion réussie ne couvre que son scénario.

Les profils graphiques natifs expérimentaux remplacent certains chemins de compatibilité et ont leurs contraintes d’identité/pilote. Ils ne prouvent ni reconstruction graphique complète, ni jeu fonctionnel, ni 60 FPS. Mesurez la même scène représentative après une modification significative, avec délai borné et preuves conservées. Surveillez l’espace : le [stockage](doc:storage) distingue originaux, sorties et caches. Le parcours [IA Portage et test](doc:ai) utilise les mêmes opérations.
