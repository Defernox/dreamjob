import { verdictScore } from '../lib/format'

/** L'ordre est celui de `scoring/score.py:CRITERES`, et la liste doit rester
 *  complète : le composant n'affiche QUE ce qui figure ici. Un critère ajouté
 *  au back sans l'être ici fait baisser le score sans que rien ne l'explique. */
const LIBELLES: Record<string, string> = {
  competences: 'Compétences',
  secteur: 'Secteur',
  // La clé reste `pays`, mais le critère compte quatre paliers depuis qu'il
  // distingue votre ville du reste du pays : « Lieu » dit ce qu'il mesure.
  pays: 'Lieu',
  seniorite: 'Séniorité',
  langue: 'Langue',
  contrat: 'Contrat',
  fraicheur: 'Fraîcheur',
}

/** Une barre par critère : la valeur obtenue, et le poids du critère.
 *  Un critère absent de `detail` n'a pas pu être évalué — on le dit, plutôt
 *  que d'afficher un zéro qui ferait croire à un mauvais résultat. */
export function BarresScore({ detail, poids, explication }: {
  detail: Record<string, number>
  poids: Record<string, number>
  explication: string
}) {
  return (
    <div className="space-y-3.5">
      {Object.keys(LIBELLES).map((critere) => {
        const valeur = detail[critere]
        const evalue = valeur !== undefined && valeur !== null
        const verdict = verdictScore(evalue ? valeur : null)
        return (
          <div key={critere}>
            <div className="flex items-baseline justify-between text-sm mb-1.5">
              <span className="font-medium text-encre-800">
                {LIBELLES[critere]}
                {/* Le poids en petit : il explique la barre sans la concurrencer. */}
                <span className="text-encre-400 font-normal ml-1.5 text-xs">
                  {poids[critere] ?? 0} %
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

      {explication && (
        <p className="text-sm text-encre-600 pt-3 mt-1 border-t border-craie-200 leading-relaxed">
          {explication}
        </p>
      )}
    </div>
  )
}
