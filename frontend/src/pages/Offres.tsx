import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useReglages } from '../api/hooks'
import {
  FILTRES_VIDES,
  PAR_PAGE,
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
import { Recherches } from '../components/Recherches'
import { ScoreBadge } from '../components/ScoreBadge'
import { anciennete, nombreFr } from '../lib/format'
import { useTemporise } from '../lib/temporiser'

const TRIS = [
  { cle: 'pertinence', libelle: 'Pertinence' },
  { cle: 'recentes', libelle: 'Plus récentes' },
  { cle: 'anciennes', libelle: 'Plus anciennes' },
  { cle: 'score', libelle: 'Meilleur score' },
]

export default function Offres() {
  const [filtres, setFiltres] = useState<Filtres>(FILTRES_VIDES)
  // La saisie s'affiche sans délai, mais n'interroge le serveur qu'une fois la
  // frappe retombée : chaque requête en déclenche quatre côté base.
  const rechercheTemporisee = useTemporise(filtres.recherche)
  const { data: page, isLoading } = useOffres({ ...filtres, recherche: rechercheTemporisee })
  const { data: stats } = useStatistiques()
  const { data: reglages } = useReglages()
  const { data: planification } = usePlanification()
  const scan = useLancerScan()
  const scorer = useScorer()

  // Changer un filtre ramène la fenêtre à sa taille initiale : garder 300
  // offres affichées après avoir coché un contrat n'aurait aucun sens. Mais
  // `limite` est elle-même un champ : la remettre à zéro ici rendrait le bouton
  // « afficher plus » inopérant.
  const maj = <K extends keyof Filtres>(champ: K, valeur: Filtres[K]) =>
    setFiltres({
      ...filtres,
      ...(champ === 'limite' ? {} : { limite: PAR_PAGE }),
      [champ]: valeur,
    })

  const afficherPlus = () => maj('limite', filtres.limite + PAR_PAGE)

  const filtreActif =
    filtres.contrats.length + filtres.sources.length + filtres.pays.length > 0 ||
    filtres.score_min > 0 || filtres.recherche !== '' || filtres.expirees !== null

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-[26px] font-bold tracking-tight text-encre-950">Offres</h1>
          <p className="text-sm text-encre-500 mt-0.5">
            {stats ? (
              <>
                <strong className="text-encre-700">{nombreFr(stats.total)}</strong> offres
                {' · '}{nombreFr(stats.aujourd_hui)} aujourd&apos;hui
                {' · '}{nombreFr(stats.vie)} V.I.E
                {stats.nouvelles > 0 && (
                  <span className="ml-2 px-2 py-0.5 rounded-full bg-ambre-100 text-ambre-800
                                   text-xs font-semibold">
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
        <p className="text-xs text-encre-400 -mt-2">
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

      <Recherches />

      <div className="bg-surface/70 rounded-carte border border-craie-200 p-4 space-y-3">
        <div className="flex gap-3 flex-wrap items-center">
          <input
            value={filtres.recherche}
            onChange={(e) => maj('recherche', e.target.value)}
            placeholder="Rechercher dans les intitulés, entreprises, descriptions…"
            className="flex-1 min-w-[16rem] rounded-lg border border-craie-300 bg-surface px-3.5 py-2
                       text-sm transition-colors placeholder:text-encre-300
                       focus:border-ambre-400 focus:outline-none"
          />
          <label className="flex items-center gap-2 text-sm">
            <span className="text-encre-500">Tri</span>
            <select
              value={filtres.tri}
              onChange={(e) => maj('tri', e.target.value)}
              className="rounded-lg border border-craie-300 px-2.5 py-2 text-sm bg-surface
                         focus:border-ambre-400 focus:outline-none"
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

        {stats && stats.expirees > 0 && (
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium text-encre-500 w-16 shrink-0">En ligne</span>
            <label className="flex items-center gap-2 text-sm text-encre-600">
              <input
                type="checkbox"
                checked={filtres.expirees === false}
                onChange={(e) => maj('expirees', e.target.checked ? false : null)}
              />
              Masquer les {nombreFr(stats.expirees)} offres probablement retirées
            </label>
          </div>
        )}

        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-encre-500 w-16 shrink-0">Score ≥</span>
          <input
            type="range" min={0} max={100} step={5}
            value={filtres.score_min}
            onChange={(e) => maj('score_min', Number(e.target.value))}
            className="w-56 accent-encre-900"
          />
          <span className="text-sm tabular-nums font-medium w-8">{filtres.score_min}</span>
          {filtreActif && (
            <button
              type="button"
              onClick={() => setFiltres({ ...FILTRES_VIDES, tri: filtres.tri })}
              className="text-sm text-encre-500 hover:text-encre-900 ml-auto"
            >
              Tout effacer
            </button>
          )}
        </div>
      </div>

      {page && (
        <p className="text-sm text-encre-500">
          {page.offres.length < page.total
            ? `${nombreFr(page.offres.length)} offres affichées sur ${nombreFr(page.total)}`
            : `${nombreFr(page.total)} offre${page.total > 1 ? 's' : ''}`}
          {filtreActif && ' après filtrage'}
        </p>
      )}

      {isLoading && <p className="text-sm text-encre-500">Chargement…</p>}
      {page?.total === 0 && <Vide filtreActif={filtreActif} />}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {page?.offres.map((o) => (
          <Carte key={o.id} offre={o} seuils={reglages?.scoring.seuils} />
        ))}
      </div>

      {page && page.offres.length < page.total && (
        <div className="flex justify-center pt-2">
          <Bouton onClick={afficherPlus}>
            Afficher {nombreFr(Math.min(PAR_PAGE, page.total - page.offres.length))} offres
            de plus
          </Bouton>
        </div>
      )}
    </div>
  )
}

function Carte({ offre, seuils }: { offre: OffreResume; seuils?: { bon: number; moyen: number } }) {
  return (
    <Link
      to={`/offres/${offre.id}`}
      className="group bg-surface rounded-carte border border-craie-200 shadow-carte
                 p-4 flex gap-3.5 transition-all duration-150
                 hover:border-ambre-300 hover:shadow-carte-levee hover:-translate-y-0.5"
    >
      <ScoreBadge score={offre.score} seuils={seuils} />
      <div className="min-w-0 flex-1">
        <h3 className="font-semibold leading-snug line-clamp-2 text-encre-900
                       group-hover:text-ambre-700 transition-colors">
          {offre.titre}
        </h3>
        <p className="text-sm text-encre-600 truncate mt-0.5">{offre.entreprise || '—'}</p>
        <p className="text-xs text-encre-500 truncate">
          {[offre.lieu, offre.pays].filter(Boolean).join(' · ') || '—'}
        </p>
        <div className="flex flex-wrap items-center gap-1.5 mt-2">
          <Etiquette>{offre.source}</Etiquette>
          {offre.type_contrat && <Etiquette>{offre.type_contrat}</Etiquette>}
          {offre.a_candidature && (
            <Pastille ton="verte">candidature</Pastille>
          )}
          {!offre.vue && !offre.expiree && (
            <Pastille ton="neuve">nouvelle</Pastille>
          )}
          {offre.expiree && (
            <Pastille
              ton="fanee"
              titre="Aucun scan ne l'a revue depuis un moment : sans doute retirée du site"
            >
              expirée ?
            </Pastille>
          )}
          <span className="text-xs text-encre-400 ml-auto shrink-0">
            {anciennete(offre.date_publication ?? offre.date_recuperation)}
          </span>
        </div>
      </div>
    </Link>
  )
}

const Etiquette = ({ children }: { children: React.ReactNode }) => (
  <span className="px-2 py-0.5 rounded-md text-[11px] font-medium bg-craie-200 text-encre-600">
    {children}
  </span>
)

/** Les états d'une offre : un point de couleur et un mot, pas un pavillon.
 *  Trois pavillons pleins sur une carte se disputaient l'attention avec le
 *  score, qui est la seule information qui doive ressortir. */
function Pastille({ ton, titre, children }: {
  ton: 'verte' | 'neuve' | 'fanee'
  titre?: string
  children: React.ReactNode
}) {
  const points = {
    verte: 'bg-[var(--color-verdict-fort)]',
    neuve: 'bg-ambre-500',
    fanee: 'bg-encre-300',
  }[ton]
  return (
    <span
      title={titre}
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px]
                 font-medium bg-surface border border-craie-300 text-encre-600"
    >
      <span className={`w-1.5 h-1.5 rounded-full ${points}`} />
      {children}
    </span>
  )
}

function Message({ ton, children }: { ton: 'vert' | 'ambre' | 'rouge'; children: React.ReactNode }) {
  const styles = {
    vert: 'bg-succes-50 border-succes-200 text-succes-900',
    ambre: 'bg-alerte-50 border-alerte-200 text-alerte-900',
    rouge: 'bg-red-50 border-red-200 text-red-900',
  }[ton]
  return <div className={`rounded-md border px-4 py-2.5 text-sm ${styles}`}>{children}</div>
}

function Vide({ filtreActif }: { filtreActif: boolean }) {
  return (
    <div className="bg-surface rounded-lg border border-dashed border-craie-300 p-10 text-center">
      <p className="text-encre-600 font-medium">
        {filtreActif ? 'Aucune offre ne correspond à ces filtres.' : 'Aucune offre en base.'}
      </p>
      <p className="text-sm text-encre-500 mt-1">
        {filtreActif
          ? 'Élargissez les filtres, ou baissez le score minimum.'
          : 'Lancez une recherche pour interroger les sources actives.'}
      </p>
    </div>
  )
}
