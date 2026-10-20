# Votre maison et ses règles

*[English version](../your-home.md) · [Guide d'utilisation](README.md)*

Tout se trouve dans **Ma maison** : les règles de chaque appareil dans l'onglet **Appareils**, votre priorité, votre contrat, vos panneaux et votre batterie dans **L'essentiel**. Un modèle prêt à l'emploi règle presque tout d'un coup ; ajustez ensuite ce qui diffère chez vous.

## Ce que WattSlot fait de chaque équipement

Le **type** d'un équipement décide de ce que le plan peut en faire, par son **comportement** :

| Comportement | Équipements typiques | Ce que fait le plan |
|---|---|---|
| **Cycle à démarrer** | Lave-linge, sèche-linge, lave-vaisselle | Choisit le meilleur départ d'un programme, d'après son énergie et sa durée habituelles (apprises dans l'historique) |
| **Besoin d'énergie avant une échéance** | Chauffe-eau, voiture électrique | Fournit une énergie donnée avant une heure, sans dépasser une puissance (d'un coup ou par paliers) |
| **Durée de fonctionnement à placer** | Pompe de piscine | Place un nombre d'heures par jour, selon la saison, quand le soleil produit le plus |
| **Stockage** | Batterie de la maison | Charge et décharge autour du plan (voir [Batterie](battery.md)) |
| **Production** | Panneaux solaires | Donne la prévision |
| **Échanges avec le réseau** | Votre compteur | Mesure vos achats et votre surplus |
| **Consommation seulement suivie** | Réfrigérateur, télévision, le reste | Mesurée, comptée dans la consommation, jamais placée |

Décochez **Pris en compte par le calcul** sur un équipement pour seulement le suivre.

## Quand un cycle est dû

Un cycle (lave-linge…) est placé un jour où quelque chose le demande :

- **Une demande** : **Demander un appareil** (`+`), *dès que possible* ou *au plus tard le* une date. Le plan choisit le meilleur moment avant cette date. **Planning › Mes demandes** les liste.
- **Une liste de tâches de Home Assistant** : choisissez la liste dans **Réglages › Calcul automatique** ; une tâche comme « lancer le lave-linge », avec une échéance, devient une demande.
- **Une récurrence**, dans les **Règles du cycle** de l'équipement : tous les N jours depuis le dernier cycle, certains jours de la semaine, ou une règle avancée (format iCalendar). Les tâches récurrentes de Home Assistant pour cet équipement sont alors ignorées.

Autres règles du cycle :

- **Démarre après la fin de** un autre équipement : le sèche-linge après le lave-linge, le même jour.
- **Peut être reporté de** N jours au plus (2 par défaut) : un cycle en attente peut glisser vers un jour plus ensoleillé.

## Contraintes horaires

Pour tout équipement placé, dans ses **Contraintes horaires** :

| Contrainte | Exemple |
|---|---|
| **Interdit** de … à … | Pas de lave-linge entre 22 h et 7 h (le bruit) |
| **Pas avant** … | Lave-vaisselle pas avant 9 h |
| **Terminé avant** … | Voiture chargée avant 7 h |

Une contrainte est stricte par défaut. Cochez **Souple** pour qu'elle soit respectée si possible : sinon, le plan place quand même l'équipement et le signale.

## Besoins d'énergie et durées de fonctionnement

- **Besoin d'énergie avant une échéance** : l'énergie à fournir, la puissance maximale, les heures **Au plus tôt à** et **Avant**, **Par paliers** (tout ou rien à pleine puissance, pour une simple prise marche/arrêt), et **Chaque jour** ou seulement quand une tâche le demande.
- **Durée de fonctionnement à placer** : une ou plusieurs **vitesses** avec leur puissance (éco, silence… pour une pompe à vitesse variable), les **heures minimales par jour** en été, à la mi-saison et en hiver, les jours qu'on peut sauter quand la batterie doit faire sa charge complète, et le nombre de démarrages par jour au plus. Sans vitesse réglée, une seule est utilisée, à la puissance mesurée sur les 30 derniers jours.

## Panneaux

Seulement si le tableau Énergie de Home Assistant n'a pas de prévision solaire : décrivez chaque **champ** (un par orientation) avec sa **puissance crête** (kWc, sur la facture de l'installateur), son **inclinaison** et son **orientation**, plus la puissance maximale de l'onduleur s'il plafonne la production. WattSlot calcule alors une prévision avec Open-Meteo, à l'emplacement (arrondi) de votre Home Assistant. Une intégration de prévision dans Home Assistant (Forecast.Solar, Solcast…) est en général plus juste.

## Objectif

**Le calcul vise** :

| Choix | En bref |
|---|---|
| **Le coût le plus bas** (par défaut) | La facture la plus basse : acheter aux heures les moins chères, consommer le surplus plutôt que le revendre à bas prix |
| **L'autonomie** | Acheter le moins d'énergie possible au réseau, même un peu plus cher |
| **L'autoconsommation** | Consommer sur place le plus de votre production, même s'il faut acheter en heures pleines |
| **Le moins de CO₂** | Acheter quand l'électricité du réseau émet le moins (il faut un capteur d'intensité carbone) |
| **Un compromis** | Des poids libres entre coût, achat, surplus, CO₂ et ménagement de la batterie |

## Modèles, sauvegarde et partage

- **Modèles prêts à l'emploi** règle d'un coup comportements, tarif, objectif et batterie. **Voir ce qui changerait** avant **Appliquer le modèle** : les équipements qu'il ne connaît pas restent tels quels.
- **Sauvegarder ou partager** exporte votre maison et ses réglages dans un fichier lisible, et en réimporte un : pour garder une copie, passer à une nouvelle installation, ou le joindre à un signalement. Votre connexion à Home Assistant n'y figure jamais.
