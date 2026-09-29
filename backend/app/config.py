"""Chargement de la configuration : config.yaml (réglages) + .env (secrets).

Rien de sensible ne vit dans config.yaml ; rien de réglable ne vit dans .env.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# backend/app/config.py -> backend/ -> DreamJob/
RACINE = Path(__file__).resolve().parents[2]
FICHIER_CONFIG = RACINE / "config.yaml"

load_dotenv(RACINE / ".env")


class PoidsScoring(BaseModel):
    """Trois groupes, trois questions — et une seule fait le score.

    - La **pertinence** (métier, contenu) : le poste est-il celui du candidat ?
      C'est elle qui fait le score.
    - L'**accessibilité** (niveau, diplôme, langue) : peut-il l'obtenir ? Elle
      ne fait que retirer, jusqu'à `part_accessibilite` : être au bon niveau
      pour un poste sans rapport ne le rend pas pertinent. Quand ces critères
      s'additionnaient au reste, un poste de comptable « compatible » empochait
      d'office le tiers du score.
    - Les **conditions** (lieu, contrat, fraîcheur) : le veut-il, ici et
      maintenant ? Elles modulent, jusqu'à `part_conditions`.

    Chaque groupe est normalisé à part : seuls les rapports internes comptent.
    """

    metier: int = 65
    competences: int = 35
    seniorite: int = 50
    formation: int = 20
    langue: int = 30
    pays: int = 45
    contrat: int = 35
    fraicheur: int = 20
    part_accessibilite: float = Field(default=0.6, ge=0.0, le=1.0)
    part_conditions: float = Field(default=0.3, ge=0.0, le=1.0)

    PERTINENCE: ClassVar[tuple[str, ...]] = ("metier", "competences")
    ACCESSIBILITE: ClassVar[tuple[str, ...]] = ("seniorite", "formation", "langue")
    CONDITIONS: ClassVar[tuple[str, ...]] = ("pays", "contrat", "fraicheur")

    def en_dict(self) -> dict[str, int]:
        return {c: getattr(self, c)
                for c in (*self.PERTINENCE, *self.ACCESSIBILITE, *self.CONDITIONS)}

    def normalises(self) -> dict[str, float]:
        """Chaque groupe ramené à une somme de 1.0, quelle que soit la saisie."""
        resultat: dict[str, float] = {}
        for groupe in (self.PERTINENCE, self.ACCESSIBILITE, self.CONDITIONS):
            total = sum(getattr(self, c) for c in groupe) or 1
            resultat.update({c: getattr(self, c) / total for c in groupe})
        return resultat


class SeuilsScoring(BaseModel):
    bon: int = 75
    moyen: int = 50


class Scoring(BaseModel):
    version: int = 1
    poids: PoidsScoring = Field(default_factory=PoidsScoring)
    seuils: SeuilsScoring = Field(default_factory=SeuilsScoring)


class Llm(BaseModel):
    fournisseur: str = "ollama"          # "ollama" (local, gratuit) | "anthropic"
    ollama_url: str = "http://127.0.0.1:11434"
    modele_local: str = "mistral:7b"
    # Volume (une par offre) vs enjeu (une par CV / par candidature).
    modele_extraction: str = "claude-sonnet-5"
    modele_redaction: str = "claude-opus-5"
    tentatives_anti_invention: int = 3
    # Passe de relecture critique du brouillon. Désactivée par défaut :
    # mesurée sans effet avec mistral:7b, qui conserve les clichés qu'on lui
    # demande de traquer. À activer avec un modèle plus capable.
    relecture_lettre: bool = False

    @property
    def local(self) -> bool:
        return self.fournisseur == "ollama"

    @property
    def modele_actif(self) -> str:
        """Le modèle qui rédigera et structurera, selon le fournisseur choisi.

        Il entre dans la clé de cache : changer de fournisseur invalide donc les
        réponses précédentes, ce qui est voulu — deux modèles ne structurent pas
        un CV de la même façon.
        """
        return self.modele_local if self.local else self.modele_redaction
    max_tokens_extraction: int = 1200
    # Réflexion comprise : Opus 5.5 réfléchit toujours avant d'écrire, et ces
    # jetons comptent dans le même budget. À 2 000, la lettre aurait été
    # tronquée dès que la réflexion dépassait 1 500 jetons.
    max_tokens_lettre: int = 16000
    max_tokens_import_cv: int = 8000

    # --- Rédaction payante : un modèle par document, choisi par l'utilisateur ---
    # La lettre est lue en entier par le recruteur : c'est là que le meilleur
    # modèle se paie. Le CV ciblé est une reformulation encadrée par des
    # contrôles en pur code : un modèle intermédiaire y suffit.
    modele_lettre: str = "claude-opus-5-5"
    modele_ciblage: str = "claude-sonnet-5"
    # « low » à « max ». Plus haut = plus de réflexion, donc plus cher.
    effort_lettre: str = "low"
    effort_ciblage: str = "low"
    max_tokens_ciblage: int = 8000
    # Reformuler les puces du CV avec le vocabulaire de l'annonce, et écrire un
    # résumé propre à l'offre. Sans effet en local : mistral:7b n'est pas assez
    # fiable pour une reformulation qui ne doit rien ajouter.
    ciblage_cv: bool = True
    # Dollars par million de jetons (entrée, sortie), pour chiffrer chaque
    # dossier dans generation.json. Tarifs Anthropic vérifiés en septembre 2026.
    tarifs: dict[str, tuple[float, float]] = {
        "claude-opus-5-5": (4.0, 20.0),
        "claude-opus-5": (5.0, 25.0),
        "claude-sonnet-5": (2.0, 10.0),
        "claude-haiku-4-5": (1.0, 5.0),
    }


class Http(BaseModel):
    requetes_par_seconde: float = 1.0
    timeout_secondes: int = 20
    tentatives_max: int = 4
    user_agent: str = "DreamJob/0.1"
    cache_ttl_heures: int = 12


class Documents(BaseModel):
    reordonner_cv: bool = True
    ouvrir_le_dossier: bool = True


class Sauvegardes(BaseModel):
    a_conserver: int = 7


class Chemins(BaseModel):
    base_donnees: str = "data/dreamjob.db"
    cache: str = "data/cache"
    logs: str = "data/logs"
    sauvegardes: str = "data/sauvegardes"
    modele_cv: str = "templates/cv_modele.docx"
    dossier_candidatures: str = "~/Jobscout/candidatures"

    def _resoudre(self, valeur: str) -> Path:
        chemin = Path(valeur).expanduser()
        return chemin if chemin.is_absolute() else (RACINE / chemin)

    @property
    def db(self) -> Path:
        return self._resoudre(self.base_donnees)

    @property
    def dossier_cache(self) -> Path:
        return self._resoudre(self.cache)

    @property
    def dossier_logs(self) -> Path:
        return self._resoudre(self.logs)

    @property
    def dossier_sauvegardes(self) -> Path:
        return self._resoudre(self.sauvegardes)

    @property
    def cv_modele(self) -> Path:
        return self._resoudre(self.modele_cv)

    @property
    def candidatures(self) -> Path:
        return self._resoudre(self.dossier_candidatures)


class Candidatures(BaseModel):
    relance_apres_jours: int = 15


class Offres(BaseModel):
    expiree_apres_jours: int = 10


class Recherche(BaseModel):
    mots_cles: list[str] = Field(default_factory=list)
    pays: list[str] = Field(default_factory=lambda: ["France"])
    contrats: list[str] = Field(default_factory=list)
    offres_max_par_source: int = 150


class Source(BaseModel):
    actif: bool = False
    libelle: str = ""
    remarque: str = ""
    # Réservée au propriétaire : ses annonces ne sont collectées que pour ses
    # recherches, et n'entrent jamais dans le fil d'un autre compte.
    personnel: bool = False


class Comptes(BaseModel):
    # Budget d'API par mois civil d'un compte ami, en dollars. Un dossier coûte
    # environ 0,08 $ : 2 $ en font vingt-cinq. Le propriétaire n'a pas de limite.
    budget_mensuel_usd: float = 2.0


class Planification(BaseModel):
    # Opt-in : c'est config.yaml qui l'active, pas un defaut implicite.
    scan_quotidien_actif: bool = False
    heure: str = "07:30"
    rattrapage_apres_heures: int = 20
    delai_rattrapage_secondes: int = 30

    def heure_minute(self) -> tuple[int, int]:
        """(heure, minute). Une valeur illisible retombe sur 7 h 30 plutôt que
        d'empêcher l'application de démarrer."""
        try:
            h, _, m = self.heure.partition(":")
            heure, minute = int(h), int(m or 0)
            if 0 <= heure <= 23 and 0 <= minute <= 59:
                return heure, minute
        except ValueError:
            pass
        return 7, 30


class Employeurs(BaseModel):
    """Les sites carrières des employeurs (`connectors/employeurs`)."""

    # La liste des employeurs suivis, relative à la racine du projet.
    fichier: str = "employeurs.yaml"
    # Une recherche sans limite de date remonte jusque-là : au-delà, une offre
    # d'un site carrières est souvent pourvue.
    fenetre_jours: int = Field(default=31, ge=1, le=120)
    # Pages de liste lues au plus par employeur et par scan (20 offres chacune
    # chez Workday) : borne le coût d'un scan, même sur un site immense.
    pages_max: int = Field(default=15, ge=1, le=100)
    # En veille (les offres de un à trois jours), une liste qui ne donne pas de
    # date serait relue en entier toutes les demi-heures : vingt-quatre pages
    # chez Oddo BHF. Les nouveautés sont en tête ; les premières pages suffisent.
    pages_veille: int = Field(default=3, ge=1, le=100)
    # Employeurs interrogés en même temps — chacun sur son propre site, et
    # toujours une requête par seconde au plus sur un même site.
    en_parallele: int = Field(default=8, ge=1, le=32)


class Veille(BaseModel):
    """La veille : repérer une offre dans l'heure où elle paraît, et alerter.

    Le scan quotidien trouve les offres le lendemain au mieux ; mesuré en local,
    où l'application n'est ouverte que de temps en temps, avec **six jours** de
    retard médian chez France Travail. La veille joue une recherche légère —
    les seules offres du jour — plusieurs fois par jour, et chaque nouvelle
    offre verte part aussitôt sur le téléphone.

    Seules les sources qui le permettent y entrent. Adzuna plafonne à 250 appels
    par jour et 2 500 par mois, et le scan quotidien en consomme déjà les trois
    cinquièmes ; DogFinance est limité à quarante pages par jour, pour une raison
    juridique. Les deux restent au scan du matin.
    """

    active: bool = False
    intervalle_minutes: int = Field(default=30, ge=10, le=240)
    # Pas d'alerte la nuit : de heure_debut (incluse) à heure_fin (exclue).
    heure_debut: int = Field(default=7, ge=0, le=23)
    heure_fin: int = Field(default=22, ge=1, le=24)
    sources: list[str] = Field(default_factory=lambda: ["france_travail", "civiweb"])
    # Quand il ne s'agit que de repérer les nouveautés, on ratisse large : aux
    # recherches enregistrées s'ajoutent les intitulés tirés du CV (titre visé,
    # postes, mots-clés d'expérience, secteurs). Le score trie ensuite.
    elargir_depuis_le_cv: bool = True
    requetes_du_cv_max: int = Field(default=10, ge=0, le=30)
    max_offres_par_requete: int = Field(default=50, ge=10, le=150)
    # None : le seuil vert de l'écran (`scoring.seuils.bon`).
    seuil_alerte: int | None = Field(default=None, ge=0, le=100)
    # L'alerte dit « vient de paraître ». Une offre plus ancienne découverte
    # tard — un employeur ajouté à la liste, une annonce republiée — ne sonne
    # pas : le résumé du matin la reprend. Sans date connue, elle sonne.
    fraicheur_alerte_jours: int = Field(default=3, ge=1, le=60)
    # Au-delà, les nouveautés du jour attendent le résumé du lendemain : une
    # sonnerie toutes les dix minutes apprend à les ignorer toutes.
    alertes_par_jour_max: int = Field(default=15, ge=1, le=100)
    # L'historique des scans garde les veilles une semaine : trente par jour
    # l'auraient noyé.
    conserver_jours: int = Field(default=7, ge=1, le=90)


class Reglages(BaseModel):
    scoring: Scoring = Field(default_factory=Scoring)
    llm: Llm = Field(default_factory=Llm)
    http: Http = Field(default_factory=Http)
    chemins: Chemins = Field(default_factory=Chemins)
    documents: Documents = Field(default_factory=Documents)
    sauvegardes: Sauvegardes = Field(default_factory=Sauvegardes)
    recherche: Recherche = Field(default_factory=Recherche)
    offres: Offres = Field(default_factory=Offres)
    comptes: Comptes = Field(default_factory=Comptes)
    candidatures: Candidatures = Field(default_factory=Candidatures)
    sources: dict[str, Source] = Field(default_factory=dict)
    planification: Planification = Field(default_factory=Planification)
    veille: Veille = Field(default_factory=Veille)
    employeurs: Employeurs = Field(default_factory=Employeurs)

    # --- Secrets, lus dans l'environnement, jamais écrits sur disque ---
    @property
    def user_agent(self) -> str:
        """User-Agent complet, adresse de contact comprise si elle est fournie."""
        base = self.http.user_agent
        contact = os.getenv("CONTACT_EMAIL")
        return f"{base[:-1]}; contact: {contact})" if contact and base.endswith(")") else base

    @property
    def cle_anthropic(self) -> str | None:
        return os.getenv("ANTHROPIC_API_KEY") or None

    @property
    def llm_disponible(self) -> bool:
        """False => mode dégradé : scoring lexical, pas de génération de lettre."""
        return bool(self.cle_anthropic)

    def secret(self, nom: str) -> str | None:
        return os.getenv(nom) or None

    # --- Hébergement ---
    @property
    def serveur(self) -> bool:
        """Vrai dans l'image Docker (`DREAMJOB_MODE=serveur`), faux en local.

        Une variable d'environnement et non un réglage de config.yaml : c'est
        l'image qui la fixe. Un conteneur lancé sans elle — erreur de
        manipulation — resterait sinon ouvert à qui connaît son adresse, et le
        profil contient un téléphone, un e-mail et un parcours complet.
        """
        return os.getenv("DREAMJOB_MODE", "").strip().lower() == "serveur"

    @property
    def connexion_requise(self) -> bool:
        return self.serveur

    @property
    def adresse_publique(self) -> str | None:
        """L'adresse à laquelle l'utilisateur ouvre l'application — pour le lien
        des notifications. Ex. https://dreamjob.tailnet-xxxx.ts.net"""
        return os.getenv("DREAMJOB_URL") or None


def _charger() -> Reglages:
    donnees: dict = {}
    if FICHIER_CONFIG.exists():
        donnees = yaml.safe_load(FICHIER_CONFIG.read_text(encoding="utf-8")) or {}
    return Reglages.model_validate(donnees)


@lru_cache(maxsize=1)
def reglages() -> Reglages:
    return _charger()


def recharger() -> Reglages:
    """Relit config.yaml sans redémarrer l'API (changement de poids à chaud)."""
    reglages.cache_clear()
    return reglages()
