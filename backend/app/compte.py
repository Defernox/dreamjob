"""Gérer les comptes — sur le serveur, en ligne de commande.

    docker compose exec dreamjob python -m app.compte creer vous@exemple.fr
    docker compose exec dreamjob python -m app.compte mot-de-passe vous@exemple.fr
    docker compose exec dreamjob python -m app.compte budget ami@exemple.fr 5
    docker compose exec dreamjob python -m app.compte budget ami@exemple.fr aucun
    docker compose exec dreamjob python -m app.compte lister

Le premier compte créé est le propriétaire : il reprend les données déjà en
base (profil, candidatures, recherches) et n'a pas de limite de dépense. Les
suivants partent d'un profil vide, avec le budget mensuel de config.yaml.

Le mot de passe est saisi au clavier, sans écho : il n'apparaît ni à l'écran,
ni dans l'historique du terminal, ni dans les journaux.
"""

from __future__ import annotations

import sys
from getpass import getpass

from sqlmodel import Session, select

from .db import creer_tables, engine
from .models import EMAIL_LOCAL, SessionUtilisateur, Utilisateur
from .services.acces import LONGUEUR_MIN, MotDePasseTropCourt, creer_utilisateur, hacher

ACTIONS = {"creer": 2, "mot-de-passe": 2, "budget": 3, "lister": 1}


def _saisir() -> str:
    premier = getpass(f"Mot de passe ({LONGUEUR_MIN} caractères minimum) : ")
    if getpass("Confirmez : ") != premier:
        sys.exit("Les deux saisies diffèrent. Rien n'a été modifié.")
    return premier


def _lister(session: Session) -> None:
    from .services.budget import depense_du_mois

    for u in session.exec(select(Utilisateur).order_by(Utilisateur.id)).all():
        if u.email == EMAIL_LOCAL:
            print(f"{u.id:>3}  (compte local, jamais réclamé : "
                  f"le premier `creer` le reprendra)")
            continue
        role = "propriétaire" if u.proprietaire else "ami"
        depense = depense_du_mois(session, u.id)
        budget = ("sans limite" if u.budget_mensuel_usd is None
                  else f"{depense:.2f} $ / {u.budget_mensuel_usd:.2f} $ ce mois")
        print(f"{u.id:>3}  {u.email:<32} {role:<13} {budget}")


def main(arguments: list[str]) -> None:
    if not arguments or ACTIONS.get(arguments[0]) != len(arguments):
        sys.exit(__doc__)
    action = arguments[0]
    creer_tables()
    with Session(engine) as session:
        if action == "lister":
            _lister(session)
            return
        email = arguments[1].strip().lower()
        existant = session.exec(select(Utilisateur).where(Utilisateur.email == email)).first()
        try:
            if action == "creer":
                if existant:
                    sys.exit(f"Le compte {email} existe déjà.")
                cree = creer_utilisateur(session, email, _saisir())
                if cree.proprietaire:
                    print(f"Compte {email} créé : propriétaire, "
                          f"il reprend les données existantes.")
                else:
                    print(f"Compte {email} créé, avec un budget de "
                          f"{cree.budget_mensuel_usd:.2f} $ par mois.")
            elif action == "budget":
                if not existant:
                    sys.exit(f"Aucun compte {email}.")
                valeur = arguments[2].strip().lower().replace(",", ".")
                try:
                    existant.budget_mensuel_usd = None if valeur == "aucun" else float(valeur)
                except ValueError:
                    sys.exit("Budget attendu : un montant en dollars (ex. 5), ou « aucun ».")
                session.add(existant)
                session.commit()
                montant = existant.budget_mensuel_usd
                print(f"Budget de {email} : "
                      + ("sans limite." if montant is None else f"{montant:.2f} $ par mois."))
            else:
                if not existant:
                    sys.exit(f"Aucun compte {email}.")
                existant.mot_de_passe = hacher(_saisir())
                session.add(existant)
                # Un mot de passe changé ferme toutes les sessions ouvertes :
                # c'est souvent précisément pour cela qu'on le change.
                for ouverte in session.exec(select(SessionUtilisateur).where(
                        SessionUtilisateur.utilisateur_id == existant.id)).all():
                    session.delete(ouverte)
                session.commit()
                print(f"Mot de passe de {email} changé ; sessions ouvertes fermées.")
        except MotDePasseTropCourt as e:
            sys.exit(str(e))


if __name__ == "__main__":
    main(sys.argv[1:])
