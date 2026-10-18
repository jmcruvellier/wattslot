# Assistant vocal

*[English version](../assistant.md) · [Guide d'utilisation](README.md)*

Posez vos questions sur votre énergie à l'**Assist** de Home Assistant (*« Pourquoi le lave-linge est-il prévu à 11 h ? »*, *« Combien les panneaux ont-ils produit hier ? »*, *« La batterie sera-t-elle pleine aujourd'hui ? »*) avec le modèle de langage que vous utilisez déjà : un modèle local sur votre réseau (Ollama, par exemple) ou un service en ligne. WattSlot fournit les réponses par un **serveur MCP** ; le plan, lui, est toujours calculé sans modèle de langage.

L'écran **Assistant** vous guide pas à pas et vérifie le branchement.

## 1. Brancher WattSlot dans Home Assistant

Dans Home Assistant : **Paramètres › Appareils et services › Ajouter une intégration › Model Context Protocol**, avec l'adresse indiquée sur l'écran **Assistant** (**Copier l'adresse du serveur MCP**) :

- **Comme application de Home Assistant** : une adresse sur le réseau interne de Home Assistant, que seul Home Assistant peut joindre.
- **En mode autonome** : `http://<adresse de WattSlot>:8100/mcp`. Home Assistant doit pouvoir la joindre ; gardez-la sur votre réseau local.

## 2. Choisir l'agent de conversation

1. Ajoutez un agent de conversation : l'intégration **Ollama** (un modèle sur votre réseau) ou celle d'un service en ligne.
2. Choisissez un modèle qui sait **appeler des outils**, avec une taille de contexte d'au moins **8 192 tokens**.
3. Dans les options de l'agent, choisissez le serveur MCP de WattSlot comme **API LLM**, puis prenez cet agent dans l'Assist.

## 3. Coller le prompt conseillé

**Copier le prompt** sur l'écran Assistant, puis collez-le dans les instructions de l'agent de conversation : il dit au modèle quel outil utiliser pour chaque question et de ne rien inventer. Il existe dans les six langues de l'application.

**Vérifier** confirme que le serveur MCP répond.

## Ce que l'assistant peut faire, et ne fait pas

- **Il lit** : le plan d'un jour et ses explications, la semaine, les mesures, la prévision, votre maison et ses problèmes.
- **Il fait une seule chose de lui-même** : déposer une demande (*« Lance le lave-vaisselle au meilleur moment avant demain soir »*), après vous l'avoir confirmée.
- **Il ne fait jamais** de calcul, ne change aucun réglage et ne pilote aucun appareil.

## Conseils

- Les petits modèles locaux répondent bien avec le prompt conseillé ; si les réponses dérapent, vérifiez que le prompt est collé et que la taille de contexte est suffisante.
- **Sécurité** : l'intégration MCP de Home Assistant n'a pas d'autre connexion qu'OAuth, que WattSlot ne propose pas. Le serveur MCP est donc protégé comme l'application elle-même : seul Home Assistant peut le joindre comme application ; réseau local seulement en mode autonome.
