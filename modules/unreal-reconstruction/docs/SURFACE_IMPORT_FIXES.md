# Raccords de terrain et transparence Anniversary

Intervention du 20 octobre 2026 à partir des captures et de la vidéo de référence.
Le projet garde les géométries et textures Anniversary. La vidéo classique sert
de référence de lecture de la scène, sans remplacer les assets remasterisés.

## Causes corrigées

Les couleurs des sommets statiques Xbox étaient interprétées RGBA alors que
leurs octets sont ARGB. Le premier octet, qui porte notamment le masque alpha
de terrain, alimentait le canal rouge. Les couches d'herbe, de terre et de roche
recevaient donc les mauvais masques. Par exemple, `[255,0,0,0]` doit devenir
RGBA `[0,0,0,255]`. Les sommets dynamiques gardent leur ordre RGBA ; l'ordre
des ensembles lumière/direction reste lui aussi traité séparément.

Ce diagnostic est également contrôlé sur les directions lumineuses non neutres :
pour 71 069 échantillons statiques A30, l'erreur médiane de longueur de direction
passe de 0,11876 en RGBA à 0,00327 en ARGB. Sur les 11 745 directions statiques
non neutres A10, elle passe de 0,28328 à 0,00350. Ce contrôle est un indice de
format ; la comparaison des buffers Unreal et les captures vérifient ensuite
le résultat de la conversion.

Les lianes `liana_01`/`liana_03` et les racines `grass_roots_01` utilisent leurs
masques de découpage. Les décals `border_dust_02` et `puddles_01` utilisent leur
transparence. Leurs textures et flags source confirment ces familles. L'alpha
de `moss_03` ou du sol n'est pas transformé arbitrairement en transparence :
il contient aussi des informations de surface. Les masques de couche vertex,
texture et vertex × texture sont distingués dans le graphe de matériau.

Chaque recette de surface de carte reçoit maintenant un identifiant qui inclut
ses couches et sa carte d'origine. Deux utilisations d'une même texture avec
des lumières ou shaders différents ne s'écrasent plus, y compris lorsqu'une
seule texture est utilisée. Les bitmaps restent partagés.

Les hashes sont exclus de la classification des surfaces. Un ancien identifiant
de roche finissait par `_LEAFC06C2` ; le mot `leaf` dans ce hash lui attribuait
à tort le comportement de feuillage et retirait sa collision.

Les coques `lighting_sm_invisible_shadowcaster` ne sont pas du décor visible.
Le proxy sans matériau du lifepod écrasé était auparavant fusionné au mesh,
dessiné avec un matériau de remplacement et susceptible de porter une collision.
Il est maintenant exclu de la coque visible. La coque visible projette les
ombres Unreal ; ce traitement ne reproduit pas le calcul d'ombres Saber à
l'identique. Les flags de visibilité de carte reconnaissent aussi ces proxies.
Un ancien slot `MissingMaterial` peut rester dans les métadonnées de réimportation
du lifepod ; le contrôle vérifie les sections réellement dessinées et confirme
qu'aucun triangle ne l'utilise. Les slots orphelins sont distingués des matériaux
manquants sur des faces visibles.

## Vérification

Les captures avant/après sont prises aux mêmes caméras, dans
`work/surface-audit`. Elles montrent le mélange du terrain et la suppression
des fonds opaques des lianes. Les triangles de carte sont conservés :
1 600 412 pour A10 et 945 987 pour A30.

La commande `audit-surfaces` compare les octets source aux vrais buffers LOD0
Unreal après passage par Blender et FBX : positions, quatre UV de textures,
quatre UV de lumière/direction, couleurs et modes de matériau. Les résultats
sont dans `surface-audit.json`, avec une preuve liée aux assets du projet dans
`surface-proof.json`. Ce contrôle ne prouve pas une équivalence de rendu pixel
par pixel avec Saber. Les résultats finaux de jeu/campagne sont repris dans
`conversion-report.json` pour chaque mission.

| Audit final dans Unreal | A10 | A30 |
|---|---:|---:|
| Sommets contrôlés | 653 | 1 849 |
| Écart maximal des masques (octets 0–255) | 0 | 0 |
| Écart UV maximal sur les huit canaux | 0,000000219 | 0,000003741 |
| Triangles de carte conservés | 1 600 412 | 945 987 |
| Morceaux de carte actuellement placés | 305 | 1 853 |

Les **30 tests Python passent**. Le lifepod possède 8 442 triangles, trois
matériaux utilisés par ses faces et aucun triangle utilisant l'ancien slot
technique `MissingMaterial`.

Les tests finaux de gameplay passent **31/31 sur chaque carte**. Les contrôles
de campagne passent **13/13 sur A10 et 15/15 sur A30**, avec un mixage PCM16
48 kHz stéréo enregistré : RMS 11 818,91 et 1 675,51 respectivement. Aucun appel
de campagne non pris en charge n'est rencontré pendant ces scénarios de départ.
Ces contrôles ne prouvent pas que les campagnes sont terminables intégralement.

![Comparaison des imports Unreal aux mêmes caméras](../work/surface-audit/comparison-anniversary.png)

```powershell
& '..\..\runtime\python\Scripts\python.exe' -m unreal_reconstruction audit-surfaces --map a30 --engine 'G:\UnrealEngine\UE_5.8'
```

Sauvegarde avant cette intervention :
`work/a10/backups/20261020-145813-surface`.

## Limites

L'eau, la réponse des matériaux, les volumes d'éclairage et plusieurs shaders
spécifiques à Saber restent des adaptations Unreal. Une texture source nommée
`white_018FA96A.png` reste absente de l'extraction A30. Ces corrections ne sont
pas un port complet du moteur de rendu, et les limites de campagne du bilan
[PRESENTATION_REPORT.md](PRESENTATION_REPORT.md) restent applicables.
