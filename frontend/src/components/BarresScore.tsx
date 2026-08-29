const LIBELLES: Record<string, string> = {
  competences: 'Compétences',
  secteur: 'Secteur',
  pays: 'Pays',
  langue: 'Langue',
  contrat: 'Contrat',
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
    <div className="space-y-3">
      {Object.keys(LIBELLES).map((critere) => {
        const valeur = detail[critere]
        const evalue = valeur !== undefined && valeur !== null
        return (
          <div key={critere}>
            <div className="flex items-baseline justify-between text-sm mb-1">
              <span className="font-medium">
                {LIBELLES[critere]}
                <span className="text-slate-400 font-normal ml-1.5">
                  {poids[critere] ?? 0} %
                </span>
              </span>
              <span className={`tabular-nums ${evalue ? 'font-medium' : 'text-slate-400 text-xs'}`}>
                {evalue ? `${Math.round(valeur)} / 100` : 'non évalué'}
              </span>
            </div>
            <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
              {evalue && (
                <div
                  className={`h-full rounded-full ${
                    valeur >= 75 ? 'bg-emerald-500' : valeur >= 50 ? 'bg-amber-500' : 'bg-slate-400'
                  }`}
                  style={{ width: `${Math.max(valeur, 1)}%` }}
                />
              )}
            </div>
          </div>
        )
      })}

      {explication && (
        <p className="text-sm text-slate-600 pt-2 border-t border-slate-100 leading-relaxed">
          {explication}
        </p>
      )}
    </div>
  )
}
