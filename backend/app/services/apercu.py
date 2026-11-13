"""Ce qu'une alerte dit de l'offre : le salaire annoncé et les missions.

L'alerte demande « Postuler ? » : l'intitulé et l'employeur ne suffisent pas à
répondre. Deux questions reviennent avant d'ouvrir une annonce — combien, et
pour faire quoi — et l'alerte y répond quand l'annonce le dit.

**Pur code, aucun modèle.** Un résumé rédigé coûterait un appel par alerte et
pourrait dire ce que l'annonce ne dit pas. Ici, tout est *repris* de l'annonce :
le salaire tel que la source le donne, les missions telles qu'elles sont écrites,
coupées mais jamais reformulées.

**Un salaire estimé n'est pas un salaire annoncé.** Adzuna calcule une
estimation quand l'annonce est muette (`salary_is_predicted`) : elle n'est pas
montrée. Sans chiffre de la source, on cherche dans le texte — un montant près
d'un mot de rémunération, jamais un montant seul : « un portefeuille de 300 M€ »
n'est pas un salaire. Rien de trouvé, l'alerte le dit : « non indiqué ».
"""

from __future__ import annotations

import html
import re

from ..models import Offer

MAX_MISSIONS = 5
LONGUEUR_MISSION = 150
LONGUEUR_EXTRAIT = 350
LONGUEUR_SALAIRE = 110


def _nombre(valeur: float) -> str:
    """35000.0 → « 35 000 » ; 4.5 reste « 4,50 »."""
    if float(valeur) == int(valeur):
        return f"{int(valeur):,}".replace(",", " ")
    return f"{valeur:,.2f}".replace(",", " ").replace(".", ",")


def _fourchette(minimum, maximum) -> str:
    try:
        bas, haut = float(minimum or 0), float(maximum or 0)
    except (TypeError, ValueError):
        return ""
    if bas > 0 and haut > 0 and bas != haut:
        return f"{_nombre(bas)} – {_nombre(haut)} €"
    if max(bas, haut) > 0:
        # Une seule borne : on ne sait pas si c'est un plancher ou un plafond
        # quand les deux sont égales, on le sait quand l'une est nulle.
        if bas == haut:
            return f"{_nombre(bas)} €"
        return f"jusqu'à {_nombre(haut)} €" if haut > 0 else f"à partir de {_nombre(bas)} €"
    return ""


# --- Salaire : ce que la source donne ----------------------------------------

_DECIMALES_VIDES = re.compile(r"(\d+)\.0\b")
_GRAND_NOMBRE = re.compile(r"\b\d{4,}\b")


def _france_travail(salaire: dict) -> str:
    """« Annuel de 35000.0 Euros à 40000.0 Euros sur 12.0 mois » → lisible."""
    libelle = str(salaire.get("libelle") or "").strip()
    libelle = _DECIMALES_VIDES.sub(r"\1", libelle)
    libelle = _GRAND_NOMBRE.sub(lambda m: _nombre(int(m.group())), libelle)
    libelle = re.sub(r"\s*Euros?\b", " €", libelle)
    # « de 55 000 € à 55 000 € » : la même borne deux fois n'est pas une fourchette.
    libelle = re.sub(r"de ([\d ]+ €) à \1", r"de \1", libelle)
    commentaire = str(salaire.get("commentaire") or "").strip()
    if commentaire and commentaire.lower() in libelle.lower():
        commentaire = ""        # France Travail le recopie parfois dans le libellé
    complements = [c.get("libelle", "") for c in salaire.get("listeComplements") or []
                   if isinstance(c, dict)][:3]
    return " · ".join(filter(None, [_couper(libelle, LONGUEUR_SALAIRE),
                                    _couper(commentaire, LONGUEUR_SALAIRE),
                                    ", ".join(filter(None, complements))]))


_PERIODES = {"ANNUEL": "par an", "MENSUEL": "par mois", "JOURNALIER": "par jour",
             "HORAIRE": "de l'heure"}


def _de_la_source(offre: Offer) -> str:
    brut = offre.raw if isinstance(offre.raw, dict) else {}
    if isinstance(brut.get("salaire"), dict):                       # France Travail
        return _france_travail(brut["salaire"])
    if isinstance(brut.get("remuneration"), dict):                  # DogFinance
        r = brut["remuneration"]
        montant = _fourchette(r.get("min"), r.get("max"))
        return " ".join(filter(None, [montant, _PERIODES.get(str(r.get("type") or "").upper(), "")])
                        ) if montant else ""
    if brut.get("indemnite"):                                       # Civiweb
        try:
            return f"Indemnité V.I.E : {_nombre(round(float(brut['indemnite'])))} € par mois"
        except (TypeError, ValueError):
            return ""
    if "salary_min" in brut or "salary_max" in brut:                # Adzuna
        if str(brut.get("salary_is_predicted", "0")) == "1":
            return ""          # une estimation d'Adzuna, pas une annonce
        # Adzuna couvre dix-neuf pays et ne dit pas la monnaie : 800 000 est un
        # salaire au Mexique, pas en euros. Le chiffre est donné sans symbole.
        montant = _fourchette(brut.get("salary_min"), brut.get("salary_max")).replace(" €", "")
        return f"{montant} (monnaie du pays, d'après Adzuna)" if montant else ""
    return ""


# --- Salaire : ce que le texte dit -------------------------------------------

_MOT_SALAIRE = re.compile(
    r"salaire|r[ée]mun[ée]ration|gratification|indemnit[ée]|\bfixe\b|\bbrut|package|"
    r"salary|compensation|base pay|pay range|\bgross\b|\bOTE\b|geh[aä]lt|verg[üu]tung", re.IGNORECASE)
_DEVISE = r"(?:k€|K€|€|euros?\b|EUR\b|£|GBP\b|CHF\b|USD\b|\$)"
_MONTANT = re.compile(
    rf"\d{{1,3}}(?:[ .,  ]?\d{{3}})*(?:[.,]\d{{1,2}})?\s?[kK]?\s?{_DEVISE}"
    rf"|[€£$]\s?\d{{1,3}}(?:[ ,]?\d{{3}})*(?:\.\d{{1,2}})?\s?[kK]?"
    rf"|\b\d{{2,3}}\s?[kK]\b")
# Ce qui suit un montant et dit de quoi il s'agit : « brut annuel », « /an », « per hour ».
_QUALIFIE = re.compile(
    r"(?:\s*(?:et |and )?(?:/\s?(?:an|mois|semaine|heure|h|jour|year|month|week|hour|day)\b|"
    r"(?:bruts?|nets?|annuels?|mensuels?|gross|par an|par mois|par semaine|par jour|de l'heure|"
    r"per (?:year|annum|month|week|hour|day)|p\.a\.|sur \d+ mois|"
    r"selon (?:profil|exp[ée]rience)(?: et (?:profil|exp[ée]rience))?)\b)"
    r"[ ,]*){0,4}", re.IGNORECASE)
# Des montants qui ne paient personne.
_AUTRE_CHOSE = re.compile(
    r"chiffre d'affaires|\bCA\b|encours|actifs? sous|portefeuille|budget|lev[ée]e|capital|"
    r"milliards?|millions?|\bM€|\bMd|billion|million|assets under|\bAUM\b|revenue|turnover",
    re.IGNORECASE)


def _du_texte(texte: str) -> str:
    for segment in re.split(r"\n+|(?<=[.!?])\s+(?=[A-ZÀ-Ý])", texte):
        mot, montant = _MOT_SALAIRE.search(segment), _MONTANT.search(segment)
        if not (mot and montant) or _AUTRE_CHOSE.search(segment):
            continue
        # Du mot de rémunération quand il ouvre la phrase, sinon de son début —
        # jusqu'au dernier montant et à ce qui le qualifie (« brut annuel ») :
        # dans une annonce d'un seul bloc, la suite parle déjà d'autre chose.
        fragment = segment[mot.start() if mot.start() < montant.start() else 0:]
        montants = [m for m in _MONTANT.finditer(fragment) if m.end() <= LONGUEUR_SALAIRE]
        if not montants:
            continue
        fin = montants[-1].end()
        fin += _QUALIFIE.match(fragment[fin:]).end()
        trouve = fragment[:fin].strip(" :-–•*\t,")
        return trouve + ")" * max(0, trouve.count("(") - trouve.count(")"))
    return ""


def salaire(offre: Offer) -> str:
    """Le salaire que l'annonce affiche, ou « » si elle n'en dit rien."""
    return _de_la_source(offre) or _du_texte(_texte(offre.description_brute))


# --- Missions ----------------------------------------------------------------

_BALISE_DE_BLOC = re.compile(r"<\s*(?:br|/p|/div|/li|li|/h\d|/ul|/ol|/tr)\b[^>]*>", re.IGNORECASE)
_BALISE = re.compile(r"<[^>]+>")
_PUCE = re.compile(r"^\s*(?:[-–—•·*▪■●○►➢✓✔→]+|\d{1,2}[.)])\s*")

_PUCE_EN_LIGNE = re.compile(r"[ \t]+[•*▪●][ \t]+")

# Les mots qui annoncent des missions…
_MOT_FORT = (r"(?:missions?|responsabilit[ée]s|responsibilities|accountabilities|activit[ée]s|"
             r"t[âa]ches|duties|aufgaben|what you(?:'ll| will) (?:do|be doing)|ce que vous ferez)")
# … et ceux qui annoncent le poste en général : à défaut des premiers.
_MOT_FAIBLE = (r"(?:r[ôo]le|poste|descriptif du poste|description du poste|"
               r"description de la mission|purpose of the role|job description|job summary|"
               r"position summary|about the (?:role|job|position)|overview)")
_DETERMINANTS = r"^\W*(?:(?:vos|tes|les|nos|votre|ton|le|la|your|key|main|the|principales)\s+){0,2}"
_TITRE_FORT = re.compile(_DETERMINANTS + r"(?:futures?\s+|principales\s+)?" + _MOT_FORT + r"\b",
                         re.IGNORECASE)
_FORT_PARTOUT = re.compile(r"\b" + _MOT_FORT + r"\b", re.IGNORECASE)
_TITRE_FAIBLE = re.compile(_DETERMINANTS + _MOT_FAIBLE + r"\b", re.IGNORECASE)
_AUTRE_TITRE = re.compile(
    r"^\W*(?:(?:votre|ton|le|your|our|the|notre|nos|vos|les)\s+)?"
    r"(?:profil|profile|comp[ée]tences|skills|qualifications|requirements|pr[ée]-?requis|"
    r"formation|exp[ée]rience|avantages|benefits|r[ée]mun[ée]ration|salaire|salary|"
    r"about (?:you|us)|[àa] propos|pourquoi|why|what we offer|we offer|who you are|"
    r"nous (?:vous )?offrons|ce que nous|conditions|contrat|informations?|candidate profile|"
    r"process|processus|qui sommes|l'entreprise|the company|company)\b", re.IGNORECASE)
# Dans une annonce d'un seul bloc (Adzuna), l'endroit où l'on commence à parler du poste.
_DEBUT_UTILE = re.compile(
    r"(?:about the (?:role|job|position)|the role|your role|" + _MOT_FORT +
    r"|le poste|description du poste|votre r[ôo]le)\s*[:–-]\s+", re.IGNORECASE)

LONGUEUR_TITRE = 90           # une ligne terminée par « : »
LONGUEUR_TITRE_NU = 50        # une ligne sans « : » : quelques mots, sans point
LONGUEUR_AUTRE_TITRE = 30
LONGUEUR_SOUS_TITRE = 90
LONGUEUR_INTERTITRE = 60      # dans une liste, une ligne sans puce plus courte la structure


def _texte(brut: str | None) -> str:
    """Le texte d'une annonce, balises retirées, une idée par ligne."""
    texte = _BALISE.sub(" ", _BALISE_DE_BLOC.sub("\n", brut or ""))
    texte = html.unescape(texte).replace("\r", "\n").replace("\u00a0", " ")
    # « … les suivantes : * Suivi des contrats * Contrôle… » : des puces à la suite.
    texte = _PUCE_EN_LIGNE.sub("\n• ", texte)
    return "\n".join(re.sub(r"[ \t]+", " ", ligne).strip() for ligne in texte.split("\n"))


def _couper(texte: str, longueur: int) -> str:
    texte = texte.strip()
    if len(texte) <= longueur:
        return texte
    return texte[:longueur].rsplit(" ", 1)[0].rstrip(" ,;:-–") + "…"


def _points(lignes: list[str]) -> list[str]:
    """Des lignes aux missions : une puce par ligne, un paragraphe par phrases."""
    points: list[str] = []
    for ligne in lignes:
        ligne = re.sub(r"\s+([,;.])", r"\1", _PUCE.sub("", ligne)).strip().rstrip(";").strip()
        if len(ligne) < 4:
            continue
        morceaux = (re.split(r"(?<=[.;!?])\s+(?=[A-ZÀ-Ý])", ligne) if len(ligne) > 220 else [ligne])
        points += [m.strip() for m in morceaux if len(m.strip()) >= 4]
    return points


def _ouvre(ligne: str, ancre: re.Pattern, partout: re.Pattern | None = None) -> tuple[bool, str]:
    """(la ligne est un titre de rubrique, ce qui le suit sur la même ligne).

    « Vos missions : piloter… » porte le titre et la première mission ; « Vous
    aurez pour missions : » en est un aussi, le mot n'importe où avant les deux
    points ; « Le poste est basé à Paris. » n'en est pas un."""
    titre, deux_points, reste = ligne.partition(":")
    if deux_points:
        if len(titre) > LONGUEUR_TITRE or _AUTRE_TITRE.match(titre):
            return False, ""
        if ancre.match(titre) and len(titre) <= LONGUEUR_TITRE_NU:
            return True, reste.strip()
        return bool(partout and not reste.strip() and partout.search(titre)), ""
    nu = len(ligne) <= LONGUEUR_TITRE_NU and not ligne.endswith((".", ",", ";"))
    return bool(nu and ancre.match(ligne)), ""


def _rubrique(lignes: list[str], ancre: re.Pattern, partout: re.Pattern | None = None) -> list[str]:
    """Les missions de la première rubrique que `ancre` reconnaît et qui en contient."""
    for rang, ligne in enumerate(lignes):
        ouvert, premier = _ouvre(ligne, ancre, partout)
        if not ouvert:
            continue
        suite = [premier] if premier else []
        for suivante in lignes[rang + 1:]:
            titre = suivante.rstrip(" :")
            est_titre = suivante.endswith(":") or (
                len(suivante) <= LONGUEUR_AUTRE_TITRE and not suivante.endswith("."))
            if est_titre and _AUTRE_TITRE.match(titre):
                break                       # « Profil recherché » : la rubrique est finie
            if suivante.endswith(":") and len(suivante) <= LONGUEUR_SOUS_TITRE:
                continue                    # « Activités principales : » n'est pas une mission
            suite.append(suivante)
        # Sous « Missions principales », une phrase d'introduction puis la liste :
        # c'est la liste qu'on veut.
        puces = [l for l in suite if _PUCE.match(l)]
        points = _points(puces if len(puces) >= 2 else suite)
        if points:
            return points
    return []


def _premiere_liste(lignes: list[str]) -> list[str]:
    """La première liste à puces de l'annonce, si elle n'est pas rangée sous
    « Profil », « Avantages »… Une annonce sans rubriques énumère presque
    toujours ses missions d'abord, le profil ensuite."""
    sous_autre_titre = False
    for rang, ligne in enumerate(lignes):
        if not _PUCE.match(ligne):
            titre = ligne.rstrip(" :")
            if ligne.endswith(":") or len(ligne) <= LONGUEUR_AUTRE_TITRE:
                sous_autre_titre = bool(_AUTRE_TITRE.match(titre))
            continue
        if sous_autre_titre:
            continue
        puces = []
        for suivante in lignes[rang:]:
            if _PUCE.match(suivante):
                puces.append(suivante)
            elif _AUTRE_TITRE.match(suivante.rstrip(" :")) or len(suivante) > LONGUEUR_INTERTITRE:
                break                       # une autre rubrique, ou la prose qui reprend
        if len(puces) >= 2:
            return _points(puces)
    return []


def missions(offre: Offer) -> tuple[bool, list[str]]:
    """(trouvées, lignes). Trouvées : la rubrique des missions de l'annonce, en
    puces — à défaut sa première liste, puis la rubrique qui décrit le poste.
    Sinon : le début de l'annonce,
    tel quel — c'est un extrait, et l'alerte le dit, au lieu de faire passer une
    présentation de l'entreprise pour des missions."""
    brut = offre.raw if isinstance(offre.raw, dict) else {}
    # DogFinance et Civiweb rangent le descriptif du poste à part de la description.
    source = next((brut[c] for c in ("missions", "missionDescription")
                   if isinstance(brut.get(c), str) and brut[c].strip()), offre.description_brute)
    lignes = [l for l in _texte(source).split("\n") if l]
    points = (_rubrique(lignes, _TITRE_FORT, _FORT_PARTOUT) or _premiere_liste(lignes)
              or _rubrique(lignes, _TITRE_FAIBLE))
    if points:
        return True, [_couper(p, LONGUEUR_MISSION) for p in points[:MAX_MISSIONS]]

    bloc = " ".join(lignes)
    utile = _DEBUT_UTILE.search(bloc)
    if utile and len(bloc) - utile.end() >= 80:
        bloc = bloc[utile.end():]
    extrait = _couper(bloc, LONGUEUR_EXTRAIT)
    return False, [extrait] if extrait else []


def apercu(offre: Offer) -> str:
    """Les lignes ajoutées à l'alerte : salaire, puis missions ou extrait."""
    lignes = [f"💶 {salaire(offre) or 'Salaire non indiqué'}"]
    trouvees, points = missions(offre)
    if points:
        if trouvees:
            lignes += ["📋 Missions"] + [f"• {p}" for p in points]
        else:
            lignes += ["📋 Extrait de l'annonce", points[0]]
    return "\n".join(lignes)
