import { useEffect, useState } from 'react'

/** Retarde la propagation d'une valeur qui change vite.
 *
 *  La zone de recherche déclenchait une requête à chaque frappe — et chaque
 *  requête coûte quatre requêtes SQL côté serveur (la liste plus les trois
 *  compteurs de facettes). Taper « analyste » en lançait huit.
 */
export function useTemporise<T>(valeur: T, delai = 250): T {
  const [retardee, setRetardee] = useState(valeur)

  useEffect(() => {
    const minuteur = setTimeout(() => setRetardee(valeur), delai)
    return () => clearTimeout(minuteur)
  }, [valeur, delai])

  return retardee
}
