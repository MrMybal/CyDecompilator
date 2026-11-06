---
id: observations
title: Comparer sorties, réseau et comportement graphique
description: Enregistrer et comparer sorties, fichiers, activité réseau et scénarios graphiques.
section: Examiner les comportements
parent: investigation
order: 12
sourceRevision: 2
---

Dans **Investigation → Comportement des versions**, configurez deux versions et le même scénario reproductible. Définissez arguments, entrée standard, fichiers initiaux, délais et pilote d’observation. Lancez uniquement l’application à tester ; les observations concernent les processus lancés et leurs enfants pris en charge.

```diagram
{"type": "flow", "title": "Du scénario à la conclusion", "nodes": [{"id": "step-0", "label": "1. Choisir les versions", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Définir les actions", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Exécuter séparément", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Capturer les preuves", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Comparer", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Préciser la conclusion", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Choisir les versions** — Consigner identités et prérequis.
2. **Définir les actions** — Utiliser mêmes entrées et contrôles.
3. **Exécuter séparément** — Borner durée et processus.
4. **Capturer les preuves** — Sorties, fichiers, écrans, réseau.
5. **Comparer** — Examiner écarts et données absentes.
6. **Préciser la conclusion** — Seuls les contrôles observés sont établis.


## Choisir un pilote {#choose-a-driver}

| Pilote | Prérequis et périmètre |
|---|---|
| Contrôles Windows | Contrôles UI Automation accessibles ; enregistreur privé .NET Framework |
| Chromium | Chrome/Edge compatible, URL du scénario et Node.js 22+ |
| Rendu Electron | Exécutable, Node.js 22+ et URL exacte du rendu en cas d’ambiguïté |

Créez les étapes avec l’éditeur graphique ou le JSON avancé. Les sélecteurs CSS doivent désigner un seul élément pour les pilotes web. Adaptez cet exemple et son texte attendu à votre application :

```json
[
  {"action":"fill","selector":"#name","text":"Rapport"},
  {"action":"click","selector":"#go"},
  {"action":"assertText","selector":"#result","text":"Terminé","timeoutMs":5000},
  {"action":"snapshot"}
]
```

Sous Windows, les sélecteurs sont des objets, par exemple avec automationId, plutôt que du CSS. Les actions varient selon le pilote ; remplir un mot de passe est refusé. L’éditeur propose action, sélecteur, texte, délai et commandes d’ajout/modification/suppression.

## Lire les preuves {#read-the-evidence}

**Différences observées** compare sorties, fichiers, contrôles, observations HTTP/TCP et messages console activés. **Écrans capturés** charge les PNG vérifiés par empreinte pour chaque version à l’étape choisie. **Enregistrements réseau** affiche méthode/URL/statut/MIME/taille, piles d’initiateurs disponibles et connexions TCP échantillonnées. Une observation proche d’une étape est une association temporelle, pas une preuve de causalité.

La capture HTTP omet en-têtes, cookies, corps et trames WebSocket. L’échantillonnage TCP peut manquer des connexions courtes et ne capture ni UDP ni contenu des paquets. L’activité Electron antérieure à la connexion au rendu peut manquer. La comparaison PNG est exacte : animation, curseur et thème peuvent différer sans régression fonctionnelle.

## Limites et conclusions {#bounds-and-conclusions}

Les limites incluent 30 étapes, 10 secondes par attente, 2 000 requêtes HTTP, 5 000 observations TCP, 500 messages console, 1 000 éléments d’état et 8 fenêtres natives. Le stockage PNG est borné à 16 Mio par image et 128 Mio par scénario. Capture absente, étape échouée, requête inachevée ou limite atteinte rendent les preuves incomplètes. Un rapport concordant ne concerne que ses critères activés et son scénario enregistré. La [reconstruction](doc:reconstruction) applique ces comparaisons aux sorties produites.
