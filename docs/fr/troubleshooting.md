# Dépannage et questions fréquentes

*[English version](../troubleshooting.md) · [Guide d'utilisation](README.md)*

## Commencez par l'état de l'application

**Réglages › État de l'application** (ou la pastille d'état du menu) liste ce qui ne va pas, par gravité : **Bloque le plan**, **Plan moins juste**, **À surveiller**. Chaque problème dit quoi faire et a un lien **Y aller**. **Vérifier à nouveau** relance les vérifications.

La section **Ressources** montre le processeur (moyenne sur 15 minutes et pic, en part d'un cœur), la mémoire (avec son pic, et la limite du conteneur ou la mémoire de la machine), l'espace occupé du disque qui porte les données de l'application, et la taille de ces données (mesurée toutes les 10 minutes). Chaque ligne se déplie sur sa courbe des dernières 24 heures, un point par minute, gardée après un redémarrage ; survolez-la pour lire une valeur. Une ligne rouge en pointillés marque le seuil d'alerte : l'alerte part quand la courbe passe au-dessus. Pour le disque, c'est la première atteinte de ses deux alertes (disque presque plein, place pour une sauvegarde) ; sur la courbe des données, c'est la taille que les données pourraient atteindre avant cette alerte, si rien d'autre ne remplissait le disque. Le processeur n'en a pas encore. La limite mémoire est celle du conteneur quand il en fixe une ; sinon, c'est la mémoire de la machine, partagée avec tout ce qui y tourne. Un résumé horaire de ces ressources est aussi gardé 30 jours, et les 7 derniers jours vont dans le rapport ci-dessous.

| Problème | Que faire |
|---|---|
| L'application ne connaît pas l'adresse de Home Assistant | Comme application : redémarrez-la. En mode autonome : réglez l'adresse et connectez-vous (**Réglages › Connexion à Home Assistant**) |
| Home Assistant ne répond pas | Vérifiez que Home Assistant tourne, et que le jeton d'accès est toujours valable (mode autonome) |
| Le tableau Énergie n'est pas configuré | Déclarez votre compteur, et votre production solaire s'il y en a une, dans Home Assistant : Paramètres › Tableaux de bord › Énergie |
| Votre maison n'est pas encore enregistrée | **Ma maison** : vérifiez les équipements proposés, puis enregistrez |
| Aucune prévision solaire | Ajoutez une prévision au tableau Énergie (Forecast.Solar, Solcast, Open-Meteo…), ou décrivez vos panneaux dans **Ma maison** |
| Un capteur n'existe plus / est indisponible / n'a rien envoyé depuis un jour | Remplacez-le dans **Ma maison**, ou vérifiez l'appareil et son intégration dans Home Assistant |
| Pas d'historique dans Home Assistant pour certains capteurs | Ils n'ont pas de statistiques (pas de `state_class`) : le plan part de leurs seules mesures en direct |
| Aucun plan n'a pu être calculé depuis plus de 2 heures | Regardez les autres problèmes, ou **Calculer** depuis la barre de titre d'**Aujourd'hui**, **Planning** ou **Courbes** |
| Peu d'espace libre sur le disque des données (moins de 20 % du disque, entre 2 et 20 Go), ou pas assez pour une sauvegarde (deux fois la taille de la base et du magasin principal) | Libérez de la place sur ce disque ; en module complémentaire, vous pouvez aussi raccourcir la conservation des mesures dans ses options |
| WattSlot utilise beaucoup de mémoire depuis 15 minutes (75 % de la limite de son conteneur, ou 1 Go sans limite de conteneur) | Si cela dure, redémarrez l'application et joignez le rapport à un signalement |
| Le dernier calcul du plan a pris 10 minutes ou plus | Si cela dure, joignez le rapport à un signalement |

Ces alertes des ressources partent aussi en notification, une fois par jour tant qu'elles durent ; désactivez-les dans **Réglages › Notifications › Messages**.

## L'application ne démarre pas : « NumPy was built with baseline optimizations (X86_V2) »

Le journal se termine par `RuntimeError: NumPy was built with baseline optimizations: (X86_V2) but your machine doesn't support: (X86_V2)`, ou par un message de WattSlot sur les instructions **x86-64-v2**.

Le processeur que voit Home Assistant ne déclare pas les instructions dont le moteur du calcul de WattSlot a besoin. Presque tous les PC des quinze dernières années les ont, mais une **machine virtuelle** peut les cacher : sous Proxmox, c'est le cas des types de CPU `kvm64` et `qemu64`.

Sous Proxmox :

1. Sélectionnez la machine virtuelle de Home Assistant.
2. Ouvrez **Matériel**, puis double-cliquez sur **Processeurs**.
3. Mettez **Type** sur **host** (ou **x86-64-v2-AES** si vous déplacez la machine virtuelle entre des serveurs différents).
4. Cliquez sur **OK**.
5. **Arrêtez** complètement la machine virtuelle (un redémarrage depuis Home Assistant ne suffit pas), puis relancez-la.
6. Relancez l'application WattSlot.

Les autres hyperviseurs ont le même réglage (par exemple *host-passthrough* avec libvirt / virt-manager). Il profite aussi à Home Assistant et aux autres applications.

## Signaler un problème

1. **Réglages › État de l'application › Préparer un rapport** : un fichier qui décrit l'état de l'application, **sans nom d'équipement, ni identifiant de capteur, ni position**. L'aperçu montre tout ce qu'il contient.
2. **Télécharger**, puis joignez-le à un [signalement](https://github.com/jmcruvellier/wattslot/issues/new/choose), avec la version et ce qui s'est passé.
3. Comme application de Home Assistant, le journal est dans **Paramètres › Applications › WattSlot › Journal** ; réglez l'option **Niveau des journaux** sur `debug` si on vous le demande.

## Questions fréquentes

**Le plan ne lance aucun appareil aujourd'hui.** Un cycle n'est placé que quand quelque chose le demande : une demande, une tâche de votre liste de tâches de Home Assistant, ou une récurrence (voir [Votre maison et ses règles](your-home.md#quand-un-cycle-est-dû)). Vérifiez aussi que l'équipement est **Pris en compte par le calcul**.

**Le plan change dans la journée.** Il est recalculé chaque heure avec les dernières mesures et la dernière prévision : une matinée plus nuageuse décale un appareil vers l'après-midi. Quand les panneaux produisent moins (ou plus) que prévu depuis le matin, le reste de la prévision du jour suit le même rapport : le plan ne compte plus sur un soleil qui ne vient pas. Les appareils déjà lancés sont gardés.

**Les valeurs mesurées sont vides pour les premières heures.** Sur une nouvelle installation, les mesures du jour commencent au démarrage de WattSlot ; la reprise de l'historique remplit les jours passés. Les données mesurées sont rafraîchies tous les quarts d'heure, ou avec **Rafraîchir les données réelles**.

**La production prévue est loin de ce que j'ai mesuré.** Une prévision est meilleure par une intégration du tableau Énergie (Solcast, Forecast.Solar) que par des panneaux décrits. La notification **Écart au plan** vous prévient quand l'écart dépasse 25 %.

**La batterie ne se comporte pas comme le plan.** WattSlot simule la batterie ; vérifiez ses réglages (plancher, puissances maximales), voir [Batterie](battery.md).

**Un compteur a compté des milliers de kWh en une heure.** Son capteur est sans doute tombé à zéro un instant. WattSlot ne compte plus une coupure brève comme une remise à zéro, et corrige les heures déjà touchées : voir **Ma maison › Données**.

**WattSlot peut-il lancer mes appareils lui-même ?** Pas encore : cette version recommande seulement. Le pilotage des appareils, avec votre confirmation d'abord, puis automatique, équipement par équipement, viendra dans une version suivante.

**Est-ce que ça marche sans panneaux solaires ?** Oui : avec des heures creuses, des jours de couleur ou des prix dynamiques, il place vos appareils aux heures les moins chères ([Tarifs](tariffs.md)).

**Combien écrit-il sur le disque ?** Quelques Go par jour au plus en usage normal ; la première reprise de l'historique écrit davantage, une seule fois. Prenez un SSD plutôt qu'une carte SD.

**Comment donner mon avis sur la bêta ?** Avec **Donner mon avis**, en bas des **Réglages**, ou directement avec le [formulaire de retour de bêta](https://github.com/jmcruvellier/wattslot/issues/new?template=beta_feedback.yml) : ce qui marche, ce qui gêne, ce que vous n'avez pas compris. En français ou en anglais.

**Où poser une question ?** Dans les [Discussions](https://github.com/jmcruvellier/wattslot/discussions) ; pour un bogue, ouvrez un [ticket GitHub](https://github.com/jmcruvellier/wattslot/issues/new/choose).
