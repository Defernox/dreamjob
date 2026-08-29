import type { ReactNode } from 'react'

export function Section({ titre, aide, action, children }: {
  titre: string
  aide?: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="bg-white rounded-lg border border-slate-200 p-5">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="font-semibold">{titre}</h2>
          {aide && <p className="text-xs text-slate-500 mt-0.5">{aide}</p>}
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
      <span className="block text-xs font-medium text-slate-600 mb-1">{libelle}</span>
      <input
        type={type}
        value={valeur}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm
                   focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400"
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
      <span className="block text-xs font-medium text-slate-600 mb-1">{libelle}</span>
      <textarea
        value={valeur}
        rows={lignes}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm resize-y
                   focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400"
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
    principal: 'bg-slate-900 text-white hover:bg-slate-800 disabled:bg-slate-300',
    secondaire: 'border border-slate-300 bg-white hover:bg-slate-50 disabled:opacity-50',
    discret: 'text-slate-500 hover:text-slate-900 hover:bg-slate-100',
    danger: 'text-red-600 hover:bg-red-50',
  }[variante]
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors disabled:cursor-not-allowed ${styles}`}
    >
      {children}
    </button>
  )
}
