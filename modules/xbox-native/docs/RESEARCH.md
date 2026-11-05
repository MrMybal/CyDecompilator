# Recherche : recompilation Xbox / Xbox 360 vers PC

État examiné le 19 octobre 2026. Les descriptions amont indiquent des capacités de
leurs projets ; les résultats locaux sont détaillés dans HALO_REPORT.md.

## Projets examinés

- [AnyPS5](https://github.com/boykopovar/AnyPS5) : reliaison vers les formats natifs
  Windows/Linux et bibliothèques système de remplacement. Cette architecture
  inspire la séparation entre analyse, traduction, compatibilité système et validation.
- [xemu](https://github.com/xemu-project/xemu) : émulateur de la première Xbox,
  utilisable comme documentation matérielle et référence comportementale future.
  Il ne fournit pas une chaîne de conversion native Xbox 360. Aucun code xemu n'est
  intégré et aucun processus xemu n'est lancé.
- [XenonRecomp](https://github.com/hedge-dev/XenonRecomp) : traduction statique
  PowerPC Xbox 360 vers C++. Le projet ne fournit pas le runtime nécessaire au jeu.
  Sa documentation décrit aussi des limites pour les exceptions, MMIO, frontières
  de fonctions et tables de sauts. Moteur retenu pour la voie CPU Xbox 360.
- [rexdex/recompiler](https://github.com/rexdex/recompiler) : autre piste historique
  Xbox 360 vers Windows ; étudiée comme référence, non intégrée dans cette version.

## Les formats et les couches à traiter

La Xbox originale utilise des exécutables XBE avec code x86. La Xbox 360 utilise
notamment XEX2 et du code PowerPC Xenon, avec des instructions vectorielles propres
à la console. Le mécanisme de reliaison d'AnyPS5 ne suffit donc pas pour ces deux cas.

Le module distingue :

1. Le conteneur : lire le disque/archive et préserver les données d'origine.
2. Le format exécutable : sections, adresses, imports, identité exacte du titre.
3. Le code CPU : décompilation/analyse ou traduction statique vers C++ puis objets natifs.
4. Les services : threads, mémoire, fichiers, synchronisation, imports Xbox/XAM.
5. Le matériel et le multimédia : GPU NV2A/Xenos, shaders, audio et périphériques.
6. La validation : objets, édition de liens, lancement, image, son et scénarios du jeu.

Une structure de registres passée aux fonctions C++ traduites n'est pas un interpréteur
de processeur : les instructions sont converties avant la compilation native. Il reste
nécessaire de conserver les conventions mémoire et les effets des appels console.
Le module ne prétend pas récupérer les noms/classes/sources C++ d'origine.

## Références de formats

- [XBE, définitions Cxbx-Reloaded](https://github.com/Cxbx-Reloaded/Cxbx-Reloaded/blob/master/src/common/xbe/Xbe.h)
  et [implémentation XBE](https://github.com/Cxbx-Reloaded/Cxbx-Reloaded/blob/master/src/common/xbe/Xbe.cpp).
- [XEX2, définitions Xenia](https://github.com/xenia-project/xenia/blob/master/src/xenia/kernel/util/xex2_info.h).
- [XDVDFS, lecteur de disque Xenia](https://github.com/xenia-project/xenia/blob/master/src/xenia/vfs/devices/disc_image_device.cc).
- [Chargeur XEX XenonRecomp](https://github.com/hedge-dev/XenonRecomp/blob/ddd128bcca99fe8bfbb99bea583c972351fa6ace/XenonUtils/xex.cpp).
- [Configuration XenonRecomp](https://github.com/hedge-dev/XenonRecomp/blob/ddd128bcca99fe8bfbb99bea583c972351fa6ace/XenonRecomp/recompiler_config.cpp).

Les lecteurs Python sont écrits localement à partir des structures de formats ; aucun
fichier de ces projets n'est recopié dans le module. Le pont C++ se lie au moteur
MIT installé séparément. Les routines utilitaires sont comparées intégralement avec
les suites canoniques : une courte signature seule ne suffit pas à les valider.

## Décision et suite technique

La première Xbox et la Xbox 360 gardent des chemins distincts. La voie Xbox dispose
d'un chargement XBE dans Ghidra et d'un export des sections ; sa recompilation x86
complète reste à implémenter. La voie Xbox 360 utilise XenonRecomp avec profils liés
à un SHA-256, journaux, tentatives isolées et vérifications Clang réelles.

Pour Halo, la génération de la branche fautive est désormais corrigée. La suite
porte sur les variantes d'instructions manquantes, les continuations de fonctions
et les chemins indirects documentés dans HALO_REPORT.md. Un portage jouable nécessite
ensuite le runtime natif et le rendu. Ces travaux ne peuvent pas être remplacés par
un EXE vide ou par un retour « succès » pour les imports manquants.

La reprise a corrigé la génération des branches sortant d'une fonction, ajouté
huit familles d'instructions et remplacé plusieurs abandons silencieux par des
diagnostics d'exécution. Les décisions ont été confrontées aux implémentations
primaires de [contrôle de flux Xenia](https://github.com/xenia-project/xenia/blob/master/src/xenia/cpu/ppc/ppc_emit_control.cc)
et de [mémoire Xenia](https://github.com/xenia-project/xenia/blob/master/src/xenia/cpu/ppc/ppc_emit_memory.cc).
La suite native utilise des XEX synthétiques locaux. Elle ne constitue pas une
comparaison exhaustive avec le matériel console. Les corrections du traducteur
sont liées à une empreinte de source amont et construites dans un répertoire séparé.

L'intégration CyDecompilator sera une étape ultérieure, après stabilisation des
contrats JSON et des capacités observées. Les pages et opérations de l'application
ne sont pas modifiées par ce prototype.
