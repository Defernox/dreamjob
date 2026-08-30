"""Ce que l'offre demande et que le profil ne couvre pas.

Le signal le plus utile du dossier de candidature, et il ne coûte aucun appel :
il ne dit pas si l'offre est bonne — le score s'en charge — mais **ce qui
manque au profil** pour cette famille de postes. Répété sur vingt offres, il
dessine la formation à suivre ou la compétence à mettre en avant.

Le calcul passe par `score.presence`, comme les compétences, le secteur et le
classement du CV : un terme couvert par un synonyme est couvert. Sans cela,
« credit risk » serait rapporté comme manquant à un profil qui affiche
« risques de crédit ».
"""

from __future__ import annotations

from collections import Counter

from ..models import Offer, Profile
from .extraction import signaux_de
from .score import presence
from .texte import GENERIQUES, ensemble_mots, mots

# En dessous, le mot est trop court pour porter un métier (« sap », « vba » et
# « bi » sont les exceptions qu'on tient à garder).
LONGUEUR_MINIMALE = 4
SIGLES_UTILES = {"sap", "vba", "sql", "erp", "ifrs", "alm", "pnl", "kyc", "aml", "bi"}

# Un terme cité une ou deux fois dans une longue annonce est souvent un détail
# de contexte, pas une exigence. Mesuré : à deux, la liste se remplissait de
# « autres », « base », « adaptation ».
OCCURRENCES_MINIMALES = 3

# Les annonces s'adressent au candidat au « vous » : « assurez », « accompagnez »,
# « participez » sont des verbes de rédaction, pas des compétences. Très peu de
# noms français finissent en -ez.
SUFFIXES_CONJUGUES = ("ez",)

# Mots de remplissage propres aux annonces d'emploi. Ils passent au travers de
# VIDES et de GENERIQUES parce qu'ils portent du sens ailleurs — mais dans une
# offre, ils ne désignent aucune compétence.
CONTEXTE_ANNONCE = {
    "sein", "destination", "lien", "autres", "autre", "base", "adaptation",
    "generale", "general", "participer", "rejoindre", "poste", "postes",
    "candidat", "candidate", "cadre", "contexte", "ensemble", "notamment",
    "different", "differents", "differentes", "divers", "diverses",
    "quotidien", "quotidienne", "interne", "externe", "principales",
    "missions", "activites", "taches", "fonction", "fonctions", "role",
}

# Au-delà, la liste cesse d'être actionnable.
MAX_TERMES = 12


def _vocabulaire_du_profil(profil: Profile) -> set[str]:
    morceaux = [profil.titre_vise, profil.resume, profil.situation_actuelle]
    morceaux += profil.secteurs
    morceaux += [s.get("nom", "") for s in profil.skills]
    for experience in profil.experiences:
        morceaux += [experience.get("poste", ""), experience.get("description", "")]
        morceaux += experience.get("tags", [])
    for formation in profil.formations:
        morceaux += [formation.get("diplome", ""), formation.get("details", "")]
    return ensemble_mots(" ".join(m for m in morceaux if m))


def mots_cles_non_couverts(profil: Profile, offre: Offer) -> list[str]:
    """Termes récurrents de l'annonce qu'aucun élément du profil ne recouvre.

    Ordonnés par fréquence dans l'annonce : le premier est celui sur lequel le
    recruteur insiste le plus.
    """
    vocabulaire_profil = _vocabulaire_du_profil(profil)
    if not vocabulaire_profil:
        return []

    # L'intitulé compte double : ce qu'il nomme est le cœur du poste.
    frequences = Counter(mots(offre.description_brute))
    for jeton in mots(offre.titre):
        frequences[jeton] += OCCURRENCES_MINIMALES

    manquants: list[tuple[int, str]] = []
    for terme, nombre in frequences.items():
        if nombre < OCCURRENCES_MINIMALES:
            continue
        if terme in GENERIQUES or terme in CONTEXTE_ANNONCE:
            continue
        if terme.endswith(SUFFIXES_CONJUGUES):
            continue
        if len(terme) < LONGUEUR_MINIMALE and terme not in SIGLES_UTILES:
            continue
        # `presence` connaît les synonymes : « credit risk » n'est pas manquant
        # pour un profil qui dit « risques de crédit ».
        if presence(terme, vocabulaire_profil, flou=True) > 0.0:
            continue
        manquants.append((nombre, terme))

    manquants.sort(key=lambda x: (-x[0], x[1]))
    return [terme for _, terme in manquants[:MAX_TERMES]]


def couverture_de_l_offre(profil: Profile, offre: Offer) -> dict:
    """Petit compte rendu : ce que l'offre demande, ce qui manque."""
    signaux = signaux_de(offre)
    return {
        "non_couverts": mots_cles_non_couverts(profil, offre),
        "langue_de_l_annonce": signaux.langue,
        "langues_exigees": signaux.exigences_langues,
    }
