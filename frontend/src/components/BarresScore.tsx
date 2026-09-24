import { verdictScore } from '../lib/format'

/** Les trois étages du score, dans l'ordre de `scoring/score.py:CRITERES`. La
 *  liste doit rester complète : le composant n'affiche QUE ce qui figure ici.
 *  Un critère ajouté au back sans l'être ici fait bouger le score sans que
 *  rien ne l'explique. */
export const GROUPES: {
  cle: 'pertinence' | 'accessibilite' | 'conditions'
  titre: string
  aide: string
  criteres: Record<string, string>
}[] = [
  {
    cle: 'pertinence',
    titre: 'Pertinence',
    aide: 'Le poste est-il le vôtre ? C’est elle qui fait le score.',
    criteres: { metier: 'Métier', competences: 'Contenu de l’annonce' },
  },
  {
    cle: 'accessibilite',
    titre: 'Accessibilité',
    aide: 'Pouvez-vous l’obtenir ? Elle ne fait que retirer des points.',
    criteres: { seniorite: 'Niveau du poste', formation: 'Diplôme', langue: 'Langue' },
  },
  {
    cle: 'conditions',
    titre: 'Conditions',
    aide: 'Le voulez-vous, ici et maintenant ? Elles modulent le score.',
    // La clé reste `pays`, mais le critère mesure le lieu, sur quatre paliers.
    criteres: { pays: 'Lieu', contrat: 'Contrat', fraicheur: 'Fraîcheur' },
  },
]

/** Le poids d'un critère dans son groupe, en pour cent. */
export const poidsDansLeGroupe = (normalises: Record<string, number>, critere: string) =>
  Math.round((normalises[critere] ?? 0) * 100)

/** Une barre par critère, groupées par étage. Un critère absent de `detail`
 *  n'a pas pu être évalué — on le dit, plutôt que d'afficher un zéro qui ferait
 *  croire à un mauvais résultat. */
export function BarresScore({ detail, poids, explication }: {
  detail: Record<string, number>
  poids: Record<string, number>
  explication: string
}) {
  const lignes = explication.split('\n').filter(Boolean)
  return (
    <div className="space-y-5">
      {GROUPES.map((groupe) => (
        <div key={groupe.cle}>
          <div className="mb-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-encre-500">
              {groupe.titre}
            </h3>
            <p className="text-xs text-encre-400">{groupe.aide}</p>
          </div>
          <div className="space-y-3">
            {Object.entries(groupe.criteres).map(([critere, libelle]) => {
              const valeur = detail[critere]
              const evalue = valeur !== undefined && valeur !== null
              const verdict = verdictScore(evalue ? valeur : null)
              return (
                <div key={critere}>
                  <div className="flex items-baseline justify-between text-sm mb-1.5">
                    <span className="font-medium text-encre-800">
                      {libelle}
                      {/* Le poids en petit : il explique la barre sans la concurrencer. */}
                      <span className="text-encre-400 font-normal ml-1.5 text-xs">
                        {poidsDansLeGroupe(poids, critere)} %
                      </span>
                    </span>
                    <span
                      className={`tabular-nums text-sm ${
                        evalue ? `font-semibold ${verdict.texte}` : 'text-encre-400 text-xs'
                      }`}
                    >
                      {evalue ? `${Math.round(valeur)}` : 'non évalué'}
                      {evalue && <span className="text-encre-300 font-normal"> / 100</span>}
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full bg-craie-200 overflow-hidden">
                    {evalue && (
                      <div
                        className={`h-full rounded-full transition-[width] duration-500 ${verdict.fond}`}
                        style={{ width: `${Math.max(valeur, 1)}%` }}
                      />
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}

      {lignes.length > 0 && (
        <ul className="text-sm text-encre-600 pt-3 mt-1 border-t border-craie-200 leading-relaxed space-y-1.5">
          {lignes.map((ligne) => {
            // « Rédhibitoire : … » ouvre l'explication quand il y en a un : il
            // doit se voir avant tout le reste.
            const redhibitoire = ligne.startsWith('Rédhibitoire')
            const [titre, ...reste] = ligne.split(' : ')
            return (
              <li key={ligne}
                  className={redhibitoire ? 'rounded bg-red-50 border border-red-200 px-2 py-1 text-red-800' : ''}>
                {reste.length ? (
                  <>
                    <span className={redhibitoire ? 'font-semibold' : 'font-medium text-encre-800'}>
                      {titre}
                    </span>{' '}: {reste.join(' : ')}
                  </>
                ) : ligne}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
