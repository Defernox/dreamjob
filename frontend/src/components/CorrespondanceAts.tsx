import type { Correspondance } from '../api/offres'

/** Ce que verra le recruteur dans son ATS, avant de générer quoi que ce soit.
 *  Le taux n'est pas un score de plus : le score dit si l'offre convient, le taux
 *  dit si le CV parle la langue de l'annonce. */
export function CorrespondanceAts({ c }: { c: Correspondance }) {
  const atteint = c.taux !== null && c.taux >= c.taux_vise
  return (
    <div className="space-y-4 text-sm">
      <div>
        <span className="block text-xs font-medium text-encre-500 mb-1">Titre sous votre nom</span>
        <span className="font-medium text-encre-900">{c.titre_cv || '—'}</span>
        {!c.titre_reprend_l_offre && (
          <p className="mt-1 text-xs text-alerte-800">
            Ce n&apos;est pas l&apos;intitulé de l&apos;annonce : un recruteur qui le cherche
            ne trouvera pas ce CV. Renseignez l&apos;accord dans votre profil si l&apos;annonce
            donne deux intitulés.
          </p>
        )}
      </div>

      {c.taux !== null && (
        <div>
          <div className="flex items-baseline justify-between mb-1.5">
            <span className="text-xs font-medium text-encre-500">Termes de l&apos;annonce couverts</span>
            <span className={`tabular-nums font-semibold ${atteint ? 'text-succes-700' : 'text-alerte-800'}`}>
              {c.taux} %<span className="text-encre-400 font-normal text-xs"> · visé {c.taux_vise} %</span>
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-craie-200 overflow-hidden">
            <div
              className={`h-full rounded-full ${atteint ? 'bg-succes-600' : 'bg-alerte-600'}`}
              style={{ width: `${Math.max(c.taux, 1)}%` }}
            />
          </div>
        </div>
      )}

      <Pastilles titre="Présents dans votre profil" termes={c.termes_couverts} teinte="succes" />
      <Pastilles
        titre="Réclamés par l'annonce, absents de votre profil"
        termes={c.termes_manquants}
        teinte="alerte"
        aide="À ajouter à votre profil si vous les maîtrisez vraiment — jamais sinon."
      />

      {(c.langues_exigees.length > 0 || c.annees_exigees !== null) && (
        <dl className="grid grid-cols-2 gap-3 text-xs">
          {c.langues_exigees.length > 0 && (
            <div>
              <dt className="text-encre-500">Langues exigées</dt>
              <dd className="font-medium text-encre-800 uppercase">{c.langues_exigees.join(', ')}</dd>
            </div>
          )}
          {c.annees_exigees !== null && (
            <div>
              <dt className="text-encre-500">Ancienneté demandée</dt>
              <dd className="font-medium text-encre-800">
                {c.annees_exigees} ans
                {c.annees_profil !== null && (
                  <span className="text-encre-500 font-normal"> · vous : {c.annees_profil}</span>
                )}
              </dd>
            </div>
          )}
        </dl>
      )}

      {c.description_tronquee && (
        <p className="rounded-md bg-alerte-50 border border-alerte-200 px-3 py-2 text-xs text-alerte-900">
          Description tronquée par la source : l&apos;annonce complète contient sans doute
          d&apos;autres exigences. Ouvrez-la avant de postuler.
        </p>
      )}
    </div>
  )
}

function Pastilles({ titre, termes, teinte, aide }: {
  titre: string
  termes: string[]
  teinte: 'succes' | 'alerte'
  aide?: string
}) {
  if (termes.length === 0) return null
  const classes = teinte === 'succes'
    ? 'bg-succes-50 border-succes-200 text-succes-900'
    : 'bg-alerte-50 border-alerte-200 text-alerte-900'
  return (
    <div>
      <span className="block text-xs font-medium text-encre-500 mb-1.5">{titre}</span>
      <div className="flex flex-wrap gap-1.5">
        {termes.map((t) => (
          <span key={t} className={`rounded-md border px-2 py-0.5 text-xs ${classes}`}>{t}</span>
        ))}
      </div>
      {aide && <p className="mt-1.5 text-xs text-encre-500">{aide}</p>}
    </div>
  )
}
