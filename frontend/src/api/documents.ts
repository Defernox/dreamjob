import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type ResultatDocuments = {
  dossier: string
  fichiers: string[]
  avertissements: string[]
  lettre_essais: number
  /** Termes récurrents de l'annonce qu'aucun élément du profil ne recouvre. */
  mots_cles_non_couverts: string[]
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
      qc.invalidateQueries({ queryKey: ['documents', offreId] })
    },
  })
}

export function useOuvrirDossier() {
  return useMutation({
    mutationFn: (offreId: number) =>
      api.post<{ ouvert: boolean; dossier: string }>(`/api/offres/${offreId}/documents/ouvrir`),
  })
}

export type DocumentsOffre = {
  dossier: string | null
  fichiers: { nom: string; taille: number }[]
}

/** Les documents déjà générés pour une offre, téléchargeables depuis l'interface. */
export const useDocumentsOffre = (offreId: number | null) =>
  useQuery({
    queryKey: ['documents', offreId],
    queryFn: () => api.get<DocumentsOffre>(`/api/offres/${offreId}/documents`),
    enabled: offreId !== null,
  })

export const lienDocument = (offreId: number, nom: string) =>
  `/api/offres/${offreId}/documents/${encodeURIComponent(nom)}`
