# LeBonDeal Bot — bot Discord multi-sites (Vinted / LeBonCoin / Kleinanzeigen)

Bot Discord qui surveille automatiquement des recherches Vinted, LeBonCoin et Kleinanzeigen
via l'API LeBonDeal, et envoie les nouvelles annonces en salon et/ou en DM. Toute la
configuration se fait avec des commandes slash, et `/dashboard` donne une vue d'ensemble
avec des boutons d'action rapide.

## Fonctionnalités

- **Détection automatique du site** : colle n'importe quel lien vinted.fr, leboncoin.fr ou
  kleinanzeigen.de dans `/filtre ajouter`, le bot devine tout seul quelle API appeler.
- **Ciblage flexible** : chaque filtre peut avoir son propre salon, être envoyé en DM, ou
  utiliser un **salon unifié** commun à tous les filtres (`/parametres salon_unifie`).
- **Activer / désactiver / relancer / supprimer** filtre par filtre ou en masse (tous les
  filtres, ou tous ceux d'un site donné).
- **Vitesse de scan** configurable en secondes/minutes/heures, par filtre.
- **Heures creuses** : coupe automatiquement un filtre entre 2 horaires (`/filtre heures_creuses`).
- **Plafond de crédits** global (`/parametres credits_max`) et par filtre
  (`/filtre credits_max`) — le scan s'arrête tout seul une fois le plafond atteint.
- **Anti-doublon** : ne renvoie jamais deux fois la même annonce (mémorisée en base).
- **Filtrage prix min/max** et **mots-clés à inclure/exclure** côté bot, en plus des
  filtres déjà appliqués dans l'URL.
- **Ping de rôle** configurable par filtre.
- **Style d'affichage** compact ou détaillé par filtre.
- **Salon de logs** avec alerte automatique quand le solde de crédits passe sous un seuil.
- **Pause globale** (`/parametres pause`) pour tout couper d'un coup sans supprimer la config.
- Respecte automatiquement les limites de débit documentées par l'API (30 req/min par clé,
  1 req/10s pour LeBonCoin, 60 req/60s pour Kleinanzeigen) grâce à un limiteur intégré,
  avec un léger jitter aléatoire sur chaque intervalle pour éviter les pics.

> ℹ️ L'API ne fournit pas d'endpoint dédié pour consulter le solde de crédits en dehors
> d'une recherche : `/credits` et le dashboard affichent donc le dernier solde `credits_remaining`
> observé lors de la dernière recherche effectuée par n'importe quel filtre.

## Commandes

### `/filtre`
`ajouter`, `supprimer`, `supprimer_tout`, `activer`, `desactiver`, `activer_tout`,
`desactiver_tout`, `relancer`, `relancer_tout`, `intervalle`, `salon`, `dm`,
`heures_creuses`, `prix`, `motscles`, `role`, `style`, `dedoublonnage`, `credits_max`, `liste`

### `/parametres`
`credits_max`, `reset_consommation`, `salon_unifie`, `salon_logs`, `alerte_credits`,
`intervalle_defaut`, `pause`

### Autres
`/dashboard` — tableau de bord interactif (boutons + menu déroulant)
`/credits` — dernier solde de crédits connu

## Installation locale

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # puis remplis DISCORD_TOKEN et LEBONDEAL_API_KEY
python main.py
```

## Déploiement sur Pterodactyl

1. Crée un serveur avec l'**egg "Generic Python"** (ou un egg Python 3.11+ équivalent).
2. Upload tout le contenu de ce dossier dans `/home/container` (ou clone ton repo GitHub
   directement depuis l'onglet "Startup" si l'egg le permet).
3. **Startup command** :
   ```
   pip install -r requirements.txt && python main.py
   ```
4. Dans l'onglet **Startup / Variables**, ajoute les variables d'environnement suivantes
   (elles doivent correspondre aux clés de `.env.example`) :
   - `DISCORD_TOKEN`
   - `LEBONDEAL_API_KEY`
   - `API_BASE_URL` (valeur par défaut : `https://bot.lebondeal-bot.fr`)
   - `DB_PATH` (laisser `data/bot.db`)
   - `OWNER_IDS` (facultatif)
   - `GUILD_ID` (facultatif, pour tester avec une synchro instantanée des commandes)
5. Démarre le serveur. Les commandes slash apparaissent en quelques secondes si `GUILD_ID`
   est renseigné, sinon jusqu'à 1h en synchro globale.
6. Sur Discord, invite le bot avec les scopes `bot` + `applications.commands`, avec au
   minimum les permissions "Envoyer des messages", "Intégrer des liens" et "Utiliser les
   commandes d'application".

## Structure du projet

```
lebondeal-bot/
├── main.py            # point d'entrée, chargement des cogs, sync des commandes
├── config.py           # variables d'environnement + limites API
├── database.py          # SQLite (filtres, réglages, dédoublonnage, crédits)
├── api_client.py         # appels HTTP vers l'API LeBonDeal + normalisation des réponses
├── site_detect.py        # détection du site à partir de l'URL collée
├── ratelimiter.py        # limiteur de débit (global + par site)
├── scheduler.py          # boucle asyncio par filtre (scan, dédoublonnage, envoi)
├── embeds.py            # construction des embeds Discord
├── cogs/
│   ├── filters.py        # commandes /filtre
│   ├── settings.py        # commandes /parametres + /credits
│   └── dashboard.py       # commande /dashboard (embed + boutons + menu)
├── requirements.txt
├── .env.example
└── data/                # base SQLite créée automatiquement au démarrage
```

## Notes importantes

- Chaque appel API a un coût réel (crédits). Configure des plafonds (`credits_max`) avant
  de lancer beaucoup de filtres en parallèle pour éviter les mauvaises surprises.
- La base SQLite (`data/bot.db`) contient toute la config des filtres et l'historique
  anti-doublon : sauvegarde ce fichier si tu changes de serveur Pterodactyl.
- `intervalle` très courts (quelques secondes) combinés à beaucoup de filtres actifs seront
  automatiquement ralentis par le limiteur de débit pour respecter les plafonds de l'API —
  ce n'est pas un bug, c'est voulu pour éviter les erreurs 429.
