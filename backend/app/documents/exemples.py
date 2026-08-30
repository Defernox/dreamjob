"""Exemples de style, tirés des lettres réellement écrites par le candidat.

Aucune consigne de prompt ne vaut deux exemples de sa propre voix : c'est le
levier le plus fort dont on dispose sur un modèle local.

**Volontairement court.** Une version longue, annotée exemple par exemple, a
été essayée : elle noie un modèle de 7 milliards de paramètres, qui se met à
recopier l'annonce puis finit par rendre la structure du prompt elle-même
(« Informations, Formations, Expériences ») sans plus aucun « je ». Un petit
modèle a un budget de complexité — chaque consigne ajoutée en coûte une autre.
Elle reste dans l'historique git si un modèle plus capable la justifie un jour.

**Les exemples sont annotés phrase par phrase.** Un exemple brut transmet ses
défauts autant que ses qualités — le modèle imite ce qu'il voit, y compris les
formules creuses que ces mêmes lettres contenaient. Chaque ligne porte donc un
✓ (à imiter) ou un ✗ (à éviter), avec la raison.

**Les noms d'entreprises tierces sont remplacés par des marqueurs.** Les
premières versions les citaient : le modèle les recopiait dans la nouvelle
lettre, où l'anti-invention les rejetait aussitôt — et la génération tournait en
boucle sans jamais aboutir. Les faits du candidat lui-même (Crédit Mutuel,
EM Normandie, les montants) restent en clair : ils figurent dans son profil,
donc leur reprise est légitime.
"""

from __future__ import annotations

EXEMPLES_STYLE_COURT = """## COMMENT J'ÉCRIS — trois extraits de mes propres lettres

✓ « Anciennement Gestionnaire de Portefeuille Export au Crédit Mutuel et diplômé
   du Master 2 PGE Finance de l'EM Normandie (mémoire noté 16,75/20) »
   → J'ouvre sur mon statut et une preuve chiffrée. Jamais sur mon intérêt.

✓ « gérer quotidiennement un portefeuille de 15 à 25 entreprises représentant un
   chiffre d'affaires de 50 à 75 millions d'euros »
   → Le fait porte seul, sans adjectif ajouté.

✓ « l'augmentation de 100 % de la trésorerie associative et la réussite d'un
   crowdfunding à 150 % des objectifs »
   → Un résultat rendu crédible par le chiffre.

✗ « Je serais ravi de vous rencontrer » — formule vide.
✗ « mon dynamisme, mon sérieux et ma volonté » — trois qualités auto-attribuées.
✗ « un environnement stimulant » — vrai de n'importe quelle entreprise.

Ces extraits montrent une MANIÈRE D'ÉCRIRE. Tu n'en reprends aucun chiffre ni
aucune entreprise qui ne soit dans le PROFIL ci-dessous."""
