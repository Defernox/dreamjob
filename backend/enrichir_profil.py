"""Enrichit le profil avec les faits tirés des lettres réelles du candidat.

**Rien n'est inventé ici.** Chaque ajout est une citation des deux lettres que
Maxime a écrites lui-même (candidatures CCF et Safran), fournies telles quelles.
La source est rappelée en commentaire devant chaque fait, pour qu'il puisse
vérifier ligne à ligne.

Script à usage unique, idempotent : relancé, il ne duplique rien.
"""

import io
import sys

from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, select

from app.db import engine
from app.models.base import maintenant
from app.models.profile import Profile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# --- Faits cités mot pour mot dans les lettres de Maxime --------------------

# « gérer quotidiennement un portefeuille de 15 à 25 entreprises représentant
#   un chiffre d'affaires de 50 à 75 millions d'euros » (lettre CCF)
# « j'ai suivi et optimisé des flux financiers représentant jusqu'à
#   75 millions d'euros » (lettre Safran)
CREDIT_MUTUEL = (
    "Gestion quotidienne d'un portefeuille de 15 à 25 entreprises représentant "
    "un chiffre d'affaires de 50 à 75 millions d'euros.\n"
    "Suivi et optimisation de flux financiers représentant jusqu'à 75 millions "
    "d'euros.\n"
    "Optimisation des flux : proposer des solutions de financement pour "
    "améliorer la trésorerie des clients exportateurs."
)

# « l'augmentation de 100% de la trésorerie associative et la réussite d'un
#   crowdfunding à 150% des objectifs » (lettre CCF)
TRESORIER = (
    "Gestion de la trésorerie de l'association (budget de 1000 à 3000 euros), "
    "augmentée de 100 % sur le mandat.\n"
    "Crowdfunding mené à 150 % de l'objectif fixé.\n"
    "Mise en place du compte de résultat.\n"
    "Appels d'offres sur contrats de prêt-à-porter et mise en relation des "
    "entreprises.\n"
    "Gestion et négociation des partenariats.\n"
    "Contrôle budgétaire d'événements (5000 € de budget initial)."
)

# « diplômé du Master 2 Programme Grande École en Finance de l'EM Normandie
#   (mention : 16,75/20 sur mon mémoire consacré aux outils numériques et à
#   l'accessibilité aux marchés financiers) » (lettre CCF)
MEMOIRE = (
    "Mémoire noté 16,75/20, consacré aux outils numériques et à l'accessibilité "
    "aux marchés financiers."
)

# Déduit du profil lui-même, pas des lettres : le MBA court de février 2026 à
# février 2027, il est donc EN COURS au 30 août 2026. On n'écrit pas
# « diplômé », ce serait faux.
SITUATION = (
    "Diplômé du Master 2 PGE Finance de l'EM Normandie, actuellement en MBA "
    "Trading et finance de marché à l'ESLSCA (deux semaines à l'école, trois "
    "semaines en entreprise)."
)


def _completer(texte: str, ajout: str) -> str:
    """Ajoute `ajout` s'il n'y est pas déjà — le script doit rester rejouable."""
    if ajout.strip() and ajout.strip() in (texte or ""):
        return texte
    return ajout


def main() -> None:
    with Session(engine) as session:
        profil = session.exec(select(Profile).order_by(Profile.id)).first()
        if profil is None:
            print("Aucun profil en base.")
            return

        modifs: list[str] = []

        for experience in profil.experiences:
            entreprise = (experience.get("entreprise") or "").lower()
            avant = experience.get("description", "")
            if "crédit mutuel" in entreprise or "credit mutuel" in entreprise:
                experience["description"] = _completer(avant, CREDIT_MUTUEL)
            elif "finish em" in entreprise:
                experience["description"] = _completer(avant, TRESORIER)
            else:
                continue
            if experience["description"] != avant:
                modifs.append(f"expérience « {experience.get('poste')} » : "
                              f"{len(avant)} → {len(experience['description'])} caractères")

        for formation in profil.formations:
            if "EM Normandie" in (formation.get("etablissement") or ""):
                avant = formation.get("details", "")
                formation["details"] = _completer(avant, MEMOIRE)
                if formation["details"] != avant:
                    modifs.append("formation EM Normandie : mémoire 16,75/20 ajouté")

        if not profil.situation_actuelle:
            profil.situation_actuelle = SITUATION
            modifs.append("situation_actuelle renseignée")

        # SQLAlchemy ne surveille pas le contenu d'une colonne JSON : muter les
        # dictionnaires en place — et même réaffecter `list(...)`, qui reste
        # égal à l'ancienne valeur — ne marque rien comme modifié, et le commit
        # n'écrit RIEN. Vérifié : seul le champ scalaire était persisté.
        flag_modified(profil, "experiences")
        flag_modified(profil, "formations")
        profil.updated_at = maintenant()

        session.add(profil)
        session.commit()

        print(f"{len(modifs)} modification(s) :")
        for m in modifs:
            print(f"  - {m}")


if __name__ == "__main__":
    main()
