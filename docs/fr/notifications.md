# Notifications et rappels

*[English version](../notifications.md) · [Guide d'utilisation](README.md)*

WattSlot envoie ses messages par Home Assistant, vers un appareil qui a l'**application compagnon de Home Assistant** (un service `notify.mobile_app_…`). Rien n'est envoyé tant que vous n'avez pas choisi un appareil et activé une notification. Les réglages sont dans **Réglages › Notifications**.

## Où les envoyer

- **Appareil commun** : utilisé par toutes les notifications qui n'ont pas leur propre appareil.
- **Appareil**, sur chaque notification : pour envoyer, par exemple, la recommandation du jour sur un téléphone et « lancez maintenant » sur un autre.
- **Autre service de notification** : tout autre service `notify.*` de Home Assistant.
- **Langue du message** : l'une des six langues de l'application.
- **Envoyer un essai** vérifie chaque notification tout de suite.

## Les cinq notifications

| Notification | Quand |
|---|---|
| **Recommandation du jour** | Le plan du jour : équipements, batterie, piscine, bilan et avertissements. **Rythme** : à chaque calcul, seulement quand le plan change, ou une fois par jour à partir d'une heure donnée |
| **« Lancez X maintenant »** | Le cycle prévu d'un équipement démarre dans l'heure et il n'est pas encore lancé |
| **Écart au plan** | Un cycle prévu n'a pas démarré 30 minutes après son heure, ou la production solaire s'écarte de plus de 25 % de la prévision |
| **Batterie pleine avant midi** | Le plan prévoit la batterie pleine avant midi : bon moment pour lancer un appareil, le surplus suivant partirait sur le réseau |
| **Prévision de demain en baisse** | La production prévue pour demain baisse de plus de 30 % par rapport à la prévision la plus haute vue jusque-là |

**Heures de silence**, sur chaque notification : rien n'est envoyé entre deux heures (la nuit, par exemple).

## Rappels

Sur **Aujourd'hui**, sous le prochain appareil à lancer, **Me le rappeler** envoie une notification au début de son créneau. Elle part sur l'appareil de **« Lancez X maintenant »**, ou sur l'appareil commun.

## Des demandes depuis Home Assistant

Dans l'autre sens, une tâche d'une **liste de tâches** de Home Assistant (« lancer le lave-linge », avec une échéance) devient une demande : choisissez la liste dans **Réglages › Calcul automatique**. L'[assistant vocal](assistant.md) peut aussi déposer des demandes.
