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
    {"credit", "crédit", "credits", "crédits"},
    {"tresorerie", "trésorerie", "treasury", "cash"},
    {"analyse", "analysis", "analytics", "analyste", "analyst"},
    {"financier", "financiere", "financière", "finance", "financial"},
    {"marche", "marché", "market", "markets"},
    {"gestion", "management", "gestionnaire", "manager"},
    {"portefeuille", "portfolio"},
    {"recouvrement", "collection", "collections", "recovery"},
    {"creance", "créance", "creances", "créances", "receivable", "receivables"},
    {"conformite", "conformité", "compliance"},
    {"reporting", "rapport", "rapports"},
    {"budget", "budgetaire", "budgétaire", "budgeting"},
    {"previsionnel", "prévisionnel", "forecast", "forecasting"},
    {"resultat", "résultat", "pnl"},
    {"bilan", "balance"},
    {"actif", "actifs", "asset", "assets"},
    {"obligation", "obligations", "bond", "bonds"},
    {"action", "actions", "equity", "equities"},
    {"derive", "dérivé", "derives", "dérivés", "derivative", "derivatives"},
    {"couverture", "hedging", "hedge"},
    {"negociation", "négociation", "trading", "trader"},
    {"solvabilite", "solvabilité", "solvency", "creditworthiness"},
    {"contrepartie", "contreparties", "counterparty", "counterparties"},
    {"encours", "outstanding", "exposure", "exposures"},
    {"banque", "bancaire", "bank", "banking"},
    {"assurance", "assurances", "insurance"},
    {"controle", "contrôle", "control", "controlling"},
    {"tableur", "excel", "spreadsheet"},
    {"donnees", "données", "data"},
    {"modelisation", "modélisation", "modeling", "modelling"},
]

# Index inversé : mot normalisé -> tous ses équivalents (lui compris).
_EQUIVALENTS: dict[str, frozenset[str]] = {}
for _famille in FAMILLES:
    _normalisee = frozenset(normaliser(mot) for mot in _famille if normaliser(mot))
    for _mot in _normalisee:
        _EQUIVALENTS[_mot] = _EQUIVALENTS.get(_mot, frozenset()) | _normalisee


def equivalents(mot: str) -> frozenset[str]:
    """Le mot et tous ses synonymes connus, normalisés."""
    return _EQUIVALENTS.get(mot, frozenset({mot}))


def present(mot: str, vocabulaire: set[str]) -> bool:
    """Le mot, ou l'un de ses synonymes, figure-t-il dans le vocabulaire ?"""
    return bool(equivalents(mot) & vocabulaire)
