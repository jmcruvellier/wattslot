# Notifications et rappels

*[English version](../notifications.md) · [Guide d'utilisation](README.md)*

WattSlot envoie ses messages par Home Assistant, vers un appareil qui a l'**application compagnon de Home Assistant** (un service `notify.mobile_app_…`). Rien n'est envoyé tant que vous n'avez pas choisi un appareil ; seules les alertes des ressources sont activées par défaut, les autres notifications sont à activer. Les réglages sont dans **Réglages › Notifications**.

## Où les envoyer

- **Appareil commun** : utilisé par toutes les notifications qui n'ont pas leur propre appareil.
- **Appareil**, sur chaque notification : pour envoyer, par exemple, la recommandation du jour sur un téléphone et « lancez maintenant » sur un autre.
- **Autre service de notification** : tout autre service `notify.*` de Home Assistant.
- **Langue du message** : l'une des six langues de l'application.
- **Envoyer un essai** vérifie chaque notification tout de suite.

## Les sept notifications

| Notification | Quand |
|---|---|
| **Recommandation du jour** | Le plan du jour : équipements, batterie, piscine, bilan et avertissements. **Rythme** : seulement quand le plan change (par défaut : ce qu'il y a à faire, comme le départ d'un équipement, une plage de fonctionnement ou un avertissement, pas ses chiffres), à chaque calcul, ou une fois par jour à partir d'une heure donnée |
| **Planning de la semaine** | Les appareils prévus pour les jours à venir, une ligne par jour (« Samedi 17 Octobre : Lave-linge 11h–13h »). **Jours et heure d'envoi** : un ou plusieurs jours de la semaine, à partir d'une heure donnée (le dimanche à partir de 18h par défaut) |
| **« Lancez X maintenant »** | Le cycle prévu d'un équipement va démarrer et il n'est pas encore lancé. Envoyée au dernier calcul automatique avant le départ ; à plus de dix minutes, le message dit l'heure au lieu de « maintenant » |
| **Écart au plan** | Un cycle prévu n'a pas démarré 30 minutes après son heure, ou la production solaire s'écarte de plus de 25 % de la prévision |
| **Batterie pleine avant midi** | Le plan prévoit la batterie pleine avant midi : bon moment pour lancer un appareil, le surplus suivant partirait sur le réseau |
| **Prévision de demain en baisse** | La production prévue pour demain baisse de plus de 30 % par rapport à la prévision la plus haute vue jusque-là |
| **Alertes des ressources** | Le disque des données est presque plein, WattSlot utilise beaucoup de mémoire, ou un calcul du plan est très long (voir [Dépannage](troubleshooting.md)). Une fois par jour pour chaque alerte tant qu'elle dure. **Activées par défaut** : désactivez-les ici |

**Heures de silence**, sur chaque notification : rien n'est envoyé entre deux heures (la nuit, par exemple).

Une notification envoyée « à partir d'une heure » part avec le premier calcul automatique après cette heure (les calculs ont lieu chaque heure, à la minute choisie dans **Réglages › Calcul automatique**). Le planning de la semaine est une prévision : au-delà de deux ou trois jours, il suit une prévision météo encore incertaine, et le plan est recalculé chaque heure. « Lancez X maintenant » et les rappels suivent le plan du moment.

## Rappels

Sur **Aujourd'hui**, sous le prochain appareil à lancer, **Me le rappeler** envoie une notification au début de son créneau. Elle part sur l'appareil de **« Lancez X maintenant »**, ou sur l'appareil commun.

## Des demandes depuis Home Assistant

Dans l'autre sens, une tâche d'une **liste de tâches** de Home Assistant (« lancer le lave-linge », avec une échéance) devient une demande : choisissez la liste dans **Réglages › Calcul automatique**. L'[assistant vocal](assistant.md) peut aussi déposer des demandes.
