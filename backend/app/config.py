"""Chargement de la configuration : config.yaml (réglages) + .env (secrets).

Rien de sensible ne vit dans config.yaml ; rien de réglable ne vit dans .env.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# backend/app/config.py -> backend/ -> DreamJob/
RACINE = Path(__file__).resolve().parents[2]
FICHIER_CONFIG = RACINE / "config.yaml"

load_dotenv(RACINE / ".env")


class PoidsScoring(BaseModel):
    competences: int = 35
    secteur: int = 25
    pays: int = 15
    langue: int = 15
    contrat: int = 10

    @property
    def total(self) -> int:
        return self.competences + self.secteur + self.pays + self.langue + self.contrat

    def normalises(self) -> dict[str, float]:
        """Poids ramenés à une somme de 1.0, quelle que soit la saisie."""
        total = self.total or 1
        return {
            "competences": self.competences / total,
            "secteur": self.secteur / total,
            "pays": self.pays / total,
            "langue": self.langue / total,
            "contrat": self.contrat / total,
        }


class SeuilsScoring(BaseModel):
    bon: int = 75
    moyen: int = 50


class Scoring(BaseModel):
    version: int = 1
    poids: PoidsScoring = Field(default_factory=PoidsScoring)
    seuils: SeuilsScoring = Field(default_factory=SeuilsScoring)
    plafond_hors_cible: float = 25.0


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
    max_tokens_lettre: int = 2000
    max_tokens_import_cv: int = 8000


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


class Reglages(BaseModel):
    scoring: Scoring = Field(default_factory=Scoring)
    llm: Llm = Field(default_factory=Llm)
    http: Http = Field(default_factory=Http)
    chemins: Chemins = Field(default_factory=Chemins)
    documents: Documents = Field(default_factory=Documents)
    sauvegardes: Sauvegardes = Field(default_factory=Sauvegardes)
    recherche: Recherche = Field(default_factory=Recherche)
    offres: Offres = Field(default_factory=Offres)
    candidatures: Candidatures = Field(default_factory=Candidatures)
    sources: dict[str, Source] = Field(default_factory=dict)
    planification: Planification = Field(default_factory=Planification)

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
