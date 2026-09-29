import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
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

/** `avertissement` : quelques sites d'employeurs muets, la source a répondu. */
export type ErreurScan = { source: string; type: 'non_configure' | 'panne' | 'inattendu' | 'avertissement'; erreur: string }

export type ScanSuivi = {
  id: number
  statut: string
  nb_nouvelles: number
  erreurs: ErreurScan[]
  started_at: string
  finished_at: string | null
  declenche_par: string
}

/** Les dernières recherches abouties ou non, pour le diagnostic. Sans les passes
 *  de veille : une toutes les demi-heures, sur une partie des sources, elles
 *  cacheraient les erreurs du scan du matin. */
export const useDerniersScans = () =>
  useQuery({
    queryKey: ['scans', 'historique'],
    queryFn: () => api.get<ScanSuivi[]>('/api/scans?limite=5&avec_veille=false'),
  })

const EN_COURS = 'en cours'

/** La recherche part en arrière-plan : avec les sites des employeurs, elle dure
 *  plusieurs minutes, et une requête qui l'attendrait serait coupée par le
 *  relais HTTPS. On lance, puis on relit le scan toutes les trois secondes
 *  jusqu'à ce qu'il soit clos. Même forme que l'ancienne mutation. */
export function useLancerScan() {
  const qc = useQueryClient()
  const [id, setId] = useState<number | null>(null)
  const lancer = useMutation({
    mutationFn: () => api.post<ScanSuivi>('/api/scans'),
    onSuccess: (scan) => {
      qc.setQueryData(['scan', scan.id], scan)
      setId(scan.id)
    },
  })
  const suivi = useQuery({
    queryKey: ['scan', id],
    queryFn: () => api.get<ScanSuivi>(`/api/scans/${id}`),
    enabled: id !== null,
    refetchInterval: (requete) => (requete.state.data?.statut === EN_COURS ? 3000 : false),
  })
  // Revenu sur l'écran pendant une recherche (ou pendant le scan du matin) :
  // on la reprend au lieu de proposer d'en lancer une seconde, refusée. Jamais
  // une passe de veille : ce n'est pas une recherche de l'utilisateur.
  const dernier = useQuery({
    queryKey: ['scans', 'dernier'],
    queryFn: () => api.get<ScanSuivi[]>('/api/scans?limite=1&avec_veille=false'),
    enabled: id === null,
  })
  useEffect(() => {
    const scan = dernier.data?.[0]
    if (id === null && scan?.statut === EN_COURS) setId(scan.id)
  }, [dernier.data, id])
  const fini = suivi.data !== undefined && suivi.data.statut !== EN_COURS
  useEffect(() => {
    if (fini) qc.invalidateQueries({ queryKey: ['offres'] })
  }, [fini, qc])
  return {
    mutate: () => lancer.mutate(),
    isPending: lancer.isPending || (id !== null && !fini),
    isError: lancer.isError || suivi.isError,
    error: lancer.error ?? suivi.error,
    isSuccess: fini,
    data: fini ? suivi.data : undefined,
  }
}

export function useScorer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (forcer: boolean) =>
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
  /** Repérer une offre dans l'heure où elle paraît, et alerter si elle est verte. */
  veille: {
    active: boolean
    intervalle_minutes: number
    heure_debut: number
    heure_fin: number
    sources: string[]
    derniere: string | null
  }
}

export const usePlanification = () =>
  useQuery({
    queryKey: ['planification'],
    queryFn: () => api.get<Planification>('/api/scans/planification'),
    staleTime: 60_000,
  })

/** Ce que verra le recruteur dans son ATS. Calculé côté serveur, sans appel payant. */
export type Correspondance = {
  titre_cv: string
  /** Faux quand l'intitulé a cédé au titre visé : le recruteur qui cherche l'intitulé exact ne trouvera pas ce CV. */
  titre_reprend_l_offre: boolean
  taux: number | null
  taux_vise: number
  termes_couverts: string[]
  termes_manquants: string[]
  competences_citees: string[]
  langue_de_l_annonce: string | null
  langues_exigees: string[]
  annees_exigees: number | null
  annees_profil: number | null
  description_tronquee: boolean
}

export const useCorrespondance = (id: number | null) =>
  useQuery({
    queryKey: ['correspondance', id],
    queryFn: () => api.get<Correspondance>(`/api/offres/${id}/correspondance`),
    enabled: id !== null,
  })
