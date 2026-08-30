import type { ReactNode } from 'react'

export function Section({ titre, aide, action, children }: {
  titre: string
  aide?: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="bg-surface rounded-carte border border-craie-200 shadow-carte p-5">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="font-semibold text-encre-900">{titre}</h2>
          {aide && <p className="text-xs text-encre-500 mt-1 leading-relaxed">{aide}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function Champ({ libelle, valeur, onChange, placeholder, type = 'text' }: {
  libelle: string
  valeur: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
}) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-encre-600 mb-1">{libelle}</span>
      <input
        type={type}
        value={valeur}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-craie-300 bg-craie-50 px-3 py-2 text-sm
                   transition-colors placeholder:text-encre-300
                   focus:bg-surface focus:border-ambre-400 focus:outline-none"
      />
    </label>
  )
}

export function ZoneTexte({ libelle, valeur, onChange, lignes = 3, placeholder }: {
  libelle: string
  valeur: string
  onChange: (v: string) => void
  lignes?: number
  placeholder?: string
}) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-encre-600 mb-1.5">{libelle}</span>
      <textarea
        value={valeur}
        rows={lignes}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-craie-300 bg-craie-50 px-3 py-2 text-sm resize-y
                   leading-relaxed transition-colors placeholder:text-encre-300
                   focus:bg-surface focus:border-ambre-400 focus:outline-none"
      />
    </label>
  )
}

export function Bouton({ children, onClick, variante = 'secondaire', disabled, type = 'button' }: {
  children: ReactNode
  onClick?: () => void
  variante?: 'principal' | 'secondaire' | 'discret' | 'danger'
  disabled?: boolean
  type?: 'button' | 'submit'
}) {
  const styles = {
    principal: 'bg-ambre-500 text-white shadow-carte hover:bg-ambre-600 '
      + 'disabled:bg-craie-300 disabled:text-encre-400 disabled:shadow-none',
    secondaire: 'border border-craie-300 bg-surface text-encre-700 '
      + 'hover:border-encre-300 hover:text-encre-900 disabled:opacity-50',
    discret: 'text-encre-500 hover:text-encre-900 hover:bg-craie-200',
    danger: 'text-red-600 hover:bg-red-50',
  }[variante]
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all
                  disabled:cursor-not-allowed ${styles}`}
    >
      {children}
    </button>
  )
}
