import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type OffreResume = {
  id: number
  source: string
  url: string
  titre: string
  entreprise: string
  lieu: string
  pays: string
  type_contrat: string
  date_publication: string | null
  date_recuperation: string
  score: number | null
  score_explication: string
  vue: boolean
  a_candidature: boolean
}

export type OffreDetail = OffreResume & {
  description_brute: string
  score_detail: Record<string, number>
  scored_at: string | null
  poids_version: number | null
}

export type Compteurs = {
  contrat: Record<string, number>
  source: Record<string, number>
  pays: Record<string, number>
}

export type PageOffres = { total: number; offres: OffreResume[]; compteurs: Compteurs }

export type Statistiques = {
  total: number
  aujourd_hui: number
  vie: number
  nouvelles: number
  non_scorees: number
  dernier_scan: string | null
}

export type Filtres = {
  contrats: string[]
  sources: string[]
  pays: string[]
  score_min: number
  recherche: string
  tri: string
}

export const FILTRES_VIDES: Filtres = {
  contrats: [], sources: [], pays: [], score_min: 0, recherche: '', tri: 'pertinence',
}

/** Les listes deviennent des paramètres répétés : ?contrats=CDI&contrats=CDD */
function versParametres(f: Filtres): string {
  const p = new URLSearchParams()
  f.contrats.forEach((v) => p.append('contrats', v))
  f.sources.forEach((v) => p.append('sources', v))
  f.pays.forEach((v) => p.append('pays', v))
  if (f.score_min > 0) p.set('score_min', String(f.score_min))
  if (f.recherche.trim()) p.set('recherche', f.recherche.trim())
  p.set('tri', f.tri)
  return p.toString()
}

export const useOffres = (filtres: Filtres) =>
  useQuery({
    queryKey: ['offres', filtres],
    queryFn: () => api.get<PageOffres>(`/api/offres?${versParametres(filtres)}`),
    placeholderData: (precedent) => precedent, // évite le clignotement à chaque clic
  })

export const useStatistiques = () =>
  useQuery({
    queryKey: ['offres', 'statistiques'],
    queryFn: () => api.get<Statistiques>('/api/offres/statistiques'),
  })

export const useOffre = (id: number | null) =>
  useQuery({
    queryKey: ['offre', id],
    queryFn: () => api.get<OffreDetail>(`/api/offres/${id}`),
    enabled: id !== null,
  })

export function useLancerScan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ statut: string; nb_nouvelles: number; erreurs: unknown[] }>('/api/scans'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['offres'] }),
  })
}

export function useScorer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (forcer = false) =>
      api.post<{ scorees: number; total: number; appels_llm: number }>(
        `/api/offres/scorer?forcer=${forcer}`,
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['offres'] }),
  })
}
