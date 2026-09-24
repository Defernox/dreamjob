"""La correspondance « ATS » d'une offre, avant de générer quoi que ce soit.

Ce que Jobscan vend, en pur code et sans appel : ce que le recruteur verra en
tête du CV, les termes de l'annonce que le profil couvre et ceux qu'il ne
couvre pas, les langues et l'ancienneté exigées.

Le taux n'est **pas** un score de plus. Le score dit si l'offre convient ; le
taux dit si le CV parle la langue de l'annonce — ce qu'interroge le recruteur
quand il cherche dans son ATS. Jobscan vise 75 à 80 % ; au-delà, un CV sent le
bourrage de mots-clés.
"""

from __future__ import annotations

from ..models import Offer, Profile
from ..scoring.couverture import MAX_TERMES, _partager
from ..scoring.extraction import signaux_de
from ..scoring.score import _ANNEES_EXIGEES, SEUIL_TROUVEE, presence
from .intitule import intitule_pour_cv, nettoyer_intitule

# Adzuna tronque ses descriptions à 500 caractères : au-dessous de ce seuil, une
# annonce a très probablement été coupée, et ses exigences réelles manquent.
DESCRIPTION_TRONQUEE = 520
TAUX_VISE = 75


def correspondance_ats(profil: Profile, offre: Offer) -> dict:
    signaux = signaux_de(offre)
    vocabulaire = set(signaux.vocabulaire)

    couverts, manquants = _partager(profil, offre)
    total = len(couverts) + len(manquants)
    taux = round(100 * len(couverts) / total) if total else None

    titre_cv = intitule_pour_cv(offre.titre, offre.lieu, profil.titre_vise, profil.accord)
    titre_offre = nettoyer_intitule(offre.titre, offre.lieu)

    texte = f"{offre.titre or ''} {offre.description_brute or ''}"
    exigees = [int(m.group(1)) for m in _ANNEES_EXIGEES.finditer(texte)]

    return {
        "titre_cv": titre_cv,
        # Faux quand l'intitulé a dû céder au titre visé (intitulé doublé sans
        # accord renseigné, ou vide après nettoyage) : le recruteur qui cherche
        # l'intitulé exact ne trouvera pas ce CV.
        "titre_reprend_l_offre": bool(titre_offre) and titre_cv == titre_offre,
        "taux": taux,
        "taux_vise": TAUX_VISE,
        "termes_couverts": couverts[:MAX_TERMES],
        "termes_manquants": manquants[:MAX_TERMES],
        "competences_citees": [
            s.get("nom", "") for s in profil.skills
            if s.get("nom") and presence(s["nom"], vocabulaire, flou=True) >= SEUIL_TROUVEE
        ],
        "langue_de_l_annonce": signaux.langue,
        "langues_exigees": list(signaux.exigences_langues),
        "annees_exigees": max(exigees) if exigees else None,
        "annees_profil": profil.annees_experience or None,
        "description_tronquee": len(offre.description_brute or "") <= DESCRIPTION_TRONQUEE,
    }
