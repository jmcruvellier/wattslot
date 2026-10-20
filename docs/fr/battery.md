# Batterie

*[English version](../battery.md) · [Guide d'utilisation](README.md)*

WattSlot ne pilote pas votre batterie : il simule son comportement (elle charge tout surplus et se décharge sur tout déficit, comme la plupart des batteries domestiques en autoconsommation) pour placer vos appareils là où ils sont le plus utiles. Plusieurs batteries sont vues comme une seule. Les réglages sont dans **Ma maison › L'essentiel › Batterie**.

## Réglages

| Réglage | Par défaut | Rôle |
|---|---|---|
| **Ne jamais décharger en dessous de** | 10 % | Le plancher : une réserve pour la nuit ou une coupure |
| **Plancher plus haut sur certaines plages** | aucun | Une réserve plus haute à certaines heures, par exemple 30 % de 18 h à 22 h |
| **Puissance de charge maximale** / **de décharge maximale** | de quoi charger ou vider la moitié de la batterie en une heure | Les limites de votre batterie, sur sa fiche technique |
| **La batterie charge et décharge de … à …** | toute la journée | Pour les batteries qui ne fonctionnent qu'à certaines heures |
| **Viser régulièrement une charge complète**, au moins tous les N jours | non | Les batteries au lithium recalent leur mesure de charge quand elles atteignent 100 % : le plan garde alors assez de surplus pour cela, et peut sauter quelques heures de piscine ces jours-là |

La capacité vient de Home Assistant quand un capteur la donne, sinon de sa fiche dans **Ma maison › Appareils** (**Capteurs, nom et type**).

## Ce que vous voyez

- **Aujourd'hui** : la charge maintenant, son point le plus haut et son niveau à minuit.
- **Planning** : la charge prévue (en pointillés) face à la charge mesurée, la ligne du plancher, et la charge et la décharge de la batterie dans le Planning des équipements.
- **Batterie pleine avant midi** ([notification](notifications.md)) : le surplus suivant partirait sur le réseau, bon moment pour lancer un appareil.

## Bon à savoir

- WattSlot **recommande** seulement. Piloter la batterie (ralentir sa charge le matin pour qu'elle ne soit pas pleine avant le pic solaire, la charger en heures creuses) est prévu dans une version suivante, équipement par équipement.
- Le comportement réel de la batterie est mesuré : s'il diffère des réglages (une puissance plus faible, un autre plancher), la courbe mesurée le montre.
