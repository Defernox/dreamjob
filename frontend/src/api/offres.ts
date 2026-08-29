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
  derniere_vue_le: string
  /** Aucun scan ne l'a revue depuis le seuil : sans doute retirée du site. */
  expiree: boolean
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
  expirees: number
  nouvelles: number
  jamais_vues: number
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
  /** null = toutes ; false = seulement celles encore en ligne. */
  expirees: boolean | null
  /** Nombre d'offres affichées. L'API en sert 60 par défaut : sans ce champ,
   *  l'écran annonçait « 448 offres » et n'en montrait que 60. */
  limite: number
}

export const PAR_PAGE = 60

export const FILTRES_VIDES: Filtres = {
  contrats: [], sources: [], pays: [], score_min: 0, recherche: '', tri: 'pertinence',
  expirees: null, limite: PAR_PAGE,
}

/** Les listes deviennent des paramètres répétés : ?contrats=CDI&contrats=CDD */
function versParametres(f: Filtres): string {
  const p = new URLSearchParams()
  f.contrats.forEach((v) => p.append('contrats', v))
  f.sources.forEach((v) => p.append('sources', v))
  f.pays.forEach((v) => p.append('pays', v))
  if (f.score_min > 0) p.set('score_min', String(f.score_min))
  if (f.recherche.trim()) p.set('recherche', f.recherche.trim())
  if (f.expirees !== null) p.set('expirees', String(f.expirees))
  p.set('tri', f.tri)
  p.set('limite', String(f.limite))
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

export type Planification = {
  actif: boolean
  heure: string
  prochaine_execution: string | null
  dernier_scan: string | null
  dernier_scan_nouvelles: number | null
  rattrapage_apres_heures: number
}

export const usePlanification = () =>
  useQuery({
    queryKey: ['planification'],
    queryFn: () => api.get<Planification>('/api/scans/planification'),
    staleTime: 60_000,
  })
