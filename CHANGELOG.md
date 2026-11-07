# Changements

[English](CHANGELOG.en.md) · [README de l’application](README.fr.md) · [Publications](https://github.com/MrMybal/CyDecompilator/releases)

CyDecompilator est **en développement**. Windows x64 est pris en charge ; Linux x64 est expérimental.
La mise à jour publiée demande un runtime Python privé compatible déjà installé ; le numéro de version
ne garantit ni une reconstruction complète ni la compatibilité des jeux console.

## 1.5.1 — 6 novembre 2026

- Documentation CyDoc mise à jour : manuel humain complet en anglais et français,
  navigation hiérarchique, recherche globale en haut et infobulles détaillées.
- Références publiques des opérations et des liens d’aide, avec paramètres, retours
  et exemples traduits ; consignes IA séparées dans `DocAI.md`.
- Nouveau dossier `app/Documentation/` autonome, utilisable hors ligne ; F1,
  aides contextuelles et anciens liens conservés.
- Génération et distribution du lecteur complet dans l’application et sur GitHub Pages.
  Sources et outils documentaires séparés dans `.CyDocBuild/`.

### Disponibilité et problèmes connus

La [publication 1.5.1](https://github.com/MrMybal/CyDecompilator/releases/tag/v1.5.1) contient le lanceur
Windows, l’application et le manuel hors ligne. Conserver les dossiers `runtime/` compatible et `data/`
existants. Les changements des sources ou de la documentation postérieurs au tag ne modifient pas cette archive.

La publication ne fournit pas de liste des bogues un par un. Consulter le véritable
[suivi des problèmes](https://github.com/MrMybal/CyDecompilator/issues) et
[la couverture des fonctions](app/Docs/CapabilityCoverage.md) ; l’absence de ticket mentionné ne prouve
pas qu’un parcours est exempt de bogues.

### Limites documentées

- Linux x64 est expérimental ; aucune publication Linux ou macOS prête à l’emploi n’est proposée ici.
- Python 3.9+ : pas de décompilation complète en sources ; bytecode et reconstruction IA disponibles.
- Les bibliothèques DXIL (`lib_6_x`, ray tracing) n’exposent actuellement que leur première fonction.
- Les archives PyInstaller chiffrées (`--key`) et les installateurs NSIS/Inno sont détectés mais pas extraits.
- La reconstruction des types C natifs reste limitée : les structures peuvent apparaître sous forme
  d’expressions pointeur/décalage. Les prototypes ARM64 placent les paramètres entiers avant les flottants.
- Les services C# demandent les références adaptées du SDK .NET. Le débogage natif et .NET Framework
  n’est pas disponible ; la console d’exécution/débogage ne permet ni saisie interactive ni modification des variables.
- La reconstruction et le remplacement de fonctions ont des contraintes de format, dépendances, ABI
  et signature. Une compilation réussie ne prouve pas l’équivalence du comportement.
- Les conversions PS5/Xbox restent expérimentales et dépendent de backends séparés et du jeu.
  La Xbox d’origine permet seulement l’inspection/préparation. Une conversion ne garantit ni jouabilité ni 60 FPS.
- L’analyse des gros binaires par Ghidra peut être longue ; la limite de fonctions est réglable dans Moteurs.

Il s’agit de limites du périmètre, pas de tickets de bogue confirmés inventés. Consulter
[le manuel](https://mrmybal.github.io/CyDecompilator/manual/Documentation.html#/fr/start) pour chaque parcours.

## 1.5.0 — 2 novembre 2026

- Migration vers CyUI 1.2 modulaire : vues de code, édition JSON, différences Git et
  refactorisations, journaux filtrables, diagnostics, Markdown et conversations IA.
- Palette de commandes Ctrl+Maj+P, propriétés de fonctions filtrables et captures
  graphiques avec zoom, déplacement et ajustement à la fenêtre.
- Révision CyUI épinglée, empreintes des sources et lien vers la licence MIT, dont
  une copie est incluse pour rester consultable sans accès au dépôt privé.
- Préparation et conversion PS5 via AnyPS5/UltraPack optionnels, diagnostic relié aux
  fonctions et profils graphiques natifs expérimentaux. Compatibilité des jeux et
  objectif de 60 FPS toujours non établis.
- Règles et profils de reconstruction Unreal exposés au Runtime, à MCP et à l'agent ;
  la conversion des jeux reste distincte.
- Conservation de l'éditeur natif pour la complétion, le débogage et Undo/Redo.
- Lanceur Windows recompilé ; runtime privé et moteurs à conserver séparément.

## 1.4.0 — 17 octobre 2026

- Interface CyUI : navigation latérale, cinq thèmes, densité et taille du texte réglables,
  barres d’outils avec infobulles et dispositions adaptées aux petites fenêtres.
- Assistant organisé en parcours autonome, conversation et actions sur une fonction.
- Agent autonome accessible dans l’application et par MCP, avec reprise, sauvegardes Git,
  corrections, compilation et preuves de validation avant de terminer une reconstruction.
- Catalogue MCP complet, guide de connexion et skill CyDecompilator installable.
- Conservation du chemin de l’application originale lors de la préparation des entrées,
  et protection des sources ouvertes pendant les modifications autonomes.
- Lanceur Windows recompilé et inclus dans l’archive d’application ; runtime privé et
  moteurs conservés dans l’installation existante.
