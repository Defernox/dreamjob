"""Le cache LLM : la pièce qui tient le critère « ne rappelle pas le LLM inutilement ».

Aucun appel réseau ici : on compte les appels d'un faux client.
"""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.config import reglages
from app.llm.client import ClientLlm
from app.models import LlmCache


class Resultat(BaseModel):
    valeur: str
    nombre: int = 0


class FauxFournisseur:
    """Remplace l'appel au modèle, quel que soit le fournisseur.

    On se branche sur `_appeler_fournisseur`, le point unique où Ollama et
    Anthropic se séparent : ces tests portent sur le cache, pas sur le
    fournisseur, et ne doivent donc dépendre ni de l'un ni de l'autre.
    """

    def __init__(self, sortie: Resultat):
        self.appels = 0
        self.sortie = sortie
        self.dernier_appel = None

    def __call__(self, systeme, message, format_sortie, modele, max_tokens):
        self.appels += 1
        self.dernier_appel = {"systeme": systeme, "message": message,
                              "modele": modele, "max_tokens": max_tokens}
        return self.sortie


@pytest.fixture
def fournisseur_anthropic(monkeypatch):
    """Force la branche Anthropic. Ces tests portent sur ses messages d'erreur ;
    par défaut la configuration du projet choisit Ollama."""
    from app.config import reglages

    monkeypatch.setattr(type(reglages().llm), "local", property(lambda self: False))


@pytest.fixture
def faux(monkeypatch):
    fournisseur = FauxFournisseur(Resultat(valeur="extrait", nombre=3))
    monkeypatch.setattr(ClientLlm, "_appeler_fournisseur", fournisseur)
    return fournisseur


def _appel(session, *, hash_source="h1", modele="modele-a", forcer=False):
    return ClientLlm(session).extraire(
        type_appel="extraction",
        hash_source=hash_source,
        systeme="consigne",
        message="contenu",
        format_sortie=Resultat,
        modele=modele,
        max_tokens=500,
        forcer=forcer,
    )


def test_deuxieme_appel_identique_ne_rappelle_pas_le_llm(session, faux):
    premier, du_cache = _appel(session)
    assert faux.appels == 1 and du_cache is False

    second, du_cache = _appel(session)
    assert faux.appels == 1, "le LLM a été rappelé alors que le cache existait"
    assert du_cache is True
    assert second == premier


def test_source_differente_declenche_un_appel(session, faux):
    _appel(session, hash_source="h1")
    _appel(session, hash_source="h2")
    assert faux.appels == 2


def test_changer_de_modele_invalide_le_cache(session, faux):
    """Un modèle différent peut extraire différemment : entrée distincte."""
    _appel(session, modele="modele-a")
    _appel(session, modele="modele-b")
    assert faux.appels == 2


def test_forcer_rappelle_le_llm(session, faux):
    _appel(session)
    _, du_cache = _appel(session, forcer=True)
    assert faux.appels == 2 and du_cache is False


def test_entree_de_cache_incompatible_est_ignoree(session, faux):
    """Le schéma a changé depuis la mise en cache : on réinterroge, on ne plante pas."""
    cle = LlmCache.construire_cle("extraction", "h1", "modele-a")
    session.add(LlmCache(cle=cle, type="extraction", hash_source="h1",
                         modele="modele-a", payload={"champ_disparu": True}))
    session.commit()

    resultat, du_cache = _appel(session)
    assert faux.appels == 1 and du_cache is False
    assert resultat.valeur == "extrait"


def test_le_prompt_systeme_est_mis_en_cache_cote_api(session, monkeypatch,
                                                     fournisseur_anthropic):
    """Le prompt système est stable d'un appel à l'autre : il doit porter
    `cache_control`, sinon chaque requête Anthropic le refacture en entier."""
    appels = []

    class FauxSdk:
        def __init__(self):
            self.messages = SimpleNamespace(parse=self._parse)

        def _parse(self, **kwargs):
            appels.append(kwargs)
            return SimpleNamespace(
                parsed_output=Resultat(valeur="extrait"),
                usage=SimpleNamespace(input_tokens=1, output_tokens=1,
                                      cache_read_input_tokens=0),
            )

    monkeypatch.setattr(ClientLlm, "_anthropic", lambda self: FauxSdk())
    _appel(session)
    assert appels[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


# --- Messages d'erreur : ce que l'utilisateur lit quand ça casse ------------


def _erreur_api(statut: int, message: str):
    """Fabrique l'exception que lèverait le SDK pour une réponse d'erreur."""
    import anthropic
    import httpx2 as httpx

    corps = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    reponse = httpx.Response(
        statut, json=corps, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    return anthropic.BadRequestError(message, response=reponse, body=corps)


@pytest.mark.parametrize(
    "message_api, attendu",
    [
        ("Your credit balance is too low to access the Anthropic API.", "Crédits Anthropic épuisés"),
        ("anthropic-workspace-id is required when authenticating with an identity-linked API key",
         "ANTHROPIC_WORKSPACE_ID"),
    ],
)
def test_les_pannes_courantes_sont_expliquees_en_francais(
    session, monkeypatch, fournisseur_anthropic, message_api, attendu
):
    """Ces deux-là sont arrivées pour de vrai : elles doivent être compréhensibles."""
    from app.llm.client import LlmErreur

    class ClientQuiEchoue:
        def __init__(self):
            self.messages = SimpleNamespace(parse=self._parse)

        def _parse(self, **_):
            raise _erreur_api(400, message_api)

    monkeypatch.setattr(ClientLlm, "_anthropic", lambda self: ClientQuiEchoue())

    with pytest.raises(LlmErreur) as info:
        _appel(session)

    texte = str(info.value)
    assert attendu in texte
    assert message_api in texte, "le message d'origine doit rester lisible pour le diagnostic"


def test_un_echec_ne_pollue_pas_le_cache(session, monkeypatch, fournisseur_anthropic):
    """Une panne ne doit pas laisser d'entrée qui empêcherait un nouvel essai."""
    from app.llm.client import LlmErreur

    class ClientQuiEchoue:
        def __init__(self):
            self.messages = SimpleNamespace(parse=lambda **_: (_ for _ in ()).throw(
                _erreur_api(400, "Your credit balance is too low.")))

    monkeypatch.setattr(ClientLlm, "_anthropic", lambda self: ClientQuiEchoue())
    with pytest.raises(LlmErreur):
        _appel(session)

    assert session.get(LlmCache, LlmCache.construire_cle("extraction", "h1", "modele-a")) is None


# --- Le fournisseur local ----------------------------------------------------


def test_le_fournisseur_local_est_utilise_quand_il_est_configure(session, monkeypatch):
    """L'import de CV restait câblé sur Anthropic alors que la lettre, elle,
    savait déjà tourner en local."""
    from app.llm import client as module_client

    appels = []

    class FauxOllama:
        def __init__(self, _reglages):
            pass

        def extraire_json(self, systeme, message, schema):
            appels.append(schema)
            return '{"valeur": "en local", "nombre": 7}'

    monkeypatch.setattr(type(reglages().llm), "local", property(lambda self: True))
    monkeypatch.setattr("app.llm.ollama.ClientOllama", FauxOllama)

    resultat, du_cache = _appel(session)
    assert resultat.valeur == "en local"
    assert du_cache is False
    # Le schéma Pydantic est bien transmis à Ollama : sans lui, le modèle
    # rendrait du texte libre au lieu d'une structure.
    assert "valeur" in appels[0]["properties"]


def test_une_structure_invalide_du_modele_local_est_expliquee(session, monkeypatch):
    """Un modèle local dévie plus facilement du schéma qu'une API contrainte."""
    from app.llm.client import LlmErreur

    class OllamaBavard:
        def __init__(self, _reglages):
            pass

        def extraire_json(self, systeme, message, schema):
            return "Bien sûr ! Voici le résultat : {pas du JSON}"

    monkeypatch.setattr(type(reglages().llm), "local", property(lambda self: True))
    monkeypatch.setattr("app.llm.ollama.ClientOllama", OllamaBavard)

    with pytest.raises(LlmErreur, match="modele_local|modèle local"):
        _appel(session)


def test_la_disponibilite_ne_depend_pas_d_une_cle_anthropic_en_local(monkeypatch):
    """Sinon l'écran affiche « mode dégradé » alors qu'Ollama fonctionne."""
    monkeypatch.setattr(type(reglages().llm), "local", property(lambda self: True))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ClientLlm().disponible is True
