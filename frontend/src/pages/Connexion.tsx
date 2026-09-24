import { useState } from 'react'
import { useConnexion } from '../api/acces'
import { Marque } from '../components/Marque'

/** Affichée à la place de l'application quand le serveur exige une connexion.
 *  Il n'y a pas d'inscription : un compte se crée sur le serveur. */
export default function Connexion() {
  const connexion = useConnexion()
  const [email, setEmail] = useState('')
  const [motDePasse, setMotDePasse] = useState('')

  const envoyer = (e: React.FormEvent) => {
    e.preventDefault()
    connexion.mutate({ email, mot_de_passe: motDePasse })
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-craie-100 px-4">
      <form
        onSubmit={envoyer}
        className="w-full max-w-sm bg-surface rounded-carte border border-craie-200 shadow-carte p-7 space-y-4"
      >
        <div className="flex items-center gap-2.5 font-semibold text-lg text-encre-900">
          <Marque />
          DreamJob
        </div>
        <label className="block">
          <span className="block text-xs font-medium text-encre-600 mb-1">Adresse e-mail</span>
          <input
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-lg border border-craie-300 bg-craie-50 px-3 py-2 text-sm
                       focus:bg-surface focus:border-ambre-400 focus:outline-none"
          />
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-encre-600 mb-1">Mot de passe</span>
          <input
            type="password"
            autoComplete="current-password"
            required
            value={motDePasse}
            onChange={(e) => setMotDePasse(e.target.value)}
            className="w-full rounded-lg border border-craie-300 bg-craie-50 px-3 py-2 text-sm
                       focus:bg-surface focus:border-ambre-400 focus:outline-none"
          />
        </label>
        {connexion.isError && (
          <p className="text-sm text-red-700">{(connexion.error as Error).message}</p>
        )}
        <button
          type="submit"
          disabled={connexion.isPending}
          className="w-full rounded-lg bg-ambre-500 hover:bg-ambre-600 text-white text-sm font-medium
                     py-2.5 transition-colors disabled:opacity-60"
        >
          {connexion.isPending ? 'Connexion…' : 'Se connecter'}
        </button>
      </form>
    </div>
  )
}
