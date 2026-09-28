"""Les pays des sites carrières, ramenés au vocabulaire du projet.

Un logiciel de recrutement donne le pays sous trois formes : un code ISO
(« GB »), un nom anglais (« United Kingdom », parfois « England »), ou un nom
dans la langue du site (« Deutschland », « Schweiz », « Italia »). Le projet ne
connaît que les noms français de `models.enums.PAYS_FILTRES` : c'est sur eux que
filtrent les recherches et que se calcule le critère « lieu ».

Un pays inconnu rend une chaîne vide, jamais une supposition : un filtre trop
large vaut mieux qu'une offre rangée dans le mauvais pays.
"""

from __future__ import annotations

import re
import unicodedata

ISO: dict[str, str] = {
    "DE": "Allemagne", "AT": "Autriche", "BE": "Belgique", "CY": "Chypre",
    "DK": "Danemark", "ES": "Espagne", "FR": "France", "IE": "Irlande",
    "IT": "Italie", "LI": "Liechtenstein", "LU": "Luxembourg", "MT": "Malte",
    "MC": "Monaco", "NO": "Norvège", "NL": "Pays-Bas", "PL": "Pologne",
    "PT": "Portugal", "GB": "Royaume-Uni", "UK": "Royaume-Uni", "SE": "Suède",
    "CH": "Suisse", "CZ": "Tchéquie", "BR": "Brésil", "CA": "Canada",
    "US": "États-Unis", "MX": "Mexique", "AU": "Australie", "CN": "Chine",
    "HK": "Hong Kong", "IN": "Inde", "JP": "Japon", "NZ": "Nouvelle-Zélande",
    "SG": "Singapour", "ZA": "Afrique du Sud", "DZ": "Algérie",
    "CI": "Côte d'Ivoire", "AE": "Émirats arabes unis", "IL": "Israël",
    "MU": "Île Maurice", "MA": "Maroc", "QA": "Qatar", "SN": "Sénégal",
    "TN": "Tunisie",
}

# Des pays hors du vocabulaire des recherches, mais fréquents sur les sites des
# groupes financiers. Les nommer, c'est pouvoir les écarter : inconnus, ils
# passaient le filtre des pays comme un lieu non précisé — un poste de SCOR à
# Bucarest arrivait ainsi dans une recherche limitée à la France.
_AUTRES: dict[str, tuple[str, tuple[str, ...]]] = {
    "RO": ("Roumanie", ("romania", "roumanie")), "HU": ("Hongrie", ("hungary", "hongrie")),
    "GR": ("Grèce", ("greece", "grece")), "TR": ("Turquie", ("turkey", "turkiye", "turquie")),
    "BG": ("Bulgarie", ("bulgaria", "bulgarie")), "HR": ("Croatie", ("croatia", "croatie")),
    "RS": ("Serbie", ("serbia", "serbie")), "SK": ("Slovaquie", ("slovakia", "slovaquie")),
    "SI": ("Slovénie", ("slovenia", "slovenie")), "FI": ("Finlande", ("finland", "finlande")),
    "EE": ("Estonie", ("estonia", "estonie")), "LV": ("Lettonie", ("latvia", "lettonie")),
    "LT": ("Lituanie", ("lithuania", "lituanie")), "IS": ("Islande", ("iceland", "islande")),
    "UA": ("Ukraine", ("ukraine",)), "RU": ("Russie", ("russia", "russie")),
    "JE": ("Jersey", ("jersey",)), "GG": ("Guernesey", ("guernsey", "guernesey")),
    "IM": ("Île de Man", ("isle of man",)), "GI": ("Gibraltar", ("gibraltar",)),
    "PH": ("Philippines", ("philippines",)), "TW": ("Taïwan", ("taiwan",)),
    "KR": ("Corée du Sud", ("south korea", "korea", "republic of korea")),
    "MY": ("Malaisie", ("malaysia", "malaisie")), "TH": ("Thaïlande", ("thailand", "thailande")),
    "ID": ("Indonésie", ("indonesia", "indonesie")), "VN": ("Viêt Nam", ("vietnam", "viet nam")),
    "PK": ("Pakistan", ("pakistan",)), "BD": ("Bangladesh", ("bangladesh",)),
    "LK": ("Sri Lanka", ("sri lanka",)), "MO": ("Macao", ("macau", "macao")),
    "SA": ("Arabie saoudite", ("saudi arabia", "arabie saoudite")),
    "BH": ("Bahreïn", ("bahrain",)), "KW": ("Koweït", ("kuwait",)), "OM": ("Oman", ("oman",)),
    "EG": ("Égypte", ("egypt", "egypte")), "NG": ("Nigeria", ("nigeria",)), "KE": ("Kenya", ("kenya",)),
    "AR": ("Argentine", ("argentina", "argentine")), "CL": ("Chili", ("chile", "chili")),
    "CO": ("Colombie", ("colombia", "colombie")), "PE": ("Pérou", ("peru", "perou")),
    "UY": ("Uruguay", ("uruguay",)), "CR": ("Costa Rica", ("costa rica",)),
    "PR": ("Porto Rico", ("puerto rico",)), "BM": ("Bermudes", ("bermuda", "bermudes")),
    "KY": ("Îles Caïmans", ("cayman islands",)), "BS": ("Bahamas", ("bahamas",)),
}
ISO.update({code: nom for code, (nom, _) in _AUTRES.items()})

# Noms rencontrés sur les sites, sans accents et en minuscules.
_NOMS: dict[str, str] = {
    "germany": "Allemagne", "deutschland": "Allemagne", "allemagne": "Allemagne",
    "austria": "Autriche", "osterreich": "Autriche", "autriche": "Autriche",
    "belgium": "Belgique", "belgique": "Belgique", "belgie": "Belgique", "belgien": "Belgique",
    "cyprus": "Chypre", "chypre": "Chypre",
    "denmark": "Danemark", "danemark": "Danemark",
    "spain": "Espagne", "espana": "Espagne", "espagne": "Espagne",
    "france": "France",
    "ireland": "Irlande", "irlande": "Irlande",
    "italy": "Italie", "italia": "Italie", "italie": "Italie",
    "liechtenstein": "Liechtenstein",
    "luxembourg": "Luxembourg", "luxemburg": "Luxembourg",
    "malta": "Malte", "malte": "Malte",
    "monaco": "Monaco",
    "norway": "Norvège", "norvege": "Norvège",
    "netherlands": "Pays-Bas", "the netherlands": "Pays-Bas", "nederland": "Pays-Bas",
    "pays-bas": "Pays-Bas", "holland": "Pays-Bas",
    "poland": "Pologne", "polska": "Pologne", "pologne": "Pologne",
    "portugal": "Portugal",
    "united kingdom": "Royaume-Uni", "uk": "Royaume-Uni", "great britain": "Royaume-Uni",
    "england": "Royaume-Uni", "scotland": "Royaume-Uni", "wales": "Royaume-Uni",
    "northern ireland": "Royaume-Uni", "royaume-uni": "Royaume-Uni", "royaume uni": "Royaume-Uni",
    "sweden": "Suède", "suede": "Suède",
    "switzerland": "Suisse", "schweiz": "Suisse", "suisse": "Suisse", "svizzera": "Suisse",
    "czech republic": "Tchéquie", "czechia": "Tchéquie", "tchequie": "Tchéquie",
    "brazil": "Brésil", "brasil": "Brésil", "bresil": "Brésil",
    "canada": "Canada",
    "united states": "États-Unis", "united states of america": "États-Unis", "usa": "États-Unis",
    "us": "États-Unis", "etats-unis": "États-Unis", "etats-unis d'amerique": "États-Unis",
    "mexico": "Mexique", "mexique": "Mexique",
    "australia": "Australie", "australie": "Australie",
    "china": "Chine", "chine": "Chine", "mainland china": "Chine",
    "hong kong": "Hong Kong", "hong kong sar": "Hong Kong", "hong-kong": "Hong Kong",
    "hong kong sar, china": "Hong Kong",
    "india": "Inde", "inde": "Inde",
    "japan": "Japon", "japon": "Japon",
    "new zealand": "Nouvelle-Zélande", "nouvelle-zelande": "Nouvelle-Zélande",
    "singapore": "Singapour", "singapour": "Singapour",
    "south africa": "Afrique du Sud", "afrique du sud": "Afrique du Sud",
    "algeria": "Algérie", "algerie": "Algérie",
    "ivory coast": "Côte d'Ivoire", "cote d'ivoire": "Côte d'Ivoire",
    "united arab emirates": "Émirats arabes unis", "uae": "Émirats arabes unis",
    "emirats arabes unis": "Émirats arabes unis",
    "israel": "Israël",
    "mauritius": "Île Maurice", "ile maurice": "Île Maurice",
    "morocco": "Maroc", "maroc": "Maroc",
    "qatar": "Qatar",
    "senegal": "Sénégal",
    "tunisia": "Tunisie", "tunisie": "Tunisie",
}
_NOMS.update({nom_local: nom for nom, noms in _AUTRES.values() for nom_local in noms})

# Les grandes villes financières : quand le site ne donne qu'une ville
# (« London », « Paris La Défense »), c'est elle qui dit le pays.
_VILLES: dict[str, str] = {
    "paris": "France", "la defense": "France", "lyon": "France", "marseille": "France",
    "lille": "France", "bordeaux": "France", "nantes": "France", "toulouse": "France",
    "strasbourg": "France", "montrouge": "France", "guyancourt": "France",
    "london": "Royaume-Uni", "londres": "Royaume-Uni", "edinburgh": "Royaume-Uni",
    "glasgow": "Royaume-Uni", "manchester": "Royaume-Uni", "birmingham": "Royaume-Uni",
    "dublin": "Irlande", "luxembourg": "Luxembourg", "brussels": "Belgique",
    "bruxelles": "Belgique", "geneva": "Suisse", "geneve": "Suisse", "zurich": "Suisse",
    "lausanne": "Suisse", "lugano": "Suisse", "frankfurt": "Allemagne", "francfort": "Allemagne",
    "munich": "Allemagne", "munchen": "Allemagne", "berlin": "Allemagne", "hamburg": "Allemagne",
    "milan": "Italie", "milano": "Italie", "rome": "Italie", "roma": "Italie",
    "new york": "États-Unis", "boston": "États-Unis", "chicago": "États-Unis",
    "toronto": "Canada", "montreal": "Canada", "singapore": "Singapour",
    "tokyo": "Japon", "sydney": "Australie", "shanghai": "Chine", "beijing": "Chine",
    "johannesburg": "Afrique du Sud", "sao paulo": "Brésil", "mexico city": "Mexique",
    "amsterdam": "Pays-Bas", "madrid": "Espagne", "lisbon": "Portugal", "lisbonne": "Portugal",
    "warsaw": "Pologne", "krakow": "Pologne", "wroclaw": "Pologne",
    "bangalore": "Inde", "bengaluru": "Inde", "mumbai": "Inde", "pune": "Inde", "chennai": "Inde",
}


def _nu(texte: str) -> str:
    sans = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in sans if not unicodedata.combining(c)).lower().strip()


def depuis_iso(code: str | None) -> str:
    return ISO.get((code or "").strip().upper(), "")


def depuis_nom(nom: str | None) -> str:
    """Un nom de pays, dans l'une des langues des sites."""
    return _NOMS.get(_nu(nom or "").strip(" ."), "")


_ANGLAIS = {
    "Allemagne": "Germany", "Autriche": "Austria", "Belgique": "Belgium", "Chypre": "Cyprus",
    "Danemark": "Denmark", "Espagne": "Spain", "France": "France", "Irlande": "Ireland",
    "Italie": "Italy", "Liechtenstein": "Liechtenstein", "Luxembourg": "Luxembourg", "Malte": "Malta",
    "Monaco": "Monaco", "Norvège": "Norway", "Pays-Bas": "Netherlands", "Pologne": "Poland",
    "Portugal": "Portugal", "Royaume-Uni": "United Kingdom", "Suède": "Sweden", "Suisse": "Switzerland",
    "Tchéquie": "Czech Republic", "Brésil": "Brazil", "Canada": "Canada", "États-Unis": "United States",
    "Mexique": "Mexico", "Australie": "Australia", "Chine": "China", "Hong Kong": "Hong Kong",
    "Inde": "India", "Japon": "Japan", "Nouvelle-Zélande": "New Zealand", "Singapour": "Singapore",
    "Afrique du Sud": "South Africa", "Algérie": "Algeria", "Côte d'Ivoire": "Ivory Coast",
    "Émirats arabes unis": "United Arab Emirates", "Israël": "Israel", "Île Maurice": "Mauritius",
    "Maroc": "Morocco", "Qatar": "Qatar", "Sénégal": "Senegal", "Tunisie": "Tunisia",
}


def en_anglais(pays: str) -> str:
    """Le nom anglais d'un pays du vocabulaire, pour les sites qui filtrent
    par nom de pays (Eightfold chez HSBC)."""
    return _ANGLAIS.get(pays, pays)


def pays_possibles(lieu: str | None) -> list[str]:
    """Tous les pays d'un lieu qui en cite plusieurs : « New York, London,
    Singapore » → États-Unis, Royaume-Uni, Singapour. Le premier voulu gagne."""
    trouves: list[str] = []
    for segment in re.split(r"[,;|/()]| [-–] ", lieu or ""):
        nu = _nu(segment).strip(" .")
        pays = depuis_nom(segment) or next(
            (p for ville, p in _VILLES.items() if re.search(rf"\b{re.escape(ville)}\b", nu)), "")
        if pays and pays not in trouves:
            trouves.append(pays)
    return trouves


def depuis_lieu(lieu: str | None) -> str:
    """Le pays d'un lieu libre (« Paris, France », « London, England »,
    « 3 Locations »). Le dernier segment d'abord, puis les villes connues."""
    if not lieu:
        return ""
    if pays := depuis_nom(lieu):
        return pays
    # « Hong Kong SAR, China » : le dernier segment dirait « Chine ».
    if "hong kong" in _nu(lieu):
        return "Hong Kong"
    # Un tiret n'est un séparateur qu'espacé : « Pays-Bas », « Paris-La Défense ».
    segments = [s for s in re.split(r"[,;|/()]| [-–] ", lieu) if s.strip()]
    for segment in reversed(segments):
        if pays := depuis_nom(segment) or depuis_iso(segment if len(segment.strip()) == 2 else ""):
            return pays
    nu = _nu(lieu)
    for ville, pays in _VILLES.items():
        if re.search(rf"\b{re.escape(ville)}\b", nu):
            return pays
    return ""
