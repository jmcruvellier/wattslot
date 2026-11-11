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

- les **puissances** s'additionnent (sans réglage, chacune compte pour la moitié de sa capacité par heure). Les puissances réglées pour la maison sont celles de toutes vos batteries ensemble : une batterie sans réglages propres en prend sa part, selon sa capacité ;
- le **plancher** suit la capacité de chacune : 30 % d'une batterie de 2 kWh et 10 % d'une batterie de 6 kWh font 1,2 kWh gardés en réserve, heure par heure avec les plages ;
- la **plage active** est celle où une batterie au moins fonctionne, et la **charge complète** suit la batterie qui la demande le plus souvent.

C'est exact pour des batteries branchées au même endroit.

Dans une maison en **triphasé** (voir [Votre maison et ses règles](your-home.md#maisons-en-triphasé)), une case demande si **la batterie compense le total des trois phases** (elle suit un compteur triphasé) ou seulement sa phase. Une batterie qui ne compense que sa phase charge sur le surplus de cette phase et ne couvre que son déficit : un lave-linge sur la phase 1 n'est pas couvert par une batterie de la phase 2. Le plan la calcule ainsi quand :

- la **phase** de la batterie est renseignée dans sa fiche, et la case est décochée ;
- la **consommation de chaque phase** est mesurée (un capteur de soutirage par phase sur le raccordement au réseau, et la phase de chaque installation solaire et de chaque batterie).

Les batteries d'une même phase sont vues comme une seule, avec leur propre contenu ; celles qui compensent le total passent après elles. Sinon, toutes les batteries sont calculées sur le total de la maison, comme avant.

Le **Planning des équipements** a alors une ligne par phase (« Batterie phase 2 », « Batterie phase 3 »), chacune avec ses propres charges et décharges, prévues et mesurées, et une ligne « Batterie (total) » pour les batteries qui compensent le total. Les courbes montrent toujours toutes vos batteries ensemble. Au-delà d'aujourd'hui, le plan ne connaît que leur contenu total et le répartit entre elles selon leur capacité.

## Ce que vous voyez

- **Aujourd'hui** : la charge maintenant, son point le plus haut et son niveau à minuit. Avec plusieurs batteries, la charge de la maison est leur moyenne, pondérée par la capacité, et chaque batterie est listée dessous avec sa propre charge, son contenu et ce qu'elle fait en ce moment. Le pourcentage est le dernier relevé ; les puissances sont des moyennes sur le dernier quart d'heure.
- **Planning** : une carte **Batteries** liste chaque batterie de la même façon quand il y en a plusieurs ; la charge prévue (en pointillés) face à la charge mesurée, la ligne du plancher, et la charge et la décharge de la batterie dans le Planning des équipements.
- **Batterie pleine avant midi** ([notification](notifications.md)) : le surplus suivant partirait sur le réseau, bon moment pour lancer un appareil.

## Bon à savoir

- WattSlot **recommande** seulement. Piloter la batterie (ralentir sa charge le matin pour qu'elle ne soit pas pleine avant le pic solaire, la charger en heures creuses) est prévu dans une version suivante, équipement par équipement.
- Le comportement réel de la batterie est mesuré : s'il diffère des réglages (une puissance plus faible, un autre plancher), la courbe mesurée le montre.
