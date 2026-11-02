"""Le résumé du matin : seulement quand il y a du vert, jamais bloquant, et
chacun le sien."""

from datetime import timedelta

import httpx
import pytest

from app.models import Profile, Utilisateur
from app.models.base import maintenant
from app.services import notification

from .conftest import ajouter_offre


@pytest.fixture
def envois(monkeypatch):
    partis = []

    def faux_post(url, content, headers, timeout):
        partis.append({"url": url, "corps": content.decode("utf-8"), "entetes": headers})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(notification.httpx, "post", faux_post)
    return partis


def _offre(session, n, score, vue=False, age_jours=0, utilisateur_id=None):
    o = ajouter_offre(session, utilisateur_id, source="t", source_id=str(n), hash=f"h{n}",
                      titre=f"Analyste {n}", entreprise="Banque", score=score, vue=vue,
                      ajoutee_le=maintenant() - timedelta(days=age_jours))
    session.commit()
    return o


def test_sans_sujet_configure_rien_ne_part(session, envois, monkeypatch):
    monkeypatch.delenv("NTFY_SUJET", raising=False)
    _offre(session, 1, 90)
    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 0
    assert envois == []


def test_seules_les_nouvelles_offres_vertes_non_vues_sont_signalees(session, envois, monkeypatch):
    monkeypatch.setenv("NTFY_SUJET", "sujet-de-test")
    depuis = maintenant() - timedelta(hours=1)
    _offre(session, 1, 91)
    _offre(session, 2, 80)
    _offre(session, 3, 60)                      # pas verte
    _offre(session, 4, 95, vue=True)            # déjà ouverte
    _offre(session, 5, 99, age_jours=3)         # d'un scan précédent

    assert notification.notifier(session, depuis) == 1
    envoi = envois[0]
    assert envoi["url"].endswith("/sujet-de-test")
    assert envoi["entetes"]["Title"].decode("utf-8") == "2 nouvelles offres vertes"
    assert envoi["corps"].splitlines() == ["91 — Analyste 1 · Banque", "80 — Analyste 2 · Banque"]


def test_aucune_offre_verte_aucune_notification(session, envois, monkeypatch):
    """Une alerte quotidienne « rien de nouveau » apprend à ignorer les autres."""
    monkeypatch.setenv("NTFY_SUJET", "sujet-de-test")
    _offre(session, 1, 55)
    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 0
    assert envois == []


def test_une_panne_de_ntfy_ne_fait_pas_echouer_le_scan(session, monkeypatch):
    monkeypatch.setenv("NTFY_SUJET", "sujet-de-test")
    _offre(session, 1, 90)

    def en_panne(*a, **kw):
        raise httpx.ConnectError("injoignable")

    monkeypatch.setattr(notification.httpx, "post", en_panne)
    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 0


# --- Plusieurs comptes ----------------------------------------------------------


def test_chacun_recoit_ses_offres_sur_son_sujet(session, envois, monkeypatch):
    monkeypatch.setenv("NTFY_SUJET", "sujet-du-proprietaire")
    from app.services.acces import proprietaire

    proprietaire(session)                       # le premier compte
    ami = Utilisateur(email="ami@exemple.fr", mot_de_passe="")
    session.add(ami)
    session.commit()
    session.add(Profile(utilisateur_id=ami.id, ntfy_sujet="sujet-de-l-ami"))
    _offre(session, 1, 91)
    _offre(session, 2, 85, utilisateur_id=ami.id)

    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 2
    par_sujet = {e["url"].rsplit("/", 1)[1]: e["corps"] for e in envois}
    assert par_sujet == {"sujet-du-proprietaire": "91 — Analyste 1 · Banque",
                         "sujet-de-l-ami": "85 — Analyste 2 · Banque"}


def test_le_sujet_de_l_env_n_est_qu_au_proprietaire(session, envois, monkeypatch):
    """Sans sujet dans son profil, un ami ne reçoit rien — surtout pas sur le
    téléphone du propriétaire."""
    monkeypatch.setenv("NTFY_SUJET", "sujet-du-proprietaire")
    from app.services.acces import proprietaire

    proprietaire(session)
    ami = Utilisateur(email="ami@exemple.fr", mot_de_passe="")
    session.add(ami)
    session.commit()
    _offre(session, 1, 91, utilisateur_id=ami.id)

    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 0
    assert envois == []


# --- Telegram, pour le propriétaire -----------------------------------------------


@pytest.fixture
def partis(monkeypatch):
    """Tout ce qui sort, ntfy comme Telegram."""
    sortis = []

    def faux_post(url, **kw):
        sortis.append({"url": url, **kw})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(notification.httpx, "post", faux_post)
    return sortis


def _reglage_telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:jeton-de-test")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "4242")
    monkeypatch.setenv("DREAMJOB_URL", "https://dreamjob.exemple.ts.net")


def test_le_proprietaire_recoit_sur_telegram(session, partis, monkeypatch):
    from app.services.acces import proprietaire

    _reglage_telegram(monkeypatch)
    monkeypatch.setenv("NTFY_SUJET", "sujet-de-test")
    proprietaire(session)
    _offre(session, 1, 91)

    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 1
    assert len(partis) == 1, "Telegram remplace ntfy pour le propriétaire, il ne s'y ajoute pas"
    envoi = partis[0]
    assert envoi["url"] == "https://api.telegram.org/bot123:jeton-de-test/sendMessage"
    assert envoi["json"]["chat_id"] == "4242"
    assert "1 nouvelle offre verte" in envoi["json"]["text"]
    assert "91 — Analyste 1 · Banque" in envoi["json"]["text"]
    bouton = envoi["json"]["reply_markup"]["inline_keyboard"][0][0]
    assert bouton["url"] == "https://dreamjob.exemple.ts.net/offres"


def test_l_alerte_telegram_ouvre_la_fiche_de_l_offre(session, partis, monkeypatch):
    from app.services.acces import proprietaire

    _reglage_telegram(monkeypatch)
    proprietaire(session)
    offre = _offre(session, 1, 95)

    assert notification.alerter(session, maintenant() - timedelta(hours=1)) == 1
    bouton = partis[0]["json"]["reply_markup"]["inline_keyboard"][0][0]
    assert bouton["url"] == f"https://dreamjob.exemple.ts.net/offres/{offre.id}"


def test_sans_identifiant_de_conversation_on_reste_sur_ntfy(session, partis, monkeypatch):
    from app.services.acces import proprietaire

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:jeton-de-test")     # l'autre moitié manque
    monkeypatch.setenv("NTFY_SUJET", "sujet-de-test")
    proprietaire(session)
    _offre(session, 1, 91)

    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 1
    assert partis[0]["url"] == "https://ntfy.sh/sujet-de-test"


def test_un_ami_garde_ntfy_quand_le_proprietaire_a_telegram(session, partis, monkeypatch):
    from app.services.acces import proprietaire

    _reglage_telegram(monkeypatch)
    proprietaire(session)
    ami = Utilisateur(email="ami@exemple.fr", mot_de_passe="")
    session.add(ami)
    session.commit()
    session.add(Profile(utilisateur_id=ami.id, ntfy_sujet="sujet-de-l-ami"))
    _offre(session, 1, 91)
    _offre(session, 2, 85, utilisateur_id=ami.id)

    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 2
    assert {e["url"] for e in partis} == {
        "https://api.telegram.org/bot123:jeton-de-test/sendMessage", "https://ntfy.sh/sujet-de-l-ami"}


def test_un_profil_ne_peut_pas_viser_la_conversation_du_proprietaire(session, partis, monkeypatch):
    """Un sujet ntfy ne contient jamais « : » : celui qui en porte un est écarté,
    sans quoi un ami écrirait la destination interne du propriétaire dans son profil."""
    from app.services.acces import proprietaire

    _reglage_telegram(monkeypatch)
    proprietaire(session)
    ami = Utilisateur(email="ami@exemple.fr", mot_de_passe="")
    session.add(ami)
    session.commit()
    session.add(Profile(utilisateur_id=ami.id, ntfy_sujet=notification.DESTINATION_TELEGRAM))
    _offre(session, 1, 85, utilisateur_id=ami.id)

    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 0
    assert partis == []


def test_un_refus_de_telegram_libere_l_offre_sans_exposer_le_jeton(session, monkeypatch, caplog):
    from app.services.acces import proprietaire

    _reglage_telegram(monkeypatch)
    proprietaire(session)
    _offre(session, 1, 91)

    def refus(url, **kw):
        requete = httpx.Request("POST", url)
        return httpx.Response(401, request=requete)

    monkeypatch.setattr(notification.httpx, "post", refus)
    with caplog.at_level("INFO", logger="dreamjob.notification"):
        assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 0
    assert "jeton-de-test" not in caplog.text
    assert "401" in caplog.text

    # L'offre n'a pas été tenue pour signalée : la passe suivante réessaie.
    monkeypatch.setattr(notification.httpx, "post",
                        lambda url, **kw: httpx.Response(200, request=httpx.Request("POST", url)))
    assert notification.notifier(session, maintenant() - timedelta(hours=1)) == 1


def test_un_delai_depasse_apres_l_envoi_ne_fait_pas_sonner_deux_fois(session, monkeypatch):
    from app.services.acces import proprietaire

    _reglage_telegram(monkeypatch)
    proprietaire(session)
    _offre(session, 1, 91)
    appels = []

    def lent(url, **kw):
        appels.append(url)
        raise httpx.ReadTimeout("trop lent")

    monkeypatch.setattr(notification.httpx, "post", lent)
    depuis = maintenant() - timedelta(hours=1)
    assert notification.notifier(session, depuis) == 1
    assert notification.notifier(session, depuis) == 0
    assert len(appels) == 1, "Telegram a pu la recevoir : on ne la renvoie pas"
