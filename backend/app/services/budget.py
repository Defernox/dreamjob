"""Ce que chaque compte dépense en API — et la limite d'un compte ami.

C'est la clé du propriétaire qui paie tout. Un ami reçoit un budget mensuel
(`Utilisateur.budget_mensuel_usd`) ; chaque appel payant qu'il déclenche —
dossier de candidature, import de CV — est chiffré et imputé à son compte.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlmodel import Session, select

from ..config import reglages
from ..models import DepenseLlm, Utilisateur
from ..models.base import maintenant


class BudgetEpuise(RuntimeError):
    """Le compte a dépensé son budget du mois."""


def depense_du_mois(session: Session, utilisateur_id: int) -> float:
    debut = maintenant().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return float(session.exec(
        select(func.coalesce(func.sum(DepenseLlm.cout_usd), 0.0))
        .where(DepenseLlm.utilisateur_id == utilisateur_id, DepenseLlm.le >= debut)
    ).one())


def verifier_budget(session: Session, utilisateur: Utilisateur) -> None:
    """Lève `BudgetEpuise` si le compte a atteint sa limite. En local (Ollama),
    rien n'est facturé : aucune limite."""
    if utilisateur.budget_mensuel_usd is None or reglages().llm.fournisseur != "anthropic":
        return
    depense = depense_du_mois(session, utilisateur.id)
    if depense >= utilisateur.budget_mensuel_usd:
        raise BudgetEpuise(
            f"Budget du mois atteint : {depense:.2f} $ dépensés sur "
            f"{utilisateur.budget_mensuel_usd:.2f} $. Il se renouvelle le 1er du mois.")


def consigner(session: Session, utilisateur_id: int, offre_id: int | None, *appels) -> float:
    """Impute au compte ce qu'ont coûté les appels — y compris ceux d'une
    génération qui a échoué en route : les jetons consommés sont facturés quand
    même. Renvoie le montant."""
    cout = sum(c.get("usd", 0.0) for appel in appels
               for c in getattr(appel, "consommation", None) or [])
    if cout > 0:
        session.add(DepenseLlm(utilisateur_id=utilisateur_id, offer_id=offre_id,
                               cout_usd=round(cout, 6)))
        session.commit()
    return cout
