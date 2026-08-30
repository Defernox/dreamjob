import { useSante } from '../api/hooks'

/** Avertit d'emblée si l'installation est incomplète — pas de panne silencieuse. */
export function BandeauSante() {
  const { data, isError } = useSante()

  if (isError) {
    return (
      <div className="bg-red-50 border-b border-red-200 px-6 py-2 text-sm text-red-800">
        API injoignable. Vérifiez que le serveur tourne sur le port 8000.
      </div>
    )
  }
  if (!data) return null

  const alertes = [
    data.llm.message,
    data.pdf.message,
    !data.modele_cv.present
      ? `Modèle de CV absent : déposez votre fichier dans ${data.modele_cv.chemin}`
      : null,
  ].filter(Boolean) as string[]

  if (alertes.length === 0) return null

  return (
    <div className="bg-alerte-50 border-b border-alerte-200 px-6 py-2 text-sm text-alerte-900">
      {alertes.map((a) => (
        <div key={a}>⚠ {a}</div>
      ))}
    </div>
  )
}
