import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("LEBONDEAL_API_KEY")
API_BASE_URL = os.getenv("API_BASE_URL", "https://bot.lebondeal-bot.fr").rstrip("/")
DB_PATH = os.getenv("DB_PATH", "data/bot.db")

# IDs séparés par des virgules autorisés à utiliser les commandes sensibles (paramètres globaux).
# Si vide, tout le monde peut utiliser les commandes (à éviter en prod).
OWNER_IDS = {int(x) for x in os.getenv("OWNER_IDS", "").split(",") if x.strip().isdigit()}

# Optionnel: si défini, les commandes slash sont synchronisées uniquement sur cette guild (sync instantané).
GUILD_ID = os.getenv("GUILD_ID")
GUILD_ID = int(GUILD_ID) if GUILD_ID and GUILD_ID.isdigit() else None

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant dans les variables d'environnement (.env).")
if not API_KEY:
    raise RuntimeError("LEBONDEAL_API_KEY manquant dans les variables d'environnement (.env).")

# Limites techniques documentées par l'API (par site + garde-fou global du compte)
SITE_LIMITS = {
    "vinted": {"max_requests": None, "per_seconds": None},       # illimité côté API dédiée
    "leboncoin": {"max_requests": 1, "per_seconds": 10},          # 1 req / 10s
    "kleinanzeigen": {"max_requests": 60, "per_seconds": 60},     # 60 req / 60s
}
GLOBAL_KEY_LIMIT = {"max_requests": 30, "per_seconds": 60}   # 30 req/min par clé, partagé entre toutes les API
