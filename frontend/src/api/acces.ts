import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

/** En local, `connexion_requise` est faux et `connecte` vrai : rien ne change. */
export type EtatAcces = {
  connexion_requise: boolean
  connecte: boolean
  email: string | null
}

export const CLE_ACCES = ['acces']

export const useEtatAcces = () =>
  useQuery({
    queryKey: CLE_ACCES,
    queryFn: () => api.get<EtatAcces>('/api/acces/etat'),
    staleTime: Infinity,
  })

export function useConnexion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (identifiants: { email: string; mot_de_passe: string }) =>
      api.post<{ email: string }>('/api/acces/connexion', identifiants),
    // Tout ce qui a été chargé avant la connexion a échoué en 401 : on repart
    // de zéro plutôt que de laisser des écrans vides en cache.
    onSuccess: () => qc.resetQueries(),
  })
}

export function useDeconnexion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ deconnecte: boolean }>('/api/acces/deconnexion'),
    onSuccess: () => {
      // L'état « déconnecté » est posé directement. `clear()` puis invalider
      // ne marchait pas : vidé du cache, l'état d'accès n'était plus là pour
      // être invalidé, et l'écran gardait son dernier « connecté » — session
      // fermée côté serveur, application toujours affichée.
      qc.setQueryData<EtatAcces>(CLE_ACCES, { connexion_requise: true, connecte: false, email: null })
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== CLE_ACCES[0] })
    },
  })
}
