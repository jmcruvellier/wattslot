# Changelog

## 0.9.7

### English

This release fixes a security issue in the standalone Docker mode, reported privately by a contributor, and makes WattSlot sturdier: the plan is always calculated, no more gaps in the data after a restart, and no more occasional errors on busy installations. **As a Home Assistant app, there is nothing to do.** In standalone mode, read the first section before updating.

- **Security (standalone Docker mode)**
  - WattSlot now only answers when opened by an IP address, a name without a dot (`http://nas:8100`) or a local name (`.local`, `.lan`, `.home.arpa`, `.internal`). **Behind a reverse proxy or with your own domain name, add it to the new `WATTSLOT_ALLOWED_HOSTS` variable**, otherwise WattSlot refuses the request; the log says which name to add.
  - Changes sent by another web page are refused.
  - Chatting with Home Assistant's conversation agents from the Assistant screen is now off by default, because Assist can control your devices and standalone mode has no login. Set `WATTSLOT_HOME_ASSISTANT_CHAT=true` to turn it back on. Open WebUI models stay available.
  - WattSlot now runs as its own user (`wattslot`, 1000) instead of root. At the first start after the update, it hands its data volume over to that user, once (a few seconds). With a host folder instead of a named volume, its owner becomes 1000: set `WATTSLOT_UID` and `WATTSLOT_GID` to keep your own user. A token file (`HA_TOKEN_FILE`) must be readable by that user. `WATTSLOT_RUN_AS_ROOT=true` keeps the old behaviour.
  - The saved Open WebUI key is no longer sent when the address is changed to another server: you type it again (this also applies to the app).

- **A plan that is always calculated**
  - A battery floor that rises during the day (for example 50 % in the evening) no longer prevents the plan from being calculated.
  - A minimum duration that no longer fits in the day (a first calculation late in the evening) gives a warning instead of no plan.
  - Negative electricity prices, or a resale price above the purchase price, no longer break the plan.
  - When the calculation runs out of time without a solution, the previous plan stays in place instead of a meaningless one.

- **Reliable data**
  - No more hours at 0 kWh followed by a spike after a restart or a Home Assistant outage: WattSlot waits for the history to be filled before adding things up.
  - The last increment of a meter, at the end of an appliance's cycle, is counted within a minute instead of possibly hours later.
  - Occasional errors on busy installations ("not enough values to unpack" in the log, a missed hourly calculation) are gone: each part of the app now has its own connection to the database.
  - Data is written to disk on shutdown even when Home Assistant does not answer, and a database update interrupted by a power cut no longer prevents the next start.
  - With a long retention of raw readings (up to 30 days), reading and cleaning old days no longer conflict.

- **Times at the home's time**
  - "Remind me" reminders now arrive at the home's time, not two hours late in summer.
  - The interface shows every time at the home's time, even when you open it from abroad.

- **Interface**
  - An error message in the title bar disappears after the next success, and a missed refresh of Today keeps the view on screen with a short notice.
  - "14h60" is gone, and numbers follow the language of the interface.
  - Starting a new conversation in the Assistant while an answer is on its way no longer brings that answer back.

- **Installation**
  - On a virtual machine whose processor type hides some instructions (Proxmox with the `kvm64` type), the log now explains what to change instead of showing a Python error. See the new troubleshooting section.

- **Under the hood**
  - Dependencies updated (Python 3.12.15, Node 22.23.3, React, FastAPI…), and the build workflows hardened.

### Français

Cette version corrige un problème de sécurité du mode Docker autonome, signalé en privé par un contributeur, et rend WattSlot plus solide : le plan est toujours calculé, plus de trou dans les données après un redémarrage, et plus d'erreur occasionnelle sur les installations chargées. **Comme application de Home Assistant, il n'y a rien à faire.** En mode autonome, lisez la première rubrique avant de mettre à jour.

- **Sécurité (mode Docker autonome)**
  - WattSlot ne répond plus qu'ouvert par une adresse IP, un nom sans point (`http://nas:8100`) ou un nom local (`.local`, `.lan`, `.home.arpa`, `.internal`). **Derrière un proxy inverse ou avec votre propre nom de domaine, ajoutez-le à la nouvelle variable `WATTSLOT_ALLOWED_HOSTS`**, sinon WattSlot refuse la requête ; le journal indique le nom à ajouter.
  - Les modifications envoyées par une autre page web sont refusées.
  - La discussion avec les agents de conversation de Home Assistant depuis l'écran Assistant est désormais désactivée par défaut : Assist peut commander vos appareils, et le mode autonome n'a pas de connexion. Définissez `WATTSLOT_HOME_ASSISTANT_CHAT=true` pour la réactiver. Les modèles d'Open WebUI restent disponibles.
  - WattSlot tourne maintenant sous son propre utilisateur (`wattslot`, 1000) plutôt qu'en root. Au premier démarrage après la mise à jour, il lui donne son volume de données, une fois (quelques secondes). Avec un dossier de l'hôte au lieu d'un volume nommé, son propriétaire devient 1000 : définissez `WATTSLOT_UID` et `WATTSLOT_GID` pour garder votre propre utilisateur. Un fichier de jeton (`HA_TOKEN_FILE`) doit être lisible par cet utilisateur. `WATTSLOT_RUN_AS_ROOT=true` garde l'ancien fonctionnement.
  - La clé d'Open WebUI enregistrée n'est plus envoyée quand l'adresse change vers un autre serveur : il faut la ressaisir (vaut aussi pour l'application).

- **Un plan toujours calculé**
  - Un plancher de batterie qui monte dans la journée (50 % le soir, par exemple) n'empêche plus le calcul du plan.
  - Une durée minimale qui ne tient plus dans la journée (premier calcul tard le soir) donne un avertissement au lieu d'aucun plan.
  - Des prix de l'électricité négatifs, ou une revente plus chère que l'achat, ne cassent plus le plan.
  - Quand le calcul manque de temps sans trouver de solution, le plan précédent reste en place au lieu d'un plan sans valeur.

- **Des données fiables**
  - Plus d'heures à 0 kWh suivies d'un pic après un redémarrage ou une coupure de Home Assistant : WattSlot attend que l'historique soit comblé avant de faire les totaux.
  - Le dernier incrément d'un compteur, à la fin du cycle d'un appareil, est compté dans la minute, et non parfois des heures plus tard.
  - Les erreurs occasionnelles sur les installations chargées (« not enough values to unpack » dans le journal, un calcul horaire manqué) ont disparu : chaque partie de l'application a maintenant sa propre connexion à la base.
  - Les données sont écrites sur le disque à l'arrêt même quand Home Assistant ne répond pas, et une mise à jour de la base interrompue par une coupure de courant n'empêche plus le démarrage suivant.
  - Avec une longue conservation des relevés bruts (jusqu'à 30 jours), la lecture et le nettoyage des anciens jours ne se gênent plus.

- **Les heures à l'heure de la maison**
  - Les rappels « Me le rappeler » arrivent à l'heure de la maison, et non avec deux heures de retard en été.
  - L'interface affiche toutes les heures à l'heure de la maison, même ouverte depuis l'étranger.

- **Interface**
  - Un message d'erreur dans la barre de titre disparaît au succès suivant, et un rafraîchissement manqué d'Aujourd'hui garde la vue à l'écran avec un petit mot.
  - Fini les « 14h60 », et les nombres suivent la langue de l'interface.
  - Lancer une nouvelle conversation dans l'Assistant pendant qu'une réponse arrive ne fait plus revenir cette réponse.

- **Installation**
  - Sur une machine virtuelle dont le type de processeur cache certaines instructions (Proxmox avec le type `kvm64`), le journal explique désormais quoi changer au lieu d'afficher une erreur Python. Voir la nouvelle rubrique de dépannage.

- **Sous le capot**
  - Dépendances à jour (Python 3.12.15, Node 22.23.3, React, FastAPI…), et chaîne de publication renforcée.

## 0.9.6

### English

A new notification sends you the week's plan on the day you choose, and the plan now follows the real sky and the real battery during the day. The assistant went through nearly 2,900 test questions on 16 local model setups, to make its answers as reliable as possible and find the best model for a small installation: Qwen3 4B Instruct, which got every question of the test suite right on a small, low-power AI computer. The Settings have also been redone page by page, and the app now has Home Assistant's highest security rating.

- **Weekly plan notification** (new, requested by a user)
  - A sixth notification lists the appliances planned for the coming days, one line per day, for example "Saturday: washing machine 11 am – 1 pm".
  - You choose the day or days and the time it is sent (Sunday from 6 pm by default). Quiet hours and the choice of phone work as for the other notifications.
  - A day with nothing planned says so, and the test message shows the plan day by day, just as on your phone.

- **A plan closer to reality**
  - When the day turns out cloudier than forecast, the plan follows the solar production actually measured, instead of counting on sunshine that isn't coming. The dotted forecast curve follows too.
  - The battery is no longer shown charging or discharging when it can't: the current hour starts from its real level, and the tiny "0.0 kWh" blocks are gone.
  - Once an appliance has started, its explanation keeps the reasons its slot was chosen (solar surplus, off-peak hours, deadline…), instead of just "started at 9:59".
  - Charts › Week: the forecast production tooltip no longer shows a confusing "surplus", which was often negative.

- **Assistant**
  - Before filing a request ("run the dishwasher before tomorrow evening"), the assistant now always asks you to confirm.
  - Answers read better: full sentences, one figure for each thing (the day's cost, the battery level in %), no technical codes.
  - It finds the right information more easily: today's cost, the next appliance to start, why an appliance runs at a given time.
  - With an Open WebUI model, the Assistant page now really reads your plan, instead of answering that it hasn't been calculated yet.
  - For a small setup, the recommended local model is Qwen3 4B Instruct: fast, and right on every question of the test suite.

- **App status**
  - Sensors that are simply idle (a plug at 0 W, an appliance switched off) are no longer flagged as "silent". Only a reading frozen in a suspicious way is.
  - The page opens with a summary ("Nothing to report" or the number of problems by severity) and shows the three most important problems first. The others unfold with one click.

- **Settings and My home, redesigned**
  - Every Settings page now has the same clear layout: sections with titles, one line per setting with a short help, and a status card at the top. This covers the voice assistant, notifications, language and display, app status, automatic calculation and the Home Assistant connection.
  - Each notification's options fit on one line and unfold when you want to change them. The Save button is at the bottom of the page.
  - The Assistant page now holds only the conversation, over the full height of the screen. The step-by-step setup of Assist moved to Settings › Voice assistant.
  - My home › Data opens with a status card ("Your data is healthy" or the number of corrected values). Long lists of corrections are folded, and "Analyse a period" is right at hand.
  - Duplicate links are gone, and every page is comfortable on a phone, without scrolling sideways.

- **Security**
  - WattSlot now runs under its own protection profile (AppArmor): it can only touch its own files. Home Assistant gives it its highest security rating, 8 out of 8.
  - The documentation explains why WattSlot needs access to Home Assistant and what it does with it: it reads, sends your notifications, and never changes anything.
  - From this version on, every release is digitally signed, so anyone can check that it really comes from WattSlot.

### Français

Une nouvelle notification vous envoie le planning de la semaine le jour de votre choix, et le plan suit désormais le vrai ciel et la vraie batterie au fil de la journée. L'assistant a été soumis à près de 2 900 questions de test sur 16 configurations de modèles locaux, pour rendre ses réponses aussi fiables que possible et trouver le meilleur modèle pour une petite installation : Qwen3 4B Instruct, qui a répondu juste à toutes les questions de la suite de test sur un petit ordinateur d'IA basse consommation. Les Réglages ont aussi été refaits page par page, et l'application obtient la meilleure note de sécurité de Home Assistant.

- **Notification « Planning de la semaine »** (nouveau, demandé par un utilisateur)
  - Une sixième notification liste les appareils prévus pour les jours à venir, une ligne par jour, par exemple « Samedi : lave-linge 11 h – 13 h ».
  - Vous choisissez le ou les jours et l'heure d'envoi (le dimanche à partir de 18 h par défaut). Les heures de silence et le choix du téléphone fonctionnent comme pour les autres notifications.
  - Un jour sans rien de prévu le dit, et le message d'essai montre le planning jour par jour, comme sur votre téléphone.

- **Un plan plus proche de la réalité**
  - Quand la journée est plus nuageuse que prévu, le plan suit la production solaire réellement mesurée au lieu de compter sur un soleil qui ne vient pas. La courbe pointillée de prévision suit aussi.
  - La batterie n'est plus montrée en train de se charger ou de se décharger quand elle ne le peut pas : l'heure en cours part de son niveau réel, et les petits blocs « 0,0 kWh » ont disparu.
  - Une fois un appareil lancé, son explication garde les raisons du choix de son créneau (surplus solaire, heures creuses, échéance…), au lieu d'un simple « lancé à 9 h 59 ».
  - Courbes › Semaine : l'info-bulle de la production prévue n'affiche plus un « surplus » déroutant, souvent négatif.

- **Assistant**
  - Avant de déposer une demande (« lance le lave-vaisselle avant demain soir »), l'assistant vous demande désormais toujours de confirmer.
  - Les réponses se lisent mieux : des phrases complètes, un seul chiffre pour chaque chose (le coût de la journée, la batterie en %), plus aucun code technique.
  - Il trouve plus facilement la bonne information : le coût du jour, le prochain appareil à lancer, la raison de l'heure choisie pour un appareil.
  - Avec un modèle d'Open WebUI, la page Assistant lit vraiment votre plan au lieu de répondre qu'il n'est pas encore calculé.
  - Pour une petite installation, le modèle local conseillé est Qwen3 4B Instruct : rapide, et juste sur toutes les questions de la suite de test.

- **État de l'application**
  - Les capteurs simplement au repos (une prise à 0 W, un appareil éteint) ne sont plus signalés comme « muets ». Seul un relevé figé de façon suspecte l'est encore.
  - La page s'ouvre sur un résumé (« Rien à signaler » ou le nombre de problèmes par gravité) et montre d'abord les trois problèmes les plus importants. Les autres se déplient d'un clic.

- **Réglages et Ma maison, refaits**
  - Toutes les pages des Réglages ont maintenant la même présentation claire : des sections titrées, une ligne par réglage avec une courte aide, et une carte d'état en tête. Cela concerne l'assistant vocal, les notifications, la langue et l'affichage, l'état de l'application, le calcul automatique et la connexion à Home Assistant.
  - Les options de chaque notification tiennent sur une ligne et se déplient pour les régler. Le bouton Enregistrer est en bas de page.
  - La page Assistant ne contient plus que la discussion, sur toute la hauteur de l'écran. Le pas à pas pour brancher Assist passe dans Réglages › Assistant vocal.
  - Ma maison › Données s'ouvre sur une carte d'état (« Vos données sont saines » ou le nombre de valeurs corrigées). Les longues listes de corrections sont repliées, et « Analyser une période » est à portée de main.
  - Les liens en double ont disparu, et chaque page est confortable sur téléphone, sans défilement de côté.

- **Sécurité**
  - WattSlot tourne désormais sous son propre profil de protection (AppArmor) : il ne peut toucher qu'à ses propres fichiers. Home Assistant lui donne sa meilleure note de sécurité, 8 sur 8.
  - La documentation explique pourquoi WattSlot a besoin d'accéder à Home Assistant et ce qu'il en fait : il lit, envoie vos notifications et ne modifie jamais rien.
  - À partir de cette version, chaque version publiée est signée numériquement : chacun peut vérifier qu'elle vient bien de WattSlot.

## 0.9.5

### English

The day charts now read like clockwork, from midnight to midnight — and meters, planning and the Home Assistant connection shrug off restarts.

- **Day charts** (Today / Yesterday / Tomorrow)
  - The time axis runs from midnight to midnight on every graph, so the last hour of the day (11 pm – midnight) is finally visible instead of being cut off.
  - Each graph is drawn the way its data deserves: production and consumption as steps filling each whole hour, the grid as bars with a line through them, and the battery level as points placed at the exact moment they describe (the point at 11 pm is the level at midnight).
  - Tooltips show the real time of each point — "9:22 pm" for a reading taken at 9:22, not just the round hour — along with its time slot ("9 pm – 10 pm").
  - The ongoing hour now has two points: the forecast at the end of the hour and the live reading in the middle, so the battery or production curve no longer jumps to midnight or stops early.
  - All points are sorted and the whole day is covered from 0 h to 24 h: no more missing hour in the middle of a curve, and the measured curve ends exactly on the latest reading instead of one point before it.

- **Meters and data quality**
  - When Home Assistant restarts, a meter can briefly report a wrong (higher) index; this phantom reading is now cancelled like a dropout, so it no longer creates a huge spike or a several-hour gap in your real curves.
  - A counter jump that is physically impossible — more energy in one step than your installation could ever deliver — is ignored, no matter how long the wrong value lasts; when the real index comes back, it is counted as a normal difference.
  - Automatic corrections ("discard this reading") are re-checked against the raw measurement as long as it exists: if the value turns out plausible after all, the correction lifts by itself and the charts fill in again within about 15 minutes. Manual corrections are never touched.

- **Planning**
  - "Starts after" now also works for tasks scheduled on a specific day, not just today's: tomorrow's dryer set to run after the washer is now really placed after it, instead of sometimes before.
  - If you pick another start time for an appliance whose planned slot has already passed but never started, the appliance now really moves to the new time in the recalculated plan — previously the old slot stayed frozen and the new calculation changed nothing.

- **Home Assistant connection**
  - If WattSlot reconnects while Home Assistant is still starting up, it re-reads the states of all your entities a little later (about one minute, then five minutes after connecting), so "sensor not found" problems in the application status clear by themselves once Home Assistant is fully up.
  - "Check again" now really re-reads the states even when the connection already shows as active — before, it did nothing in that state and only restarting the app fixed the problem.

- **Project**
  - Daily download statistics of the app are now collected automatically every day (a small script queries the GitHub API and a scheduled workflow stores the result), so the team can see how many installations use each version.

### Français

Les courbes du jour se lisent désormais comme une horloge, de minuit à minuit — et compteurs, planning et connexion à Home Assistant encaissent les redémarrages sans accroc.

- **Courbes du jour** (Aujourd'hui / Hier / Demain)
  - L'axe du temps va désormais de minuit à minuit sur chaque graphe : la dernière heure de la journée (23 h – minuit) est enfin visible au lieu d'être coupée.
  - Chaque graphe est tracé selon la nature de ses données : production et consommation en paliers remplissant chaque heure entière, réseau en barres traversées par une ligne, niveau de batterie en points placés à l'instant exact qu'ils décrivent (le point de 23 h est le niveau à minuit).
  - Les info-bulles indiquent l'heure réelle de chaque point — « 21 h 22 » pour un relevé pris à 21 h 22, pas seulement l'heure ronde — avec sa tranche (« 21 h – 22 h »).
  - La tranche en cours comporte désormais deux points : la prévision à la fin de l'heure et le relevé en direct au milieu ; la courbe de batterie ou de production ne saute donc plus jusqu'à minuit et ne s'arrête plus en avance.
  - Tous les points sont triés et toute la journée est couverte de 0 h à 24 h : plus d'heure manquante au milieu d'une courbe, et la courbe mesurée s'arrête exactement sur le dernier relevé au lieu de s'arrêter un point avant.

- **Compteurs et qualité des données**
  - Au redémarrage de Home Assistant, un compteur peut rapporter brièvement un index erroné (plus haut) ; ce relevé fantôme est désormais annulé comme une coupure : plus de pic géant ni de trou de plusieurs heures dans vos courbes réelles.
  - Un saut de compteur physiquement impossible — plus d'énergie en un seul pas que votre installation ne pourrait jamais en délivrer — est ignoré, quelle que soit la durée de la mauvaise valeur ; quand l'index réel revient, il est compté comme un écart normal.
  - Les corrections automatiques (« écarter cette mesure ») sont revérifiées contre la mesure brute tant qu'elle existe : si la valeur s'avère finalement plausible, la correction se lève toute seule et les courbes se remplissent à nouveau en environ 15 minutes. Les corrections manuelles ne sont jamais touchées.

- **Planning**
  - « Démarre après » fonctionne aussi pour les tâches prévues à un jour précis, pas seulement pour aujourd'hui : le sèche-linge de demain réglé « après le lave-linge » est désormais réellement placé après, et non parfois avant.
  - Si vous choisissez une autre heure de départ pour un appareil dont le créneau prévu est déjà passé mais ne s'est pas lancé, l'appareil est réellement déplacé à la nouvelle heure dans le plan recalculé — auparavant l'ancien créneau restait figé et le nouveau calcul ne changeait rien.

- **Connexion à Home Assistant**
  - Si WattSlot se reconnecte pendant que Home Assistant démarre encore, il relit un peu plus tard les états de toutes vos entités (environ une minute, puis cinq minutes après la connexion) : les problèmes « capteur introuvable » affichés dans l'état de l'application disparaissent donc d'eux-mêmes une fois Home Assistant complètement démarré.
  - « Vérifier à nouveau » relit réellement les états même quand la connexion est déjà active — auparavant, il ne faisait rien dans cet état et seul un redémarrage de l'application réglait le problème.

- **Projet**
  - Des statistiques de téléchargement quotidiennes de l'application sont désormais collectées automatiquement chaque jour (un petit script interroge l'API GitHub et un workflow planifié enregistre le résultat), pour voir combien d'installations utilisent chaque version.

## 0.9.4

WattSlot speaks more precisely, and the graph of your home becomes an explorer.

- **Assistant**: it now answers questions about cost, the next appliance to start, your tariff and your requests. The time it took to answer is shown.
- **Tariff**: time-of-use price bands can start and end at the exact minute (off-peak from 10:30 pm, for instance); prices are weighed by the minute, a band's end always follows its start in the day, and the minute is shown right next to the hour.
- **Graph of your home**: a whole new graph to explore your home — a global view of everything at once, double-click to enter an element and **Back** to come out, full screen, and a search to find an element. Many readability fixes: no more overlapping objects, views centered on first display, a lower zoom floor, a clearer properties panel.
- **Day timeline**: the other possible starts of an appliance appear right on the day's timeline; a planned appliance can be cancelled from the timeline or from **Next action**; an appliance already running no longer opens a choice sheet.
- **My home**: a device's sensor can be replaced from its sheet; the sensor list fits in the sheet and the unit is shown next to it.
- **Data quality**: a corrected impossible reading now fills the gap in the charts, the corrected value replaces the wrong one, and the message about a discarded reading follows the range you are viewing.
- **Today**: the trend is now a pill you can read at a glance, shown at the top of the Battery and Sun cards.
- **Charts**: legend settings moved under a **Customize** icon in the title bar; **Compute** and **Refresh real data** became icons in the title bar, with the age of the last calculation staying stable.
- **Fixes**: the measured production is 0 kWh after sunset; the connection to Home Assistant is repaired after its restart; **Other starts** is readable in all themes.

## 0.9.3

WattSlot now adapts to your home: no talk of the sun without panels, nor of a battery without one.

- Without solar panels, the weather, production, surplus and self-consumption disappear from every screen; without a battery, everything about the battery too. Use **Read Home Assistant again** in **My home › Devices** if you add them later.
- No appliance to place yet (none in the Energy dashboard): Today and the first steps invite you to add one.
- Provisional plan: while WattSlot is still importing your Home Assistant history, the plan says so; its figures become accurate at the first calculation after the import.
- First steps: the status shows "Getting started" instead of a red "calculation blocked"; it refreshes when you change screen and after a calculation. Templates are named after your contract (single price, off-peak hours, Tempo, dynamic price).
- Detection: a power setting (an inverter's limit, for instance) is no longer taken for a measured power; the grid and an unnamed battery get a name in your Home Assistant language; a missing sensor is reported once.

## 0.9.2

Fixes found while installing the beta on a fresh Home Assistant.

- First steps: when something required is missing before the first plan (a solar forecast, for instance), the last step says what and opens the right setting, instead of "All set" and a calculation that silently did nothing. A calculation that fails is now reported.
- Standalone (Docker): the Home Assistant address given in `HA_URL` is filled in on the connection page.

## 0.9.1

Public beta for testers: clearer screens, data you can trust, and an easy way to give feedback.

- Beta: a "Beta" badge, a **Give feedback** button at the bottom of Settings (a ready-made form on GitHub), and a **Support WattSlot** card (GitHub Sponsors, Ko-fi).
- New **Charts** section: the figures and charts of the plan, moved out of Planning. The week is a table with one row per day.
- **My home** in four tabs (Essentials, Devices, Data, Advanced), one setting per sheet, and a complete sheet for each device.
- **Data quality**: WattSlot checks your meters, corrects impossible readings (a sensor dropout counted as a reset) and lets you choose another correction or undo it. One wrong reading no longer hides the others in the charts. The original data is never changed.
- **Other possible starts**: up to three other starts proposed by the plan, with their effect on the cost; choose one, or go back to the calculation's choice.
- Planning: **My requests** under the plan; Compute and Refresh next to the tabs; plan indicators for the whole day.
- **Assistant**: chat with Home Assistant's assistant (or Open WebUI) from the app, with the conversation kept; the internal address of the MCP server is remembered and can be changed.
- Your contract: subscription and subscribed power; the currency of your prices, shown everywhere.
- Week: where the horizon stops is explained, and missing days are shown.
- Fixes: a clear message when the expected consumption is impossible; the forecast production axis of the week starts at 0; no more tiny negative values or duplicated hours; no more occasional "Unable to read the plan".
- New README and user guide in English and French, with new screenshots.

## 0.9.0

Public beta, under the new name WattSlot.

- New name, icon and logo: WattSlot is a new app in Home Assistant (`wattslot`), installed from a public repository without any token.
- Homes without solar panels: off-peak, day colour or dynamic tariffs work on their own, without solar forecast.
- New version notice in Settings and Application status.
- Planning of appliances: taller tracks without legend, planned above and measured below, energy written in each block.
- History import writes about 5 times less to disk.
- Solver retries once differently when it wrongly reports a plan as impossible; the "battery full" bonus only breaks ties.
- Fixes: first-step "Notification" check, today's real data right after the update, start times of today's real cycles, hour axis of daily charts, stale warning of an appliance already placed in today's plan.
- The old v1 dashboard is removed.
- User documentation in English and French, links to support the project.

## 0.8.0

Home Assistant app quality: updates, backups and options.

- Updates from the app store: the app is published on its own branch, only once its image is online, so Home Assistant offers "Update" for each new version.
- Hot backups: before Home Assistant copies the app's folder, the app freezes a consistent copy of its database and graph; only that copy is backed up, and it is put back in place after a restore. Raw readings are left out (kept 3 days, rebuilt from Home Assistant's history).
- Options, in English and French: log level, how long raw readings (1 to 30 days) and quarter-hour data (31 to 3660 days) are kept.
- Clean stop: 30 seconds to write pending data before stopping; watched by the image's health check, so Home Assistant's watchdog restarts the app if it stops answering.
- Icon, logo and updated documentation.

## 0.7.0

First version planned for everyday use (development phases 0 to 6 bis).

- Reads your home from Home Assistant's Energy dashboard: solar production, grid, battery and appliances; history imported from Home Assistant's statistics.
- Daily plan and seven-day horizon: when to start each appliance, when to charge and discharge the battery, around solar forecast and electricity prices (single, off-peak, day colour or dynamic).
- Your home, your rules: appliance behaviours, time constraints, recurrences, battery settings, objective (cost, self-consumption, grid, CO₂), ready-made templates, backup and sharing.
- New interface: Today, Planning (agenda and detailed charts), My home in plain sentences, Assistant, Settings; guided first steps; five themes with automatic light and dark; six languages (German, Dutch, Spanish and Italian to be reviewed).
- Requests from the app or Home Assistant's Assist, reminders, configurable notifications.
- MCP server for Home Assistant's Assist (`/mcp`).
- Application status: problems explained in plain words, anonymised report.

## 0.0.1

- First development build: application state and connection to Home Assistant.
