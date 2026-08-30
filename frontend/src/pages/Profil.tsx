import { useEffect, useRef, useState } from 'react'
import { useReglages, useSante } from '../api/hooks'
import {
  useEnregistrerProfil,
  useImporterCv,
  useProfil,
  type Experience,
  type Formation,
  type Langue,
  type Profil as TypeProfil,
  type Skill,
} from '../api/profil'
import { Bouton, Champ, Section, ZoneTexte } from '../components/champs'
import { ChoixMultipleGroupe, ChoixOrdonne, ListeTags } from '../components/ListeTags'
import { dateHeureFr } from '../lib/format'

/** Remplace un élément d'une liste sans muter l'original. */
function remplacer<T>(liste: T[], index: number, patch: Partial<T>): T[] {
  return liste.map((e, i) => (i === index ? { ...e, ...patch } : e))
}

export default function Profil() {
  const { data: distant, isLoading } = useProfil()
  const { data: reglages } = useReglages()
  const enregistrer = useEnregistrerProfil()
  const importer = useImporterCv()

  const [profil, setProfil] = useState<TypeProfil | null>(null)
  const [modifie, setModifie] = useState(false)
  const fichierRef = useRef<HTMLInputElement>(null)

  // Le serveur fait foi tant que rien n'a été touché localement.
  useEffect(() => {
    if (distant && !modifie) setProfil(distant)
  }, [distant, modifie])

  if (isLoading || !profil) {
    return <p className="text-sm text-slate-500">Chargement du profil…</p>
  }

  const maj = <K extends keyof TypeProfil>(champ: K, valeur: TypeProfil[K]) => {
    setProfil({ ...profil, [champ]: valeur })
    setModifie(true)
  }

  const soumettre = () => {
    enregistrer.mutate(profil, { onSuccess: () => setModifie(false) })
  }

  const choisirFichier = (e: React.ChangeEvent<HTMLInputElement>) => {
    const fichier = e.target.files?.[0]
    if (!fichier) return
    importer.mutate(fichier, { onSuccess: () => setModifie(false) })
    e.target.value = '' // permet de réimporter le même fichier
  }

  return (
    <div className="max-w-4xl space-y-5 pb-24">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Profil</h1>
          <p className="text-sm text-slate-500">
            La base du scoring : ce que vous savez faire, et ce que vous acceptez.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fichierRef}
            type="file"
            accept=".pdf,.docx"
            onChange={choisirFichier}
            className="hidden"
          />
          <Bouton onClick={() => fichierRef.current?.click()} disabled={importer.isPending}>
            {importer.isPending ? 'Lecture du CV…' : 'Importer un CV'}
          </Bouton>
          <Bouton variante="principal" onClick={soumettre} disabled={!modifie || enregistrer.isPending}>
            {enregistrer.isPending ? 'Enregistrement…' : modifie ? 'Enregistrer' : 'Enregistré'}
          </Bouton>
        </div>
      </div>

      {importer.isError && <Encart ton="rouge">{(importer.error as Error).message}</Encart>}
      {enregistrer.isError && <Encart ton="rouge">{(enregistrer.error as Error).message}</Encart>}
      {importer.isSuccess && (
        <Encart ton="vert">
          <div>
            CV lu ({importer.data.caracteres_lus.toLocaleString('fr-FR')} caractères) et structuré
            {importer.data.depuis_cache
              ? ' — servi depuis le cache, aucun appel facturé.'
              : ` par ${importer.data.modele}.`}{' '}
            Relisez et corrigez avant d'enregistrer.
          </div>
          {importer.data.avertissements.map((a) => (
            <div key={a} className="mt-1 text-amber-800">⚠ {a}</div>
          ))}
        </Encart>
      )}
      {modifie && <Encart ton="ambre">Modifications non enregistrées.</Encart>}

      <Section titre="Identité">
        <div className="grid grid-cols-2 gap-3">
          <Champ libelle="Prénom" valeur={profil.prenom} onChange={(v) => maj('prenom', v)} />
          <Champ libelle="Nom" valeur={profil.nom} onChange={(v) => maj('nom', v)} />
          <Champ libelle="Email" type="email" valeur={profil.email} onChange={(v) => maj('email', v)} />
          <Champ libelle="Téléphone" valeur={profil.telephone} onChange={(v) => maj('telephone', v)} />
          <Champ libelle="Ville" valeur={profil.ville} onChange={(v) => maj('ville', v)} />
          <Champ libelle="Pays" valeur={profil.pays} onChange={(v) => maj('pays', v)} />
          <div className="col-span-2">
            <Champ libelle="LinkedIn" valeur={profil.linkedin} onChange={(v) => maj('linkedin', v)} />
          </div>
        </div>
      </Section>

      <Section titre="Poste visé" aide="Le titre et les secteurs pèsent 25 % du score d'une offre.">
        <div className="space-y-3">
          <Champ libelle="Titre visé" valeur={profil.titre_vise} onChange={(v) => maj('titre_vise', v)}
                 placeholder="Analyste financier, Chef de projet…" />
          <ZoneTexte libelle="Résumé" valeur={profil.resume} onChange={(v) => maj('resume', v)} lignes={3} />
          <Champ libelle="Situation actuelle" valeur={profil.situation_actuelle}
                 onChange={(v) => maj('situation_actuelle', v)}
                 placeholder="Diplômé du Master 2 Finance, en MBA à l'ESLSCA" />
          <Champ libelle="Disponibilité" valeur={profil.disponibilite}
                 onChange={(v) => maj('disponibilite', v)}
                 placeholder="Immédiate — laissez vide si vous préférez ne rien annoncer" />
          <div>
            <span className="block text-xs font-medium text-slate-600 mb-1">Secteurs cibles</span>
            <ListeTags valeurs={profil.secteurs} onChange={(v) => maj('secteurs', v)}
                       placeholder="Tapez un secteur puis Entrée" />
          </div>
        </div>
      </Section>

      <Section
        titre="Préférences de recherche"
        aide="Absentes de votre CV : à renseigner ici. Elles pèsent 25 % du score (pays 15 %, contrat 10 %)."
      >
        <div className="space-y-5">
          <div>
            <span className="block text-xs font-medium text-slate-600 mb-2">Pays acceptés</span>
            <ChoixMultipleGroupe
              zones={reglages?.vocabulaires.pays_par_zone ?? {}}
              valeurs={profil.pays_acceptes}
              onChange={(v) => maj('pays_acceptes', v)}
            />
          </div>
          <div>
            <span className="block text-xs font-medium text-slate-600 mb-2">
              Contrats acceptés —{' '}
              <span className="font-normal text-slate-500">du plus souhaité au moins souhaité</span>
            </span>
            <ChoixOrdonne
              options={reglages?.vocabulaires.contrats ?? []}
              valeurs={profil.contrats_acceptes}
              onChange={(v) => maj('contrats_acceptes', v)}
            />
          </div>
        </div>
      </Section>

      <Section
        titre="Compétences"
        aide="Les compétences « ancrées » sont exigées en correspondance exacte par le scoring — réservez-les à vos 3 à 6 signatures."
        action={
          <Bouton onClick={() => maj('skills', [...profil.skills, { nom: '', niveau: '', ancree: false }])}>
            + Ajouter
          </Bouton>
        }
      >
        {profil.skills.length === 0 ? (
          <Vide>Aucune compétence. Importez un CV ou ajoutez-les à la main.</Vide>
        ) : (
          <div className="space-y-2">
            {profil.skills.map((s: Skill, i) => (
              <div key={i} className="flex items-center gap-2">
                <input
                  value={s.nom}
                  onChange={(e) => maj('skills', remplacer(profil.skills, i, { nom: e.target.value }))}
                  placeholder="Compétence"
                  className="flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm"
                />
                <input
                  value={s.niveau}
                  onChange={(e) => maj('skills', remplacer(profil.skills, i, { niveau: e.target.value }))}
                  placeholder="niveau"
                  className="w-32 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm"
                />
                <label className="flex items-center gap-1.5 text-sm text-slate-600 select-none">
                  <input
                    type="checkbox"
                    checked={s.ancree}
                    onChange={(e) => maj('skills', remplacer(profil.skills, i, { ancree: e.target.checked }))}
                  />
                  ancrée
                </label>
                <Bouton variante="danger" onClick={() => maj('skills', profil.skills.filter((_, j) => j !== i))}>
                  ×
                </Bouton>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section
        titre="Langues"
        aide="15 % du score : une offre rédigée dans une langue que vous ne maîtrisez pas est écartée."
        action={
          <Bouton onClick={() => maj('langues', [...profil.langues, { code: '', libelle: '', niveau: '' }])}>
            + Ajouter
          </Bouton>
        }
      >
        {profil.langues.length === 0 ? (
          <Vide>Aucune langue renseignée.</Vide>
        ) : (
          <div className="space-y-2">
            {profil.langues.map((l: Langue, i) => (
              <div key={i} className="flex items-center gap-2">
                <input
                  value={l.code}
                  onChange={(e) => maj('langues', remplacer(profil.langues, i, { code: e.target.value }))}
                  placeholder="fr"
                  className="w-16 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm"
                />
                <input
                  value={l.libelle}
                  onChange={(e) => maj('langues', remplacer(profil.langues, i, { libelle: e.target.value }))}
                  placeholder="Français"
                  className="flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm"
                />
                <input
                  value={l.niveau}
                  onChange={(e) => maj('langues', remplacer(profil.langues, i, { niveau: e.target.value }))}
                  placeholder="natif, courant, TOEIC 775…"
                  className="flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm"
                />
                <Bouton variante="danger" onClick={() => maj('langues', profil.langues.filter((_, j) => j !== i))}>
                  ×
                </Bouton>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section
        titre="Expériences"
        aide="Réordonnées automatiquement dans le CV généré, selon l'offre visée."
        action={
          <Bouton onClick={() => maj('experiences', [...profil.experiences, {
            entreprise: '', poste: '', lieu: '', debut: '', fin: '', description: '', tags: [],
          }])}>
            + Ajouter
          </Bouton>
        }
      >
        {profil.experiences.length === 0 ? (
          <Vide>Aucune expérience.</Vide>
        ) : (
          <div className="space-y-4">
            {profil.experiences.map((x: Experience, i) => (
              <div key={i} className="rounded-md border border-slate-200 p-3 space-y-2.5">
                <div className="grid grid-cols-2 gap-2.5">
                  <Champ libelle="Poste" valeur={x.poste}
                         onChange={(v) => maj('experiences', remplacer(profil.experiences, i, { poste: v }))} />
                  <Champ libelle="Entreprise" valeur={x.entreprise}
                         onChange={(v) => maj('experiences', remplacer(profil.experiences, i, { entreprise: v }))} />
                  <Champ libelle="Lieu" valeur={x.lieu}
                         onChange={(v) => maj('experiences', remplacer(profil.experiences, i, { lieu: v }))} />
                  <div className="grid grid-cols-2 gap-2.5">
                    <Champ libelle="Début" valeur={x.debut} placeholder="2023-09"
                           onChange={(v) => maj('experiences', remplacer(profil.experiences, i, { debut: v }))} />
                    <Champ libelle="Fin" valeur={x.fin} placeholder="en cours"
                           onChange={(v) => maj('experiences', remplacer(profil.experiences, i, { fin: v }))} />
                  </div>
                </div>
                <ZoneTexte libelle="Missions" valeur={x.description} lignes={3}
                           onChange={(v) => maj('experiences', remplacer(profil.experiences, i, { description: v }))} />
                <div>
                  <span className="block text-xs font-medium text-slate-600 mb-1">Mots-clés</span>
                  <ListeTags valeurs={x.tags}
                             onChange={(v) => maj('experiences', remplacer(profil.experiences, i, { tags: v }))}
                             placeholder="Tapez un mot-clé puis Entrée" />
                </div>
                <div className="flex justify-end">
                  <Bouton variante="danger"
                          onClick={() => maj('experiences', profil.experiences.filter((_, j) => j !== i))}>
                    Supprimer
                  </Bouton>
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section
        titre="Formations"
        action={
          <Bouton onClick={() => maj('formations', [...profil.formations, {
            etablissement: '', diplome: '', annee: '', lieu: '', details: '',
          }])}>
            + Ajouter
          </Bouton>
        }
      >
        {profil.formations.length === 0 ? (
          <Vide>Aucune formation.</Vide>
        ) : (
          <div className="space-y-4">
            {profil.formations.map((f: Formation, i) => (
              <div key={i} className="rounded-md border border-slate-200 p-3 space-y-2.5">
                <div className="grid grid-cols-4 gap-2.5">
                  <div className="col-span-2">
                    <Champ libelle="Diplôme" valeur={f.diplome}
                           onChange={(v) => maj('formations', remplacer(profil.formations, i, { diplome: v }))} />
                  </div>
                  <Champ libelle="Établissement" valeur={f.etablissement}
                         onChange={(v) => maj('formations', remplacer(profil.formations, i, { etablissement: v }))} />
                  <Champ libelle="Année" valeur={f.annee}
                         onChange={(v) => maj('formations', remplacer(profil.formations, i, { annee: v }))} />
                </div>
                <ZoneTexte libelle="Détails" valeur={f.details} lignes={2}
                           onChange={(v) => maj('formations', remplacer(profil.formations, i, { details: v }))} />
                <div className="flex justify-end">
                  <Bouton variante="danger"
                          onClick={() => maj('formations', profil.formations.filter((_, j) => j !== i))}>
                    Supprimer
                  </Bouton>
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      {profil.cv_importe_le && (
        <p className="text-xs text-slate-400">
          Dernier import de CV : {dateHeureFr(profil.cv_importe_le)} — {profil.cv_source_path}
        </p>
      )}

      <Diagnostic />
    </div>
  )
}

function Encart({ ton, children }: { ton: 'vert' | 'ambre' | 'rouge'; children: React.ReactNode }) {
  const styles = {
    vert: 'bg-emerald-50 border-emerald-200 text-emerald-900',
    ambre: 'bg-amber-50 border-amber-200 text-amber-900',
    rouge: 'bg-red-50 border-red-200 text-red-900',
  }[ton]
  return <div className={`rounded-md border px-4 py-2.5 text-sm ${styles}`}>{children}</div>
}

function Vide({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-400">{children}</p>
}

/** L'état de l'installation, replié : utile quand quelque chose ne marche pas. */
function Diagnostic() {
  const { data: sante } = useSante()
  const { data: reglages } = useReglages()
  if (!sante) return null

  return (
    <details className="bg-white rounded-lg border border-slate-200 p-5">
      <summary className="font-semibold cursor-pointer select-none">Diagnostic de l'installation</summary>
      <dl className="mt-4 divide-y divide-slate-100 text-sm border-t border-slate-100">
        <Ligne libelle="Base de données" valeur={sante.base_donnees} ok={sante.base_existe} />
        <Ligne libelle="Modèle Word du CV" valeur={sante.modele_cv.chemin} ok={sante.modele_cv.present} />
        <Ligne libelle="Conversion PDF (LibreOffice)" valeur={sante.pdf.chemin ?? 'introuvable'} ok={sante.pdf.disponible} />
        <Ligne libelle="LLM — extraction" valeur={sante.llm.modele_extraction} ok={sante.llm.disponible} />
        <Ligne libelle="LLM — rédaction" valeur={sante.llm.modele_redaction} ok={sante.llm.disponible} />
        <Ligne libelle="Dossiers de candidature" valeur={sante.dossier_candidatures} ok />
      </dl>

      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mt-5 mb-2">
        Sources d'offres
      </h3>
      <div className="divide-y divide-slate-100 text-sm border-t border-slate-100">
        {sante.sources.map((s) => (
          <div key={s.cle} className="py-2.5 flex items-start gap-3">
            <span className={`mt-0.5 shrink-0 px-2 py-0.5 rounded text-xs font-medium ${
              s.actif ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-500'
            }`}>
              {s.actif ? 'actif' : 'inactif'}
            </span>
            <div>
              <div className="font-medium">{s.libelle}</div>
              <div className="text-slate-500 text-xs">{s.remarque}</div>
            </div>
          </div>
        ))}
      </div>

      {reglages && (
        <>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mt-5 mb-2">
            Poids du scoring (version {reglages.scoring.version})
          </h3>
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            {Object.entries(reglages.scoring.poids).map(([critere, poids]) => (
              <span key={critere}>
                <span className="text-slate-500">{critere}</span>{' '}
                <span className="font-medium tabular-nums">{poids} %</span>
              </span>
            ))}
          </div>
          <p className="text-xs text-slate-400 mt-2">
            Modifiables dans <code>config.yaml</code> — le score est recalculé en pur code,
            sans rappeler le LLM.
          </p>
        </>
      )}
    </details>
  )
}

function Ligne({ libelle, valeur, ok }: { libelle: string; valeur?: string; ok?: boolean }) {
  return (
    <div className="py-2.5 flex items-center justify-between gap-4">
      <dt className="text-slate-600 shrink-0">{libelle}</dt>
      <dd className="flex items-center gap-2 min-w-0">
        <span className="truncate text-slate-500 text-xs font-mono">{valeur ?? '…'}</span>
        <span className={ok ? 'text-emerald-600' : 'text-amber-600'}>{ok ? '✓' : '⚠'}</span>
      </dd>
    </div>
  )
}
