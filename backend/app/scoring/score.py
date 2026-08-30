"""Le calcul du score — code pur, déterministe, sans réseau ni LLM.

Deux propriétés à préserver :

- **Rejouable.** Mêmes entrées, même score, toujours. Changer un poids dans
  `config.yaml` recalcule tout sans rien réinterroger.
- **Explicable.** Chaque sous-score se justifie en une ligne (cf. `explain.py`).

Un critère qu'on ne peut pas juger (profil incomplet) vaut `None` : son poids est
alors **redistribué** sur les autres. Lui donner 0 punirait l'offre pour une
lacune du profil ; lui donner 100 fabriquerait un score flatteur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re

from rapidfuzz import fuzz, process

from ..config import PoidsScoring
from ..models import Offer, Profile
from ..models.base import maintenant
from .extraction import Signaux
from .synonymes import present as synonyme_present
from .texte import mots, poids_jeton

CRITERES = ("competences", "secteur", "pays", "seniorite", "langue",
            "contrat", "fraicheur")

# La fraîcheur ne dit rien de l'ADÉQUATION : elle mesure si l'annonce est encore
# ouverte, pas si le poste convient. Elle est donc exclue du fond — sans quoi un
# profil vide, dont aucun critère de fond n'est évaluable, verrait la
# redistribution lui donner tout le poids et sortir un score de 100 sur une
# offre que personne n'a pu juger.
CRITERES_DE_FOND = tuple(c for c in CRITERES if c != "fraicheur")

# Une annonce ne cite jamais tout un profil : on mesure la QUALITÉ des meilleures
# correspondances, pas la proportion de compétences citées. Sans quoi le score
# serait mécaniquement plafonné à 20 % pour un profil un peu fourni.
# Trois parts, et non deux. La première version ne retenait QUE la meilleure
# ancrée pour 60 % du critère : le nombre d'ancrées reconnues était ignoré.
# Mesuré sur 2 490 offres, le résultat était perverti — une offre reconnaissant
# trois compétences signature obtenait 40 sur ce critère, MOINS que la moyenne
# (36,1) de celles qui n'en reconnaissaient qu'une, et 83 des 84 offres à
# égalité sur 76 points avaient exactement une ancrée trouvée. C'était la
# machine à égalités.
PART_MEILLEURE_ANCREE = 0.50   # la signature qui colle le mieux
PART_AUTRES_ANCREES = 0.25     # combien d'AUTRES signatures collent aussi
PART_PERIPHERIQUES = 0.25      # les compétences non ancrées
# Au-delà de la meilleure, deux ancrées supplémentaires suffisent : une annonce
# ne cite jamais tout un profil.
NB_ANCREES_ATTENDUES = 2
NB_AUTRES_ATTENDUES = 3      # au-delà, une annonce n'en dit pas plus
# Ressemblance minimale pour accepter une variante (gestion / gestionnaire).
SEUIL_FLOU = 88
# Une correspondance approximative ne vaut jamais une correspondance exacte.
CREDIT_FLOU = 0.8
# Proportion des mots d'une compétence à retrouver pour la dire « trouvée ».
SEUIL_TROUVEE = 0.5
# Secteur reconnu seulement dans le corps de l'annonce, pas dans l'intitulé.
CREDIT_SECTEUR_FAIBLE = 0.6
# Un secteur d'UN SEUL mot reconnu dans le corps n'est presque pas une preuve :
# « Finance » cité une fois dans deux mille mots donnait 60 sur ce critère à un
# poste de pharmacovigilance. Dans l'intitulé, en revanche, le même mot reste un
# signal fort — c'est le sujet de l'annonce.
CREDIT_SECTEUR_UN_MOT = 0.3

# --- Séniorité ---------------------------------------------------------------
# Une annonce qui réclame dix ans d'expérience quand on en a trois n'est pas une
# bonne offre, si bien notée soit-elle par ailleurs. Le signal ne couvre qu'une
# annonce sur dix : le reste du temps le critère n'est pas évaluable, et son
# poids est redistribué — c'est exactement l'usage prévu pour ce mécanisme.

_ANNEES_EXIGEES = re.compile(
    r"(\d{1,2})\s*(?:\+|ans?|années?)\s*(?:\+)?\s*(?:minimum|mini|au moins)?\s*"
    r"(?:d[e'’]\s*)?(?:exp[ée]rience|exp\b)", re.IGNORECASE)

_JUNIOR = re.compile(
    r"\bjunior\b|\bd[ée]butant|jeune dipl[oô]m|premi[eè]re exp[ée]rience|"
    r"sans exp[ée]rience|profil junior", re.IGNORECASE)
_SENIOR = re.compile(
    r"\bsenior\b|\bconfirm[ée]s?\b|\bexp[ée]riment[ée]s?\b|\bexpert\b|"
    r"\bdirecteur\b|\bhead of\b|\bchief\b", re.IGNORECASE)

# Écart toléré avant de pénaliser : réclamer un an de plus que ce qu'on a ne
# ferme aucune porte, en réclamer cinq de plus, si.
ECART_INDIFFERENT = 1
ECART_REDHIBITOIRE = 6

# Sans années chiffrées, on se rabat sur le vocabulaire. Un profil junior face à
# une annonce « senior » perd, mais pas tout : les intitulés mentent souvent.
SENIORITE_VOCABULAIRE_CONTRE = 40.0
SENIORITE_VOCABULAIRE_POUR = 100.0

# Au-dessous, on se considère junior. Volontairement bas : c'est le seuil à
# partir duquel une annonce « confirmé » cesse d'être hors de portée.
ANNEES_JUNIOR = 4


def score_seniorite(profil: Profile, offre: Offer) -> float | None:
    """L'offre est-elle à la portée du candidat, en termes d'ancienneté ?

    Deux signaux, dans cet ordre : les années chiffrées quand l'annonce en
    donne, le vocabulaire sinon. Ni l'un ni l'autre n'étant présent, le critère
    n'est pas évaluable — et son poids part sur les autres.
    """
    if not profil.annees_experience:
        return None

    texte = f"{offre.titre or ''} {offre.description_brute or ''}"

    exigees = [int(m.group(1)) for m in _ANNEES_EXIGEES.finditer(texte)]
    if exigees:
        # La plus forte exigence décide : c'est elle qui filtrera la candidature.
        ecart = max(exigees) - profil.annees_experience
        if ecart <= ECART_INDIFFERENT:
            return 100.0
        if ecart >= ECART_REDHIBITOIRE:
            return 0.0
        reste = (ECART_REDHIBITOIRE - ecart) / (ECART_REDHIBITOIRE - ECART_INDIFFERENT)
        return 100.0 * reste

    junior = profil.annees_experience < ANNEES_JUNIOR
    if _SENIOR.search(texte):
        return SENIORITE_VOCABULAIRE_CONTRE if junior else SENIORITE_VOCABULAIRE_POUR
    if _JUNIOR.search(texte):
        return SENIORITE_VOCABULAIRE_POUR if junior else SENIORITE_VOCABULAIRE_CONTRE
    return None


# --- Fraîcheur ----------------------------------------------------------------
# Une annonce de septembre 2023 notait exactement comme celle de ce matin. Le
# signal est renseigné sur 100 % des offres et s'étale de 0 à 1 072 jours :
# c'est le meilleur départageur dont on dispose.
#
# **Ce critère dépend du jour où l'on score.** La promesse « mêmes entrées, même
# score » tient toujours — la date du jour EST une entrée — mais un score stocké
# vieillit. `services/scoring.py` rescore donc ce qui a plus d'un jour ; sur
# 2 490 offres l'opération prend une seconde.
FRAICHEUR_PLEINE_JOURS = 7      # une offre de la semaine vaut le maximum
FRAICHEUR_NULLE_JOURS = 120     # au-delà, elle n'est probablement plus ouverte


def score_fraicheur(offre: Offer, aujourd_hui: datetime | None = None) -> float | None:
    """Décroissance linéaire entre une semaine et quatre mois.

    Linéaire et non par paliers : une valeur continue départage, des paliers
    recréeraient les égalités qu'on cherche à défaire.
    """
    publiee = offre.date_publication or offre.date_recuperation
    if publiee is None:
        return None
    # `maintenant()` et non `datetime.utcnow()` : le second est déprécié
    # depuis Python 3.12, et c'est déjà l'horloge de toute la base — les
    # dates stockées sont en UTC naïf, la comparaison doit l'être aussi.
    jours = ((aujourd_hui or maintenant()) - publiee).days
    if jours <= FRAICHEUR_PLEINE_JOURS:
        return 100.0
    if jours >= FRAICHEUR_NULLE_JOURS:
        return 0.0
    reste = (FRAICHEUR_NULLE_JOURS - jours) / (FRAICHEUR_NULLE_JOURS - FRAICHEUR_PLEINE_JOURS)
    return 100.0 * reste


# Le niveau est saisi en texte libre : il faut couvrir les deux nombres et les
# deux langues, sans quoi une saisie non reconnue tombe sur le repli.
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
# Niveau retenu quand la saisie n'est pas reconnue. Il valait 85 — au-dessus
# d'« intermédiaire » — ce qui faisait passer une saisie incomprise pour une
# quasi-maîtrise : « TOEIC 775 » et « Notion » d'allemand étaient tous deux lus
# comme 85. Deux tiers des offres tiraient leur note de ce repli.
NIVEAU_LANGUE_PAR_DEFAUT = 70.0


@dataclass
class Resultat:
    score: float
    hors_cible: bool = False
    detail: dict[str, float] = field(default_factory=dict)
    non_evaluables: list[str] = field(default_factory=list)
    # Matière première de l'explication.
    ancrees_trouvees: list[str] = field(default_factory=list)
    ancrees_manquantes: list[str] = field(default_factory=list)
    autres_trouvees: list[str] = field(default_factory=list)
    secteur_reconnu: str = ""
    explication: str = ""


# --------------------------------------------------------------- compétences


def presence(terme: str, vocabulaire: set[str], *, flou: bool) -> float:
    """À quel point `terme` est présent dans le vocabulaire : de 0 à 1.

    Une compétence est souvent une expression (« gestion des risques de crédit »)
    qu'aucune annonce ne reprend mot pour mot. On mesure donc la **proportion
    pondérée** de ses mots retrouvés : les mots génériques (gestion, analyse…)
    comptent moins que les mots spécifiques (trésorerie, crédit).
    """
    jetons = mots(terme)
    if not jetons:
        return 0.0

    total = obtenu = 0.0
    for jeton in jetons:
        poids = poids_jeton(jeton)
        total += poids
        # Les synonymes comptent comme le mot lui-même : « risques de crédit »
        # doit rencontrer « credit risk », sinon la moitié du marché est écartée.
        if synonyme_present(jeton, vocabulaire):
            obtenu += poids
        elif flou:
            # Variante proche (gestion/gestionnaire) : jamais autant qu'un mot exact.
            proche = process.extractOne(
                jeton, vocabulaire, scorer=fuzz.ratio, score_cutoff=SEUIL_FLOU
            )
            if proche is not None:
                obtenu += poids * (proche[1] / 100.0) * CREDIT_FLOU

    return obtenu / total if total else 0.0


def score_competences(profil: Profile, signaux: Signaux, resultat: Resultat,
                      vocabulaire: set[str] | None = None) -> float | None:
    """Qualité de la correspondance, pas taux de couverture.

    - 50 % : la **meilleure** compétence ancrée retrouvée. Une signature qui
      colle vaut toujours plus que dix compétences périphériques.
    - 25 % : combien d'AUTRES ancrées sont reconnues, plafonné à deux. C'est
      cette part qui départage : sans elle, reconnaître trois signatures
      rapportait autant qu'en reconnaître une seule.
    - 25 % : les compétences non ancrées retrouvées, plafonné à trois.

    On mesure toujours la qualité, jamais le taux de couverture — une annonce
    ne cite jamais tout un profil. Mais à qualité égale, en reconnaître
    davantage doit valoir davantage.

    Un profil sans compétence ancrée est jugé sur la dernière part seule.
    """
    if not profil.skills:
        return None

    def _nb(skills: list[dict], *, ancree: bool) -> int:
        return sum(1 for s in skills if bool(s.get("ancree")) is ancree and s.get("nom"))

    if vocabulaire is None:
        vocabulaire = set(signaux.vocabulaire)
    meilleure_ancree = 0.0
    ancrees_trouvees = 0
    a_des_ancrees = False
    somme_autres = 0.0

    for skill in profil.skills:
        nom = skill.get("nom") or ""
        if not nom:
            continue
        ancree = bool(skill.get("ancree"))
        # Une compétence ancrée est une signature : pas d'à-peu-près dessus.
        trouvee = presence(nom, vocabulaire, flou=not ancree)

        if ancree:
            a_des_ancrees = True
            meilleure_ancree = max(meilleure_ancree, trouvee)
            if trouvee >= SEUIL_TROUVEE:
                ancrees_trouvees += 1
                resultat.ancrees_trouvees.append(nom)
            else:
                resultat.ancrees_manquantes.append(nom)
        elif trouvee >= SEUIL_TROUVEE:
            # Seules les compétences réellement retrouvées comptent. Additionner
            # les correspondances sous le seuil laissait dix compétences frôlant
            # un mot générique saturer cette moitié du score : une offre de
            # boulangerie atteignait 83/100 sur un profil finance, sans qu'aucune
            # compétence ne soit rapportée à l'utilisateur.
            somme_autres += trouvee
            resultat.autres_trouvees.append(nom)

    # Le dénominateur est ce que le PROFIL peut offrir, pas un idéal abstrait.
    #
    # Mesuré : un profil de six compétences, dont deux seulement non ancrées, ne
    # pouvait jamais dépasser 2/3 sur ce quart du score — quelle que soit
    # l'offre. Le critère plafonnait à 77,6 sur 2 490 annonces là où tous les
    # autres atteignent 100, ce qui fausse la moyenne pondérée : lui donner
    # 35 % du poids revenait à réserver des points que personne ne peut gagner.
    # On pénalisait le candidat pour la forme de son profil, pas pour
    # l'adéquation de l'annonce.
    attendues_autres = min(NB_AUTRES_ATTENDUES, _nb(profil.skills, ancree=False)) or 1
    part_autres = min(1.0, somme_autres / attendues_autres)
    if not a_des_ancrees:
        return 100.0 * part_autres

    # La meilleure ancrée est déjà comptée par `meilleure_ancree` : on ne
    # dénombre ici que les SUIVANTES — d'où le « - 1 » des deux côtés.
    attendues_ancrees = min(NB_ANCREES_ATTENDUES, _nb(profil.skills, ancree=True) - 1) or 1
    part_ancrees = min(1.0, max(0, ancrees_trouvees - 1) / attendues_ancrees)
    return 100.0 * (
        PART_MEILLEURE_ANCREE * meilleure_ancree
        + PART_AUTRES_ANCREES * part_ancrees
        + PART_PERIPHERIQUES * part_autres
    )


# ------------------------------------------------------------------- secteur


def score_secteur(profil: Profile, signaux: Signaux, resultat: Resultat,
                  vocabulaire: set[str] | None = None) -> float | None:
    """Le secteur se mesure comme les compétences, avec `presence`.

Il utilisait une simple appartenance d'ensemble, donc sans les synonymes ni
    la pondération des mots génériques : « Finance » ne rencontrait jamais
    « financial markets », et un secteur reconnu sur le seul mot « gestion »
    valait autant qu'un secteur reconnu en entier. Sur un critère qui pèse 25 %,
    un quart des offres en sortaient sous-notées.

    Le crédit accordé au corps de l'annonce dépend de la **spécificité** du
    secteur : « Banque et assurance » reconnu en entier est une preuve,
    « Finance » croisé une fois dans deux mille mots n'en est pas une.
    """
    if not profil.secteurs:
        return None

    mots_titre = set(mots(signaux.texte_secteur))
    mots_corps = set(signaux.vocabulaire) if vocabulaire is None else vocabulaire

    meilleur = 0.0
    for secteur in profil.secteurs:
        # Reconnu dans l'intitulé ou le libellé ROME : signal fort.
        fort = presence(secteur, mots_titre, flou=False) * 100.0
        # Seulement dans le corps de l'annonce : signal plus faible, et plus
        # faible encore si le secteur tient en un mot — un terme courant croisé
        # au détour d'une longue annonce ne dit rien du métier.
        credit = (CREDIT_SECTEUR_FAIBLE if len(mots(secteur)) > 1
                  else CREDIT_SECTEUR_UN_MOT)
        faible = presence(secteur, mots_corps, flou=False) * 100.0 * credit
        # Le meilleur des deux, et non « le fort sauf s'il est nul » : un titre
        # à moitié reconnu écrasait un corps qui, lui, reconnaissait tout — le
        # critère n'était pas monotone, un titre muet valait mieux.
        valeur = max(fort, faible)
        if valeur > meilleur:
            meilleur, resultat.secteur_reconnu = valeur, secteur
    return meilleur


# ----------------------------------------------------- pays, langue, contrat


# Quatre paliers plutôt qu'un oui/non. Le critère était binaire : 99 % des
# offres retenues valaient 100, si bien que 15 % du poids ne départageait
# strictement rien — un poste à Morristown, New Jersey, notait exactement comme
# un poste à Paris. Le lieu est pourtant renseigné sur 99,9 % des offres, et
# déménager n'est pas un détail.
LOC_MEME_VILLE = 100.0
LOC_MEME_PAYS = 80.0
LOC_PAYS_ACCEPTE = 60.0     # accepté, donc pas pénalisé — mais pas équivalent
LOC_REFUSE = 0.0


def score_pays(profil: Profile, offre: Offer) -> float | None:
    """À quel point l'offre est commodément située, de 0 à 100.

    Un pays accepté reste noté haut : le candidat a dit oui, on ne le punit
    pas. Mais « oui, j'irais » et « c'est à côté de chez moi » ne sont pas la
    même chose, et le score doit savoir les distinguer.

    La ville se reconnaît par appariement de jetons, sans table de communes :
    les sources écrivent « 75 - Paris », « Paris, Ile-de-France » ou « Paris »
    selon leur humeur, et le nom suffit à les rapprocher.
    """
    if not profil.pays_acceptes or not offre.pays:
        return None
    if offre.pays not in profil.pays_acceptes:
        return LOC_REFUSE

    ville = set(mots(profil.ville))
    if ville and ville & set(mots(offre.lieu)):
        return LOC_MEME_VILLE

    # Sans pays de résidence renseigné, on ne sait pas distinguer « chez moi »
    # de « à l'étranger » : on ne le devine pas, et on ne pénalise personne.
    # Toutes les offres acceptées valent alors le palier du même pays, la ville
    # restant le seul moyen de se démarquer.
    if not profil.pays or offre.pays == profil.pays:
        return LOC_MEME_PAYS
    return LOC_PAYS_ACCEPTE


def _niveau_du_profil(profil: Profile, code: str) -> float | None:
    """Note du candidat pour cette langue, ou None s'il ne la parle pas.

    Plusieurs niveaux reconnus dans la même saisie ⇒ on retient **le plus
    prudent** : « courant (B2) » vaut B2, pas « courant ». Retenir le premier
    jeton rencontré surestimait le candidat selon l'ordre de sa frappe.
    """
    for langue in profil.langues:
        if (langue.get("code") or "").lower() != code:
            continue
        reconnus = [NIVEAUX_LANGUE[j] for j in mots(langue.get("niveau") or "")
                    if j in NIVEAUX_LANGUE]
        return min(reconnus) if reconnus else NIVEAU_LANGUE_PAR_DEFAUT
    return None


def score_langue(profil: Profile, signaux: Signaux) -> float | None:
    """Deux questions distinctes : la langue dans laquelle l'annonce est écrite,
    et celles qu'elle **exige**.

    Une offre en français réclamant « anglais courant » était jugée
    parfaitement accessible : seule la langue de rédaction comptait. C'est
    l'exigence la plus dure qui décide.
    """
    if not profil.langues:
        return None

    notes: list[float] = []
    if signaux.langue:
        notes.append(_niveau_du_profil(profil, signaux.langue) or 0.0)
    for code in signaux.exigences_langues:
        notes.append(_niveau_du_profil(profil, code) or 0.0)

    if not notes:
        return None      # texte trop court, aucune exigence : on ne pénalise pas
    return min(notes)


def score_contrat(profil: Profile, offre: Offer) -> float | None:
    acceptes = profil.contrats_acceptes
    if not acceptes or not offre.type_contrat:
        return None
    if offre.type_contrat not in acceptes:
        return 0.0
    if len(acceptes) == 1:
        return 100.0
    # L'ordre porte la préférence, mais un contrat accepté reste acceptable :
    # on descend de 100 à 60, pas jusqu'à zéro.
    rang = acceptes.index(offre.type_contrat)
    return 100.0 - 40.0 * rang / (len(acceptes) - 1)


# ------------------------------------------------------------------ synthèse


def calculer(
    profil: Profile,
    offre: Offer,
    signaux: Signaux,
    poids: PoidsScoring,
    plafond_hors_cible: float = 100.0,
) -> Resultat:
    resultat = Resultat(score=0.0)

    # Construit une fois : les deux critères qui s'en servent le reconstruisaient
    # chacun de leur côté, sur plusieurs centaines de mots, pour chaque offre.
    vocabulaire = set(signaux.vocabulaire)

    sous_scores: dict[str, float | None] = {
        "competences": score_competences(profil, signaux, resultat, vocabulaire),
        "secteur": score_secteur(profil, signaux, resultat, vocabulaire),
        "pays": score_pays(profil, offre),
        "seniorite": score_seniorite(profil, offre),
        "langue": score_langue(profil, signaux),
        "contrat": score_contrat(profil, offre),
        "fraicheur": score_fraicheur(offre),
    }

    normalises = poids.normalises()
    evaluables = {c: v for c, v in sous_scores.items() if v is not None}
    resultat.non_evaluables = [c for c in CRITERES if sous_scores[c] is None]
    resultat.detail = {c: round(v, 1) for c, v in evaluables.items()}

    # Aucun critère de fond évaluable : il n'y a rien à dire de cette offre, et
    # la fraîcheur seule ne fera pas un score.
    if not any(sous_scores[c] is not None for c in CRITERES_DE_FOND):
        return resultat

    poids_utile = sum(normalises[c] for c in evaluables)
    if poids_utile == 0:
        return resultat

    # Redistribution : le poids des critères non évaluables est réparti au
    # prorata sur ceux qui le sont.
    brut = sum(valeur * normalises[c] for c, valeur in evaluables.items()) / poids_utile

    # Ni les compétences ni le secteur ne correspondent : pays, langue et contrat
    # sont des filtres, pas des mérites. Une offre hors cible ne doit pas remonter
    # au seul motif qu'elle est en CDI près de chez soi.
    #
    # `None` compte ici comme un 0, volontairement : un critère non évaluable
    # n'est pas une preuve de pertinence, et une offre dont on ne peut juger ni
    # les compétences ni le secteur ne doit pas remonter. C'est la seule entorse
    # assumée à la règle « non évaluable ⇒ pas de pénalité », et elle ne change
    # rien tant qu'un des deux critères est évaluable.
    pertinence = max(sous_scores.get("competences") or 0.0,
                     sous_scores.get("secteur") or 0.0)
    if pertinence <= 0.0 and brut > plafond_hors_cible:
        resultat.hors_cible = True
        brut = plafond_hors_cible

    resultat.score = round(brut, 1)
    return resultat
