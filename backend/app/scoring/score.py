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

from rapidfuzz import fuzz, process

from ..config import PoidsScoring
from ..models import Offer, Profile
from .extraction import Signaux
from .synonymes import present as synonyme_present
from .texte import mots, poids_jeton

CRITERES = ("competences", "secteur", "pays", "langue", "contrat")

# Une annonce ne cite jamais tout un profil : on mesure la QUALITÉ des meilleures
# correspondances, pas la proportion de compétences citées. Sans quoi le score
# serait mécaniquement plafonné à 20 % pour un profil un peu fourni.
PART_ANCREES = 0.6           # ce que pèse la meilleure compétence signature
NB_AUTRES_ATTENDUES = 3      # au-delà, une annonce n'en dit pas plus
# Ressemblance minimale pour accepter une variante (gestion / gestionnaire).
SEUIL_FLOU = 88
# Une correspondance approximative ne vaut jamais une correspondance exacte.
CREDIT_FLOU = 0.8
# Proportion des mots d'une compétence à retrouver pour la dire « trouvée ».
SEUIL_TROUVEE = 0.5
# Secteur reconnu seulement dans le corps de l'annonce, pas dans l'intitulé.
CREDIT_SECTEUR_FAIBLE = 0.6

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

    - 60 % : la **meilleure** compétence ancrée retrouvée. Une signature qui
      colle vaut plus que dix compétences périphériques.
    - 40 % : le nombre d'autres compétences retrouvées, plafonné à trois.

    Un profil sans compétence ancrée est jugé sur la seconde moitié seule.
    """
    if not profil.skills:
        return None

    if vocabulaire is None:
        vocabulaire = set(signaux.vocabulaire)
    meilleure_ancree = 0.0
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
            (resultat.ancrees_trouvees if trouvee >= SEUIL_TROUVEE
             else resultat.ancrees_manquantes).append(nom)
        elif trouvee >= SEUIL_TROUVEE:
            # Seules les compétences réellement retrouvées comptent. Additionner
            # les correspondances sous le seuil laissait dix compétences frôlant
            # un mot générique saturer cette moitié du score : une offre de
            # boulangerie atteignait 83/100 sur un profil finance, sans qu'aucune
            # compétence ne soit rapportée à l'utilisateur.
            somme_autres += trouvee
            resultat.autres_trouvees.append(nom)

    part_autres = min(1.0, somme_autres / NB_AUTRES_ATTENDUES)
    if not a_des_ancrees:
        return 100.0 * part_autres
    return 100.0 * (PART_ANCREES * meilleure_ancree + (1 - PART_ANCREES) * part_autres)


# ------------------------------------------------------------------- secteur


def score_secteur(profil: Profile, signaux: Signaux, resultat: Resultat,
                  vocabulaire: set[str] | None = None) -> float | None:
    """Le secteur se mesure comme les compétences, avec `presence`.

    Il utilisait une simple appartenance d'ensemble, donc sans les synonymes ni
    la pondération des mots génériques : « Finance » ne rencontrait jamais
    « financial markets », et un secteur reconnu sur le seul mot « gestion »
    valait autant qu'un secteur reconnu en entier. Sur un critère qui pèse 25 %,
    un quart des offres en sortaient sous-notées.
    """
    if not profil.secteurs:
        return None

    mots_titre = set(mots(signaux.texte_secteur))
    mots_corps = set(signaux.vocabulaire) if vocabulaire is None else vocabulaire

    meilleur = 0.0
    for secteur in profil.secteurs:
        # Reconnu dans l'intitulé ou le libellé ROME : signal fort.
        fort = presence(secteur, mots_titre, flou=False) * 100.0
        # Seulement dans le corps de l'annonce : signal plus faible.
        faible = presence(secteur, mots_corps, flou=False) * 100.0 * CREDIT_SECTEUR_FAIBLE
        # Le meilleur des deux, et non « le fort sauf s'il est nul » : un titre
        # à moitié reconnu écrasait un corps qui, lui, reconnaissait tout — le
        # critère n'était pas monotone, un titre muet valait mieux.
        valeur = max(fort, faible)
        if valeur > meilleur:
            meilleur, resultat.secteur_reconnu = valeur, secteur
    return meilleur


# ----------------------------------------------------- pays, langue, contrat


def score_pays(profil: Profile, offre: Offer) -> float | None:
    if not profil.pays_acceptes or not offre.pays:
        return None
    return 100.0 if offre.pays in profil.pays_acceptes else 0.0


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
        "langue": score_langue(profil, signaux),
        "contrat": score_contrat(profil, offre),
    }

    normalises = poids.normalises()
    evaluables = {c: v for c, v in sous_scores.items() if v is not None}
    resultat.non_evaluables = [c for c in CRITERES if sous_scores[c] is None]
    resultat.detail = {c: round(v, 1) for c, v in evaluables.items()}

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
