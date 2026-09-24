"""Exemples de style, tirés des lettres réellement écrites par le candidat.

Aucune consigne de prompt ne vaut deux exemples de sa propre voix : c'est le
levier le plus fort dont on dispose sur un modèle local.

**Les extraits appartiennent au profil, pas au code** (`Profile.exemples_style`).
Ils ont longtemps été écrits ici en dur : c'étaient les phrases, les chiffres
et les employeurs d'UN candidat, et avec plusieurs comptes ils seraient partis
dans le prompt de tous. Ce module n'en garde que le cadre.

**Volontairement court.** Une version longue, annotée exemple par exemple, a
été essayée : elle noie un modèle de 7 milliards de paramètres, qui se met à
recopier l'annonce puis finit par rendre la structure du prompt elle-même
(« Informations, Formations, Expériences ») sans plus aucun « je ». Un petit
modèle a un budget de complexité — chaque consigne ajoutée en coûte une autre.

**Les exemples sont annotés phrase par phrase.** Un exemple brut transmet ses
défauts autant que ses qualités — le modèle imite ce qu'il voit, y compris les
formules creuses que ces mêmes lettres contenaient. Chaque ligne porte donc un
✓ (à imiter) ou un ✗ (à éviter), avec la raison.

**Les noms d'entreprises tierces sont à remplacer par des marqueurs.** Cités en
clair, le modèle les recopiait dans la nouvelle lettre, où l'anti-invention les
rejetait aussitôt — et la génération tournait en boucle sans jamais aboutir.
Les faits du candidat lui-même restent en clair : ils figurent dans son profil,
donc leur reprise est légitime.
"""

from __future__ import annotations

EN_TETE = "## COMMENT J'ÉCRIS — extraits de mes propres lettres"

PIED = """Ces extraits montrent une MANIÈRE D'ÉCRIRE. Tu n'en reprends aucun chiffre ni
aucune entreprise qui ne soit dans le PROFIL ci-dessous."""


def bloc_exemples(extraits: str) -> str:
    """Le bloc d'exemples du prompt, ou rien : sans extraits, pas d'en-tête vide."""
    extraits = extraits.strip()
    if not extraits:
        return ""
    return f"{EN_TETE}\n\n{extraits}\n\n{PIED}\n\n"
