# Portage Xbox natif dans CyDecompilator

## Rendu Anniversary noir : correction 2026-10-21.1

Sur le XEX SHA-256 `1412845884eba9eb61cdc00213ca3777be19c71f6196faea69e435a350fd3f19`,
le mode remasterisé Saber exige les réglages suivants avec le plugin personnalisé :
`native_querybatch_range=256`, `readback_resolve=full`,
`gamma_render_target_as_unorm16=false`, `gpu_allow_invalid_fetch_constants=true`,
`occlusion_query_enable=true` et `query_occlusion_fake_sample_count=0`.
Le lancement intégré applique ces options à ce profil seulement. Le chemin RTV normal
convient ; passer uniquement en ROV ne résout pas cet écran noir.

Les écritures Z-pass sont des snapshots cumulatifs. Les surveys QueryBatch de Saber
ne se réduisent pas à une paire de blocs adjacents. Le gestionnaire matériel conserve
les segments traversant plusieurs listes et exclut les passes de capture RT des compteurs.
La plage positive 256 active cependant un **repli synthétique borné**, compatible avec
la visibilité de Saber ; elle ne fournit pas une occlusion géométrique exacte des flares.
La valeur 0 réactive les snapshots matériels. Les flares traversants restent à corriger.
Les readbacks complets corrigent l'exposition/HDR côté CPU mais peuvent coûter beaucoup
de performances. Ne pas les remplacer par `fast` sur la seule base d'une scène déjà chargée.

Validation visuelle en jeu : salle de réveil `a10` et plage `b30`, bascule Classic/Anniversary,
RT désactivé. Cela ne valide ni toute la campagne, ni le RT, ni la coop. Les captures et
empreintes locales sont dans `data/reports/halo-anniversary-fix.json`.

**Lancer une carte directement.** Le prototype accepte `Play-Halo.cmd --map b30` et fournit
`Play-Halo-Carte.cmd`. Il passe par le frontend de campagne, avec impulsions A temporaires,
puis remplace le nom dans **LoadLevelSolo et Saber LoadLevel**. Changer uniquement
`map_name` laisse le menu ou la scène Saber précédente ; remplacer seulement LoadLevelSolo
peut charger deux cartes différentes entre Blam et Saber. Les chaînes invitées doivent
conserver leur allocation, leur compteur de références et le contexte PPC. Les hooks sont
liés à cette empreinte XEX. Le lancement direct est solo ; la coop conserve la sélection normale.
Le `game.cfg` extrait localement désactive la vidéo de démarrage ; sa copie précédente est
conservée sous `work/gpu-occlusion/anniversary-original-game.cfg`.

Référence : [suivi officiel Xenia Canary, Halo Anniversary](https://github.com/xenia-canary/game-compatibility/issues/552),
notamment les observations QueryBatch et readback/gamma. Ces contournements documentés
ont été adaptés au runtime recompilé ; aucun processus Xenia n'est lancé.


## Utilisation

Ouvrir **Portage Xbox** dans la barre latérale. Préparer un dossier de jeu extrait,
une ISO XDVDFS ou un ZIP contenant une ISO. Un fichier XBE/XEX seul importe uniquement
l'exécutable, sans rechercher des données dans tout son dossier parent. Les originaux
sont conservés et les ressources du dossier/disque sont copiées dans le projet.

Pour Xbox 360, installer/configurer ReXGlue dans les outils Xbox, créer le projet
natif puis le compiler. Le parcours intégré vise Windows x64 avec Visual Studio C++,
Clang, CMake, Ninja et le SDK Windows. Le SDK officiel 0.10.0 est séparé sous
`runtime/engines/rexglue/`, avec vérification SHA-256 de son archive épinglée.
Les sources C++/CMake générées restent sous `data/projects/<id>/xbox/builds/`.
**Modifier les sources natives** ouvre ce dossier dans l'IDE de projet.

La section **Projet Xbox natif existant** rattache le projet Halo déjà préparé sans
recopier ses jeux ni modifier son build. Il dépend alors de son emplacement d'origine.
Le lancement est explicite. Le jeu appartient à une tâche du Runtime : annuler cette
tâche arrête son arbre de processus. Les journaux sont liés à la tâche ; sauvegardes
et caches restent sous `data/` dans le projet natif. Les réglages du jeu peuvent
remplacer le plein écran demandé au lancement.

## Méthode utilisée

Halo Anniversary est ici un jeu **Xbox 360**. Son XEX vérifié a pour SHA-256 :

`1412845884eba9eb61cdc00213ca3777be19c71f6196faea69e435a350fd3f19`

ReXGlue traduit à l'avance les instructions PowerPC en C++, compilé pour PC avec
un runtime de compatibilité console et un backend graphique issu de Xenia. xemu
était une référence pour la Xbox première génération ; il ne fait pas tourner ce
portage Xbox 360. Aucun processus d'émulateur séparé n'est lancé. Le C++ généré
représente le comportement machine : les noms, types et sources d'origine ne sont
pas automatiquement retrouvés.

Le profil Halo fournit des limites de fonctions, callbacks, tables virtuelles et
indications d'analyse des exceptions. Les adaptations locales ajoutent commandes PC,
cadence, interpolation, certains sous-pas de physique et profils hors ligne. Chaque
modification d'adresses est limitée au SHA-256 exact. Un autre jeu reçoit un projet
ReXGlue générique ; sa compatibilité demande une investigation propre.

Les fichiers BSD du SDK nécessaires aux profils sont livrés avec leurs licences et
empreintes sous `xbox_support/third_party/rexglue`. Les versions modifiées sont générées
dans `native-overlay/` de chaque projet. Le SDK et son checkout original restent intacts.

## États et limites

Préparation, traduction CPU, compilation, lien, lancement et validation du gameplay
sont des preuves différentes. Un code de sortie nul donne **Exécuté ; comportement
non vérifié**, pas « jeu compatible ». `nativeGameReady` reste faux. Le bon résultat
observé sur Halo ne démontre pas le support de tout le catalogue Xbox.

La Xbox première génération permet l'inspection XBE et la préparation des données ;
son runtime/recompilateur natif complet n'est pas implémenté. Le portage PS5 reste un
parcours distinct. Les adresses et correctifs Xbox ne s'y appliquent pas.

## Problèmes rencontrés et erreurs à éviter

**Analyse du code.** Identifier les helpers de sauvegarde/restauration des registres,
les appels indirects, callbacks, tables de sauts et exceptions pour le binaire exact.
Ne pas transformer une destination inconnue en retour silencieux réussi. Deux branches
de ce Halo peuvent atteindre l'instruction illégale nulle à `0x8317EE64` : la garde
locale conserve une erreur fatale si elles sont prises. Cette règle n'est pas générique.

**Imports et ABI.** Respecter les registres PowerPC r3-r10, les paramètres sur pile et
les structures big-endian. Le paramètre « caller » de NetDll décale les arguments des
sockets : confondre r8/r9 abîme la destination de sendto. Convertir explicitement l'ordre
des octets des ports Windows. Adapter à la fois les appels directs C++ générés et la
résolution dynamique des imports par ordinal/registre. Un stub qui renvoie zéro n'est
pas une fonction réseau opérationnelle.

**FPS et simulation.** Débloquer l'affichage indépendamment de l'horloge de simulation.
Plus de FPS n'augmente pas automatiquement la cadence de l'IA, des collisions ou des
animations. Interpoler entre deux états de simulation, sans réinterpoler une pose déjà
interpolée. Conserver les identités/générations d'objets ; réinitialiser après téléportation,
changement de carte, remplacement, pause ou saut de temps. Restaurer les données invitées
temporairement modifiées après l'export de la pose de rendu.

**Personnages, cinématiques et véhicules.** Vérifier séparément les bras/armes, poses
ennemies et positions du monde. Le vaisseau d'une cinématique utilise un autre chemin
de transformations qu'un personnage. Les véhicules et leur caméra de suivi nécessitent
aussi un traitement distinct. En écran partagé, historique et caméra doivent être propres
à chaque vue/joueur. Les sous-pas physiques doivent conserver le temps total d'un tick ;
ils n'accélèrent pas automatiquement les scripts. La course agit sur la vitesse souhaitée
du joueur à pied ; le balancement de l'arme doit s'arrêter en l'air et éviter les véhicules.

**Souris et menus.** La visée relative directe évite la zone morte et l'accélération d'un
stick analogique. Consommer chaque déplacement une fois ; effacer les deltas anciens lors
d'une perte de focus, pause ou changement de capture. Envoyer les clics à l'interface GFx
existante, sur son thread invité, en préservant les registres et l'ordre appui/relâchement.
Des curseurs virtuels/Kinect concurrents peuvent écraser le curseur PC. Tenir compte du
viewport, des bandes noires et de l'étirement pour convertir les coordonnées.

**Pause et joueurs locaux.** Échap doit réellement envoyer une pause/Start. Deux joueurs
nécessitent deux profils hors ligne et des entrées distinctes : clavier/souris J1, première
manette J2, ou deux manettes si la réservation clavier est désactivée. Le SDK ne présentait
qu'un seul profil. Séparer les paramètres du second profil, conserver la sauvegarde principale
et ne pas annoncer une deuxième campagne sauvegardée indépendamment.

**Lens flares.** Les snapshots de visibilité Halo peuvent utiliser deux enregistrements
adjacents de 32 octets. Une mauvaise association début/fin, une fin orpheline ou une séparation
des listes D3D12 peut casser les requêtes d'occlusion. Ne pas remplacer une requête absente
par une visibilité positive fixe de 1000 échantillons : les flares traversent alors les objets.
Vérifier durée de vie, segments cumulés, profondeur et véritables lumières visibles/masquées.
Les correctifs précédents ne prouvent pas que tous les défauts signalés sont résolus.

**Ray tracing.** Le plugin GPU optionnel apporte SMAA et du DXR expérimental. Il reste une
DLL de runtime distincte. La capture actuelle ne reconstruit pas complètement les matériaux
et éclairages à la manière de Remix : géométrie, transformations, UV, textures, découpes alpha,
transparence, émissifs indépendants, lumières et profondeur primaire doivent être corrects.
Une couleur HDR déjà éclairée n'est pas un canal émissif séparé. Deux passes spatiales
bilatérales ne remplacent pas une accumulation temporelle avec reprojection, mouvement et
gestion des désocclusions. Le RT est suspendu avec deux profils locaux car sa capture actuelle
suppose une seule vue. Ne pas annoncer un éclairage ou un débruitage complet.

Le plugin optionnel peut être reconstruit avec le script livré
`xbox_support/scripts/rex_gpu_diagnostics.py --source <checkout> --sdk <sdk-root>
--fix-occlusion --work <dossier-de-build-runtime>`. Il exige le commit SDK
`f5337cdc947ff6d4c4196737e2c807a48f2a1fc2`, construit une copie adaptée sans modifier
le checkout et produit `plugin.json` et `build/rexgpu-xenos-occlusion.dll`.
Configurer cette DLL dans les outils Xbox puis reconstruire le jeu pour la copier
dans son build. L'application ne distribue ni plugin compilé ni contenu des jeux.

**Réseau.** Le périmètre demandé est la campagne coop, locale et à terme par IP directe.
Le compétitif Reach est exclu. `ReachTU1.xex` est un second exécutable : sa présence sur le
disque ne signifie pas qu'il est compilé dans la campagne. UDP et conversion d'adresses ne
suffisent pas : session hôte/client, découverte, membres et état de campagne synchronisé sont
encore nécessaires. L'IP directe actuelle ne crée pas de session de campagne opérationnelle.
Ne pas simuler un état « connecté » pour cacher les fonctions XGI/XNet manquantes. Le routage
de deux profils locaux est implémenté ; la session complète en écran partagé reste à tester.
Aucun service Xbox Live n'est fourni.

**Livraison.** Vérifier l'empreinte de l'EXE et du plugin réellement lancés après une mise à
jour. Modifier les sources sans reconstruire avait déjà faussé les essais. Ne pas désactiver
l'antivirus automatiquement ni contourner une quarantaine ; garder build reproductible,
journaux et empreintes pour l'investigation. Conserver jeux, SDK, builds et caches hors du
code livré avec l'application. Une interface qui dépend d'un checkout de recherche privé
ne constitue pas une intégration complète.

## Opérations partagées

`xbox_open`, `xbox_info`, `xbox_tools`, `xbox_install`, `xbox_attach`, `xbox_create`,
`xbox_build`, `xbox_run`, `xbox_guide` utilisent le même Runtime authentifié en ImGui,
CLI et MCP. Lire leur schéma avant utilisation. Le Runtime prépare les fichiers ; les
dossiers sont copiés avec limites et refus des liens/reparse points. Attendre la fin
d'une annulation avant de nettoyer les fichiers temporaires.

Référence officielle : https://github.com/rexglue/rexglue-sdk
