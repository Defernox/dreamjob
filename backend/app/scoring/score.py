"""Le calcul du score — code pur, déterministe, sans réseau ni LLM.

**Ce que le score mesure : à quel point une offre correspond au CV.** Deux
étages, parce que deux questions :

1. **L'adéquation** — le poste est-il fait pour ce candidat ? Le métier
   (l'intitulé), les exigences de l'annonce couvertes par le CV, le niveau du
   poste, le diplôme demandé, la langue. C'est le fond, et c'est lui qui décide.
2. **Les conditions** — le lieu, le contrat, la fraîcheur de l'annonce. Elles
   **modulent** le score (jusqu'à `part_conditions`), elles ne le font pas.
   Dans la première version, elles pesaient autant que le reste dans une même
   moyenne : un poste sans rapport, en CDI à Paris, remontait au seul motif
   qu'il était en CDI à Paris.

Et des **points rédhibitoires** : une langue exigée que le candidat ne parle
pas, un poste de direction pour trois ans d'expérience, une certification ou un
statut qu'il n'a pas. Ceux-là plafonnent le score, quel que soit le reste.

Deux propriétés à préserver :

- **Rejouable.** Mêmes entrées, même score. Les entrées sont le profil, l'offre,
  les poids, le corpus des offres du compte (`corpus.py`) et la date du jour.
- **Explicable.** Chaque critère garde la matière de sa justification
  (`Resultat`), que `explain.py` met en phrases.

Un critère qu'on ne peut pas juger vaut `None` : son poids est alors
**redistribué** sur les autres. Lui donner 0 punirait l'offre pour une lacune du
profil ; lui donner 100 fabriquerait un score flatteur.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime

from rapidfuzz import fuzz, process

from ..config import PoidsScoring
from ..models import Offer, Profile
from ..models.base import maintenant
from .cible import ProfilCible
from .corpus import NEUTRE, Corpus
from .exigences import RANG
from .extraction import Signaux
from .lexique import CREUX, canon
from .synonymes import present as synonyme_present
from .texte import GENERIQUES, mots, normaliser, poids_jeton

CRITERES_PERTINENCE = ("metier", "competences")
CRITERES_ACCESSIBILITE = ("seniorite", "formation", "langue")
CRITERES_CONDITIONS = ("pays", "contrat", "fraicheur")
CRITERES = CRITERES_PERTINENCE + CRITERES_ACCESSIBILITE + CRITERES_CONDITIONS

# Proportion des mots d'une compétence à retrouver pour la dire « trouvée ».
# Sert aux documents (ordre des puces, correspondance) : voir `presence`.
SEUIL_TROUVEE = 0.5
SEUIL_FLOU = 88
CREDIT_FLOU = 0.8

# Gardé pour `documents/correspondance.py`, qui lit les années exigées.
_ANNEES_EXIGEES = re.compile(
    r"(\d{1,2})\s*(?:\+|ans?|années?)\s*(?:\+)?\s*(?:minimum|mini|au moins)?\s*"
    r"(?:d[e'’]\s*)?(?:exp[ée]rience|exp\b)", re.IGNORECASE)


# --- Présence d'une expression dans un vocabulaire (documents) ---------------------


def presence(terme: str, vocabulaire: set[str], *, flou: bool) -> float:
    """À quel point `terme` est présent dans le vocabulaire : de 0 à 1.

    Sert aux documents — l'ordre des puces du CV, le panneau « Ce que verra le
    recruteur », le contrôle du CV ciblé. Le score, lui, compare des jetons
    canoniques (`lexique.py`).

    Une compétence est souvent une expression qu'aucune annonce ne reprend mot
    pour mot : on mesure la proportion pondérée de ses mots retrouvés, les mots
    génériques (gestion, analyse…) comptant moins que les mots spécifiques.
    """
    jetons_terme = mots(terme)
    if not jetons_terme:
        return 0.0
    total = obtenu = 0.0
    for jeton in jetons_terme:
        poids = poids_jeton(jeton)
        total += poids
        if synonyme_present(jeton, vocabulaire):
            obtenu += poids
        elif flou:
            proche = process.extractOne(jeton, vocabulaire, scorer=fuzz.ratio,
                                        score_cutoff=SEUIL_FLOU)
            if proche is not None:
                obtenu += poids * (proche[1] / 100.0) * CREDIT_FLOU
    return obtenu / total if total else 0.0


# --- Poids d'un terme ---------------------------------------------------------------

# Les mots qui disent la FORME d'un poste, pas son contenu : « Responsable
# financier » et « Chargé financier » font le même métier à deux niveaux — le
# niveau a son propre critère.
_GENERIQUES_INTITULE = {canon(normaliser(m)) for m in (
    *GENERIQUES, "specialist", "specialiste", "officer", "associate", "consultant",
    "consultante", "conseiller", "conseillere", "agent", "collaborateur", "collaboratrice",
    "employe", "technicien", "technicienne", "operateur", "operator", "coordinateur",
    "coordinator", "administrateur", "administrator", "representative", "expert",
    "adjoint", "adjointe", "business", "senior", "director", "directeur", "head", "lead",
    "team", "equipe", "department", "service", "group", "groupe",
)}
POIDS_GENERIQUE = 0.4


def _poids_forme(terme: str, generiques: set[str]) -> float:
    """Un mot générique pèse moins ; une expression pèse selon ses deux mots."""
    if "|" in terme:
        a, b = terme.split("|", 1)
        return max(_poids_forme(a, generiques), _poids_forme(b, generiques))
    return POIDS_GENERIQUE if terme in generiques else 1.0


_GENERIQUES_CORPS = {canon(normaliser(m)) for m in GENERIQUES}

# Des mots que toute annonce emploie pour parler d'elle-même — le cadre, les
# avantages, la candidature — et qui ne disent rien de ce que le poste exige.
_BANALITES = {canon(normaliser(m)) for m in (
    "remuneration", "salaire", "salary", "avantage", "avantages", "benefits", "mutuelle",
    "ticket", "tickets", "restaurant", "prime", "primes", "conge", "conges", "rtt",
    "teletravail", "remote", "hybrid", "hybride", "cdi", "cdd", "contrat", "contract",
    "temps", "plein", "horaire", "horaires", "heure", "heures", "semaine", "jour", "jours",
    "lundi", "vendredi", "candidature", "candidatures", "postuler", "apply", "application",
    "recrutement", "recruteur", "recruiter", "recruitment", "cabinet", "handicap",
    "egalite", "diversite", "diversity", "inclusion", "rqth", "carriere", "career",
    "rejoindre", "rejoignez", "join", "integrer", "integrez", "filiale", "siege", "locaux",
    "ville", "region", "transport", "parking", "date", "debut", "demarrage", "start",
    "opportunite", "opportunity", "role", "company", "entreprise", "societe", "leader",
    "acteur", "croissance", "developpement", "dynamique", "passion", "valeur", "valeurs",
    "culture", "ambiance", "bienveillance", "annee", "annees", "ans", "year", "years",
    "euros", "eur", "brut", "k", "mois", "month", "work", "working", "vous", "notre",
    "etc", "description", "descriptif", "poste", "missions", "profil", "recherche",
    "recherchons", "souhaitez", "possible", "rapidement", "asap", "immediat",
)}


# --- 1. Le métier : l'intitulé face à ce que le candidat vise --------------------------

# Deux sens : le rappel (l'offre reprend-elle un intitulé visé ?) et la
# précision (le candidat parle-t-il le vocabulaire de l'intitulé de l'offre ?),
# combinés par `combiner_metier`.
# Un intitulé visé d'un seul mot banal — « Finance » — ne peut pas, à lui seul,
# faire d'une offre une offre ciblée. Sa spécificité se mesure à l'IDF de ses
# mots dans le corps des annonces : il en faut ce total pour peser pleinement.
SPECIFICITE_PLEINE = 3.0
# Un second intitulé visé retrouvé dans la même offre ajoute un peu : deux
# recherches qui se rejoignent sont une preuve de plus.
BONUS_SECOND_INTITULE = 0.2
# Poids du CV à partir duquel un terme est « pleinement » connu du candidat.
POIDS_PLEIN = 0.7


def _couvert(cible: ProfilCible, terme: str) -> float:
    return min(1.0, cible.poids(terme) / POIDS_PLEIN)


def score_metier(cible: ProfilCible, signaux: Signaux, corpus: Corpus,
                 resultat: "Resultat") -> float | None:
    intitule = set(signaux.intitule) | set(signaux.intitule_bigrammes)
    if not signaux.intitule or not cible.intitules:
        return None

    def poids(terme: str) -> float:
        # La racine de l'IDF : un mot rare de l'intitulé (« Guardian ») ne doit
        # pas écraser à lui seul tout ce que le candidat reconnaît.
        return _poids_forme(terme, _GENERIQUES_INTITULE) * math.sqrt(corpus.idf_intitule(terme))

    # Le rappel : le meilleur intitulé visé retrouvé dans celui de l'offre.
    notes = []
    for visé in cible.intitules:
        termes = set(visé.jetons) | visé.bigrammes
        total = sum(poids(t) for t in termes)
        if total <= 0:
            continue
        trouve = [t for t in termes if t in intitule]
        proportion = sum(poids(t) for t in trouve) / total
        specificite = min(1.0, sum(corpus.idf_corps(t) for t in set(visé.jetons))
                          / SPECIFICITE_PLEINE)
        notes.append((proportion * specificite * visé.poids, visé, trouve))
    notes.sort(key=lambda n: -n[0])
    rappel = 0.0
    if notes and notes[0][0] > 0:
        second = notes[1][0] if len(notes) > 1 else 0.0
        rappel = min(1.0, notes[0][0] + BONUS_SECOND_INTITULE * second)
        resultat.intitule_vise = notes[0][1].libelle
        resultat.intitule_origine = notes[0][1].origine

    # La précision : les mots de l'intitulé de l'offre que le CV connaît. Les
    # expressions n'y entrent que reconnues : « Trading Risk and Control » était
    # pénalisé parce que le CV ne dit pas « risk trading », alors qu'il connaît
    # chacun des mots. Une association nouvelle n'est pas un mot inconnu.
    connus = {t: _couvert(cible, t) for t in intitule}
    comptes = [t for t in intitule if "|" not in t or connus[t] > 0]
    total = sum(poids(t) for t in comptes)
    precision = sum(poids(t) * connus[t] for t in comptes) / total if total else 0.0
    resultat.intitule_connus = [t for t in signaux.intitule if connus.get(t, 0) >= 0.5]
    resultat.intitule_inconnus = [t for t in signaux.intitule
                                  if connus.get(t, 0) < 0.5 and t not in _GENERIQUES_INTITULE]
    resultat.metier_rappel, resultat.metier_precision = rappel, precision
    return 100.0 * combiner_metier(rappel, precision)


def combiner_metier(rappel: float, precision: float) -> float:
    """Moyenne harmonique : les deux sens sont nécessaires. Reprendre un
    intitulé visé ne suffit pas si le reste de l'intitulé parle d'un autre
    métier (« Ingénieur analyses de risques cybersécurité » face à une recherche
    « analyste risques ») ; parler le vocabulaire du CV ne suffit pas si le
    poste n'est aucun de ceux que le candidat cherche. Mesuré contre les
    étiquettes posées à la main, elle devance toute moyenne pondérée."""
    return 2 * rappel * precision / (rappel + precision) if rappel + precision else 0.0


# --- 2. Le contenu : ce que l'annonce demande, face à ce que le CV contient -------------
#
# Une similarité cosinus entre deux vecteurs pondérés : l'annonce (chaque terme
# selon sa répétition et sa rareté) et le CV (chaque terme selon l'endroit où il
# apparaît). Un terme rare que les deux partagent pèse lourd ; le bruit propre à
# une seule annonce — un nom propre, un voisinage fortuit — ne fait que diluer.
#
# Une première version extrayait les « termes clés » de l'annonce, puis
# mesurait leur couverture : sur des annonces courtes, où chaque mot n'apparaît
# qu'une fois, « le plus rare » n'était pas « le plus exigé », et la liste se
# remplissait de « Sopra », « Steria » et « autonome, méthodique ».

# Une expression partagée (« risque de crédit ») pèse plus qu'un mot.
BONUS_EXPRESSION = 1.3
# L'intitulé dit ce qu'est le poste : ses mots comptent aussi dans le contenu.
POIDS_INTITULE_CONTENU = 2.0
# Combien d'annonces doivent employer un mot, ou une expression, pour qu'il
# compte : vu une seule fois, c'est presque toujours un nom propre, une coquille
# ou un voisinage fortuit — et sa rareté lui donnait le poids le plus fort.
MINIMUM_MOT, MINIMUM_EXPRESSION = 3, 4
# La similarité se lit par rapport aux meilleures offres du compte : celle qui
# atteint ce centile vaut 100. Sans étalonnage (un score calculé isolément), on
# retient `REFERENCE_PAR_DEFAUT`. Un plancher empêche qu'un fil sans aucune
# bonne offre fasse passer la moins mauvaise pour excellente.
CENTILE_REFERENCE = 0.95
REFERENCE_PAR_DEFAUT = 0.05
REFERENCE_MINIMALE = 0.02


def vecteur_offre(signaux: Signaux, corpus: Corpus) -> dict[str, float]:
    vecteur: dict[str, float] = {}
    for terme, frequence in signaux.corps.items():
        if (terme in _BANALITES or terme in CREUX or len(terme) < 2 or terme.isdigit()
                or not corpus.etabli(terme, MINIMUM_MOT)):
            continue
        vecteur[terme] = ((1 + math.log(frequence)) * corpus.idf_corps(terme)
                          * _poids_forme(terme, _GENERIQUES_CORPS))
    for expression in signaux.corps_bigrammes:
        a, b = expression.split("|", 1)
        if {a, b} & (_BANALITES | CREUX) or not corpus.etabli(expression, MINIMUM_EXPRESSION):
            continue
        vecteur[expression] = (BONUS_EXPRESSION * corpus.idf_corps(expression)
                               * _poids_forme(expression, _GENERIQUES_CORPS))
    for terme in [*signaux.intitule, *signaux.intitule_bigrammes]:
        vecteur[terme] = vecteur.get(terme, 0.0) + POIDS_INTITULE_CONTENU * corpus.idf_corps(
            terme) * _poids_forme(terme, _GENERIQUES_CORPS)
    return vecteur


def vecteur_cv(cible: ProfilCible, corpus: Corpus) -> dict[str, float]:
    return {t: p * corpus.idf_corps(t) * _poids_forme(t, _GENERIQUES_CORPS)
            for t, p in cible.vocabulaire.items() if t not in _BANALITES}


def similarite(cv: dict[str, float], offre: dict[str, float]) -> tuple[float, dict[str, float]]:
    """Cosinus, et la contribution de chaque terme partagé."""
    communs = {t: offre[t] * cv[t] for t in offre.keys() & cv.keys()}
    normes = math.sqrt(sum(v * v for v in offre.values())) * math.sqrt(
        sum(v * v for v in cv.values()))
    return (sum(communs.values()) / normes if normes else 0.0), communs


def etalonner(cible: ProfilCible, signaux: list[Signaux], corpus: Corpus) -> None:
    """Fixe la similarité qui vaut 100 : le centile `CENTILE_REFERENCE` des
    offres du compte. Appelé une fois par scoring, avant les offres."""
    cv = vecteur_cv(cible, corpus)
    valeurs = sorted(similarite(cv, vecteur_offre(s, corpus))[0] for s in signaux if s.corps)
    if valeurs:
        rang = min(len(valeurs) - 1, int(CENTILE_REFERENCE * len(valeurs)))
        cible.reference_contenu = max(REFERENCE_MINIMALE, valeurs[rang])
    cible.vecteur = cv


def score_competences(cible: ProfilCible, signaux: Signaux, corpus: Corpus,
                      resultat: "Resultat") -> float | None:
    if not (signaux.corps or signaux.intitule) or not cible.vocabulaire:
        return None
    cv = cible.vecteur if cible.vecteur is not None else vecteur_cv(cible, corpus)
    offre = vecteur_offre(signaux, corpus)
    valeur, communs = similarite(cv, offre)
    reference = cible.reference_contenu or REFERENCE_PAR_DEFAUT

    resultat.cles_couvertes = [t for t, _ in sorted(communs.items(), key=lambda kv: -kv[1])
                               if "|" not in t][:8]
    resultat.cles_manquantes = [t for t, _ in sorted(offre.items(), key=lambda kv: -kv[1])
                                if t not in cv and "|" not in t][:6]
    return min(100.0, 100.0 * valeur / reference)


# --- 3. Le niveau du poste ------------------------------------------------------------

# Écart de niveau (poste - candidat) -> note. Un cran en dessous reste
# accessible ; au-dessus, la porte se ferme vite — c'est ce qui filtrera la
# candidature, avant même la lecture du CV.
NOTE_ECART = {-3: 60.0, -2: 70.0, -1: 90.0, 0: 100.0, 1: 65.0, 2: 30.0, 3: 5.0}
# Années chiffrées : réclamer un an de plus ne ferme rien, cinq de plus, si.
ECART_INDIFFERENT = 1
ECART_REDHIBITOIRE = 6


def niveau_candidat(annees: int) -> str:
    if annees < 2:
        return "junior"
    if annees < 6:
        return "intermediaire"
    if annees < 10:
        return "confirme"
    return "encadrement"


def score_seniorite(cible: ProfilCible, signaux: Signaux, resultat: "Resultat") -> float | None:
    """Le poste est-il à la portée du candidat ? Le niveau que dit l'intitulé,
    et les années que chiffre l'annonce : la plus sévère des deux décide.

    Sans années d'expérience saisies, on ne juge pas : on ne note personne
    débutant faute de réponse.
    """
    if not cible.annees:
        return None
    resultat.niveau_poste = signaux.niveau_poste
    ecart = RANG[signaux.niveau_poste] - RANG[niveau_candidat(cible.annees)]
    note = NOTE_ECART[max(-3, min(3, ecart))]
    if signaux.niveau_poste == "stage" and cible.accepte_stage:
        note = NOTE_ECART[-1]

    if signaux.annees_exigees:
        resultat.annees_exigees = signaux.annees_exigees
        manque = signaux.annees_exigees - cible.annees
        if manque >= ECART_REDHIBITOIRE:
            note_annees = 0.0
        elif manque <= ECART_INDIFFERENT:
            note_annees = 100.0
        else:
            note_annees = 100.0 * (ECART_REDHIBITOIRE - manque) / (
                ECART_REDHIBITOIRE - ECART_INDIFFERENT)
        note = min(note, note_annees)
    return note


# --- 4. Diplôme, certifications, statut -------------------------------------------------


def score_formation(cible: ProfilCible, signaux: Signaux, resultat: "Resultat") -> float | None:
    if signaux.statut_public:
        resultat.redhibitoires.append("poste réservé aux fonctionnaires titulaires")
        return 10.0
    manquantes = [c for c in signaux.certifications if c not in cible.certifications]
    if manquantes:
        resultat.redhibitoires.append(f"exige : {', '.join(manquantes)}")
        return 20.0
    if not signaux.etudes or cible.etudes is None:
        return None
    requis, plafond = min(signaux.etudes), max(signaux.etudes)
    resultat.etudes_demandees = (requis, plafond)
    if cible.etudes < requis:
        return max(0.0, 100.0 - 35.0 * (requis - cible.etudes))
    # Un poste à Bac+2 pour un Bac+5 n'est pas fermé — mais c'est rarement le
    # bon poste, et le recruteur le pensera aussi.
    if plafond <= cible.etudes - 3:
        return 55.0
    if plafond <= cible.etudes - 2:
        return 75.0
    return 100.0


# --- 5. La langue ---------------------------------------------------------------------------

NIVEAUX_LANGUE = {
    "natif": 100.0, "native": 100.0, "bilingue": 100.0, "bilingual": 100.0,
    "maternelle": 100.0, "maternel": 100.0, "courant": 100.0, "couramment": 100.0,
    "c2": 100.0, "c1": 100.0, "avance": 100.0, "avancee": 100.0, "fluent": 100.0,
    "proficient": 100.0,
    "intermediaire": 70.0, "intermediaires": 70.0, "intermediate": 70.0,
    "b2": 70.0, "b1": 70.0, "professionnel": 70.0, "professionnelle": 70.0,
    "operationnel": 70.0, "operationnelle": 70.0, "working": 70.0, "moyen": 70.0,
    "notions": 40.0, "notion": 40.0, "debutant": 40.0, "debutante": 40.0,
    "a2": 40.0, "a1": 40.0, "scolaire": 40.0, "scolaires": 40.0,
    "base": 40.0, "bases": 40.0, "basique": 40.0, "basic": 40.0,
    "elementaire": 40.0, "beginner": 40.0, "limite": 40.0, "limitee": 40.0,
}
# Niveau retenu quand la saisie n'est pas reconnue (« TOEIC 775 ») : jamais
# au-dessus d'« intermédiaire ».
NIVEAU_LANGUE_PAR_DEFAUT = 70.0


def _niveau_du_profil(profil: Profile, code: str) -> float | None:
    """Note du candidat pour cette langue, ou None s'il ne la parle pas.
    Plusieurs niveaux reconnus dans la même saisie ⇒ le plus prudent."""
    for langue in profil.langues:
        if (langue.get("code") or "").lower() != code:
            continue
        reconnus = [NIVEAUX_LANGUE[j] for j in mots(langue.get("niveau") or "")
                    if j in NIVEAUX_LANGUE]
        return min(reconnus) if reconnus else NIVEAU_LANGUE_PAR_DEFAUT
    return None


def score_langue(profil: Profile, signaux: Signaux) -> float | None:
    """La langue de rédaction ET celles que l'annonce exige : la plus dure décide."""
    if not profil.langues:
        return None
    notes: list[float] = []
    if signaux.langue:
        notes.append(_niveau_du_profil(profil, signaux.langue) or 0.0)
    for code in signaux.exigences_langues:
        notes.append(_niveau_du_profil(profil, code) or 0.0)
    if not notes:
        return None
    return min(notes)


# --- Conditions : lieu, contrat, fraîcheur ---------------------------------------------------

LOC_MEME_VILLE = 100.0
LOC_MEME_PAYS = 80.0
LOC_PAYS_ACCEPTE = 60.0
LOC_REFUSE = 0.0


def score_pays(profil: Profile, offre: Offer) -> float | None:
    """Quatre paliers : votre ville, votre pays, un pays accepté, un pays refusé."""
    if not profil.pays_acceptes or not offre.pays:
        return None
    if offre.pays not in profil.pays_acceptes:
        return LOC_REFUSE
    ville = set(mots(profil.ville))
    if ville and ville & set(mots(offre.lieu)):
        return LOC_MEME_VILLE
    if not profil.pays or offre.pays == profil.pays:
        return LOC_MEME_PAYS
    return LOC_PAYS_ACCEPTE


def score_contrat(profil: Profile, offre: Offer) -> float | None:
    acceptes = profil.contrats_acceptes
    if not acceptes or not offre.type_contrat:
        return None
    if offre.type_contrat not in acceptes:
        return 0.0
    if len(acceptes) == 1:
        return 100.0
    rang = acceptes.index(offre.type_contrat)
    return 100.0 - 40.0 * rang / (len(acceptes) - 1)


FRAICHEUR_PLEINE_JOURS = 7
FRAICHEUR_NULLE_JOURS = 120


def score_fraicheur(offre: Offer, aujourd_hui: datetime | None = None) -> float | None:
    """Décroissance linéaire entre une semaine et quatre mois : une valeur
    continue départage, des paliers recréeraient des égalités."""
    publiee = offre.date_publication or offre.date_recuperation
    if publiee is None:
        return None
    jours = ((aujourd_hui or maintenant()) - publiee).days
    if jours <= FRAICHEUR_PLEINE_JOURS:
        return 100.0
    if jours >= FRAICHEUR_NULLE_JOURS:
        return 0.0
    return 100.0 * (FRAICHEUR_NULLE_JOURS - jours) / (FRAICHEUR_NULLE_JOURS - FRAICHEUR_PLEINE_JOURS)


# --- Synthèse -----------------------------------------------------------------------------------

# Au-dessous de ces notes, le critère ferme la porte : le score est plafonné.
PLAFOND_REDHIBITOIRE = 15.0
SEUIL_LANGUE_REDHIBITOIRE = 0.0
SEUIL_NIVEAU_REDHIBITOIRE = 5.0
SEUIL_FORMATION_REDHIBITOIRE = 20.0


@dataclass
class Resultat:
    score: float
    hors_cible: bool = False
    detail: dict[str, float] = field(default_factory=dict)
    non_evaluables: list[str] = field(default_factory=list)
    pertinence: float = 0.0
    accessibilite: float | None = None
    conditions: float | None = None
    redhibitoires: list[str] = field(default_factory=list)
    # Matière de l'explication (jetons canoniques, remis en mots par explain.py).
    metier_rappel: float = 0.0
    metier_precision: float = 0.0
    intitule_vise: str = ""
    intitule_origine: str = ""
    intitule_connus: list[str] = field(default_factory=list)
    intitule_inconnus: list[str] = field(default_factory=list)
    cles_couvertes: list[str] = field(default_factory=list)
    cles_manquantes: list[str] = field(default_factory=list)
    niveau_poste: str = ""
    annees_exigees: int | None = None
    etudes_demandees: tuple[int, int] | None = None
    explication: str = ""


def _moyenne(notes: dict[str, float | None], poids: dict[str, float]) -> float | None:
    evaluables = {c: v for c, v in notes.items() if v is not None and poids.get(c, 0) > 0}
    total = sum(poids[c] for c in evaluables)
    if not total:
        return None
    return sum(v * poids[c] for c, v in evaluables.items()) / total


def calculer(
    profil: Profile,
    offre: Offer,
    signaux: Signaux,
    poids: PoidsScoring,
    cible: ProfilCible,
    corpus: Corpus = NEUTRE,
) -> Resultat:
    resultat = Resultat(score=0.0)

    notes: dict[str, float | None] = {
        "metier": score_metier(cible, signaux, corpus, resultat),
        "competences": score_competences(cible, signaux, corpus, resultat),
        "seniorite": score_seniorite(cible, signaux, resultat),
        "formation": score_formation(cible, signaux, resultat),
        "langue": score_langue(profil, signaux),
        "pays": score_pays(profil, offre),
        "contrat": score_contrat(profil, offre),
        "fraicheur": score_fraicheur(offre),
    }
    resultat.non_evaluables = [c for c in CRITERES if notes[c] is None]
    resultat.detail = {c: round(v, 1) for c, v in notes.items() if v is not None}

    # Ni le métier ni les exigences ne se jugent : on ne sait rien dire de
    # l'adéquation, et les conditions seules ne feront pas un score.
    if notes["metier"] is None and notes["competences"] is None:
        return resultat

    ponderation = poids.normalises()
    pertinence = _moyenne({c: notes[c] for c in CRITERES_PERTINENCE}, ponderation) or 0.0
    accessibilite = _moyenne({c: notes[c] for c in CRITERES_ACCESSIBILITE}, ponderation)
    conditions = _moyenne({c: notes[c] for c in CRITERES_CONDITIONS}, ponderation)
    resultat.pertinence = round(pertinence, 1)
    resultat.accessibilite = round(accessibilite, 1) if accessibilite is not None else None
    resultat.conditions = round(conditions, 1) if conditions is not None else None

    def facteur(valeur: float | None, part: float) -> float:
        # Non évaluable : rien à retirer.
        return 1.0 if valeur is None else 1 - part + part * valeur / 100

    brut = (pertinence * facteur(accessibilite, poids.part_accessibilite)
            * facteur(conditions, poids.part_conditions))

    # --- Ce qui ferme la porte, quoi qu'il arrive ailleurs ---
    if notes["langue"] is not None and notes["langue"] <= SEUIL_LANGUE_REDHIBITOIRE:
        resultat.redhibitoires.append("annonce dans une langue que vous ne parlez pas")
    if notes["seniorite"] is not None and notes["seniorite"] <= SEUIL_NIVEAU_REDHIBITOIRE:
        resultat.redhibitoires.append("poste hors de portée en expérience")
    if notes["contrat"] == 0.0:
        resultat.redhibitoires.append("contrat que vous n'acceptez pas")
    if notes["pays"] == LOC_REFUSE:
        resultat.redhibitoires.append("pays que vous n'acceptez pas")
    if resultat.redhibitoires:
        resultat.hors_cible = True
        brut = min(brut, PLAFOND_REDHIBITOIRE)

    resultat.score = round(brut, 1)
    return resultat
