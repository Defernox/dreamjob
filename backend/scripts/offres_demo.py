"""Offres de démonstration, pour voir l'interface avant d'avoir les identifiants.

    python scripts/offres_demo.py           # ajoute les offres de démo et les score
    python scripts/offres_demo.py --vider   # les retire, sans toucher aux vraies

Elles portent toutes la source « demo » : aucune confusion possible avec les
offres réelles, et leur suppression est sans risque.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402

from app.config import reglages  # noqa: E402
from app.db import engine  # noqa: E402
from app.models import Application, Offer  # noqa: E402
from app.models.base import maintenant  # noqa: E402
from app.services.dedup import calculer_hash  # noqa: E402
from app.services.scoring import ProfilVide, profil_courant, scorer_offre  # noqa: E402

SOURCE = "demo"

OFFRES = [
    ("Chargé de recouvrement de créances export (H/F)", "Assureur Crédit", "92 - Nanterre",
     "France", "CDI", 3,
     "Vous assurez la gestion des risques de crédit à l'export, le suivi et le recouvrement "
     "des créances, la négociation avec les débiteurs et l'analyse financière des "
     "contreparties internationales. Maîtrise d'Excel indispensable.", "C1206"),
    ("Analyste risques de crédit (H/F)", "Banque Exemple", "75 - Paris 09",
     "France", "CDI", 8,
     "Au sein de la direction des risques, vous évaluez la solvabilité des contreparties, "
     "suivez les encours et produisez les dossiers du comité de crédit.", "C1206"),
    ("Credit Risk Analyst (M/F)", "Global Bank", "Luxembourg",
     "Luxembourg", "CDI", 20,
     "Within the risk department, you will assess the solvency of counterparties, monitor "
     "outstanding exposures and prepare the credit committee files for our corporate clients.",
     "C1206"),
    ("Alternance - Assistant trésorerie (H/F)", "Groupe Exemple", "92 - Courbevoie",
     "France", "Alternance", 30,
     "Vous assistez le trésorier dans le suivi des flux, la construction du budget "
     "prévisionnel et le contrôle budgétaire des projets.", "M1203"),
    ("V.I.E - Analyste financier (H/F)", "Corp International", "Montréal",
     "Canada", "V.I.E", 50,
     "Analyse financière des filiales du groupe, reporting mensuel et construction des "
     "budgets. Environnement anglophone.", "M1201"),
    ("Mission - Gestionnaire back office titres", "Agence Intérim", "69 - Lyon 03",
     "France", "Intérim", 120,
     "Mission d'intérim de 6 mois en back office titres : traitement des opérations, "
     "rapprochements et suivi des suspens.", "C1302"),
    ("Boulanger (H/F)", "Fournil du Coin", "75 - Paris 12",
     "France", "CDI", 5,
     "Vous confectionnez les pains et viennoiseries chaque matin dans notre fournil "
     "artisanal, en respectant les recettes de la maison et les règles d'hygiène.", "D1102"),
]


def vider(session: Session) -> tuple[int, int]:
    """Retire les offres de démo, et d'abord les candidatures qui s'y rattachent :
    la clé étrangère interdit de supprimer une offre encore référencée."""
    offres = list(session.exec(select(Offer).where(Offer.source == SOURCE)).all())
    identifiants = [o.id for o in offres]

    candidatures = list(session.exec(
        select(Application).where(Application.offer_id.in_(identifiants))
    ).all()) if identifiants else []
    for candidature in candidatures:
        session.delete(candidature)

    for offre in offres:
        session.delete(offre)
    session.commit()
    return len(offres), len(candidatures)


def remplir(session: Session) -> int:
    ajoutees = 0
    for i, (titre, entreprise, lieu, pays, contrat, jours, description, rome) in enumerate(OFFRES):
        empreinte = calculer_hash(titre, entreprise, lieu, description)
        if session.exec(select(Offer).where(Offer.hash == empreinte)).first():
            continue
        session.add(Offer(
            source=SOURCE, source_id=f"demo-{i}", hash=empreinte,
            url="https://exemple.test/offre/" + str(i),
            titre=titre, entreprise=entreprise, lieu=lieu, pays=pays,
            type_contrat=contrat,
            date_publication=maintenant() - timedelta(hours=jours),
            description_brute=description,
            raw={"romeCode": rome, "demo": True},
        ))
        ajoutees += 1
    session.commit()
    return ajoutees


def main() -> None:
    with Session(engine) as session:
        if "--vider" in sys.argv:
            offres, candidatures = vider(session)
            print(f"{offres} offre(s) de démo supprimée(s), "
                  f"{candidatures} candidature(s) rattachée(s).")
            return

        ajoutees = remplir(session)
        print(f"{ajoutees} offre(s) de démo ajoutée(s).")

        r = reglages()
        try:
            profil = profil_courant(session)
        except ProfilVide as e:
            print(f"Non scorées : {e}")
            return
        offres = list(session.exec(select(Offer).where(Offer.source == SOURCE)).all())
        for offre in offres:
            session.add(scorer_offre(profil, offre, r.scoring.poids,
                                     r.scoring.version, r.scoring.plafond_hors_cible))
        session.commit()
        print(f"{len(offres)} offre(s) de démo scorée(s), sans aucun appel LLM.")


if __name__ == "__main__":
    main()
