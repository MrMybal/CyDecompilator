# Travail sur la cadence de simulation Halo

État de l'audit initial du 20 octobre 2026 : la logique du jeu conserve 30 Hz.
La version jouable **2026-10-20.2 intègre ensuite des sous-pas physiques des
personnages à 60 Hz par défaut**, réglables à 30/60/120 Hz dans F2. Elle ne
débloque pas toute la logique, l'IA, les scripts et les véhicules.
Les FPS d'affichage sont débloqués et les copies de rendu des personnages sont
interpolées. Le travail ci-dessous est un essai isolé de conversion des unités,
pas un déblocage complet déjà installé dans le jeu.

## Essai reproductible

Depuis la racine du dépôt :

```powershell
runtime/python/Scripts/python.exe modules/xbox-native/scripts/check_rex_controls.py
```

Le programme console charge le XEX comme données et appelle les véritables
fonctions recompilées sur une mémoire de test. Il ne crée pas de fenêtre et ne
lance pas le thread principal du jeu. `native/rex_timing_checks.cpp` est lié
uniquement à cette cible de test. Le fichier source XEX, le profil et l'exécutable
jouable ne sont pas modifiés. Le reçu `project/input-checks.json` contient les
mesures ; une copie se trouve dans le répertoire de l'essai, sous
`simulation-timing.json`.

## Résultats et unités

| Partie | Fonction / donnée vérifiée | Résultat |
|---|---|---|
| Ordonnanceur | `822D1D80`, constante 30 à `820009E8` | 60 ticks sur deux secondes à 30, 60, 120 et 240 FPS d'affichage |
| Ordonnanceur accéléré | Même code, multiplicateur de vitesse 2 dans la mémoire de test | 120 ticks sur deux secondes ; cela ne convertit pas les unités du reste du jeu |
| Compteur de bipède | `82D36470`, durée écrite dans l'octet `+4D1` | 15 ticks dans les deux cas : 0,5 s à 30 Hz et 0,25 s à 60 Hz |
| Physique aérienne | `82D36520`, bloc de paramètres contrôlé, sans collision | Le déplacement horizontal double à 60 Hz sans conversion |
| Physique aérienne convertie | Même code à 60 puis 120 pas/s | Une unité parcourue par seconde, vitesse verticale finale conservée et convergence de la trajectoire balistique |

Pour ce dernier noyau, la mémoire contient une vitesse en unités par tick,
et la gravité globale `8347A260` représente une accélération en unités par tick
au carré. Avec `r = 30 / fréquence_cible`, il faut multiplier les vitesses par
`r` et cette gravité par `r²`. Multiplier toutes les constantes par le même
rapport ne convient donc pas. Le changement de pas modifie aussi l'erreur
d'intégration discrète : conserver la vitesse ne garantit pas une trajectoire
bit à bit identique à celle de 30 Hz.

Les producteurs des paramètres de déplacement sont notamment `82D38B68` et
`82D39F10` ; ils utilisent encore `1/30` à `82000A34`. Le test fournit directement
un bloc entièrement converti au noyau, ce qui ne valide pas encore ces producteurs
ni leurs autres consommateurs.

## Éléments à traiter avant une activation en jeu

La conversion aérienne n'a exercé ni le contact au sol, ni les pentes, ni les
véhicules. Il reste à adapter les producteurs et consommateurs des vitesses,
les réponses aux collisions et les compteurs de personnages, d'armes, d'IA,
d'animations et de scripts. Le compteur de 15 ticks ci-dessus constitue déjà
un contre-exemple concret à une modification du seul ordonnanceur.

Le champ « ticks écoulés » n'a pas besoin d'un correctif spéculatif de remise à
zéro : cette image Xbox 360 l'écrit déjà à `822D3330`, y compris lorsqu'aucun tick
n'a été exécuté. Les changements de simulation futurs doivent préserver ce
comportement, les pauses et les sauvegardes. Le réglage physique de la version .2
subdivise chaque appel du noyau `82D36520`, convertit les entrées/sorties et les
trois forces constantes via un facteur local au thread. Il préserve les entrées
du tick d'origine et réunit les événements de contact. Ce réglage ne modifie pas
la cadence des compteurs et des scripts. La compilation est livrée pour les essais
de l'utilisateur, sans nouvelle session de test en jeu à sa demande.
