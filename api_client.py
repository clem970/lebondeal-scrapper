import aiohttp

from config import API_BASE_URL, API_KEY

ENDPOINTS = {
    "vinted": "/api/v1/vinted/search",
    "leboncoin": "/api/v1/leboncoin/search",
    "kleinanzeigen": "/api/v1/kleinanzeigen/search",
}

# Un timeout client généreux: l'API peut prendre jusqu'à ~40s en cas d'incident temporaire (retries internes).
TIMEOUT = aiohttp.ClientTimeout(total=50)

ERROR_MESSAGES = {
    "invalid_url": "URL manquante ou invalide pour ce site.",
    "unauthorized": "Clé API absente, invalide ou révoquée.",
    "insufficient_credits": "Solde de crédits insuffisant.",
    "account_paused": "Compte en pause (solde ou plafond de dépense global atteint).",
    "api_limit_reached": "Plafond jour/mois/max atteint pour cette API.",
    "api_not_activated": "Cette API n'est pas activée sur le compte.",
    "rate_limited": "Trop de requêtes, réessai dans quelques secondes.",
    "unexpected_error": "Incident temporaire côté LeBonDeal (ou recherche vide) — réessai plus tard.",
}


class APIError(Exception):
    def __init__(self, status, error_code, message=None):
        self.status = status
        self.error_code = error_code
        self.message = message or ERROR_MESSAGES.get(error_code, "Erreur inconnue.")
        super().__init__(f"[{status}] {error_code}: {self.message}")


async def search(site: str, url: str) -> dict:
    """Appelle l'API de recherche pour le site donné. Lève APIError en cas d'échec."""
    if site not in ENDPOINTS:
        raise ValueError(f"Site inconnu: {site}")

    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.get(
            API_BASE_URL + ENDPOINTS[site], headers=headers, params={"url": url}
        ) as resp:
            try:
                data = await resp.json()
            except Exception:
                data = {}
            if resp.status != 200:
                error_code = data.get("error", "unexpected_error")
                raise APIError(resp.status, error_code, data.get("message"))
            return data


def extract_items(site: str, data: dict) -> list[dict]:
    """Normalise les résultats des 3 sites vers un format commun."""
    raw_items = data.get("items") if site != "leboncoin" else data.get("ads")
    raw_items = raw_items or []
    normalized = []
    for it in raw_items:
        if site == "vinted":
            normalized.append({
                "id": str(it.get("id")),
                "title": it.get("title"),
                "price": it.get("price"),
                "location": None,
                "url": it.get("url"),
                "image": (it.get("photos") or [None])[0],
                "extra": {"marque": it.get("brand"), "taille": it.get("size"), "état": it.get("status")},
            })
        elif site == "leboncoin":
            normalized.append({
                "id": str(it.get("id")),
                "title": it.get("title"),
                "price": f"{it.get('price')} €" if it.get("price") is not None else None,
                "location": it.get("location"),
                "url": it.get("url"),
                "image": (it.get("images") or [None])[0],
                "extra": {"publié": it.get("published")},
            })
        elif site == "kleinanzeigen":
            normalized.append({
                "id": str(it.get("id")),
                "title": it.get("title"),
                "price": it.get("price"),
                "location": it.get("location"),
                "url": it.get("url"),
                "image": (it.get("images") or [None])[0],
                "extra": {"publié": it.get("published")},
            })
    return normalized
