# Dépannage et questions fréquentes

*[English version](../troubleshooting.md) · [Guide d'utilisation](README.md)*

## Commencez par l'état de l'application

**Réglages › État de l'application** (ou la pastille d'état du menu) liste ce qui ne va pas, par gravité : **Bloque le plan**, **Plan moins juste**, **À surveiller**. Chaque problème dit quoi faire et a un lien **Y aller**. **Vérifier à nouveau** relance les vérifications.

| Problème | Que faire |
|---|---|
| L'application ne connaît pas l'adresse de Home Assistant | Comme application : redémarrez-la. En mode autonome : réglez l'adresse et connectez-vous (**Réglages › Connexion à Home Assistant**) |
| Home Assistant ne répond pas | Vérifiez que Home Assistant tourne, et que le jeton d'accès est toujours valable (mode autonome) |
| Le tableau Énergie n'est pas configuré | Déclarez votre compteur, et votre production solaire s'il y en a une, dans Home Assistant : Paramètres › Tableaux de bord › Énergie |
| Votre maison n'est pas encore enregistrée | **Ma maison** : vérifiez les équipements proposés, puis enregistrez |
| Aucune prévision solaire | Ajoutez une prévision au tableau Énergie (Forecast.Solar, Solcast, Open-Meteo…), ou décrivez vos panneaux dans **Ma maison** |
| Un capteur n'existe plus / est indisponible / n'a rien envoyé depuis un jour | Remplacez-le dans **Ma maison**, ou vérifiez l'appareil et son intégration dans Home Assistant |
| Pas d'historique dans Home Assistant pour certains capteurs | Ils n'ont pas de statistiques (pas de `state_class`) : le plan part de leurs seules mesures en direct |
| Aucun plan n'a pu être calculé depuis plus de 2 heures | Regardez les autres problèmes, ou **Calculer** depuis **Planning** |

## Signaler un problème

1. **Réglages › État de l'application › Préparer un rapport** : un fichier qui décrit l'état de l'application, **sans nom d'équipement, ni identifiant de capteur, ni position**. L'aperçu montre tout ce qu'il contient.
2. **Télécharger**, puis joignez-le à un [signalement](https://github.com/jmcruvellier/wattslot/issues/new/choose), avec la version et ce qui s'est passé.
3. Comme application de Home Assistant, le journal est dans **Paramètres › Applications › WattSlot › Journal** ; réglez l'option **Niveau des journaux** sur `debug` si on vous le demande.

## Questions fréquentes

**Le plan ne lance aucun appareil aujourd'hui.** Un cycle n'est placé que quand quelque chose le demande : une demande, une tâche de votre liste de tâches de Home Assistant, ou une récurrence (voir [Votre maison et ses règles](your-home.md#quand-un-cycle-est-dû)). Vérifiez aussi que l'équipement est **Pris en compte par le calcul**.

**Le plan change dans la journée.** Il est recalculé chaque heure avec les dernières mesures et la dernière prévision : une matinée plus nuageuse décale un appareil vers l'après-midi. Les appareils déjà lancés sont gardés.

**Les valeurs mesurées sont vides pour les premières heures.** Sur une nouvelle installation, les mesures du jour commencent au démarrage de WattSlot ; la reprise de l'historique remplit les jours passés. Les données mesurées sont rafraîchies tous les quarts d'heure, ou avec **Rafraîchir les données réelles**.

**La production prévue est loin de ce que j'ai mesuré.** Une prévision est meilleure par une intégration du tableau Énergie (Solcast, Forecast.Solar) que par des panneaux décrits. La notification **Écart au plan** vous prévient quand l'écart dépasse 25 %.

**La batterie ne se comporte pas comme le plan.** WattSlot simule la batterie ; vérifiez ses réglages (plancher, puissances maximales), voir [Batterie](battery.md).

**WattSlot peut-il lancer mes appareils lui-même ?** Pas encore : cette version recommande seulement. Le pilotage des appareils, avec votre confirmation d'abord, puis automatique, équipement par équipement, viendra dans une version suivante.

**Est-ce que ça marche sans panneaux solaires ?** Oui : avec des heures creuses, des jours de couleur ou des prix dynamiques, il place vos appareils aux heures les moins chères ([Tarifs](tariffs.md)).

**Combien écrit-il sur le disque ?** Quelques Go par jour au plus en usage normal ; la première reprise de l'historique écrit davantage, une seule fois. Prenez un SSD plutôt qu'une carte SD.

**Où poser une question ?** Dans les [Discussions](https://github.com/jmcruvellier/wattslot/discussions) ; pour un bogue, ouvrez un [ticket GitHub](https://github.com/jmcruvellier/wattslot/issues/new/choose).
