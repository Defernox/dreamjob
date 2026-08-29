import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type ResultatDocuments = {
  dossier: string
  fichiers: string[]
  avertissements: string[]
  lettre_essais: number
  ouvert: boolean
}

export function useGenererDocuments() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (offreId: number) =>
      api.post<ResultatDocuments>(`/api/offres/${offreId}/documents`),
    onSuccess: (_, offreId) => {
      qc.invalidateQueries({ queryKey: ['offre', offreId] })
      qc.invalidateQueries({ queryKey: ['candidatures'] })
    },
  })
}

export function useOuvrirDossier() {
  return useMutation({
    mutationFn: (offreId: number) =>
      api.post<{ ouvert: boolean; dossier: string }>(`/api/offres/${offreId}/documents/ouvrir`),
  })
}
