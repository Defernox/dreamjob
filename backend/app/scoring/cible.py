"""Ce que le candidat vise et ce qu'il sait faire — lu dans TOUT le CV.

Le premier score ne regardait que la liste des compétences et des secteurs :
six phrases saisies à la main, dont « Esprit d'analyse et de synthèse ». Les
expériences, les missions, les diplômes, les recherches enregistrées — la partie
la plus riche du profil — étaient ignorés. Un CV de marchés financiers
rencontrait « Responsable administratif et financier » sur le seul mot
« financier ».

Deux choses en sont tirées :

- **les intitulés visés**, pondérés : le titre visé et les recherches (ce que le
  candidat dit chercher), les postes occupés (les récents plus que les
  anciens), les diplômes et les secteurs cibles ;
- **un vocabulaire pondéré** : chaque jeton canonique du CV, avec le poids de
  l'endroit où il apparaît — une compétence signature pèse plus qu'un mot d'une
  mission d'il y a cinq ans.

**Le vocabulaire d'un domaine visé est ajouté, à faible poids.** Un junior qui
vise le middle office n'a pas encore écrit « règlement-livraison » dans son CV ;
une annonce qui en parle n'en est pas moins dans sa cible. Ces mots ne servent
qu'à classer les offres — ils n'entrent jamais dans un document : un CV ou une
lettre qui les reprendrait mentirait.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..models import Profile
from .exigences import CERTIFICATIONS, niveaux_etudes
from .lexique import CREUX, bigrammes, jetons, jetons_intitule
from .texte import normaliser

# --- Poids de chaque source ------------------------------------------------------

POIDS_TITRE_VISE = 1.0
POIDS_RECHERCHE = 1.0           # ce que le candidat dit chercher
POIDS_POSTE_RECENT = 0.9        # le dernier poste occupé…
DECROISSANCE_POSTE = 0.15       # … puis chaque poste plus ancien un peu moins
POIDS_POSTE_MIN = 0.45
POIDS_DIPLOME = 0.6
# Les mots-clés d'une expérience (« Risque, Crédit, Export ») disent ce que le
# candidat a fait — donc ce pour quoi on peut l'embaucher. Sans eux, un CV de
# risque de crédit ne reconnaissait pas « Analyste crédit » : aucune recherche
# ne disait « crédit ».
POIDS_THEME = 0.6               # multiplié par la récence du poste
POIDS_SECTEUR = 0.6
POIDS_ANCREE = 1.0
POIDS_COMPETENCE = 0.7
POIDS_MISSION = 0.6             # multiplié par la récence du poste
POIDS_TAG = 0.7
POIDS_RESUME = 0.6
POIDS_SITUATION = 0.5
POIDS_DETAIL_FORMATION = 0.4
POIDS_LANGUE = 0.5
POIDS_DOMAINE = 0.35            # vocabulaire d'un domaine visé, jamais écrit dans le CV

# --- Le vocabulaire des domaines -----------------------------------------------------
# Déclencheur (une expression du CV) -> ce que le métier recouvre. Les deux côtés
# passent par `jetons` : les synonymes et l'anglais suivent.

DOMAINES: dict[str, str] = {
    "finance de marché": (
        "marché trading trader salle desk front office middle office back office actions "
        "obligations dérivés taux change forex options futures swaps produits financiers "
        "valorisation pnl risque de marché liquidité cotation courtage broker exécution "
        "ordres investissement fonds gestion d'actifs portefeuille bourse"),
    "trading": (
        "trader desk salle de marché exécution ordres pnl position book actions obligations "
        "dérivés taux change options futures swaps liquidité market making risque de marché"),
    "middle office": (
        "règlement livraison confirmation contrôle rapprochement valorisation pnl opérations "
        "trade booking collatéral appels de marge fonds mandats reporting back office "
        "front office dépositaire réconciliation"),
    "analyste risques": (
        "risque crédit marché opérationnel contrepartie notation rating scoring solvabilité "
        "exposition limites bâle provisions stress test var conformité contrôle permanent "
        "cartographie"),
    "risque de crédit": (
        "crédit contrepartie notation rating scoring solvabilité exposition encours limites "
        "garanties provisions défaut bâle analyse financière"),
    "trésorerie": (
        "cash liquidité flux financement placements banques rapprochement bancaire "
        "prévisions couverture change cash pooling"),
    "contrôle de gestion": (
        "budget reporting prévisions écarts kpi tableaux de bord coûts analytique pilotage "
        "performance clôture fpa business partner"),
    "gestion de patrimoine": (
        "patrimoine clientèle privée wealth placements épargne assurance vie conseil "
        "investissement allocation private banking"),
    "fond d'investissement": (
        "fonds private equity capital investissement gestion d'actifs valorisation "
        "due diligence lbo participations levée de fonds"),
    "outil si finance": (
        "erp sap oracle epm consolidation reporting paramétrage projet système "
        "d'information business analyst recette"),
    "banque": (
        "crédit compte client financement bancaire conformité kyc entreprises "
        "professionnels"),
    "gestionnaire de portefeuille": (
        "portefeuille clients entreprises chiffre d'affaires financement crédit relation "
        "commerciale chargé d'affaires"),
    "export": (
        "international commerce extérieur crédit documentaire garanties affacturage "
        "trade finance"),
}
_DOMAINES = [(set(jetons(declencheur)), declencheur, jetons(contenu))
             for declencheur, contenu in DOMAINES.items()]


@dataclass
class Intitule:
    libelle: str
    jetons: list[str]
    bigrammes: set[str]
    poids: float
    origine: str          # « titre visé », « recherche », « poste », « diplôme », « secteur »


@dataclass
class ProfilCible:
    intitules: list[Intitule] = field(default_factory=list)
    # jeton canonique (ou expression « a|b ») -> poids de 0 à 1
    vocabulaire: dict[str, float] = field(default_factory=dict)
    # D'où vient chaque mot : ce qui permet de dire « crédit (votre stage) ».
    origines: dict[str, str] = field(default_factory=dict)
    # Les mots qui font le candidat : compétences signature et intitulés visés.
    noyau: dict[str, float] = field(default_factory=dict)
    domaines: list[str] = field(default_factory=list)
    annees: int = 0
    # Le candidat accepte-t-il un stage ou une alternance ? Alors un poste de
    # stagiaire n'est pas « trop junior » : c'est un contrat qu'il a choisi.
    accepte_stage: bool = False
    etudes: int | None = None
    certifications: set[str] = field(default_factory=set)
    # Posés par `score.etalonner` : le vecteur du CV et la similarité qui vaut 100.
    vecteur: dict[str, float] | None = None
    reference_contenu: float | None = None

    def poids(self, terme: str) -> float:
        return self.vocabulaire.get(terme, 0.0)


# --- Construction ---------------------------------------------------------------------


def _annee_de_fin(experience: dict) -> int:
    """L'année où le poste s'arrête, pour ordonner par récence. Un poste en
    cours est de cette année."""
    fin = normaliser(experience.get("fin") or "")
    if not fin or any(m in fin for m in ("cours", "aujourd", "present", "actuel", "now")):
        return date.today().year
    annees = [int(a) for a in re.findall(r"\b(19\d\d|20\d\d)\b", fin)]
    if annees:
        return max(annees)
    debut = [int(a) for a in re.findall(r"\b(19\d\d|20\d\d)\b",
                                        normaliser(experience.get("debut") or ""))]
    return max(debut) if debut else 0


def _ajouter(cible: ProfilCible, texte: str | None, poids: float, origine: str,
             *, noyau: bool = False) -> None:
    suite = [j for j in jetons(texte) if j not in CREUX]
    for terme in [*suite, *bigrammes(suite)]:
        if poids > cible.vocabulaire.get(terme, 0.0):
            cible.vocabulaire[terme] = poids
            cible.origines[terme] = origine
        if noyau:
            cible.noyau[terme] = max(cible.noyau.get(terme, 0.0), poids)


def _intitule(cible: ProfilCible, libelle: str, poids: float, origine: str) -> None:
    suite = jetons_intitule(libelle)
    if not suite:
        return
    cible.intitules.append(Intitule(libelle.strip(), suite, bigrammes(suite), poids, origine))
    _ajouter(cible, libelle, poids, origine, noyau=poids >= POIDS_POSTE_RECENT)


def construire(profil: Profile, recherches: list[list[str]] | None = None) -> ProfilCible:
    """Le profil de ciblage d'un compte. `recherches` : les mots-clés de ses
    recherches enregistrées actives."""
    cible = ProfilCible(annees=profil.annees_experience or 0,
                        accepte_stage=bool({"Stage", "Alternance"}
                                           & set(profil.contrats_acceptes or [])))

    # --- Ce que le candidat vise ---
    if profil.titre_vise:
        _intitule(cible, profil.titre_vise, POIDS_TITRE_VISE, "titre visé")
    for mots_cles in recherches or []:
        for mot_cle in mots_cles:
            _intitule(cible, mot_cle, POIDS_RECHERCHE, "recherche")

    experiences = sorted(profil.experiences or [], key=_annee_de_fin, reverse=True)
    for rang, experience in enumerate(experiences):
        recence = max(POIDS_POSTE_MIN, POIDS_POSTE_RECENT - DECROISSANCE_POSTE * rang)
        if experience.get("poste"):
            _intitule(cible, experience["poste"], recence, f"poste « {experience['poste']} »")
        origine = f"expérience « {experience.get('poste') or experience.get('entreprise')} »"
        _ajouter(cible, experience.get("description"), POIDS_MISSION * recence / POIDS_POSTE_RECENT,
                 origine)
        _ajouter(cible, " ".join(experience.get("tags") or []),
                 POIDS_TAG * recence / POIDS_POSTE_RECENT, origine)
        for theme in experience.get("tags") or []:
            _intitule(cible, theme, POIDS_THEME * recence / POIDS_POSTE_RECENT,
                      f"thème de l'expérience « {experience.get('poste') or ''} »")

    for formation in profil.formations or []:
        if formation.get("diplome"):
            _intitule(cible, formation["diplome"], POIDS_DIPLOME,
                      f"diplôme « {formation['diplome']} »")
        _ajouter(cible, formation.get("details"), POIDS_DETAIL_FORMATION, "formation")

    for secteur in profil.secteurs or []:
        _intitule(cible, secteur, POIDS_SECTEUR, "secteur visé")

    # --- Ce qu'il sait faire ---
    for skill in profil.skills or []:
        ancree = bool(skill.get("ancree"))
        _ajouter(cible, skill.get("nom"), POIDS_ANCREE if ancree else POIDS_COMPETENCE,
                 f"compétence « {skill.get('nom')} »", noyau=ancree)
    _ajouter(cible, profil.resume, POIDS_RESUME, "résumé")
    _ajouter(cible, profil.situation_actuelle, POIDS_SITUATION, "situation actuelle")
    for langue in profil.langues or []:
        _ajouter(cible, langue.get("libelle"), POIDS_LANGUE, "langues")

    # --- Le vocabulaire des domaines visés ---
    sources = [set(i.jetons) for i in cible.intitules]
    sources += [set(jetons(e.get("description"))) for e in experiences]
    for declencheur_jetons, declencheur, contenu in _DOMAINES:
        if declencheur_jetons and any(declencheur_jetons <= s for s in sources):
            cible.domaines.append(declencheur)
            for terme in [*contenu, *bigrammes(contenu)]:
                if cible.vocabulaire.get(terme, 0.0) < POIDS_DOMAINE:
                    cible.vocabulaire[terme] = POIDS_DOMAINE
                    cible.origines[terme] = f"domaine « {declencheur} »"

    # --- Niveau ---
    diplomes = " ".join(f"{f.get('diplome', '')} {f.get('details', '')}"
                        for f in profil.formations or [])
    niveaux = niveaux_etudes(diplomes)
    cible.etudes = max(niveaux) if niveaux else None
    tout = normaliser(" ".join([diplomes, *(s.get("nom", "") for s in profil.skills or [])]))
    cible.certifications = {nom for nom, motif in CERTIFICATIONS.items() if re.search(motif, tout)}
    return cible
