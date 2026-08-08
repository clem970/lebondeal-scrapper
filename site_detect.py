from urllib.parse import urlparse

SITE_DOMAINS = {
    "vinted": ("vinted.fr", "vinted.co.uk", "vinted.com", "vinted.de", "vinted.es", "vinted.it"),
    "leboncoin": ("leboncoin.fr",),
    "kleinanzeigen": ("kleinanzeigen.de",),
}


def detect_site(url: str) -> str | None:
    """Retourne 'vinted' / 'leboncoin' / 'kleinanzeigen' ou None si l'URL ne correspond à aucun site géré."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return None
    host = host.removeprefix("www.")
    for site, domains in SITE_DOMAINS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return site
    return None


def is_valid_search_url(url: str, site: str) -> bool:
    """Vérifications basiques pour éviter d'envoyer une URL de fiche annonce au lieu d'une page de résultats."""
    if site == "kleinanzeigen":
        return "/s-anzeige/" not in url and "/s-" in url
    if site == "leboncoin":
        return "/recherche" in url
    if site == "vinted":
        return "/catalog" in url
    return False
