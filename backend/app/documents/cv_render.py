"""Rendu du CV depuis `templates/cv_modele.docx`.

Deux exigences du cahier des charges, tenues ici :

1. **La mise en page du modèle ne doit jamais casser.** Aucun paragraphe n'est
   créé de zéro : on duplique ceux du modèle et on remplace leur texte.
2. **Réordonnancement selon l'offre.** Expériences et compétences les plus
   proches de l'annonce passent en tête (désactivable dans `config.yaml`).

Rien n'est inventé : tout provient du profil.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import docx

from ..models import Offer, Profile
from ..scoring.extraction import signaux_de
from ..scoring.score import presence
from .docx_outils import (
    cloner_apres,
    cloner_xml_apres,
    copier_xml,
    definir_morceaux,
    definir_texte,
    est_gras,
    est_puce,
    decouper_en_sections,
    supprimer,
    supprimer_section,
)

log = logging.getLogger("dreamjob.cv")

MAX_PUCES = 5
MAX_COMPETENCES_PAR_LIGNE = 8

# --- Tenir sur une page ------------------------------------------------------
# Un CV de deux pages n'est pas une convention discutable : le recruteur lit la
# première, et la seconde arrive après sa décision.
#
# On NE DEVINE PAS la hauteur rendue. Une première version estimait un nombre de
# lignes à partir du nombre de caractères : elle annonçait 55 lignes pour un CV
# qui en occupait 47, et rabotait donc les expériences à une seule puce chacune
# — un CV mutilé pour un débordement qui n'existait pas. La mise en page dépend
# de la police, des marges et des césures du modèle ; seul le rendu la connaît.
#
# `dossier.py` mesure donc le PDF réellement produit et rappelle `rendre` avec
# moins de puces si la page déborde. La première conversion était de toute façon
# nécessaire : dans le cas courant, la mesure ne coûte rien.
PUCES_PAR_ESSAI = (MAX_PUCES, 3, 2, 1)


class ModeleIntrouvable(FileNotFoundError):
    pass


# ------------------------------------------------------------------ pertinence


def _pertinence(texte: str, vocabulaire: set[str]) -> float:
    """À quel point l'offre emploie le vocabulaire de `texte`, de 0 à 1.

    On passe par `presence`, la même fonction que le scoring : le classement du
    CV doit reposer sur la même mesure que le score affiché à l'écran, sinon les
    deux se contredisent sous les yeux de l'utilisateur.

    C'était une troisième implémentation de la même idée — simple appartenance
    d'ensemble, sans les synonymes ni la pondération des mots génériques. Une
    expérience « gestion des risques de crédit » ne rencontrait donc jamais une
    offre parlant de « credit risk », et une expérience reconnue sur le seul mot
    « gestion » passait devant une expérience réellement pertinente.
    """
    return presence(texte, vocabulaire, flou=False)


def _experiences_ordonnees(profil: Profile, vocabulaire: set[str], reordonner: bool) -> list[dict]:
    if not reordonner:
        return list(profil.experiences)
    return sorted(
        profil.experiences,
        key=lambda x: _pertinence(
            f"{x.get('poste', '')} {x.get('description', '')} {' '.join(x.get('tags', []))}",
            vocabulaire,
        ),
        reverse=True,
    )


def _competences_ordonnees(profil: Profile, vocabulaire: set[str], reordonner: bool) -> list[str]:
    noms = [s.get("nom", "") for s in profil.skills if s.get("nom")]
    if not reordonner:
        return noms
    ancrees = {s.get("nom") for s in profil.skills if s.get("ancree")}
    # D'abord ce que l'offre mentionne, puis les compétences signature.
    return sorted(noms, key=lambda n: (_pertinence(n, vocabulaire), n in ancrees), reverse=True)


# --------------------------------------------------------------------- blocs


def _blocs(paragraphes: list) -> list[list]:
    """Découpe une section en blocs : chacun commence par une ligne en gras."""
    blocs: list[list] = []
    for paragraphe in paragraphes:
        if est_gras(paragraphe) and not est_puce(paragraphe):
            blocs.append([paragraphe])
        elif blocs:
            blocs[-1].append(paragraphe)
    return blocs


def _decouper_en_puces(texte: str, maximum: int = MAX_PUCES) -> list[str]:
    """Une description en prose devient des puces lisibles.

    `maximum` se resserre quand le CV déborde sur une seconde page — c'est
    `dossier.py` qui le décide, après avoir mesuré le PDF rendu.
    """
    if not texte.strip():
        return []
    lignes = [l.strip(" -•\t") for l in texte.splitlines() if l.strip()]
    if len(lignes) > 1:
        return lignes[:maximum]
    phrases = [p.strip() for p in re.split(r"(?<=[.!?])\s+", texte) if len(p.strip()) > 15]
    return (phrases or [texte.strip()])[:maximum]


def _ajuster_puces(bloc: list, textes: list[str]):
    """Aligne le nombre de puces du modèle sur le nombre de textes à écrire.

    Renvoie le dernier paragraphe du bloc — il change dès qu'une puce est
    ajoutée, et l'appelant s'en sert comme point d'insertion du bloc suivant.
    """
    puces = [p for p in bloc if est_puce(p)]
    if not puces:
        return bloc[-1]

    for i, texte in enumerate(textes):
        if i < len(puces):
            definir_texte(puces[i], texte)
        else:
            nouvelle = cloner_apres(puces[0], puces[-1])
            definir_texte(nouvelle, texte)
            puces.append(nouvelle)

    for surplus in puces[len(textes):]:
        supprimer(surplus)

    restantes = puces[:len(textes)]
    return restantes[-1] if restantes else bloc[max(0, len(bloc) - len(puces) - 1)]


def _appliquer_blocs(blocs: list[list], donnees: list, remplir) -> None:
    """Rend `donnees` en dupliquant le premier bloc du modèle autant que besoin."""
    if not blocs or not donnees:
        for bloc in blocs:
            for paragraphe in bloc:
                supprimer(paragraphe)
        return

    patron = blocs[0]
    photo = copier_xml(patron)          # photographie du modèle vierge

    # Les blocs surnuméraires du modèle partent AVANT toute duplication : sinon
    # les clones s'intercaleraient entre eux et l'ordre deviendrait incohérent.
    for bloc in blocs[1:]:
        for paragraphe in bloc:
            supprimer(paragraphe)

    # `remplir` peut ajouter des puces : il renvoie donc le vrai dernier
    # paragraphe du bloc, seul point d'insertion valide pour le suivant.
    dernier = remplir(patron, donnees[0])

    for element in donnees[1:]:
        clone = []
        for xml in photo:
            dernier = cloner_xml_apres(xml, dernier)
            clone.append(dernier)
        dernier = remplir(clone, element)


# ------------------------------------------------------------------- sections


def _recherche(profil: Profile, offre: Offer) -> str:
    """Le contrat annoncé en en-tête : celui de l'offre, quand il convient.

    Un CV envoyé pour un CDI n'a pas à annoncer qu'on cherche aussi un stage :
    la liste complète dilue la candidature et laisse penser qu'on postule à
    tout. Quand l'offre porte sur un contrat que le profil accepte, on ne
    mentionne que celui-là — c'est vrai, et c'est ce que le recruteur veut lire.

    Le reste du temps — contrat non précisé par la source, ou hors des
    préférences — on retombe sur la liste du profil : mieux vaut dire ce qu'on
    cherche que de taire l'information.
    """
    acceptes = profil.contrats_acceptes
    if not acceptes:
        return ""
    if offre.type_contrat and offre.type_contrat in acceptes:
        return offre.type_contrat
    return ", ".join(acceptes)


def _remplir_entete(entete: list, profil: Profile, offre: Offer) -> None:
    if len(entete) < 4:
        return
    definir_texte(entete[0], f"{profil.prenom} {profil.nom}".strip().upper())
    # Le titre reprend l'intitulé de l'offre : c'est ce que lisent les filtres ATS.
    definir_texte(entete[1], offre.titre or profil.titre_vise)

    contact = " | ".join(filter(None, [
        ", ".join(filter(None, [profil.ville, profil.pays])),
        profil.telephone, profil.email, profil.linkedin,
    ]))
    definir_texte(entete[2], contact)

    # **Pas de ligne de mobilité.** Les pays acceptés du profil servent à
    # filtrer les offres, pas à figurer sur un CV : le recruteur sait où est son
    # poste, et le candidat qui postule y est par définition disponible. Cette
    # ligne étalait dix-sept pays sur trois lignes d'en-tête — aucune
    # information, et assez de place perdue pour faire déborder le CV sur une
    # seconde page.
    #
    # Un fragment sans contenu est omis, jamais rempli d'un tiret : « Recherche
    # : — » sous le nom donne l'impression d'un document mal fusionné. Si rien
    # n'est renseigné, la ligne entière disparaît.
    recherche = _recherche(profil, offre)
    if recherche:
        definir_texte(entete[3], f"Recherche : {recherche}")
    else:
        supprimer(entete[3])


def _remplir_competences(paragraphes: list, competences: list[str]) -> None:
    """Répartit les compétences sur les lignes du modèle.

    **Les libellés de catégorie du modèle sont retirés.** Ils étaient conservés
    tels quels alors que les compétences y étaient versées par tranches, sans
    rapport avec le thème annoncé : le CV affichait « Quantitatif & données :
    R, VBA, Power BI, Word, PowerPoint ». Un CV ne doit pas affirmer un
    classement que son propre contenu dément. Faute de pouvoir catégoriser
    honnêtement, on liste — la mise en forme du modèle, elle, est préservée.
    """
    if not paragraphes or not competences:
        for paragraphe in paragraphes:
            supprimer(paragraphe)
        return

    lignes_utiles = min(len(paragraphes), max(1, -(-len(competences) // MAX_COMPETENCES_PAR_LIGNE)))
    par_ligne = -(-len(competences) // lignes_utiles)

    for i in range(lignes_utiles):
        tranche = competences[i * par_ligne:(i + 1) * par_ligne]
        if not tranche:
            break
        definir_texte(paragraphes[i], ", ".join(tranche))

    for surplus in paragraphes[lignes_utiles:]:
        supprimer(surplus)


def _remplir_experience(bloc: list, element: tuple[dict, list[str]]):
    experience, puces = element
    definir_texte(bloc[0], experience.get("poste") or "Poste")
    periode = " – ".join(filter(None, [experience.get("debut"), experience.get("fin")]))
    ligne = " — ".join(filter(None, [
        experience.get("entreprise"), experience.get("lieu"), periode,
    ]))
    if len(bloc) > 1:
        definir_texte(bloc[1], ligne)
    return _ajuster_puces(bloc, puces)


def _remplir_formation(bloc: list, formation: dict):
    definir_texte(bloc[0], formation.get("diplome") or "Diplôme")
    ligne = " — ".join(filter(None, [
        formation.get("etablissement"), formation.get("lieu"), formation.get("annee"),
    ]))
    if len(bloc) > 1:
        definir_texte(bloc[1], ligne)
    return _ajuster_puces(bloc, _decouper_en_puces(formation.get("details", "")))


def _remplir_langues(paragraphes: list, profil: Profile) -> None:
    if not paragraphes:
        return
    if not profil.langues:
        supprimer(paragraphes[0])
        return
    texte = " — ".join(
        f"{l.get('libelle') or l.get('code', '')} : {l.get('niveau') or '—'}"
        for l in profil.langues
    )
    definir_texte(paragraphes[0], texte)
    for surplus in paragraphes[1:]:
        supprimer(surplus)


# ---------------------------------------------------------------------- rendu


def rendre(
    profil: Profile,
    offre: Offer,
    modele: Path,
    destination: Path,
    *,
    reordonner: bool = True,
    max_puces: int = MAX_PUCES,
) -> Path:
    """Écrit le CV adapté à `offre` dans `destination`. Renvoie le chemin.

    `max_puces` borne le nombre de puces par expérience. `dossier.py` le
    resserre quand le PDF rendu déborde sur une seconde page — voir
    PUCES_PAR_ESSAI.
    """
    if not modele.exists():
        raise ModeleIntrouvable(
            f"Modèle de CV introuvable : {modele}. Déposez votre CV Word à cet emplacement."
        )

    document = docx.Document(str(modele))
    vocabulaire = set(signaux_de(offre).vocabulaire)

    entete, sections = decouper_en_sections(document)
    _remplir_entete(entete, profil, offre)

    if "Profil" in sections and sections["Profil"]:
        definir_texte(sections["Profil"][0], profil.resume or profil.titre_vise)
        for surplus in sections["Profil"][1:]:
            supprimer(surplus)

    competences = _competences_ordonnees(profil, vocabulaire, reordonner)
    _remplir_competences(sections.get("Compétences", []), competences)

    experiences = _experiences_ordonnees(profil, vocabulaire, reordonner)
    puces = [_decouper_en_puces(x.get("description", ""), max_puces) for x in experiences]
    _appliquer_blocs(
        _blocs(sections.get("Expériences professionnelles", [])),
        list(zip(experiences, puces)),
        _remplir_experience,
    )
    _appliquer_blocs(
        _blocs(sections.get("Formation", [])),
        list(profil.formations),
        _remplir_formation,
    )
    _remplir_langues(sections.get("Langues", []), profil)

    # Une rubrique sans contenu ne doit pas rester dans le CV rendu.
    for nom in ("Certifications", "Projets", "Divers"):
        supprimer_section(document, nom)
    if not profil.experiences:
        supprimer_section(document, "Expériences professionnelles")
    if not profil.formations:
        supprimer_section(document, "Formation")

    destination.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(destination))
    log.info("CV rendu : %s", destination)
    return destination
