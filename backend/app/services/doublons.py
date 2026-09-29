"""Le même poste, d'une source à l'autre : ce qui empêche de sonner deux fois.

La base reconnaît une annonce republiée à l'identique (`dedup.calculer_hash`),
pas un même poste décrit autrement. Or c'est le cas courant : la banque le
publie sur son site, France Travail le reprend avec sa propre mise en forme,
Adzuna le tronque à 500 caractères, et chaque version est une offre distincte
en base — trois alertes pour un seul poste. Et un employeur qui ouvre le même
poste dans dix agences (« Gestionnaire middle office », Crystal) sonnait dix
fois.

Deux offres sont le même poste quand :

- **l'employeur est le même** : les noms, débarrassés des formes juridiques et
  des mots génériques, s'incluent l'un l'autre (« Société Générale » et
  « SOCIETE GENERALE SA », « Caisse d'Épargne » et « Caisse d'Epargne Normandie ») ;
  un nom vide ou purement générique (« Banque ») ne prouve rien ;
- **l'intitulé est le même**, lu avec le vocabulaire du score — « Credit Risk
  Analyst » et « Analyste risques de crédit (H/F) - CDI » donnent les mêmes
  mots —, sans genre, sans CDI ni CDD, sans référence, sans le lieu de l'offre ;
  le niveau et les contrats particuliers restent : « Stage - Analyste » n'est
  pas « Analyste », ni « Junior » « Senior » ;
- **rien ne les sépare** : ni deux pays connus différents, ni deux contrats
  connus différents.

La ville n'entre pas en compte : le même intitulé chez le même employeur dans
deux villes ne vaut qu'une alerte, qui dit « et d'autres lieux ».

**Mieux vaut un doublon qui sonne qu'un poste tu.** Tout est fait pour ne
jamais confondre deux postes distincts : dans le doute, ce sont deux postes.
"""

from __future__ import annotations

import re

from ..scoring.lexique import jetons
from ..scoring.texte import normaliser

# Formes juridiques et mots qui ne distinguent pas un employeur d'un autre.
_FORMES = {
    "sa", "sas", "sasu", "sarl", "eurl", "sca", "scs", "snc", "se", "ag", "gmbh", "kg", "kgaa", "spa",
    "srl", "nv", "bv", "plc", "ltd", "limited", "llc", "llp", "lp", "inc", "corp", "corporation", "co",
    "cie", "company", "compagnie", "group", "groupe", "gruppe", "gruppo", "holding", "holdings", "the",
    "le", "la", "les", "de", "du", "des", "et", "and", "of", "international", "france", "europe", "uk",
    "usa", "us", "emea",
}
# Seuls, ces mots ne nomment personne : « Banque » peut être n'importe laquelle.
_GENERIQUES = {
    "banque", "bank", "banking", "assurance", "assurances", "insurance", "conseil", "cabinet", "finance",
    "financial", "financiere", "capital", "gestion", "asset", "management", "partners", "invest",
    "investment", "investments", "securities", "services", "solutions", "consulting", "recrutement",
    "interim", "entreprise", "societe", "client", "confidentiel", "confidential",
}
# Retirés d'un intitulé : ils ne disent pas le poste. Les contrats particuliers
# (stage, alternance, V.I.E) et les niveaux restent.
_NEUTRES = {jeton for mot in (
    "cdi", "cdd", "permanent", "contract", "contrat", "fixed", "term", "ref", "reference", "hf", "fh",
    "mwd", "mfd", "wmd", "fhx", "full", "time", "temps", "plein", "remote", "hybrid", "hybride",
    "teletravail", "urgent", "poste", "job", "offre", "new", "nouveau", "all", "genders",
) for jeton in jetons(mot)}
# Ce qui distingue deux postes au même intitulé : jamais « un mot de plus ».
_DISTINCTIFS = {jeton for mot in (
    "stage", "stagiaire", "intern", "internship", "alternance", "alternant", "apprenti", "vie",
    "junior", "senior", "confirme", "experimente", "manager", "responsable", "head", "director",
    "directeur", "associate", "vice", "president", "lead", "chief", "chef", "assistant", "graduate",
    "trainee", "summer", "analyst", "analyste",
) for jeton in jetons(mot)}
_ANNEE = re.compile(r"^20\d\d$")


def cle_entreprise(nom: str | None) -> frozenset[str]:
    """Les mots qui nomment l'employeur ; vide s'ils ne nomment personne."""
    mots = {m for m in normaliser(nom).split() if m not in _FORMES and len(m) > 1}
    return frozenset(mots) if mots - _GENERIQUES else frozenset()


def cle_intitule(titre: str | None, lieu: str | None = "") -> frozenset[str]:
    """Les mots du poste, sous leur forme canonique — FR et EN confondus."""
    du_lieu = set(jetons(lieu))
    return frozenset(
        j for j in jetons(titre)
        if j not in _NEUTRES and j not in du_lieu
        # Une référence (« 2600032a ») n'est pas un mot du poste ; une
        # promotion (« 2027 Summer Analyst ») en est un.
        and (not any(c.isdigit() for c in j) or _ANNEE.match(j)))


def memes_mots(a: frozenset[str], b: frozenset[str]) -> bool:
    """Le même intitulé : les mêmes mots, ou un seul de plus quand l'intitulé
    court en a déjà trois — pourvu que ce mot ne change pas le poste
    (« Analyste risques crédit » et « … crédit entreprises », oui ;
    « Analyste » et « Analyste senior », non)."""
    if not a or not b:
        return False
    if a == b:
        return True
    court, long_ = (a, b) if len(a) <= len(b) else (b, a)
    reste = long_ - court
    return court < long_ and len(court) >= 3 and len(reste) == 1 and not reste & _DISTINCTIFS


def meme_poste(a, b) -> bool:
    """Deux offres (Offer, ou tout objet qui en a les champs) sont-elles le même
    poste ? Dans le doute, non."""
    if a is b or (getattr(a, "id", None) is not None and a.id == getattr(b, "id", None)):
        return True
    if a.hash and a.hash == b.hash:
        return True
    if a.url and a.url == b.url:
        return True
    if a.pays and b.pays and a.pays != b.pays:
        return False
    if a.type_contrat and b.type_contrat and a.type_contrat != b.type_contrat:
        return False
    ea, eb = cle_entreprise(a.entreprise), cle_entreprise(b.entreprise)
    if not ea or not eb or not (ea <= eb or eb <= ea):
        return False
    return memes_mots(cle_intitule(a.titre, a.lieu), cle_intitule(b.titre, b.lieu))
