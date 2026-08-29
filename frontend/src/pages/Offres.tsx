import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useReglages } from '../api/hooks'
import {
  FILTRES_VIDES,
  useLancerScan,
  useOffres,
  useScorer,
  usePlanification,
  useStatistiques,
  type Filtres,
  type OffreResume,
} from '../api/offres'
import { Bouton } from '../components/champs'
import { GroupeChips } from '../components/Chips'
import { ScoreBadge } from '../components/ScoreBadge'
import { anciennete, nombreFr } from '../lib/format'

const TRIS = [
  { cle: 'pertinence', libelle: 'Pertinence' },
  { cle: 'recentes', libelle: 'Plus récentes' },
  { cle: 'anciennes', libelle: 'Plus anciennes' },
  { cle: 'score', libelle: 'Meilleur score' },
]

export default function Offres() {
  const [filtres, setFiltres] = useState<Filtres>(FILTRES_VIDES)
  const { data: page, isLoading } = useOffres(filtres)
  const { data: stats } = useStatistiques()
  const { data: reglages } = useReglages()
  const { data: planification } = usePlanification()
  const scan = useLancerScan()
  const scorer = useScorer()

  const maj = <K extends keyof Filtres>(champ: K, valeur: Filtres[K]) =>
    setFiltres({ ...filtres, [champ]: valeur })

  const filtreActif =
    filtres.contrats.length + filtres.sources.length + filtres.pays.length > 0 ||
    filtres.score_min > 0 || filtres.recherche !== ''

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold">Offres</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {stats ? (
              <>
                <strong className="text-slate-700">{nombreFr(stats.total)}</strong> offres
                {' · '}{nombreFr(stats.aujourd_hui)} aujourd&apos;hui
                {' · '}{nombreFr(stats.vie)} V.I.E
                {stats.nouvelles > 0 && (
                  <span className="ml-2 px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 text-xs font-medium">
                    {nombreFr(stats.nouvelles)} nouvelles
                  </span>
                )}
              </>
            ) : '…'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {stats && stats.non_scorees > 0 && (
            <Bouton onClick={() => scorer.mutate(false)} disabled={scorer.isPending}>
              {scorer.isPending ? 'Calcul…' : `Scorer ${nombreFr(stats.non_scorees)} offres`}
            </Bouton>
          )}
          <Bouton variante="principal" onClick={() => scan.mutate()} disabled={scan.isPending}>
            {scan.isPending ? 'Recherche en cours…' : 'Lancer une recherche'}
          </Bouton>
        </div>
      </div>

      {planification && (
        <p className="text-xs text-slate-400 -mt-2">
          {planification.actif
            ? `Recherche automatique chaque jour à ${planification.heure}, et au démarrage si aucune n'a eu lieu depuis ${planification.rattrapage_apres_heures} h.`
            : 'Recherche automatique désactivée (config.yaml → planification).'}
          {planification.dernier_scan &&
            ` Dernière recherche ${anciennete(planification.dernier_scan)}` +
              (planification.dernier_scan_nouvelles
                ? ` — ${planification.dernier_scan_nouvelles} nouvelle(s) offre(s).`
                : ' — aucune nouveauté.')}
        </p>
      )}

      {scan.isError && <Message ton="rouge">{(scan.error as Error).message}</Message>}
      {scan.isSuccess && (
        <Message ton={scan.data.erreurs.length ? 'ambre' : 'vert'}>
          Recherche terminée : {scan.data.nb_nouvelles} nouvelle(s) offre(s).
          {scan.data.erreurs.length > 0 &&
            ' Certaines sources n’ont pas répondu — voir Profil → Diagnostic.'}
        </Message>
      )}
      {scorer.isError && <Message ton="rouge">{(scorer.error as Error).message}</Message>}
      {scorer.isSuccess && (
        <Message ton="vert">
          {scorer.data.scorees} offre(s) scorée(s) sur {scorer.data.total} — aucun appel LLM,
          calcul local.
        </Message>
      )}

      <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-3">
        <div className="flex gap-3 flex-wrap items-center">
          <input
            value={filtres.recherche}
            onChange={(e) => maj('recherche', e.target.value)}
            placeholder="Rechercher dans les intitulés, entreprises, descriptions…"
            className="flex-1 min-w-[16rem] rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
          <label className="flex items-center gap-2 text-sm">
            <span className="text-slate-500">Tri</span>
            <select
              value={filtres.tri}
              onChange={(e) => maj('tri', e.target.value)}
              className="rounded-md border border-slate-300 px-2 py-1.5 text-sm bg-white"
            >
              {TRIS.map((t) => <option key={t.cle} value={t.cle}>{t.libelle}</option>)}
            </select>
          </label>
        </div>

        <GroupeChips
          titre="Contrat"
          options={reglages?.vocabulaires.contrats ?? []}
          compteurs={page?.compteurs.contrat ?? {}}
          valeurs={filtres.contrats}
          onChange={(v) => maj('contrats', v)}
        />
        <GroupeChips
          titre="Source"
          options={Object.keys(page?.compteurs.source ?? {}).sort()}
          compteurs={page?.compteurs.source ?? {}}
          valeurs={filtres.sources}
          onChange={(v) => maj('sources', v)}
        />
        <GroupeChips
          titre="Pays"
          options={reglages?.vocabulaires.pays ?? []}
          compteurs={page?.compteurs.pays ?? {}}
          valeurs={filtres.pays}
          onChange={(v) => maj('pays', v)}
        />

        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-slate-500 w-16 shrink-0">Score ≥</span>
          <input
            type="range" min={0} max={100} step={5}
            value={filtres.score_min}
            onChange={(e) => maj('score_min', Number(e.target.value))}
            className="w-56 accent-slate-900"
          />
          <span className="text-sm tabular-nums font-medium w-8">{filtres.score_min}</span>
          {filtreActif && (
            <button
              type="button"
              onClick={() => setFiltres({ ...FILTRES_VIDES, tri: filtres.tri })}
              className="text-sm text-slate-500 hover:text-slate-900 ml-auto"
            >
              Tout effacer
            </button>
          )}
        </div>
      </div>

      {page && (
        <p className="text-sm text-slate-500">
          {nombreFr(page.total)} offre{page.total > 1 ? 's' : ''}
          {filtreActif && ' après filtrage'}
        </p>
      )}

      {isLoading && <p className="text-sm text-slate-500">Chargement…</p>}
      {page?.total === 0 && <Vide filtreActif={filtreActif} />}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {page?.offres.map((o) => (
          <Carte key={o.id} offre={o} seuils={reglages?.scoring.seuils} />
        ))}
      </div>
    </div>
  )
}

function Carte({ offre, seuils }: { offre: OffreResume; seuils?: { bon: number; moyen: number } }) {
  return (
    <Link
      to={`/offres/${offre.id}`}
      className="bg-white rounded-lg border border-slate-200 p-4 flex gap-3
                 hover:border-slate-400 hover:shadow-sm transition-all"
    >
      <ScoreBadge score={offre.score} seuils={seuils} />
      <div className="min-w-0 flex-1">
        <h3 className="font-medium leading-snug line-clamp-2">{offre.titre}</h3>
        <p className="text-sm text-slate-600 truncate">{offre.entreprise || '—'}</p>
        <p className="text-xs text-slate-500 truncate">
          {[offre.lieu, offre.pays].filter(Boolean).join(' · ') || '—'}
        </p>
        <div className="flex flex-wrap items-center gap-1.5 mt-2">
          <Etiquette>{offre.source}</Etiquette>
          {offre.type_contrat && <Etiquette>{offre.type_contrat}</Etiquette>}
          {offre.a_candidature && (
            <span className="px-1.5 py-0.5 rounded text-xs bg-emerald-100 text-emerald-800">
              candidature
            </span>
          )}
          {!offre.vue && (
            <span className="px-1.5 py-0.5 rounded text-xs bg-sky-100 text-sky-800">nouvelle</span>
          )}
          <span className="text-xs text-slate-400 ml-auto shrink-0">
            {anciennete(offre.date_publication ?? offre.date_recuperation)}
          </span>
        </div>
      </div>
    </Link>
  )
}

const Etiquette = ({ children }: { children: React.ReactNode }) => (
  <span className="px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600">{children}</span>
)

function Message({ ton, children }: { ton: 'vert' | 'ambre' | 'rouge'; children: React.ReactNode }) {
  const styles = {
    vert: 'bg-emerald-50 border-emerald-200 text-emerald-900',
    ambre: 'bg-amber-50 border-amber-200 text-amber-900',
    rouge: 'bg-red-50 border-red-200 text-red-900',
  }[ton]
  return <div className={`rounded-md border px-4 py-2.5 text-sm ${styles}`}>{children}</div>
}

function Vide({ filtreActif }: { filtreActif: boolean }) {
  return (
    <div className="bg-white rounded-lg border border-dashed border-slate-300 p-10 text-center">
      <p className="text-slate-600 font-medium">
        {filtreActif ? 'Aucune offre ne correspond à ces filtres.' : 'Aucune offre en base.'}
      </p>
      <p className="text-sm text-slate-500 mt-1">
        {filtreActif
          ? 'Élargissez les filtres, ou baissez le score minimum.'
          : 'Lancez une recherche pour interroger les sources actives.'}
      </p>
    </div>
  )
}
