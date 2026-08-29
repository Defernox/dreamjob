import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type Recherche = {
  id: number
  nom: string
  mots_cles: string[]
  /** Vides = les pays et contrats du profil s'appliquent. */
  pays: string[]
  contrats: string[]
  departement: string
  publiee_depuis_jours: number | null
  max_offres: number
  active: boolean
  ordre: number
  updated_at: string
}

export type NouvelleRecherche = Omit<Recherche, 'id' | 'updated_at'>

export const useRecherches = () =>
  useQuery({ queryKey: ['recherches'], queryFn: () => api.get<Recherche[]>('/api/recherches') })

function invalider(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ['recherches'] })
}

export function useCreerRecherche() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (r: Partial<NouvelleRecherche>) => api.post<Recherche>('/api/recherches', r),
    onSuccess: () => invalider(qc),
  })
}

export function useMajRecherche() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...champs }: { id: number } & Partial<Recherche>) =>
      api.patch<Recherche>(`/api/recherches/${id}`, champs),
    onSuccess: () => invalider(qc),
  })
}

export function useSupprimerRecherche() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/api/recherches/${id}`),
    onSuccess: () => invalider(qc),
  })
}
