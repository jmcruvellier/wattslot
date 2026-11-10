# Batterie

*[English version](../battery.md) · [Guide d'utilisation](README.md)*

WattSlot ne pilote pas votre batterie : il simule son comportement (elle charge tout surplus et se décharge sur tout déficit, comme la plupart des batteries domestiques en autoconsommation) pour placer vos appareils là où ils sont le plus utiles. Plusieurs batteries sont vues comme une seule, chacune pouvant avoir ses propres réglages (voir [Plusieurs batteries](#plusieurs-batteries)). Les réglages sont dans **Ma maison › L'essentiel › Batterie**.

## Réglages

| Réglage | Par défaut | Rôle |
|---|---|---|
| **Ne jamais décharger en dessous de** | 10 % | Le plancher : une réserve pour la nuit ou une coupure |
| **Plancher plus haut sur certaines plages** | aucun | Une réserve plus haute à certaines heures, par exemple 30 % de 18 h à 22 h |
| **Puissance de charge maximale** / **de décharge maximale** | de quoi charger ou vider la moitié de la batterie en une heure | Les limites de votre batterie, sur sa fiche technique |
| **La batterie charge et décharge de … à …** | toute la journée | Pour les batteries qui ne fonctionnent qu'à certaines heures |
| **Viser régulièrement une charge complète**, au moins tous les N jours | non | Les batteries au lithium recalent leur mesure de charge quand elles atteignent 100 % : le plan garde alors assez de surplus pour cela, et peut sauter quelques heures de piscine ces jours-là |

La capacité vient de Home Assistant quand un capteur la donne, sinon de sa fiche dans **Ma maison › Appareils** (**Capteurs, nom et type**).

## Plusieurs batteries

Les réglages ci-dessus valent pour toutes vos batteries. Quand la maison en a plusieurs, la feuille **Batterie** liste chacune sous **Réglages par batterie** : **Donner ses propres réglages à cette batterie** lui ouvre les mêmes réglages, pour elle seule ; **Reprendre les réglages de la maison** les retire.

Le calcul voit toujours vos batteries comme une seule :

- les **puissances** s'additionnent (sans réglage, chacune compte pour la moitié de sa capacité par heure) ;
- le **plancher** suit la capacité de chacune : 30 % d'une batterie de 2 kWh et 10 % d'une batterie de 6 kWh font 1,2 kWh gardés en réserve, heure par heure avec les plages ;
- la **plage active** est celle où une batterie au moins fonctionne, et la **charge complète** suit la batterie qui la demande le plus souvent.

C'est exact pour des batteries branchées au même endroit. Deux batteries qui ne voient pas le même surplus (une par phase en triphasé, par exemple) peuvent se remplir différemment : le plan est alors un peu optimiste.

Dans une maison en **triphasé** (voir [Votre maison et ses règles](your-home.md#maisons-en-triphasé)), une case demande si **la batterie compense le total des trois phases** (elle suit un compteur triphasé) ou seulement sa phase. Le plan n'en tient pas encore compte.

## Ce que vous voyez

- **Aujourd'hui** : la charge maintenant, son point le plus haut et son niveau à minuit.
- **Planning** : la charge prévue (en pointillés) face à la charge mesurée, la ligne du plancher, et la charge et la décharge de la batterie dans le Planning des équipements.
- **Batterie pleine avant midi** ([notification](notifications.md)) : le surplus suivant partirait sur le réseau, bon moment pour lancer un appareil.

## Bon à savoir

- WattSlot **recommande** seulement. Piloter la batterie (ralentir sa charge le matin pour qu'elle ne soit pas pleine avant le pic solaire, la charger en heures creuses) est prévu dans une version suivante, équipement par équipement.
- Le comportement réel de la batterie est mesuré : s'il diffère des réglages (une puissance plus faible, un autre plancher), la courbe mesurée le montre.
