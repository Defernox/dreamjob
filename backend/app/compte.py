"""Créer un compte, ou changer son mot de passe — sur le serveur, en ligne de commande.

    docker compose exec dreamjob python -m app.compte creer vous@exemple.fr
    docker compose exec dreamjob python -m app.compte mot-de-passe vous@exemple.fr

Le mot de passe est saisi au clavier, sans écho : il n'apparaît ni à l'écran,
ni dans l'historique du terminal, ni dans les journaux.
"""

from __future__ import annotations

import sys
from getpass import getpass

from sqlmodel import Session, select

from .db import creer_tables, engine
from .models import SessionUtilisateur, Utilisateur
from .services.acces import LONGUEUR_MIN, MotDePasseTropCourt, creer_utilisateur, hacher


def _saisir() -> str:
    premier = getpass(f"Mot de passe ({LONGUEUR_MIN} caractères minimum) : ")
    if getpass("Confirmez : ") != premier:
        sys.exit("Les deux saisies diffèrent. Rien n'a été modifié.")
    return premier


def main(arguments: list[str]) -> None:
    if len(arguments) != 2 or arguments[0] not in ("creer", "mot-de-passe"):
        sys.exit(__doc__)
    action, email = arguments[0], arguments[1].strip().lower()
    creer_tables()
    with Session(engine) as session:
        existant = session.exec(select(Utilisateur).where(Utilisateur.email == email)).first()
        try:
            if action == "creer":
                if existant:
                    sys.exit(f"Le compte {email} existe déjà.")
                creer_utilisateur(session, email, _saisir())
                print(f"Compte {email} créé.")
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
