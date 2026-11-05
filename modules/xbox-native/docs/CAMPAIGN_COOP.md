# Campagne coop — version PC 2026-10-20.9

Périmètre demandé : campagne à deux, écran partagé local et connexion directe
par IP. Le multijoueur compétitif Reach est exclu à la demande de l'utilisateur.

## Version locale à essayer

Lancer `Play-Halo-Coop.cmd`. Il utilise le même exécutable Halo recompilé que
`Play-Halo.cmd`, avec deux profils locaux. Le clavier/souris commande le joueur 1
et la première manette physique le joueur 2. Dans le menu de campagne, rejoindre
avec Start sur cette manette. F2 propose aussi « Joueurs locaux » et un raccourci
Start joueur 2 ; fermer F2 pour transmettre cette impulsion au jeu.

Les profils ont des identifiants distincts. Le profil principal conserve son
emplacement de données ; les paramètres de profil du joueur 2 sont séparés dans
`project/data/user/local_players/2/<title_id>`. Ce changement ne crée pas une
deuxième sauvegarde de campagne indépendante. Le réglage du nombre de joueurs
et l'attribution des manettes sont conservés dans `campaign-coop.toml`.

En mode solo, la première manette continue de commander le joueur 1.
Avec deux profils et la réservation clavier désactivée, deux manettes peuvent
commander respectivement les joueurs 1 et 2. Le RT est suspendu lorsque deux
profils locaux sont activés : sa capture actuelle ne prend en charge qu'une vue.

Validation : compilation native réussie ; la partie coop complète et le rendu
des deux vues restent à vérifier dans le jeu. Aucun test prolongé ni lancement
automatique n'est effectué.

## IP directe : intégration incomplète

Le module contient un adaptateur UDP IPv4 et les conversions d'adresses XNet.
Il corrige notamment l'ordre des octets des ports et permet de diriger les
annonces broadcast vers une IP précise. Les imports statiques recompilés et les
imports résolus dynamiquement utilisent les mêmes adaptateurs locaux.

Ces fonctions ne constituent pas une connexion de campagne opérationnelle.
Le runtime d'origine laisse la création, la recherche et les détails de session
XGI incomplets. Le menu PC indique explicitement l'état expérimental ; mémoriser
une IP ne lance pas une session coop. Aucun état « connecté » n'est fabriqué.
Il reste à relier une vraie session de campagne hôte/client au transport PC et à
vérifier sa synchronisation. Aucun service Xbox Live n'est ajouté.

Les modifications restent dans le module et ses sources générées. Le SDK épinglé
et les exécutables originaux du disque ne sont pas modifiés.
