# Capteurs dans Home Assistant (expérimental)

*[English version](../sensors.md) · [Guide d'utilisation](README.md)*

WattSlot peut écrire certaines de ses prévisions dans des capteurs de Home Assistant, pour que vos tableaux de bord, vos automatisations ou une autre intégration les lisent. C'est **expérimental** et **désactivé par défaut** : les capteurs et leur format peuvent encore changer.

## Prévision de consommation de la maison

Activez **Réglages › Calcul et données › Capteurs dans Home Assistant › Publier la prévision de consommation de la maison**. Rien d'autre à installer : WattSlot se sert de la connexion qu'il a déjà, comme application de Home Assistant ou avec Docker.

Trois capteurs apparaissent dans Home Assistant, en kWh :

| Capteur | Valeur |
|---|---|
| `sensor.wattslot_home_consumption_forecast_remaining_today` | Consommation prévue de la maison de maintenant à minuit |
| `sensor.wattslot_home_consumption_forecast_today` | Consommation prévue de la journée entière |
| `sensor.wattslot_home_consumption_forecast_tomorrow` | Consommation prévue de demain |

Ce sont les nombres de la courbe de consommation des écrans **Aujourd'hui** et **Planning** : la consommation habituelle de votre maison à chaque heure (le même jour de la semaine d'abord), plus les appareils que le plan a placés. La batterie n'en fait pas partie.

Chaque capteur porte aussi deux attributs : `forecast_date` (le jour de la prévision) et `computed_at` (l'heure du dernier calcul du plan).

## Quand ils sont mis à jour

- après chaque calcul du plan (chaque heure par défaut) ;
- tous les quarts d'heure, parce que le reste de la journée diminue avec l'heure ;
- à chaque reconnexion de WattSlot à Home Assistant.

Un capteur est **indisponible** quand WattSlot n'a pas encore de plan pour ce jour : avant le premier calcul, ou juste après minuit jusqu'au calcul suivant. Une intégration qui le lit doit alors revenir à sa propre estimation.

## Bon à savoir

- **Pas d'historique propre.** Une prévision n'est pas une mesure : les capteurs n'ont pas de `state_class`, Home Assistant n'en garde donc pas de statistiques à long terme. Leurs états récents restent dans l'historique comme ceux de tout capteur.
- **Ni appareil ni réglage dans Home Assistant.** Ces capteurs sont écrits par l'API de Home Assistant : ils n'ont pas d'identifiant unique, on ne peut donc ni les renommer, ni les masquer, ni les ranger dans une pièce depuis l'interface de Home Assistant.
- **Après un redémarrage de Home Assistant**, ils disparaissent un instant, puis reviennent quand WattSlot se reconnecte, en général en moins d'une minute.
- **Désactiver le réglage** les retire de Home Assistant.
- **Compte administrateur.** Avec Docker, le compte utilisé pour la connexion à Home Assistant doit être administrateur : Home Assistant ne laisse écrire des états qu'aux administrateurs. Sinon le réglage indique que Home Assistant refuse l'écriture.
- WattSlot ne propose jamais ses propres capteurs quand vous choisissez les capteurs de votre maison : il ne relit pas ce qu'il publie.

## Exemple : une carte de tableau de bord

```yaml
type: entities
title: Prévision de consommation de la maison
entities:
  - sensor.wattslot_home_consumption_forecast_remaining_today
  - sensor.wattslot_home_consumption_forecast_today
  - sensor.wattslot_home_consumption_forecast_tomorrow
```

Dites-nous ce que vous faites de ces capteurs, et lesquels vous aimeriez encore (prochain appareil à lancer, coût prévu de la journée…) : [donnez votre avis](https://github.com/jmcruvellier/wattslot/issues/new?template=beta_feedback.yml).
