# Premiers pas

*[English version](../getting-started.md) · [Guide d'utilisation](README.md)*

À la première ouverture de WattSlot, un parcours guidé en quatre écrans remplace l'accueil jusqu'à ce que les étapes indispensables soient faites. Tout reste modifiable ensuite.

## Les quatre premiers écrans

1. **Reliez l'application à Home Assistant.** Comme application de Home Assistant, il n'y a rien à faire. En mode autonome, saisissez l'adresse de votre Home Assistant et connectez-vous (voir [Installation](installation.md#en-mode-autonome-docker)).
2. **Voici ce que nous avons trouvé chez vous.** WattSlot lit le tableau Énergie de Home Assistant et propose vos équipements : production solaire, réseau, batterie, chauffe-eau, lave-linge, sèche-linge, lave-vaisselle, pompe de piscine… Décochez ce qui ne doit pas être pris en compte. Un équipement absent du tableau Énergie (une prise connectée, une pompe à chaleur) s'ajoute plus tard dans **Ma maison › Appareils et capteurs › Ajouter un équipement**.
3. **Quel est votre contrat d'électricité ?** Choisissez le modèle le plus proche : tarif, batterie et appareils sont réglés d'un coup, avec des prix indicatifs à remplacer par les vôtres (voir [Tarifs](tariffs.md)).

   | Modèle | Pour |
   |---|---|
   | Solaire, tarif unique | Le même prix toute la journée |
   | Solaire, heures creuses | Des heures moins chères la nuit (indicatif : de minuit à 6 h et de 22 h à minuit) |
   | Solaire, Tempo | Contrat Tempo d'EDF, couleur du jour lue dans Home Assistant |
   | Solaire, prix dynamique | Prix horaires du marché lus dans une entité de Home Assistant |

4. **Tout est prêt.** Cliquez sur **Calculer mon premier plan**. WattSlot recalcule ensuite chaque heure, tout seul.

**Voir toutes les étapes** affiche la liste complète à tout moment ; elle reste aussi sur l'écran Aujourd'hui, repliée, tant qu'une étape facultative reste à faire.

## La liste complète

| Étape | Indispensable | Ce qu'il faut |
|---|---|---|
| Connexion à Home Assistant | oui | Home Assistant joignable |
| Tableau Énergie de Home Assistant | oui | Votre compteur, et votre production solaire s'il y en a une, déclarés dans Paramètres › Tableaux de bord › Énergie |
| Votre maison | oui | Les équipements proposés vérifiés et enregistrés |
| Prévision solaire | oui, avec des panneaux | Une prévision dans le tableau Énergie (Forecast.Solar, Solcast, Open-Meteo…), ou vos panneaux décrits dans **Ma maison** (puissance, inclinaison, orientation) : WattSlot en calcule alors une avec Open-Meteo |
| Historique de consommation | | Rien à faire : repris de Home Assistant tout seul |
| Premier plan | oui | Les étapes ci-dessus |
| Modèle prêt à l'emploi | | Facultatif, règle tout d'un coup |
| Tarif de l'électricité | | Sinon, un prix unique de 0,25 €/kWh est supposé |
| Batterie | | Réglages par défaut tant que vous ne les ajustez pas |
| Notification | | Un appareil pour recevoir les messages, voir [Notifications](notifications.md) |

## La reprise de l'historique

Pour prévoir votre consommation et apprendre combien de temps tourne chaque appareil, WattSlot reprend l'historique que Home Assistant garde déjà (ses **statistiques**) : les valeurs horaires aussi loin qu'elles remontent, et les valeurs à 5 minutes des derniers jours.

- Elle démarre toute seule une fois votre maison enregistrée, compteur après compteur. La liste indique **Reprise de l'historique de Home Assistant en cours (N compteur(s) restant(s)) : rien à faire**.
- Elle prend de quelques minutes à plus d'une heure sur un Raspberry Pi, selon la profondeur de votre historique et le nombre de compteurs.
- Pendant ce temps, le plan fonctionne déjà ; les jours passés se remplissent au fil de la reprise.
- Un capteur sans statistiques dans Home Assistant (sans `state_class`) est signalé dans **Réglages › État de l'application** : le plan part alors de ses seules mesures en direct.

## Après le premier plan

- **Aujourd'hui** vous dit ce qui se passe maintenant et le prochain appareil à lancer.
- **Planning** montre le plan heure par heure, comparé à ce qui a été mesuré.
- Ajustez vos règles dans **Ma maison** : voir [Votre maison et ses règles](your-home.md).
