import { Link, useParams } from 'react-router-dom'
import { useReglages } from '../api/hooks'
import { usePostuler } from '../api/candidatures'
import { useGenererDocuments } from '../api/documents'
import { useOffre } from '../api/offres'
import { BarresScore } from '../components/BarresScore'
import { Bouton } from '../components/champs'
import { ScoreBadge } from '../components/ScoreBadge'
import { anciennete, dateHeureFr } from '../lib/format'

export default function OffreDetail() {
  const { id } = useParams()
  const identifiant = id ? Number(id) : null
  const { data: offre, isLoading, isError, error } = useOffre(identifiant)
  const { data: reglages } = useReglages()
  const postuler = usePostuler()
  const documents = useGenererDocuments()

  if (isLoading) return <p className="text-sm text-slate-500">Chargement de l&apos;offre…</p>
  if (isError) {
    return (
      <div className="max-w-xl">
        <Retour />
        <p className="mt-4 text-sm text-red-700">{(error as Error).message}</p>
      </div>
    )
  }
  if (!offre) return null

  const dejaPostule = offre.a_candidature || postuler.isSuccess

  return (
    <div className="max-w-6xl">
      <Retour />

      <div className="mt-4 grid gap-5 lg:grid-cols-[1fr_20rem] items-start">
        <div className="space-y-5">
          <div className="bg-white rounded-lg border border-slate-200 p-5">
            <div className="flex gap-4">
              <ScoreBadge score={offre.score} seuils={reglages?.scoring.seuils} taille="grand" />
              <div className="min-w-0">
                <h1 className="text-xl font-semibold leading-snug">{offre.titre}</h1>
                <p className="text-slate-600">{offre.entreprise || '—'}</p>
                <p className="text-sm text-slate-500">
                  {[offre.lieu, offre.pays].filter(Boolean).join(' · ') || '—'}
                  {' · '}
                  {anciennete(offre.date_publication ?? offre.date_recuperation)}
                </p>
                <div className="flex flex-wrap items-center gap-1.5 mt-2.5">
                  <Etiquette>{offre.source}</Etiquette>
                  {offre.type_contrat && <Etiquette>{offre.type_contrat}</Etiquette>}
                  {offre.url && (
                    <a
                      href={offre.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sm text-slate-600 underline underline-offset-2 hover:text-slate-900 ml-1"
                    >
                      Source ↗
                    </a>
                  )}
                </div>
              </div>
            </div>
          </div>

          <section className="bg-white rounded-lg border border-slate-200 p-5">
            <h2 className="font-semibold mb-4">Détail du score</h2>
            {offre.score === null ? (
              <p className="text-sm text-slate-500">
                Cette offre n&apos;a pas encore été scorée. Lancez le calcul depuis
                l&apos;écran Offres.
              </p>
            ) : (
              <>
                <BarresScore
                  detail={offre.score_detail}
                  poids={reglages?.scoring.poids ?? {}}
                  explication={offre.score_explication}
                />
                <p className="text-xs text-slate-400 mt-4">
                  Calculé localement le {dateHeureFr(offre.scored_at)} — aucun appel à un
                  modèle de langage. Les poids se modifient dans <code>config.yaml</code>.
                </p>
              </>
            )}
          </section>

          <section className="bg-white rounded-lg border border-slate-200 p-5">
            <h2 className="font-semibold mb-3">Description</h2>
            <p className="text-sm text-slate-700 whitespace-pre-wrap leading-relaxed">
              {offre.description_brute || 'Aucune description fournie par la source.'}
            </p>
          </section>
        </div>

        <aside className="bg-white rounded-lg border border-slate-200 p-5 space-y-4 lg:sticky lg:top-5">
          <div>
            <h2 className="font-semibold">Actions</h2>
            <p className="text-sm text-slate-500 mt-0.5">
              Générez vos documents (Word + PDF) puis postulez en un clic.
            </p>
          </div>

          <div className="space-y-2">
            <Bouton
              onClick={() => documents.mutate(offre.id)}
              disabled={documents.isPending}
            >
              {documents.isPending ? 'Génération en cours…' : 'Générer les documents'}
            </Bouton>
            {documents.isPending && (
              <p className="text-xs text-slate-500">
                Le CV se rend depuis votre modèle, la lettre est écrite en local et
                vérifiée. Comptez une minute.
              </p>
            )}
            {documents.isError && (
              <p className="text-xs text-red-700">{(documents.error as Error).message}</p>
            )}
            {documents.isSuccess && (
              <div className="rounded-md bg-emerald-50 border border-emerald-200 px-3 py-2.5 text-xs text-emerald-900">
                <p className="font-medium">
                  ✓ {documents.data.fichiers.length} fichiers générés
                  {documents.data.ouvert && ' — dossier ouvert'}
                </p>
                <ul className="mt-1 space-y-0.5">
                  {documents.data.fichiers.map((f) => <li key={f}>· {f}</li>)}
                </ul>
                {documents.data.lettre_essais > 1 && (
                  <p className="mt-1.5 text-emerald-800">
                    Lettre acceptée au {documents.data.lettre_essais}e essai — les
                    versions précédentes contenaient des éléments absents de votre profil.
                  </p>
                )}
                <p className="mt-1.5 font-mono text-[11px] text-emerald-800 break-all">
                  {documents.data.dossier}
                </p>
                {documents.data.avertissements.map((a) => (
                  <p key={a} className="mt-1.5 text-amber-800">⚠ {a}</p>
                ))}
                {documents.data.mots_cles_non_couverts.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-emerald-200">
                    <p className="font-medium text-emerald-900">
                      Ce que cette offre demande et que votre profil ne couvre pas
                    </p>
                    <p className="mt-1 flex flex-wrap gap-1">
                      {documents.data.mots_cles_non_couverts.map((m) => (
                        <span key={m}
                              className="rounded bg-white/70 px-1.5 py-0.5 text-emerald-800">
                          {m}
                        </span>
                      ))}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="space-y-2 pt-2 border-t border-slate-100">
            {dejaPostule ? (
              <div className="rounded-md bg-emerald-50 border border-emerald-200 px-3 py-2.5 text-sm text-emerald-900">
                <p className="font-medium">✓ Candidature enregistrée</p>
                <p className="mt-1 text-emerald-800">
                  L&apos;offre est ouverte dans un nouvel onglet — mettez à jour le statut
                  depuis l&apos;onglet Candidatures.
                </p>
              </div>
            ) : (
              <Bouton
                variante="principal"
                disabled={postuler.isPending || !offre.url}
                onClick={() => {
                  // L'onglet s'ouvre AVANT l'appel réseau : ouvert depuis un clic,
                  // il ne sera pas bloqué comme une popup.
                  window.open(offre.url, '_blank', 'noopener')
                  postuler.mutate(offre.id)
                }}
              >
                {postuler.isPending ? 'Enregistrement…' : 'Postuler'}
              </Bouton>
            )}
            {!offre.url && (
              <p className="text-xs text-amber-700">
                Cette offre n&apos;a pas d&apos;URL : impossible d&apos;ouvrir l&apos;annonce.
              </p>
            )}
            {postuler.isError && (
              <p className="text-xs text-red-700">{(postuler.error as Error).message}</p>
            )}
          </div>

          <dl className="text-xs text-slate-500 space-y-1 pt-2 border-t border-slate-100">
            <Ligne libelle="Récupérée le" valeur={dateHeureFr(offre.date_recuperation)} />
            <Ligne libelle="Publiée le" valeur={dateHeureFr(offre.date_publication)} />
            <Ligne libelle="Identifiant source" valeur={offre.source} />
          </dl>
        </aside>
      </div>
    </div>
  )
}

const Retour = () => (
  <Link to="/offres" className="text-sm text-slate-500 hover:text-slate-900">
    ← Retour aux offres
  </Link>
)

const Etiquette = ({ children }: { children: React.ReactNode }) => (
  <span className="px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600">{children}</span>
)

const Ligne = ({ libelle, valeur }: { libelle: string; valeur: string }) => (
  <div className="flex justify-between gap-3">
    <dt>{libelle}</dt>
    <dd className="text-slate-600">{valeur}</dd>
  </div>
)
