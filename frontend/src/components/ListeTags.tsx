import { useState } from 'react'

/** Saisie libre de mots-clés : Entrée ajoute, × retire, Retour arrière retire le dernier. */
export function ListeTags({ valeurs, onChange, placeholder }: {
  valeurs: string[]
  onChange: (v: string[]) => void
  placeholder?: string
}) {
  const [saisie, setSaisie] = useState('')

  const ajouter = (brut: string) => {
    const valeur = brut.trim()
    if (!valeur || valeurs.includes(valeur)) return
    onChange([...valeurs, valeur])
    setSaisie('')
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-craie-300 px-2 py-1.5
                    focus-within:ring-2 focus-within:ring-encre-900/10 focus-within:border-encre-400">
      {valeurs.map((v) => (
        <span key={v} className="inline-flex items-center gap-1 bg-craie-200 rounded px-2 py-0.5 text-sm">
          {v}
          <button
            type="button"
            onClick={() => onChange(valeurs.filter((x) => x !== v))}
            className="text-encre-400 hover:text-encre-900 leading-none"
            aria-label={`Retirer ${v}`}
          >
            ×
          </button>
        </span>
      ))}
      <input
        value={saisie}
        placeholder={valeurs.length === 0 ? placeholder : ''}
        onChange={(e) => setSaisie(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            ajouter(saisie)
          } else if (e.key === 'Backspace' && !saisie && valeurs.length) {
            onChange(valeurs.slice(0, -1))
          }
        }}
        onBlur={() => ajouter(saisie)}
        className="flex-1 min-w-[8rem] text-sm outline-none bg-transparent py-0.5"
      />
    </div>
  )
}

/** Choix multiple dans une liste fermée (les pays). */
export function ChoixMultiple({ options, valeurs, onChange }: {
  options: string[]
  valeurs: string[]
  onChange: (v: string[]) => void
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const actif = valeurs.includes(o)
        return (
          <button
            key={o}
            type="button"
            onClick={() => onChange(actif ? valeurs.filter((v) => v !== o) : [...valeurs, o])}
            className={`px-2.5 py-1 rounded-full text-sm border transition-colors ${
              actif
                ? 'bg-ambre-500 text-white border-ambre-500'
                : 'bg-surface text-encre-600 border-craie-300 hover:border-encre-400'
            }`}
          >
            {o}
          </button>
        )
      })}
    </div>
  )
}

/** Choix multiple groupé par zone : au-delà d'une vingtaine d'options, une
 *  liste à plat devient illisible. */
export function ChoixMultipleGroupe({ zones, valeurs, onChange }: {
  zones: Record<string, string[]>
  valeurs: string[]
  onChange: (v: string[]) => void
}) {
  const basculer = (pays: string) =>
    onChange(valeurs.includes(pays) ? valeurs.filter((v) => v !== pays) : [...valeurs, pays])

  return (
    <div className="space-y-3">
      {Object.entries(zones).map(([zone, pays]) => {
        const choisis = pays.filter((p) => valeurs.includes(p)).length
        const tousChoisis = choisis === pays.length
        return (
          <div key={zone}>
            <div className="flex items-baseline gap-2 mb-1.5">
              <span className="text-xs font-medium text-encre-500">{zone}</span>
              <button
                type="button"
                onClick={() =>
                  onChange(tousChoisis
                    ? valeurs.filter((v) => !pays.includes(v))
                    : [...new Set([...valeurs, ...pays])])
                }
                className="text-xs text-encre-400 hover:text-encre-900"
              >
                {tousChoisis ? 'tout retirer' : 'tout choisir'}
              </button>
              {choisis > 0 && (
                <span className="text-xs text-encre-400 tabular-nums">
                  {choisis}/{pays.length}
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {pays.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => basculer(p)}
                  className={`px-2.5 py-1 rounded-full text-sm border transition-colors ${
                    valeurs.includes(p)
                      ? 'bg-ambre-500 text-white border-ambre-500'
                      : 'bg-surface text-encre-600 border-craie-300 hover:border-encre-400'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/** Choix ORDONNÉ : la position porte la préférence, elle doit être visible et modifiable. */
export function ChoixOrdonne({ options, valeurs, onChange }: {
  options: string[]
  valeurs: string[]
  onChange: (v: string[]) => void
}) {
  const deplacer = (index: number, delta: number) => {
    const cible = index + delta
    if (cible < 0 || cible >= valeurs.length) return
    const copie = [...valeurs]
    ;[copie[index], copie[cible]] = [copie[cible], copie[index]]
    onChange(copie)
  }

  return (
    <div className="space-y-3">
      {valeurs.length > 0 && (
        <ol className="space-y-1">
          {valeurs.map((v, i) => (
            <li key={v} className="flex items-center gap-2 text-sm">
              <span className="w-5 text-right text-encre-400 tabular-nums">{i + 1}.</span>
              <span className="flex-1 font-medium">{v}</span>
              <button type="button" onClick={() => deplacer(i, -1)} disabled={i === 0}
                className="px-1.5 text-encre-400 hover:text-encre-900 disabled:opacity-25"
                aria-label="Monter">↑</button>
              <button type="button" onClick={() => deplacer(i, 1)} disabled={i === valeurs.length - 1}
                className="px-1.5 text-encre-400 hover:text-encre-900 disabled:opacity-25"
                aria-label="Descendre">↓</button>
              <button type="button" onClick={() => onChange(valeurs.filter((x) => x !== v))}
                className="px-1.5 text-encre-400 hover:text-red-600"
                aria-label={`Retirer ${v}`}>×</button>
            </li>
          ))}
        </ol>
      )}
      <div className="flex flex-wrap gap-1.5">
        {options.filter((o) => !valeurs.includes(o)).map((o) => (
          <button
            key={o}
            type="button"
            onClick={() => onChange([...valeurs, o])}
            className="px-2.5 py-1 rounded-full text-sm border border-dashed border-craie-300
                       text-encre-500 hover:border-encre-400 hover:text-encre-900"
          >
            + {o}
          </button>
        ))}
      </div>
    </div>
  )
}
