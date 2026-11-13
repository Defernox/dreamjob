"""Ce qu'on sait des logiciels de recrutement (ATS), employeur par employeur.

DreamJob connaît le logiciel de chaque site carrières (`employeurs.yaml`) : au
moment de postuler, il peut dire au candidat ce que CE logiciel fera de son CV.

**Recherche du 2026-11-13, et ce qu'elle vaut.** Presque tout ce qui se lit sur
les ATS vient de vendeurs d'outils à CV ; leurs chiffres (« 75 % des CV rejetés
par un robot », « 95 % de réussite ») n'ont pas de source. Chaque fiche dit donc
son niveau de preuve :

- `documente` : la documentation de l'éditeur lui-même ;
- `convergent` : plusieurs sources secondaires disent la même chose, sans
  preuve de première main ;
- `inconnu` : rien de fiable — la fiche ne donne alors que le conseil commun.

**Ce que la recherche établit, tous logiciels confondus :**

1. *Un ATS rejette rarement un CV sur son contenu.* La seule étude trouvée
   (Enhancv, 25 recruteurs américains, 2025 — petite, et commandée par un
   vendeur) : 23 sur 25 disent que leur outil ne rejette rien automatiquement
   sur la forme ou le contenu. Le rejet automatique documenté passe par les
   **questions du formulaire** (Greenhouse : « application rules » sur les
   questions oui/non et à choix ; Oracle Taleo : questions de disqualification).
2. *Ensuite, c'est un humain qui cherche* — par mots-clés, dans la base ou la
   liste des candidats, parfois aidé d'un score de correspondance. Un mot écrit
   autrement que dans l'annonce peut ne pas ressortir : d'où la mesure « au mot
   près » de `lecture_ats.py`, distincte de celle par synonymes du score.
3. *Le CV est d'abord converti en texte* par un analyseur (Textkernel chez SAP
   SuccessFactors). Colonnes, tableaux, zones de texte, en-têtes et images sont
   ce qui se perd ; un document à une colonne, aux rubriques classiques, se lit
   partout. C'est ce que `lecture_ats.py` vérifie sur chaque CV produit.
4. *Jobscan*, qui vend la mesure de correspondance, pondère dans cet ordre :
   compétences techniques, diplôme, intitulé du poste, savoir-être, autres
   mots — et vise 75 %.

Rien ici ne sert à tromper un logiciel : ni texte caché, ni mot-clé que le
candidat n'a pas. Les fiches disent comment être *lu correctement*.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from ..models import Offer

DOCUMENTE, CONVERGENT, INCONNU = "documente", "convergent", "inconnu"

CONSEIL_COMMUN = ("Les questions du formulaire comptent plus que le CV : une réponse "
                  "éliminatoire écarte la candidature avant toute lecture.")


@dataclass(frozen=True)
class FicheAts:
    nom: str
    # Ce que le logiciel fait du CV, en une phrase pour le candidat.
    conseil: str
    preuve: str
    # « docx » quand le Word est réputé mieux lu que le PDF ; sinon le PDF suffit.
    format: str = "pdf"
    sources: tuple[str, ...] = ()


FICHES: dict[str, FicheAts] = {
    "workday": FicheAts(
        "Workday",
        "Le site relit votre CV pour préremplir le formulaire : corrigez chaque champ "
        "(postes, dates, diplômes), c'est cette version que le recruteur consulte, à côté "
        "du fichier. " + CONSEIL_COMMUN,
        CONVERGENT,
        sources=("https://doc.workday.com/hiredscore/en-us/workday-hiredscore/"
                 "recruiter-productivity-/concept--candidate-profiles.html",),
    ),
    "successfactors": FicheAts(
        "SAP SuccessFactors",
        "Votre CV est lu par l'analyseur Textkernel, qui reconnaît le français et range "
        "les compétences dans son référentiel : des compétences en mots (« Excel », "
        "« VBA ») s'y rangent mieux que des phrases. " + CONSEIL_COMMUN,
        DOCUMENTE,
        sources=("https://userapps.support.sap.com/sap/support/knowledge/en/2951470",
                 "https://developer.textkernel.com/tx-platform/v10/resume-parser/overview/specs/"),
    ),
    "oracle": FicheAts(
        "Oracle Recruiting",
        "Le tri se fait d'abord sur vos réponses aux questions de présélection : une "
        "question de disqualification écarte la candidature d'office. Joignez le CV en "
        "Word : sa lecture du PDF est réputée moins sûre.",
        DOCUMENTE, format="docx",
        sources=("https://docs.oracle.com/en/cloud/saas/taleo-enterprise/20b/otrec/"
                 "candidate-prescreening.html",),
    ),
    "greenhouse": FicheAts(
        "Greenhouse",
        "Aucun tri automatique sur le CV n'est documenté ; le seul rejet automatique passe "
        "par les questions du formulaire (oui/non, choix), quand l'employeur l'a réglé. "
        "Répondez-y avec soin.",
        DOCUMENTE,
        sources=("https://support.greenhouse.io/hc/en-us/articles/203105595-Application-Rules-Overview",),
    ),
    "smartrecruiters": FicheAts(
        "SmartRecruiters",
        "Le recruteur voit une note de correspondance de 1 à 5 étoiles, calculée sur le "
        "contenu du CV face à l'annonce — jamais sur le nom, l'âge ou le genre. "
        + CONSEIL_COMMUN,
        CONVERGENT,
        sources=("https://www.smartrecruiters.com/fr/recruiting-software/match-winston/",),
    ),
    "talentsoft": FicheAts(
        "Cegid Talentsoft",
        "Le CV est analysé automatiquement puis rapproché de l'offre ; l'éditeur présente "
        "ce rapprochement comme une présélection proposée au recruteur, qui décide. "
        + CONSEIL_COMMUN,
        DOCUMENTE,
        sources=("https://www.cegid.com/fr/blog/3-pistes-pour-exploiter-son-vivier-de-talents-"
                 "grace-au-matching-offre-candidat/",),
    ),
}

# Aucune source fiable trouvée pour eux : le conseil commun, sans rien affirmer de plus.
_SANS_FICHE = {"lever": "Lever", "eightfold": "Eightfold", "cornerstone": "Cornerstone",
               "recruitee": "Recruitee", "pinpoint": "Pinpoint", "jibe": "Jibe",
               "beesite": "Beesite", "brassring": "BrassRing", "bpce": "le site du groupe BPCE"}

# Reconnaître le logiciel à l'adresse de candidature, pour les offres venues
# d'un agrégateur : le lien mène souvent au site carrières de l'employeur.
_HOTES = (
    ("myworkdayjobs.com", "workday"), ("myworkdaysite.com", "workday"),
    ("successfactors.", "successfactors"), ("sapsf.", "successfactors"),
    ("taleo.net", "oracle"), ("oraclecloud.com", "oracle"),
    ("greenhouse.io", "greenhouse"), ("smartrecruiters.com", "smartrecruiters"),
    ("talent-soft.com", "talentsoft"), ("talentsoft.", "talentsoft"),
    ("lever.co", "lever"), ("eightfold.ai", "eightfold"), ("csod.com", "cornerstone"),
    ("recruitee.com", "recruitee"),
)


def logiciel_de(offre: Offer) -> str:
    """Le logiciel de recrutement derrière une offre, ou « » si on l'ignore."""
    brut = offre.raw if isinstance(offre.raw, dict) else {}
    logiciel = str(brut.get("logiciel") or "").strip().lower()
    if logiciel in FICHES or logiciel in _SANS_FICHE:
        return logiciel
    contact = brut.get("contact") if isinstance(brut.get("contact"), dict) else {}
    for adresse in (str(contact.get("urlPostulation") or ""), offre.url or ""):
        hote = (urlsplit(adresse).hostname or "").lower()
        for motif, nom in _HOTES:
            if motif in hote:
                return nom
    return ""


def fiche_de(offre: Offer) -> FicheAts | None:
    """Ce qu'on sait du logiciel de cette offre. None quand il est inconnu : on
    ne prête pas à un site les règles d'un autre."""
    logiciel = logiciel_de(offre)
    if logiciel in FICHES:
        return FICHES[logiciel]
    if logiciel in _SANS_FICHE:
        return FicheAts(_SANS_FICHE[logiciel], CONSEIL_COMMUN, INCONNU)
    return None
