import { useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useReglages } from '../api/hooks'
import {
  useCandidatures,
  useImporterSuivi,
  useMajCandidature,
  useSupprimerCandidature,
  type Candidature,
} from '../api/candidatures'
import { Bouton } from '../components/champs'
import { ScoreBadge } from '../components/ScoreBadge'
import { dateFr, nombreFr } from '../lib/format'

const TOUS = 'Tous statuts'

export default function Candidatures() {
  const { data: candidatures, isLoading } = useCandidatures()
  const { data: reglages } = useReglages()
  const maj = useMajCandidature()
  const supprimer = useSupprimerCandidature()
  const importer = useImporterSuivi()

  const [recherche, setRecherche] = useState('')
  const [statut, setStatut] = useState(TOUS)
  const fichierRef = useRef<HTMLInputElement>(null)

  const visibles = useMemo(() => {
    const terme = recherche.trim().toLowerCase()
    return (candidatures ?? []).filter((c) => {
      if (statut !== TOUS && c.statut !== statut) return false
      if (!terme) return true
      return [c.titre, c.entreprise, c.notes, c.contact, c.pays]
        .join(' ').toLowerCase().includes(terme)
    })
  }, [candidatures, recherche, statut])

  if (isLoading) return <p className="text-sm text-encre-500">Chargement…</p>

  const total = candidatures?.length ?? 0

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-[26px] font-bold tracking-tight text-encre-950">Candidatures</h1>
          <p className="text-sm text-encre-500 mt-0.5">
            {nombreFr(total)} candidature{total > 1 ? 's' : ''}
            {visibles.length !== total && ` · ${nombreFr(visibles.length)} affichée(s)`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fichierRef}
            type="file"
            accept=".xlsx,.xlsm"
            className="hidden"
            onChange={(e) => {
              const fichier = e.target.files?.[0]
              if (fichier) importer.mutate(fichier)
              e.target.value = ''
            }}
          />
          <Bouton onClick={() => fichierRef.current?.click()} disabled={importer.isPending}>
            {importer.isPending ? 'Lecture…' : 'Importer'}
          </Bouton>
          <a
            href="/api/candidatures/export.xlsx"
            className="px-3.5 py-2 rounded-lg text-sm font-medium bg-ambre-500 text-white
                       shadow-carte hover:bg-ambre-600 transition-all"
          >
            Exporter (.xlsx)
          </a>
        </div>
      </div>

      {importer.isError && <Encart ton="rouge">{(importer.error as Error).message}</Encart>}
      {importer.isSuccess && (
        <Encart ton={importer.data.ignorees ? 'ambre' : 'vert'}>
          <p>
            {importer.data.mises_a_jour} candidature(s) mise(s) à jour
            {importer.data.ignorees > 0 && `, ${importer.data.ignorees} ligne(s) sans offre correspondante`}.
          </p>
          {importer.data.problemes.map((p) => (
            <p key={p} className="mt-1 text-xs">· {p}</p>
          ))}
        </Encart>
      )}

      <div className="bg-white rounded-carte border border-craie-200 shadow-carte p-3 flex gap-3 flex-wrap">
        <input
          value={recherche}
          onChange={(e) => setRecherche(e.target.value)}
          placeholder="Rechercher une entreprise, un poste, une note…"
          className="flex-1 min-w-[16rem] rounded-md border border-craie-300 px-3 py-1.5 text-sm"
        />
        <select
          value={statut}
          onChange={(e) => setStatut(e.target.value)}
          className="rounded-md border border-craie-300 px-2 py-1.5 text-sm bg-white"
        >
          <option>{TOUS}</option>
          {reglages?.vocabulaires.statuts.map((s) => <option key={s}>{s}</option>)}
        </select>
      </div>

      {total === 0 ? (
        <Vide />
      ) : (
        <div className="bg-white rounded-carte border border-craie-200 shadow-carte overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-encre-500 border-b border-craie-200">
                <Th>Date</Th><Th>Entreprise</Th><Th>Poste</Th><Th>Pays</Th>
                <Th>Score</Th><Th>Deadline</Th><Th>Statut</Th><Th>Notes</Th>
                <Th>Contact</Th><Th></Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-craie-200">
              {visibles.map((c) => (
                <Ligne
                  key={c.id}
                  candidature={c}
                  statuts={reglages?.vocabulaires.statuts ?? []}
                  seuils={reglages?.scoring.seuils}
                  onChange={(champs) => maj.mutate({ id: c.id, ...champs })}
                  onSupprimer={() => supprimer.mutate(c.id)}
                />
              ))}
            </tbody>
          </table>
          {visibles.length === 0 && (
            <p className="px-4 py-6 text-sm text-encre-500 text-center">
              Aucune candidature ne correspond à cette recherche.
            </p>
          )}
        </div>
      )}

      <p className="text-xs text-encre-400">
        L&apos;export est pensé pour être envoyé tel quel à France Travail : une ligne par
        candidature, dates au format français, en-têtes figés.
      </p>
    </div>
  )
}

const Th = ({ children }: { children?: React.ReactNode }) => (
  <th className="px-3 py-2 font-medium whitespace-nowrap">{children}</th>
)

/** Une ligne éditable. Les champs texte s'enregistrent à la sortie du champ,
 *  les listes et les dates dès le changement : pas de bouton « Enregistrer ». */
function Ligne({ candidature, statuts, seuils, onChange, onSupprimer }: {
  candidature: Candidature
  statuts: string[]
  seuils?: { bon: number; moyen: number }
  onChange: (champs: Partial<Candidature>) => void
  onSupprimer: () => void
}) {
  const [notes, setNotes] = useState(candidature.notes)
  const [contact, setContact] = useState(candidature.contact)

  return (
    <tr className="align-top hover:bg-craie-50/60">
      <td className="px-3 py-2 whitespace-nowrap text-encre-600">
        {dateFr(candidature.date_candidature)}
        {candidature.relance_conseillee && (
          <span
            className="ml-2 px-1.5 py-0.5 rounded text-xs bg-alerte-100 text-alerte-800 font-medium"
            title={`Envoyée il y a ${candidature.jours_depuis} jours, sans nouvelle`}
          >
            à relancer
          </span>
        )}
      </td>
      <td className="px-3 py-2 font-medium">{candidature.entreprise || '—'}</td>
      <td className="px-3 py-2 max-w-[18rem]">
        <Link
          to={`/offres/${candidature.offer_id}`}
          className="hover:underline underline-offset-2"
        >
          {candidature.titre || '—'}
        </Link>
      </td>
      <td className="px-3 py-2 whitespace-nowrap text-encre-600">{candidature.pays || '—'}</td>
      <td className="px-3 py-2">
        <ScoreBadge score={candidature.score} seuils={seuils} />
      </td>
      <td className="px-3 py-2">
        <input
          type="date"
          value={candidature.deadline ?? ''}
          onChange={(e) => onChange({ deadline: e.target.value || null })}
          className="rounded border border-craie-300 px-1.5 py-1 text-sm w-36"
        />
      </td>
      <td className="px-3 py-2">
        <select
          value={candidature.statut}
          onChange={(e) => onChange({ statut: e.target.value })}
          className="rounded border border-craie-300 px-1.5 py-1 text-sm bg-white w-32"
        >
          {statuts.map((s) => <option key={s}>{s}</option>)}
        </select>
      </td>
      <td className="px-3 py-2 min-w-[14rem]">
        <textarea
          value={notes}
          rows={2}
          onChange={(e) => setNotes(e.target.value)}
          onBlur={() => notes !== candidature.notes && onChange({ notes })}
          placeholder="Relance, contact pris…"
          className="w-full rounded border border-craie-300 px-1.5 py-1 text-sm resize-y"
        />
      </td>
      <td className="px-3 py-2 min-w-[10rem]">
        <input
          value={contact}
          onChange={(e) => setContact(e.target.value)}
          onBlur={() => contact !== candidature.contact && onChange({ contact })}
          placeholder="Nom, email…"
          className="w-full rounded border border-craie-300 px-1.5 py-1 text-sm"
        />
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        {candidature.url && (
          <a
            href={candidature.url}
            target="_blank"
            rel="noreferrer"
            className="text-encre-400 hover:text-encre-900 mr-2"
            title="Ouvrir l'annonce"
          >
            ↗
          </a>
        )}
        <button
          type="button"
          onClick={() => onSupprimer()}
          className="text-encre-400 hover:text-red-600"
          title="Supprimer cette candidature"
        >
          ×
        </button>
      </td>
    </tr>
  )
}

function Encart({ ton, children }: { ton: 'vert' | 'ambre' | 'rouge'; children: React.ReactNode }) {
  const styles = {
    vert: 'bg-succes-50 border-succes-200 text-succes-900',
    ambre: 'bg-alerte-50 border-alerte-200 text-alerte-900',
    rouge: 'bg-red-50 border-red-200 text-red-900',
  }[ton]
  return <div className={`rounded-md border px-4 py-2.5 text-sm ${styles}`}>{children}</div>
}

function Vide() {
  return (
    <div className="bg-white rounded-lg border border-dashed border-craie-300 p-10 text-center">
      <p className="text-encre-600 font-medium">Aucune candidature enregistrée.</p>
      <p className="text-sm text-encre-500 mt-1">
        Ouvrez une offre et cliquez sur « Postuler » — la candidature apparaîtra ici.
      </p>
      <Link
        to="/offres"
        className="inline-block mt-3 text-sm text-encre-900 underline underline-offset-2"
      >
        Voir les offres
      </Link>
    </div>
  )
}
