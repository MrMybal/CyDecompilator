# Investigations natives, Electron et web

L’onglet **Investigation** fournit des preuves avec SHA256 de la cible, fichier et
ligne ou adresse native. Les liens statiques et rapprochements candidats restent
distincts des observations d’exécution.

## JavaScript, Electron et web

Installer **TypeScript parser** depuis les moteurs ou le bouton de l’onglet.
TypeScript 5.9.3 est téléchargé dans le runtime privé depuis le registre officiel
npm et vérifié avec son SHA512. Node.js doit être disponible dans le PATH.

Saisir un dossier, une archive `.asar`, un fichier JS/TS/JSX/TSX ou HTML et choisir
**Analyser l’application**. Le moteur n’exécute pas les modules inspectés. Rechercher
un texte visible, un identifiant HTML, un symbole, un canal IPC ou une URL avec
**Rechercher les preuves**, puis sélectionner un résultat pour voir sa source et
les relations qui l’expliquent.

Le moteur relève imports ESM/CommonJS, fonctions, appels, ressources HTML,
associations `getElementById().addEventListener()`, options `BrowserWindow`, preload,
`contextBridge` et canaux IPC littéraux. Un canal n’est rapproché que s’il a un unique
gestionnaire statique dans le même sens de communication (renderer vers main ou
main vers renderer, notamment `BrowserWindow.webContents.send`). Les callbacks,
accès aux API exposées par le bridge et appels locaux sont des candidats : alias,
réaffectations, routage des frameworks et code dynamique peuvent empêcher leur
résolution. Les récepteurs masqués sont exclus de l’attribution à Electron et signalés.

Les source maps locales v3 sont décodées : VLQ, positions, noms et empreintes des
sources embarquées. Les positions viennent des segments de mapping sans garantir
l’équivalence sémantique. Maps externes, URL `data:` et maps indexées non prises en
charge ; aucune source distante n’est téléchargée.

**Rapprocher la capture HAR** importe une capture existante et compare ses URL aux
références littérales. Seuls URL, méthode, statut, date et durée sont retenus ; cookies,
en-têtes et corps ne sont pas copiés. Un rapprochement ne prouve pas l’exécution d’un
gestionnaire. La capture de navigateur en direct est disponible dans le scénario graphique décrit ci-dessous.

La copie persistante est dédupliquée par manifeste de chemins et SHA256. La navigation
vérifie les sources. Limites : 10 000 fichiers, 128 Mio au total, 16 Mio par fichier ;
AST : 4 Mio par source, 32 Mio de sources, 10 000 faits par source, 60 000 au total.
`node_modules`, `.git`, `.svn`, `.hg`, `bin`, `obj`, `.cydec` et liens sont exclus et
signalés. Les références ASAR restent relatives ; tailles, offsets et SHA256 publiés
sont vérifiés. Les fichiers `.asar.unpacked` présents sont lus ; les liens ASAR sont exclus.

## Natif

Analyser le binaire avec **Ghidra**, sélectionner une fonction dans l’espace de travail,
puis **Examiner la fonction native sélectionnée** dans Investigation. Le projet Ghidra
est réutilisé avec `-noanalysis -readOnly`.

Le dossier conserve prototype, convention d’appel, paramètres, disposition des types
composites, pointeurs, tableaux, instructions, références exactes, sites d’appel et
chaînes référencées. Les opérations high p-code relient leurs entrées et sorties via
les valeurs SSA de la fonction, dans le graphe des instructions et fonctions appelées.

Limites : 2 000 instructions, 1 500 opérations, types sur trois niveaux, 128 champs par
composite ; graphe des 20 000 premières fonctions et de la fonction sélectionnée. Les
types restent les résultats de Ghidra. Les alias mémoire, appels indirects et valeurs
entre fonctions ne sont pas résolus. Pas d’intégration Hopper/IDA ni de nouveau
débogueur natif. Le graphe limite les relations à 100 000 ; les limites sont signalées.

## Comparaison des versions

Dans **Comportement des versions**, indiquer deux exécutables et leurs arguments JSON.
Pour un script JS, utiliser `node.exe` avec le chemin absolu du script en argument.
Définir les mêmes stdin, fichiers initiaux et dossier de fichiers du scénario, capturer
chaque version, puis comparer les enregistrements.

Chaque exécution utilise un dossier de travail neuf. La capture conserve stdout/stderr
texte, code de retour, SHA256 des exécutables et arguments fichiers, et fichiers créés,
modifiés et supprimés. La comparaison montre différences de sorties et d’empreintes
des fichiers finaux. Le scénario est identique si stdin, fichiers initiaux, délai et
arguments correspondent ; les chemins absolus de fichiers représentant les versions
peuvent différer. Les captures peuvent être sélectionnées après réouverture.

Les enfants Windows sont rattachés à un Job Object, arrêté à sa fermeture. Limites :
300 secondes, 1 Mio par sortie, 4 000 fichiers, 32 Mio par fichier et 128 Mio au total.
Délai dépassé, sortie tronquée, exclusions ou cible modifiée rendent la capture
incomplète. L’entrée stdin est finie, sans séquencement temporel ni pseudo-terminal.

### Réseau et scénarios graphiques

Ouvrir **Scénario réseau et graphique**, choisir le pilote et cocher **Enregistrer le réseau**.
Les paramètres et étapes sont communs aux deux versions. Chaque étape conserve son résultat,
l’état des contrôles et une capture PNG. L’application et ses enfants sont arrêtés après le
scénario ; la terminaison distingue scénario terminé, étape échouée et sortie du processus.

- **Contrôles Windows** : sélectionner les contrôles accessibles par `automationId`, `name`
  ou `controlType` (par exemple `Button`). Actions : `click`, `fill`, `toggle`, `select`,
  `waitFor`, `assertText`, `wait`, `snapshot`. Seules les fenêtres du processus lancé et de
  ses enfants sont utilisées. Le recorder privé est compilé avec le .NET Framework de Windows.
- **Navigateur Chromium** : indiquer l’exécutable Chrome/Edge, l’URL du scénario et éventuellement
  le mode sans fenêtre. Node.js 22+ est requis. Une session privée est créée, avec un rendu
  de 1280 × 800 pixels. Les arguments de profil et de débogage sont gérés par la capture.
- **Rendu Electron** : indiquer l’exécutable de l’application et ses arguments. Node.js 22+
  est requis. Si plusieurs pages existent, fournir l’URL exacte du rendu ciblé. Les activités
  antérieures à la connexion au rendu ne sont pas observées.

Les pilotes web utilisent des sélecteurs CSS correspondant à un seul élément. Actions :
`click`, `fill`, `press`, `navigate`, `waitFor`, `assertText`, `wait`, `snapshot`.
Les champs mot de passe sont masqués dans les états et refusés pour `fill`.

L’éditeur d’étapes permet de choisir une action, un sélecteur, le texte et les délais,
puis **Ajouter l’étape**. Sélectionner une étape pour la modifier et **Appliquer l’étape**,
ou **Retirer l’étape**. **Nouvelle étape** quitte la modification. Le JSON reste disponible
dans **JSON avancé du scénario** pour importer ou adapter un scénario.

Exemple web dans **Étapes graphiques (JSON)** :

```json
[
  {"action":"fill","selector":"#name","text":"Rapport"},
  {"action":"click","selector":"#go"},
  {"action":"assertText","selector":"#result","text":"Terminé","timeoutMs":5000}
]
```

Pour Windows, remplacer les sélecteurs par un objet tel que `{"automationId":"go"}`.
**Insérer un exemple de scénario** fournit un point de départ. **Écrans capturés** puis
**Charger les écrans capturés** affiche les deux versions côte à côte ; le curseur choisit
l’état initial (étape −1), puis les étapes. Les PNG sont vérifiés par SHA256 avant affichage.
La vue **Différences observées** compare les états, sorties, fichiers, métadonnées HTTP/TCP
et console. Les empreintes PNG détectent toute différence visuelle, y compris animations,
curseurs, thèmes et autres variations d’affichage ; aucun seuil de tolérance n’est appliqué.
**Enregistrements réseau** permet d’examiner les requêtes, statuts et piles d’initiateurs
de chaque version, les connexions TCP et les messages console. Chaque requête indique
l’étape en cours lors de son observation ; cette proximité temporelle ne prouve pas
que l’action a causé la requête.

L’observation HTTP conserve URL, méthode, statut, MIME, volume et pile de l’initiateur.
Elle couvre le rendu sélectionné ; en-têtes, cookies, corps et trames WebSocket ne sont
pas enregistrés. Les connexions TCP des processus lancés sont échantillonnées toutes les
250 ms : les connexions courtes peuvent échapper à l’observation, UDP et contenus ne sont
pas capturés. Les ports locaux temporaires, PID et temps d’observation sont exclus de la
comparaison TCP. Le trafic du navigateur ou de son environnement reste observable et
peut varier. Seule la bannière du point de débogage introduit par la capture est normalisée
dans stderr ; les journaux et empreintes originaux sont conservés.

Limites : 30 étapes, 10 secondes par attente, 2 000 requêtes HTTP, 5 000 observations TCP,
500 messages console, 1 000 éléments par état et 8 fenêtres natives. Le stockage des PNG
est limité à 16 Mio par image et 128 Mio par scénario. Une étape échouée,
une limite atteinte, une requête inachevée ou une capture indisponible rend le résultat
incomplet. Les inconnues décrivent également les limites inhérentes au périmètre.
Les contrôles Windows doivent être accessibles et les captures dépendent du fournisseur
de fenêtre ; une application à rendu personnalisé peut nécessiter un scénario web.

Le dossier n’est pas un bac à sable du système : l’application peut accéder au réseau
et écrire ailleurs. Les fichiers hors du dossier restent hors observation. Des observations
identiques ne prouvent pas l’équivalence. Les rapprochements avec des routes ou contrôles
statiques sont des inférences, avec les enregistrements comme preuves observées.

## API et preuves

`application_open`, `investigation_native`, `investigation_query`, `investigation_source`,
`investigation_har`, `behavior_capture`, `behavior_captures`, `behavior_evidence`, `behavior_compare` sont
accessibles par interface, MCP, CLI et HTTP. Les requêtes retournent éléments, liens,
chemins depuis les correspondances, inconnues et indicateur de résultat partiel. Les
captures et HAR sont conservés après une nouvelle analyse de la même cible.

`tests/test_runtime_observation.py` vérifie un vrai navigateur Chromium, une fenêtre
Windows compilée localement, les échecs d’étapes, les connexions TCP et l’intégrité des PNG.
`tests/test_investigation.py` utilise le vrai Ghidra, le parseur privé, des fixtures
Electron/TypeScript/HTML/ASAR/source maps et des processus Windows. Captures de l’interface :
`data/reports/investigation-evidence.png` et `data/reports/investigation-behavior.png`.
