# Bêta publique : tri des retours et réponses types

Ce document sert au mainteneur pendant la bêta (0.9.x). Les testeurs écrivent par trois portes :

- le **formulaire « Beta feedback »** (`.github/ISSUE_TEMPLATE/beta_feedback.yml`), ouvert par « Donner mon avis » en bas des Réglages et depuis le README ; il pose l'étiquette `beta` ;
- les **Discussions**, catégorie **Beta** (formulaire `.github/DISCUSSION_TEMPLATE/beta.yml`), pour les questions et les échanges ;
- les modèles habituels (bogue, idée, traduction).

## Étiquettes

| Étiquette | Usage |
|---|---|
| `beta` | Retour d'un testeur (posée par le formulaire) |
| `bug`, `enhancement`, `translation`, `documentation`, `accessibility` | La nature du ticket, une seule |
| `area: install`, `area: plan`, `area: data`, `area: tariffs`, `area: interface`, `area: assistant` | La partie de l'application concernée, une ou deux |
| `needs info` | En attente de précisions du testeur |
| `confirmed` | Reproduit ou compris : à corriger ou à faire |
| `duplicate`, `wontfix`, `invalid`, `question` | Clôture |
| `good first issue`, `help wanted` | Ouvert aux contributions |

## Tri, deux fois par semaine

1. **Nouveaux tickets `beta`** : remercier (réponse 1), poser la nature et la partie. Un retour qui mêle plusieurs sujets : un ticket par sujet, liés entre eux.
2. **Il manque quelque chose** (version, mode, rapport anonymisé) : réponse 2, étiquette `needs info`.
3. **Compris ou reproduit** : `confirmed`, et le ticket rejoint le projet « WattSlot roadmap ». Un bogue qui empêche le calcul ou l'installation passe avant tout le reste.
4. **Ce n'est pas un défaut** : limite connue (réponse 4), doublon (réponse 5), idée pour plus tard (réponse 6).
5. **Corrigé** : réponse 7 quand la version qui le corrige est publiée, puis clôture.
6. **`needs info` sans nouvelles depuis 14 jours** : réponse 8, clôture ; le testeur peut rouvrir.

Chaque semaine, un court bilan dans la catégorie **Announcements** : ce qui a été corrigé, ce qui arrive, merci aux testeurs.

## Réponses types

On répond dans la langue du testeur. Pour les enregistrer dans GitHub : avatar › **Settings** › **Saved replies** › titre et texte, puis **Add saved reply** ; elles s'insèrent ensuite avec l'icône de flèche de la zone de commentaire (ou `Ctrl` + `.`).

### 1. Merci

> **FR** — Merci d'avoir testé WattSlot et pris le temps d'écrire ! Je regarde ça et je reviens vers vous ici.
>
> **EN** — Thanks for testing WattSlot and taking the time to write! I'll look into it and get back to you here.

### 2. Il manque des précisions

> **FR** — Merci ! Pour comprendre ce qui se passe, il me manque : la version de WattSlot (Réglages › État de l'application), le mode d'installation (application de Home Assistant ou Docker), et si possible le rapport anonymisé (Réglages › État de l'application › Préparer un rapport, à joindre ici). Il ne contient ni nom d'appareil, ni identifiant de capteur, ni position.
>
> **EN** — Thanks! To understand what happens, I need: your WattSlot version (Settings › App status), the installation mode (Home Assistant app or Docker), and if possible the anonymised report (Settings › App status › Prepare a report, attached here). It contains no device name, sensor ID or location.

### 3. Confirmé

> **FR** — Je le reproduis, merci ! C'est noté pour une prochaine version ; je préviendrai ici quand ce sera corrigé.
>
> **EN** — I can reproduce it, thanks! It's planned for an upcoming version; I'll let you know here when it's fixed.

### 4. Limite connue

> **FR** — Merci pour ce retour. Pendant la bêta, WattSlot recommande seulement : il ne lance pas les appareils et ne pilote pas la batterie. C'est vous qui lancez, ou qui écrivez une automatisation à partir de ses recommandations. Le pilotage, avec votre confirmation, viendra dans une version suivante.
>
> **EN** — Thanks for the feedback. During the beta, WattSlot only recommends: it doesn't start appliances or control the battery. You start them, or build an automation from its recommendations. Control, with your confirmation, will come in a later version.

### 5. Doublon

> **FR** — Merci ! Le même sujet est suivi dans #NUMÉRO : je ferme celui-ci pour garder la discussion au même endroit. N'hésitez pas à y ajouter vos précisions.
>
> **EN** — Thanks! The same topic is tracked in #NUMBER: I'm closing this one to keep the discussion in one place. Feel free to add your details there.

### 6. Idée pour plus tard

> **FR** — Bonne idée, merci ! Elle n'entre pas dans la bêta, mais je la garde dans la feuille de route. Si d'autres testeurs la veulent aussi, un 👍 sur ce ticket aide à choisir les priorités.
>
> **EN** — Good idea, thanks! It won't make it into the beta, but I'm keeping it on the roadmap. If other testers want it too, a 👍 on this issue helps set priorities.

### 7. Corrigé

> **FR** — C'est corrigé dans la version VERSION, disponible maintenant (mise à jour depuis Home Assistant, ou `docker compose pull`). Pouvez-vous me dire si c'est bon chez vous ? Merci encore pour le signalement.
>
> **EN** — Fixed in version VERSION, available now (update from Home Assistant, or `docker compose pull`). Could you tell me if it works for you? Thanks again for the report.

### 8. Clôture sans nouvelles

> **FR** — Je ferme ce ticket faute de nouvelles depuis deux semaines. Il suffit de répondre ici pour le rouvrir si le problème revient.
>
> **EN** — Closing this issue as there has been no reply for two weeks. Just reply here to reopen it if the problem comes back.

### 9. Merci pour la traduction

> **FR** — Merci beaucoup pour cette relecture ! Je l'intègre dans la prochaine version et je vous cite dans le journal des versions, si vous êtes d'accord.
>
> **EN** — Thank you so much for proofreading! I'll include it in the next version and credit you in the changelog, if you agree.
