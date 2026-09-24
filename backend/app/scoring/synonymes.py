"""Synonymes métier, pour que le scoring reconnaisse ce qu'il devrait.

Sans cette table, « risques de crédit » dans le profil ne rencontre jamais
« credit risk » dans une annonce britannique, et « compte de résultat » rate
« P&L ». Les offres de ce domaine sont massivement bilingues : ignorer ces
équivalences revient à écarter la moitié du marché.

Le tableau reste volontairement court et orienté finance de marché. Une liste
exhaustive serait ingérable ; ce qui compte, ce sont les termes qui reviennent.
"""

from __future__ import annotations

from .texte import normaliser

# Chaque ligne regroupe des termes équivalents. La relation est symétrique :
# peu importe lequel figure dans le profil et lequel dans l'annonce.
FAMILLES: list[set[str]] = [
    {"risque", "risques", "risk", "risks"},
    {"credit", "crédit", "credits", "crédits", "lending"},
    {"tresorerie", "trésorerie", "treasury", "cash", "tresorier", "trésorier", "treasurer"},
    {"liquidite", "liquidité", "liquidites", "liquidity"},
    {"analyse", "analysis", "analytics", "analyste", "analyst"},
    {"financier", "financiere", "financière", "finance", "financial"},
    {"financement", "financements", "financing", "funding"},
    {"marche", "marché", "market", "markets"},
    # « gestion » est une activité, « manager » un niveau hiérarchique : les
    # confondre faisait d'une offre de « Finance Manager » un poste de gestion.
    {"gestion", "management"},
    {"responsable", "manager", "managers"},
    {"portefeuille", "portfolio"},
    {"recouvrement", "collection", "collections", "recovery"},
    {"creance", "créance", "creances", "créances", "receivable", "receivables"},
    {"conformite", "conformité", "compliance"},
    {"reporting", "rapport", "rapports"},
    {"budget", "budgetaire", "budgétaire", "budgeting"},
    {"previsionnel", "prévisionnel", "forecast", "forecasting", "prevision", "prévision"},
    {"resultat", "résultat", "pnl"},
    {"bilan", "balance"},
    {"actif", "actifs", "asset", "assets"},
    {"obligation", "obligations", "bond", "bonds", "obligataire"},
    {"action", "actions", "equity", "equities"},
    {"derive", "dérivé", "derives", "dérivés", "derivative", "derivatives"},
    {"couverture", "hedging", "hedge"},
    # « négociation » est aussi — surtout, dans un CV — celle d'un commercial ou
    # d'un partenariat : la ranger avec « trading » faisait d'un CV qui négocie
    # des partenariats un CV de trader.
    {"trading", "trader", "traders"},
    {"negociation", "négociation", "negotiation", "negocier", "négocier"},
    {"solvabilite", "solvabilité", "solvency", "creditworthiness"},
    {"contrepartie", "contreparties", "counterparty", "counterparties"},
    {"encours", "outstanding", "exposure", "exposures"},
    {"banque", "banques", "bancaire", "bancaires", "bank", "banking"},
    {"assurance", "assurances", "insurance"},
    {"controle", "contrôle", "control", "controlling"},
    {"tableur", "excel", "spreadsheet"},
    {"donnees", "données", "data"},
    {"modelisation", "modélisation", "modeling", "modelling"},
    {"investissement", "investissements", "investment", "investments"},
    {"fonds", "fond", "fund", "funds"},
    {"patrimoine", "wealth"},
    {"comptabilite", "comptabilité", "comptable", "comptables", "accounting",
     "accountant", "accountants"},
    {"audit", "auditeur", "auditor", "auditors"},
    {"fusion", "fusions", "merger", "mergers"},
    {"valorisation", "valuation", "valuations"},
    {"reglement", "règlement", "settlement", "settlements"},
    {"rapprochement", "rapprochements", "reconciliation", "reconciliations"},
    {"paiement", "paiements", "payment", "payments"},
    {"flux", "flow", "flows"},
    {"export", "exports", "exportateur", "exportateurs", "exportation"},
    {"client", "clients", "clientele", "clientèle", "customer", "customers"},
    {"souscription", "souscripteur", "underwriting", "underwriter"},
    {"titrisation", "securitisation", "securitization"},
    {"taux", "rates"},
    {"quantitatif", "quantitative", "quant"},
    {"crypto", "cryptomonnaie", "cryptomonnaies", "cryptocurrency", "cryptocurrencies"},
    {"bourse", "boursier", "boursiere", "boursière", "boursiers"},
    {"fiscal", "fiscale", "fiscalite", "fiscalité", "tax", "taxation"},
    {"paie", "payroll"},
    {"commercial", "commerciale", "commerciaux", "sales"},
    {"achat", "achats", "procurement", "purchasing", "acheteur", "buyer"},
    {"juridique", "legal"},
]

def _index_inverse(familles: list[set[str]]) -> dict[str, frozenset[str]]:
    """Index inversé : mot normalisé -> tous ses équivalents, lui compris.

    Les familles qui partagent un mot sont fusionnées **avant** l'indexation.
    Sans cela la relation cesserait d'être symétrique : le mot commun hériterait
    de l'union des deux familles pendant que ses voisins garderaient la leur, et
    le score dépendrait alors de quel terme se trouve dans le profil plutôt que
    dans l'annonce.
    """
    groupes: list[set[str]] = []
    for famille in familles:
        normalisee = {n for n in (normaliser(mot) for mot in famille) if n}
        if not normalisee:
            continue
        # On absorbe tout groupe déjà formé qui partage un mot avec celui-ci.
        restants = []
        for groupe in groupes:
            if groupe & normalisee:
                normalisee |= groupe
            else:
                restants.append(groupe)
        restants.append(normalisee)
        groupes = restants

    index: dict[str, frozenset[str]] = {}
    for groupe in groupes:
        fige = frozenset(groupe)
        for mot in fige:
            index[mot] = fige
    return index


_EQUIVALENTS: dict[str, frozenset[str]] = _index_inverse(FAMILLES)


def equivalents(mot: str) -> frozenset[str]:
    """Le mot et tous ses synonymes connus, normalisés."""
    return _EQUIVALENTS.get(mot, frozenset({mot}))


def present(mot: str, vocabulaire: set[str]) -> bool:
    """Le mot, ou l'un de ses synonymes, figure-t-il dans le vocabulaire ?"""
    return bool(equivalents(mot) & vocabulaire)
