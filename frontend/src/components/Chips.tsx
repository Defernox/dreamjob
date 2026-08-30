import { useState } from 'react'

/** Au-delà, la rangée devient un mur : vingt-cinq pays alignés se parcourent
 *  moins vite qu'ils ne se replient. Les options actives restent toujours
 *  visibles, sinon on ne saurait plus ce qu'on filtre. */
const VISIBLES_PAR_DEFAUT = 10

/** Chips de filtre avec compteur en direct. Une option à 0 reste cliquable
 *  si elle est active : sinon on ne pourrait plus la décocher. */
export function GroupeChips({ titre, options, compteurs, valeurs, onChange }: {
  titre: string
  options: string[]
  compteurs: Record<string, number>
  valeurs: string[]
  onChange: (v: string[]) => void
}) {
  const [tout, setTout] = useState(false)
  const visibles = options.filter((o) => compteurs[o] > 0 || valeurs.includes(o))
  if (visibles.length === 0) return null

  // Les actives d'abord : replié, on doit voir ce qu'on a coché.
  const ordonnees = [...visibles].sort(
    (a, b) => Number(valeurs.includes(b)) - Number(valeurs.includes(a)),
  )
  const replie = !tout && ordonnees.length > VISIBLES_PAR_DEFAUT
  const affichees = replie ? ordonnees.slice(0, VISIBLES_PAR_DEFAUT) : ordonnees

  return (
    <div className="flex items-start gap-3">
      <span className="text-xs font-medium text-encre-500 w-16 shrink-0 pt-1.5">{titre}</span>
      <div className="flex flex-wrap gap-1.5">
        {affichees.map((o) => {
          const actif = valeurs.includes(o)
          return (
            <button
              key={o}
              type="button"
              onClick={() => onChange(actif ? valeurs.filter((v) => v !== o) : [...valeurs, o])}
              className={`px-2.5 py-1 rounded-full text-[13px] border transition-all ${
                actif
                  ? 'bg-ambre-500 text-white border-ambre-500 shadow-carte'
                  : 'bg-white text-encre-600 border-craie-300 hover:border-ambre-300 hover:text-encre-900'
              }`}
            >
              {o}
              <span className={`ml-1.5 tabular-nums text-xs ${
                actif ? 'text-white/70' : 'text-encre-400'
              }`}>
                {compteurs[o] ?? 0}
              </span>
            </button>
          )
        })}
        {ordonnees.length > VISIBLES_PAR_DEFAUT && (
          <button
            type="button"
            onClick={() => setTout(!tout)}
            className="px-2.5 py-1 rounded-full text-[13px] text-encre-500
                       hover:text-ambre-600 transition-colors"
          >
            {replie ? `+ ${ordonnees.length - VISIBLES_PAR_DEFAUT} autres` : 'réduire'}
          </button>
        )}
      </div>
    </div>
  )
}
