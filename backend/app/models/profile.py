"""Le profil : mon CV structuré.

Une seule ligne en pratique (id=1). Les blocs riches (compétences, expériences…)
sont stockés en JSON : ils sont édités d'un seul tenant depuis l'interface et
n'ont aucune vie propre côté base — pas de jointure, pas de migration à chaque
champ ajouté.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from .base import colonne_json, maintenant


class Profile(SQLModel, table=True):
    __tablename__ = "profile"

    id: int | None = Field(default=None, primary_key=True)

    # --- Identité ---
    prenom: str = ""
    nom: str = ""
    email: str = ""
    telephone: str = ""
    ville: str = ""
    pays: str = ""
    linkedin: str = ""

    # --- Cible ---
    titre_vise: str = ""
    resume: str = ""
    # Où en est le candidat aujourd'hui, en une ligne — « Diplômé du Master 2
    # PGE Finance (EM Normandie), en MBA Trading à l'ESLSCA ». La lettre ouvrait
    # sur du vide faute de cette information : le modèle la déduisait, donc
    # l'inventait.
    situation_actuelle: str = ""
    # Sans ce champ, le prompt de la lettre INTERDISAIT d'annoncer une
    # disponibilité — une date inventée est une faute. Renseigné, le dernier
    # paragraphe peut enfin conclure.
    disponibilite: str = ""

    # ["communication digitale", "gestion de projet"]
    secteurs: list = Field(default_factory=list, sa_column=colonne_json())
    # [{"code": "fr", "libelle": "Français", "niveau": "natif"}]
    langues: list = Field(default_factory=list, sa_column=colonne_json())
    # ["France", "Belgique", ...]
    pays_acceptes: list = Field(default_factory=list, sa_column=colonne_json())
    # ORDONNÉE : le premier est le contrat préféré, l'ordre pilote le sous-score contrat.
    contrats_acceptes: list = Field(default_factory=list, sa_column=colonne_json())

    # [{"nom": "YouTube", "niveau": "avancé", "ancree": true}]
    # « ancrée » = compétence signature, exigée en correspondance exacte par le scoring.
    skills: list = Field(default_factory=list, sa_column=colonne_json())
    # [{"entreprise", "poste", "lieu", "debut", "fin", "description", "tags": []}]
    experiences: list = Field(default_factory=list, sa_column=colonne_json())
    # [{"etablissement", "diplome", "annee", "lieu"}]
    formations: list = Field(default_factory=list, sa_column=colonne_json())

    # Traçabilité de l'import
    cv_source_path: str = ""
    cv_importe_le: datetime | None = None

    created_at: datetime = Field(default_factory=maintenant)
    updated_at: datetime = Field(default_factory=maintenant)

    # --- Aides au scoring (pur Python, aucune requête) ---

    def noms_skills(self) -> list[str]:
        return [s.get("nom", "") for s in self.skills if s.get("nom")]

    def skills_ancrees(self) -> list[str]:
        return [s.get("nom", "") for s in self.skills if s.get("ancree") and s.get("nom")]

    def codes_langues(self) -> list[str]:
        return [lg.get("code", "").lower() for lg in self.langues if lg.get("code")]

    def entreprises_connues(self) -> list[str]:
        """Sert au garde-fou anti-invention de la lettre de motivation."""
        return [e.get("entreprise", "") for e in self.experiences if e.get("entreprise")]
