/** Chips de filtre avec compteur en direct. Une option à 0 reste cliquable
 *  si elle est active : sinon on ne pourrait plus la décocher. */
export function GroupeChips({ titre, options, compteurs, valeurs, onChange }: {
  titre: string
  options: string[]
  compteurs: Record<string, number>
  valeurs: string[]
  onChange: (v: string[]) => void
}) {
  const visibles = options.filter((o) => compteurs[o] > 0 || valeurs.includes(o))
  if (visibles.length === 0) return null

  return (
    <div className="flex items-baseline gap-3">
      <span className="text-xs font-medium text-slate-500 w-16 shrink-0">{titre}</span>
      <div className="flex flex-wrap gap-1.5">
        {visibles.map((o) => {
          const actif = valeurs.includes(o)
          return (
            <button
              key={o}
              type="button"
              onClick={() => onChange(actif ? valeurs.filter((v) => v !== o) : [...valeurs, o])}
              className={`px-2.5 py-1 rounded-full text-sm border transition-colors ${
                actif
                  ? 'bg-slate-900 text-white border-slate-900'
                  : 'bg-white text-slate-600 border-slate-300 hover:border-slate-400'
              }`}
            >
              {o}
              <span className={`ml-1.5 tabular-nums ${actif ? 'text-slate-300' : 'text-slate-400'}`}>
                {compteurs[o] ?? 0}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
