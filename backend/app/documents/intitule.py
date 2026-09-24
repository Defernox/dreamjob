"""L'intitulé de poste tel qu'il doit figurer sur un CV et dans une lettre.

L'intitulé brut d'une annonce est écrit pour un moteur de recherche d'emplois,
pas pour un recruteur. Mesuré sur 722 offres pertinentes : **45 %** auraient
mis « (H/F) » en tête du CV, jusqu'à « Analyste Risques Financiers (H/F)- PARIS
(H/F) » ou « CDI - Gestionnaire de comptes Middle Office Employeurs (54) (H/F) ».
C'est la première ligne que lit le recruteur, sous le nom du candidat.

Garder l'intitulé de l'annonce reste le bon choix — c'est ce que cherche le
recruteur dans son ATS, et Jobscan mesure trois fois et demie plus d'entretiens
quand le titre du CV reprend celui de l'offre. On le **nettoie**, on ne le
remplace pas.

Ce qui est retiré, et seulement cela :

- les marqueurs de genre de l'annonce (H/F, F/H, M/W/X…) : ils s'adressent aux
  candidats, pas au candidat ;
- le contrat et la durée : la ligne « Recherche » du CV les porte déjà ;
- le département entre parenthèses, et le lieu **quand c'est celui de l'offre**
  — mesuré, le dernier segment après un tiret est rarement un lieu : « - Bank »,
  « - Trading », « - Middle Office » sont des spécialités ;
- le télétravail, les références internes, « URGENT » et les points
  d'exclamation.

Les accords inclusifs (« Chargé(e) ») sont laissés tels quels : les résoudre
supposerait de connaître le genre du candidat, que le profil ne renseigne pas.
"""

from __future__ import annotations

import re
import unicodedata

# Les marqueurs de genre, dans toutes leurs variantes relevées : (H/F), H/F,
# F/H, H/F/X, m/f/d, M/W/X, H-F — avec ou sans parenthèses. La frontière de mot
# en tête protège « Cash-flow » ou « Front/Middle ».
_GENRE = re.compile(
    r"\(?\s*\b[HFMhfm]\s*[/-]\s*[FHWfhw](?:\s*/\s*[XDxd])?\b\s*\)?")

_CONTRAT_EN_TETE = re.compile(
    r"^\s*(?:CDI|CDD|Stage|Alternance|Apprentissage|Int[ée]rim|Internship|"
    r"V\.?\s?I\.?\s?E\.?)\b"
    r"(?:\s*(?:de\s+)?\d+\s*mois)?"
    r"(?:\s+de\s+fin\s+d['’][ée]tudes|\s+de\s+pr[ée]-?embauche)?"
    r"\s*[-–—:/|]?\s*",
    re.IGNORECASE)
_CONTRAT_AILLEURS = re.compile(
    r"\s*[-–—,(]?\s*\b(?:en\s+)?(?:CDI|CDD|alternance|stage)\b"
    r"(?:\s*(?:de\s+)?\d+\s*mois)?\s*\)?",
    re.IGNORECASE)
_DUREE = re.compile(r"\s*[-–—,(]?\s*\b\d+\s*mois\b\s*\)?", re.IGNORECASE)
_DEPARTEMENT = re.compile(r"\s*\(\s*\d{2,3}\s*\)")
_TELETRAVAIL = re.compile(
    r"\s*[-–—,(]?\s*(?:\d+\s*%\s*)?(?:t[ée]l[ée]travail|hybride|full remote|remote)"
    r"(?:\s+partiel)?\s*\)?",
    re.IGNORECASE)
_REFERENCE = re.compile(r"\s*\(\s*r[ée]f\.?[^)]*\)|\s*#\d+|\s*\[[A-Z0-9-]+\]",
                        re.IGNORECASE)
_URGENT = re.compile(r"\bURGENT\b\s*[-–—:]?\s*|!+", re.IGNORECASE)
_PARENTHESES_VIDES = re.compile(r"\(\s*\)")
# Un séparateur espacé (« - », « | », une virgule) : le trait d'union d'un mot
# composé — Front-Office, Île-de-France — n'en est pas un.
_SEPARATEUR_ESPACE = re.compile(r"\s+[-–—|]\s*|\s*[-–—|]\s+|\s*,\s*")
_TIRET_COLLE_AVANT = re.compile(r"(?<=\S)([-–—])\s+")
_TIRET_COLLE_APRES = re.compile(r"\s+([-–—])(?=\S)")
_BORDS = " -–—:|,/"

# Sigles à laisser en capitales quand un intitulé tout en majuscules est remis
# en casse normale : sans eux, « RAF » deviendrait « Raf ».
SIGLES = {
    "RAF", "DAF", "CFO", "CEO", "COO", "RH", "DRH", "ESG", "RSE", "IFRS", "ALM",
    "KYC", "AML", "LCB", "FT", "BI", "IT", "SI", "PME", "ETI", "TPE", "M&A",
    "FP&A", "P&L", "PMO", "AMOA", "MOA", "CIB", "VBA", "SQL", "SAP", "ERP", "EPM",
    "CRM", "OTC", "FX", "ETF", "UCITS", "AMF", "ACPR", "BCE", "UE", "EMEA",
    "APAC", "US", "UK", "VIE", "II", "III", "IV",
}
# Les accents que perd un intitulé écrit en capitales, pour les mots de métier
# les plus fréquents. Un mot absent de la table reste sans accent — c'est moins
# grave qu'un accent faux.
ACCENTS = {
    "charge": "chargé", "chargee": "chargée", "controleur": "contrôleur",
    "controleuse": "contrôleuse", "controle": "contrôle", "tresorier": "trésorier",
    "tresoriere": "trésorière", "tresorerie": "trésorerie",
    "comptabilite": "comptabilité", "credit": "crédit", "credits": "crédits",
    "reglementaire": "réglementaire", "specialiste": "spécialiste",
    "secretaire": "secrétaire", "general": "général", "generale": "générale",
    "delegue": "délégué", "deleguee": "déléguée", "referent": "référent",
    "referente": "référente", "etudes": "études", "gerant": "gérant",
    "gerante": "gérante", "operationnel": "opérationnel",
    "operationnelle": "opérationnelle", "operations": "opérations",
    "societe": "société", "financiere": "financière", "ingenieur": "ingénieur",
    "ingenieure": "ingénieure", "securite": "sécurité", "conformite": "conformité",
    "developpement": "développement", "experimente": "expérimenté",
    "experimentee": "expérimentée", "strategie": "stratégie",
    "negociateur": "négociateur", "negociatrice": "négociatrice",
    "precontentieux": "précontentieux",
}
_MOTS_OUTILS = {"de", "du", "des", "et", "en", "la", "le", "les", "au", "aux",
                "pour", "sur", "par", "a", "à", "d", "l"}


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texte)
                   if not unicodedata.combining(c)).lower()


def _casse_normale(titre: str) -> str:
    """« RESPONSABLE ADMINISTRATIF ET FINANCIER » → « Responsable administratif
    et financier ». Seulement pour un intitulé écrit TOUT en capitales : une
    casse choisie par l'annonceur (« Business Analyst ») est respectée."""
    morceaux = re.split(r"(\s+|[-/'’()])", titre)
    sortie: list[str] = []
    premier = True
    for morceau in morceaux:
        if not morceau or not re.search(r"[A-Za-zÀ-ÿ]", morceau):
            sortie.append(morceau)
            continue
        if morceau.upper() in SIGLES:
            sortie.append(morceau.upper())
        else:
            bas = morceau.lower()
            bas = ACCENTS.get(_sans_accents(bas), bas)
            if premier:
                bas = bas[:1].upper() + bas[1:]
            sortie.append(bas)
        premier = False
    return "".join(sortie)


def _ville(lieu: str | None) -> str:
    """« 75 - Paris 9e Arrondissement » → « paris ».

    Le premier mot **significatif** : « La Défense » donnerait sinon « la », et
    tout segment final commençant par « la » serait pris pour un lieu.
    """
    if not lieu:
        return ""
    sans_departement = re.sub(r"^\s*\d{2,3}\s*-\s*", "", lieu)
    for mot in re.split(r"[\s,(]+", sans_departement.strip()):
        mot = _sans_accents(mot)
        if len(mot) >= 3 and mot not in _MOTS_OUTILS:
            return mot
    return ""


def _retirer_lieu_final(titre: str, ville: str) -> str:
    """Retire « - PARIS » en fin d'intitulé quand c'est la ville de l'offre."""
    while True:
        dernier = None
        for dernier in _SEPARATEUR_ESPACE.finditer(titre):
            pass
        if dernier is not None and _sans_accents(
                titre[dernier.end():].strip()).startswith(ville):
            titre = titre[:dernier.start()]
            continue
        # « … de crédit Lille » : la ville collée en dernier mot, sans tiret.
        # Égalité stricte ici — sans séparateur, « Lyonnaise » n'est pas Lyon.
        mots = titre.rsplit(None, 1)
        if len(mots) == 2 and _sans_accents(mots[1]) == ville:
            titre = mots[0]
            continue
        return titre


def _intitule_double(titre: str) -> tuple[str, str] | None:
    """« Auditeur comptable et financier / Auditrice comptable et financière ».

    France Travail publie ses appellations au masculin puis au féminin, parfois
    tronquées à la seconde moitié (« Responsable administratif, comptable et
    financier / Responsable a »). Reconnu quand les deux moitiés commencent par
    le même radical.
    """
    if " / " not in titre:
        return None
    gauche, droite = (m.strip() for m in titre.split(" / ", 1))
    if len(gauche) >= 5 and _sans_accents(gauche)[:5] == _sans_accents(droite)[:5]:
        return gauche, droite
    return None


def _moitie_selon_accord(titre: str, accord: str) -> str | None:
    """La moitié qui correspond à l'accord du profil, ou None si on ne peut pas
    choisir — accord non renseigné, ou moitié féminine tronquée par la source."""
    double = _intitule_double(titre)
    if double is None:
        return titre
    masculin, feminin = double
    if accord == "masculin":
        return masculin
    if accord == "feminin" and len(feminin.split()) >= len(masculin.split()):
        return feminin
    return None


def nettoyer_intitule(titre: str | None, lieu: str | None = None) -> str:
    """L'intitulé d'annonce débarrassé de ce qui ne concerne pas le candidat."""
    if not titre:
        return ""
    t = titre
    for motif, remplacement in (
        (_GENRE, " "), (_REFERENCE, " "), (_URGENT, " "), (_CONTRAT_EN_TETE, ""),
        (_TELETRAVAIL, " "), (_CONTRAT_AILLEURS, " "), (_DUREE, " "),
        (_DEPARTEMENT, " "), (_PARENTHESES_VIDES, " "),
    ):
        t = motif.sub(remplacement, t)

    ville = _ville(lieu)
    if ville:
        t = _retirer_lieu_final(t, ville)

    t = re.sub(r"\s+", " ", t).strip(_BORDS)
    # Un tiret espacé d'un seul côté (« Financiers- PARIS ») retrouve ses deux
    # espaces ; un trait d'union sans espace (« Front-Office ») n'est pas touché.
    t = _TIRET_COLLE_AVANT.sub(r" \1 ", t)
    t = _TIRET_COLLE_APRES.sub(r" \1 ", t)
    t = re.sub(r"\s+", " ", t).strip(_BORDS)

    lettres = [c for c in t if c.isalpha()]
    if len(lettres) > 4 and all(c.isupper() for c in lettres):
        t = _casse_normale(t)
    return t


def intitule_pour_cv(titre: str | None, lieu: str | None, titre_vise: str | None,
                     accord: str = "") -> str:
    """Le titre à placer sous le nom — et dans l'objet de la lettre.

    Celui de l'annonce, nettoyé. Le titre visé du profil ne le remplace que dans
    deux cas : le nettoyage ne laisse presque rien (« Stage : Finance » donnerait
    « Finance », qui ne dit pas quel poste on vise), ou l'intitulé est doublé au
    masculin et au féminin sans que le profil dise lequel retenir.
    """
    repli = (titre_vise or "").strip()
    propre = nettoyer_intitule(titre, lieu)
    choisi = _moitie_selon_accord(propre, accord)
    if choisi is None:
        return repli or propre
    if len(re.findall(r"[A-Za-zÀ-ÿ]{2,}", choisi)) >= 2:
        return choisi
    return repli or choisi


def au_poste(intitule: str) -> str:
    """« de Contrôleur » / « d'Analyste ».

    Faute relevée dans l'objet de chaque lettre dont l'intitulé commence par une
    voyelle — environ une sur dix : « candidature au poste de Analyste ». Le h
    n'est pas élidé : la plupart des intitulés concernés sont anglais (« Head
    of »), et l'usage y garde « de ».
    """
    intitule = intitule.strip()
    if not intitule:
        return ""
    if _sans_accents(intitule[:1]) in "aeiou":
        return f"d'{intitule}"
    return f"de {intitule}"
