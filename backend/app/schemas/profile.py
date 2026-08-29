"""Formes du profil : ce que le LLM doit rendre, ce que l'API expose.

La table `Profile` stocke des blocs JSON libres ; ces schémas sont le contrat
qui les valide, à l'import comme à l'édition.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from ..models.enums import CONTRATS


class Langue(BaseModel):
    code: str = Field(description="Code ISO 639-1 en minuscules : fr, en, de, es…")
    libelle: str = Field(description="Nom de la langue en français : Français, Anglais…")
    niveau: str = Field(default="", description="natif, courant, intermédiaire, notions — ou un score (TOEIC 775)")


class Skill(BaseModel):
    nom: str
    niveau: str = Field(default="", description="expert, avancé, courant, notions")
    # « Ancrée » = compétence signature. Le scoring exige une correspondance
    # exacte dessus, pas une simple ressemblance.
    ancree: bool = False


class Experience(BaseModel):
    entreprise: str
    poste: str
    lieu: str = ""
    debut: str = Field(default="", description="AAAA-MM si connu, sinon le texte tel quel")
    fin: str = Field(default="", description="AAAA-MM, ou « en cours »")
    description: str = ""
    tags: list[str] = Field(default_factory=list, description="mots-clés métier tirés de la mission")


class Formation(BaseModel):
    etablissement: str
    diplome: str
    annee: str = ""
    lieu: str = ""
    details: str = ""


class ProfilStructure(BaseModel):
    """Ce que le LLM renvoie après lecture d'un CV. Rien d'autre.

    Aucun champ de préférence ici (pays acceptés, contrats acceptés) : ils ne
    figurent pas dans un CV et seraient donc inventés. Ils sont saisis dans
    l'interface.
    """

    prenom: str = ""
    nom: str = ""
    email: str = ""
    telephone: str = ""
    ville: str = ""
    pays: str = ""
    linkedin: str = ""

    titre_vise: str = Field(default="", description="Le titre affiché en tête du CV")
    resume: str = Field(default="", description="Le paragraphe « à propos », reformulé sobrement")

    secteurs: list[str] = Field(default_factory=list)
    langues: list[Langue] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    experiences: list[Experience] = Field(default_factory=list)
    formations: list[Formation] = Field(default_factory=list)


class ProfilMaj(ProfilStructure):
    """Édition depuis l'interface : le profil complet, préférences comprises."""

    pays_acceptes: list[str] = Field(default_factory=list)
    contrats_acceptes: list[str] = Field(default_factory=list)

    @field_validator("contrats_acceptes")
    @classmethod
    def _contrats_connus(cls, valeurs: list[str]) -> list[str]:
        inconnus = [v for v in valeurs if v not in CONTRATS]
        if inconnus:
            raise ValueError(
                f"Contrat inconnu : {', '.join(inconnus)}. Valeurs acceptées : {', '.join(CONTRATS)}"
            )
        return valeurs


class ProfilLecture(ProfilMaj):
    """Ce que l'API renvoie."""

    id: int
    cv_source_path: str = ""
    cv_importe_le: datetime | None = None
    updated_at: datetime | None = None


class ResultatImport(BaseModel):
    profil: ProfilLecture
    depuis_cache: bool
    modele: str
    fichier: str
    caracteres_lus: int
    avertissements: list[str] = Field(default_factory=list)
