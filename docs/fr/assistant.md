# Assistant vocal

*[English version](../assistant.md) · [Guide d'utilisation](README.md)*

Posez vos questions sur votre énergie à l'**Assist** de Home Assistant (*« Pourquoi le lave-linge est-il prévu à 11 h ? »*, *« Combien les panneaux ont-ils produit hier ? »*, *« La batterie sera-t-elle pleine aujourd'hui ? »*) avec le modèle de langage que vous utilisez déjà : un modèle local sur votre réseau (Ollama, par exemple) ou un service en ligne. WattSlot fournit les réponses par un **serveur MCP** ; le plan, lui, est toujours calculé sans modèle de langage.

L'écran **Assistant** vous guide pas à pas et vérifie le branchement.

## 1. Brancher WattSlot dans Home Assistant

Dans Home Assistant : **Paramètres › Appareils et services › Ajouter une intégration › Model Context Protocol**, avec l'adresse indiquée sur l'écran **Assistant** (**Copier l'adresse du serveur MCP**) :

- **Comme application de Home Assistant** : une adresse sur le réseau interne de Home Assistant, que seul Home Assistant peut joindre.
- **En mode autonome** : `http://<adresse de WattSlot>:8100/mcp`, son adresse sur votre réseau local : seuls Home Assistant (et Open WebUI) appellent le serveur MCP, jamais votre navigateur. WattSlot la retient la première fois que vous ouvrez la page depuis votre réseau local, et l'affiche ensuite même depuis l'extérieur ; **Modifier** la corrige.

## 2. Choisir l'agent de conversation

1. Ajoutez un agent de conversation : l'intégration **Ollama** (un modèle sur votre réseau) ou celle d'un service en ligne.
2. Choisissez un modèle qui sait **appeler des outils**, avec une taille de contexte d'au moins **8 192 tokens**.
3. Dans les options de l'agent, choisissez le serveur MCP de WattSlot comme **API LLM**, puis prenez cet agent dans l'Assist.

## 3. Coller le prompt conseillé

**Copier le prompt** sur l'écran Assistant, puis collez-le dans les instructions de l'agent de conversation : il dit au modèle quel outil utiliser pour chaque question et de ne rien inventer. Il existe dans les six langues de l'application.

**Vérifier** confirme que le serveur MCP répond.

Quand une mise à jour de WattSlot apporte de nouveaux outils, copiez à nouveau le prompt et remplacez celui de l'agent : un ancien prompt ne les cite pas.

## Exemples de questions

La carte de discussion de l'écran **Assistant** propose des questions, par thème, tant que la conversation est vide ; un clic en met une dans la zone de saisie, où vous pouvez la modifier (un autre appareil, un autre jour) avant de l'envoyer.

| Thème | Questions | Ce qui répond |
|---|---|---|
| Aujourd'hui | *Que dois-je faire aujourd'hui ?* · *Quel est le prochain appareil à lancer ?* · *Pourquoi le lave-linge est-il prévu à 11 h ?* · *Qu'est-ce qui alimente la maison en ce moment ?* · *Combien va me coûter la journée ?* | le plan du jour, son coût et le prochain appareil, avec ses autres heures de départ possibles ; les mesures du moment |
| Demain et la semaine | *Combien les panneaux produiront-ils demain ?* · *Quel jour de la semaine sera le plus ensoleillé ?* · *Quand sont les heures creuses demain ?* | la prévision, les jours suivants, le tarif (prix heure par heure, heures creuses, couleur du jour) |
| Mesures | *Combien les panneaux ont-ils produit hier ?* · *Le lave-vaisselle a-t-il démarré à l'heure ?* | l'énergie mesurée d'un jour, par appareil ; ce qu'a fait chaque appareil par rapport au plan |
| Demandes et état | *Lance le lave-vaisselle au meilleur moment avant demain soir.* · *Quelles sont mes demandes en cours ?* · *Est-ce que quelque chose ne va pas ?* | les demandes (comme dans **Mes demandes**), les problèmes de l'application |

## Ce que l'assistant peut faire, et ne fait pas

- **Il lit** : le plan d'un jour, son coût et ses explications, la semaine, les mesures, la prévision, le tarif, vos demandes, votre maison et ses problèmes.
- **Il fait une seule chose de lui-même** : déposer une demande (*« Lance le lave-vaisselle au meilleur moment avant demain soir »*), après vous l'avoir confirmée.
- **Il ne fait jamais** de calcul, ne change aucun réglage et ne pilote aucun appareil.

## Conseils

- Les petits modèles locaux répondent bien avec le prompt conseillé ; si les réponses dérapent, vérifiez que le prompt est collé et que la taille de contexte est suffisante.
- **Sécurité** : l'intégration MCP de Home Assistant n'a pas d'autre connexion qu'OAuth, que WattSlot ne propose pas. Le serveur MCP est donc protégé comme l'application elle-même : seul Home Assistant peut le joindre comme application ; réseau local seulement en mode autonome.
