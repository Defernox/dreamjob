import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type Candidature = {
  id: number
  offer_id: number
  date_candidature: string
  statut: string
  deadline: string | null
  notes: string
  contact: string
  dossier_local: string
  updated_at: string
  titre: string
  entreprise: string
  pays: string
  score: number | null
  url: string
  jours_depuis: number
  /** Envoyée et sans nouvelle depuis le seuil : une relance s'impose. */
  relance_conseillee: boolean
}

export const useCandidatures = () =>
  useQuery({ queryKey: ['candidatures'], queryFn: () => api.get<Candidature[]>('/api/candidatures') })

export function usePostuler() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (offerId: number) =>
      api.post<Candidature>('/api/candidatures', { offer_id: offerId }),
    onSuccess: (_, offerId) => {
      qc.invalidateQueries({ queryKey: ['candidatures'] })
      qc.invalidateQueries({ queryKey: ['offre', offerId] })
      qc.invalidateQueries({ queryKey: ['offres'] })
    },
  })
}

export function useMajCandidature() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...champs }: { id: number } & Partial<Candidature>) =>
      api.patch<Candidature>(`/api/candidatures/${id}`, champs),
    // Mise à jour optimiste : saisir une note ne doit pas faire clignoter la ligne.
    onMutate: async ({ id, ...champs }) => {
      await qc.cancelQueries({ queryKey: ['candidatures'] })
      const precedent = qc.getQueryData<Candidature[]>(['candidatures'])
      qc.setQueryData<Candidature[]>(['candidatures'], (liste) =>
        (liste ?? []).map((c) => (c.id === id ? { ...c, ...champs } : c)),
      )
      return { precedent }
    },
    onError: (_e, _v, contexte) => {
      if (contexte?.precedent) qc.setQueryData(['candidatures'], contexte.precedent)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['candidatures'] }),
  })
}

export function useSupprimerCandidature() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/api/candidatures/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['candidatures'] })
      qc.invalidateQueries({ queryKey: ['offres'] })
    },
  })
}

export type ResultatReprise = {
  mises_a_jour: number
  ignorees: number
  problemes: string[]
}

export function useImporterSuivi() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fichier: File) => {
      const donnees = new FormData()
      donnees.append('fichier', fichier)
      return api.upload<ResultatReprise>('/api/candidatures/importer', donnees)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['candidatures'] }),
  })
}
