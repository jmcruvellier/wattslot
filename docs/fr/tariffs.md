# Tarifs

*[English version](../tariffs.md) · [Guide d'utilisation](README.md)*

Le plan place vos appareils là où l'électricité est gratuite (votre surplus) ou bon marché. Réglez votre contrat dans **Ma maison › L'essentiel › Mon contrat**. Sans tarif, un prix unique de 0,25 par kWh, dans votre devise, est supposé, et le plan cherche seulement à acheter le moins possible au réseau.

**Proposer d'après le tableau Énergie** lit les prix déclarés dans le tableau Énergie de Home Assistant, s'il y en a.

## Types de tarif

| Type | Quand | Ce qu'il faut saisir |
|---|---|---|
| **Prix unique** | Le même prix à toute heure (option base) | Le prix du kWh |
| **Heures creuses et pleines** | Un prix plus bas à certaines heures | Le prix des heures pleines, puis une **plage** par tranche moins chère (de, à, prix). Une plage peut être **limitée à certains jours ou mois** (week-end, été) |
| **Couleur du jour (Tempo)** | Le prix dépend de la couleur du jour et de l'heure | Le capteur de Home Assistant qui donne la couleur du jour (et celle du lendemain, facultatif), l'heure où commence le jour de couleur, puis chaque couleur avec son prix hors plages et ses plages. La première couleur sert quand la couleur n'est pas connue |
| **Prix dynamique** | Un prix pour chaque heure, par votre fournisseur ou le marché | Le capteur de Home Assistant qui donne le prix de l'heure en cours et des heures à venir, son unité, et le prix à utiliser quand il n'est pas connu |

## Revendre votre surplus

**Prix de revente du surplus** : ce que vous rapporte un kWh envoyé au réseau (0 si vous ne le vendez pas). Il peut aussi être lu dans un capteur. Avec l'objectif **le coût le plus bas**, le plan préfère consommer votre surplus quand il vaut plus que son prix de revente.

## Votre contrat

Ces deux champs valent pour tous les types de tarif :

- **Abonnement** (par mois) : le prix de l'abonnement, sans les kWh. Il est divisé par le nombre de jours du mois et ajouté au coût de chaque journée ; les indicateurs du plan le montrent (« dont abonnement 0,50 € »). Il ne change pas le plan, seulement le coût affiché. Laissez 0 pour ne pas le compter.
- **Puissance souscrite** (kVA) : la puissance au-delà de laquelle votre disjoncteur coupe, par exemple 6, 9 ou 12 kVA. Le plan évite de soutirer plus que cela au réseau en une heure (1 kW par kVA), par exemple en ne faisant pas tourner le chauffe-eau et le sèche-linge en même temps. Si votre consommation de base la dépasse déjà, un avertissement le signale. Le calcul porte sur des totaux horaires : un pic de quelques minutes n'est pas vu. Laissez vide si vous ne la connaissez pas.

## Sans panneaux solaires

WattSlot est tout aussi utile sans panneaux : avec des heures creuses, des jours de couleur ou des prix dynamiques, le plan déplace vos appareils, votre chauffe-eau et votre voiture vers les heures les moins chères. Ne déclarez pas de production solaire dans le tableau Énergie ; l'étape de prévision solaire ne s'applique alors pas.

## Conseils

- Les prix des modèles sont **indicatifs** : remplacez-les par les vôtres, ils guident chaque décision.
- Pour Tempo, le capteur de couleur vient en général de l'intégration **RTE Tempo** ; saisissez le nom des couleurs exactement comme le capteur les affiche.
- Les prix sont au kWh, dans la devise de votre maison (**Réglages › Langue et affichage**). Pour un capteur au MWh (prix spot) ou en centimes, choisissez cette unité : WattSlot convertit.
