# Manifest du Tool

Le manifeste applicatif est généré par `app/build_manifest.py` depuis
`app/operations.py`. Chargement : `cydec.mcp.load_manifest(path)`.
Référence exécutable : `app/CyTool.json` et `app/tool.py` ; validation des entrées
par le registre natif CyMCPSDK. Voir [CyMCPSDK.md](CyMCPSDK.md).

Champs obligatoires : schemaVersion, protocolVersion, id, name, version, description,
operations, platforms, concurrency. Un id commence par une lettre puis contient des
lettres ASCII, chiffres, `_`, `.` ou `-`, au maximum 128 caractères.

Champs d'identité optionnels : displayName, vendor, author, categories, tags, executable,
license, documentation, homepage, repository. Le manifest ne lance pas executable :
c'est une indication de découverte et d'installation.

Champs de capacités : capabilities, interfaces, backends, runtimeRequirements,
idleUnloadPolicy. Chaque opération porte ses schémas et ses capacités propres.
Le runtime vérifie l'unicité des IDs et les références aux backends.

Les champs inconnus sont préservés ; `extensions` permet les ajouts propres à un Tool.
Les paramètres métier peuvent au contraire refuser les champs inconnus avec
additionalProperties:false. Version majeure incompatible → IncompatibleVersion.
Ne pas placer de clés API, jetons, comptes utilisateur ou chemins privés de développeur
dans un manifest distribuable.

Depuis le SDK 0.10.0, `operations[].exclusiveGroups` est un tableau optionnel d'IDs
uniques. Les opérations partageant un groupe ne s'exécutent pas simultanément dans
le même Runtime. Les anciens manifestes sans ce champ gardent leur comportement.
Voir [Scheduler.md](Scheduler.md) avant de remplacer une file GPU interne.
