"""Le profil : mon CV structuré.

Un profil par compte (`utilisateur_id`). Les blocs riches (compétences, expériences…)
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
    utilisateur_id: int | None = Field(default=None, foreign_key="utilisateur.id",
                                       unique=True, index=True)

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
    # Années d'expérience professionnelle, pour le critère de séniorité. Une
    # annonce qui réclame dix ans quand on en a trois n'est pas une bonne
    # offre, si bien notée soit-elle par ailleurs. À 0, le critère n'est pas
    # évalué : on ne devine pas un parcours à partir de dates en texte libre.
    annees_experience: int = 0
    # « masculin », « feminin », ou vide. Saisi par l'utilisateur, jamais déduit
    # du prénom. Deux usages : choisir la moitié d'un intitulé doublé (« Auditeur
    # comptable / Auditrice comptable », 9 % des offres pertinentes) et laisser
    # la lettre accorder « diplômé » au lieu de contourner tout adjectif.
    # Vide, rien n'est accordé et l'intitulé doublé cède au titre visé.
    accord: str = ""

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

    # Extraits annotés des vraies lettres du candidat, montrés au modèle comme
    # exemples de style (voir `documents/lettre.py`). Ce sont SES phrases, ses
    # chiffres, ses employeurs : ils appartiennent au profil, pas au code — dans
    # le code, ils partaient dans le prompt de tous les comptes.
    exemples_style: str = ""
    # Sujet ntfy du résumé du matin. Vide : pas de notification (le
    # propriétaire peut aussi le fixer par NTFY_SUJET dans .env).
    ntfy_sujet: str = ""

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
