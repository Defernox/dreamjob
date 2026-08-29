import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import type { Reglages, Sante } from './types'

export const useSante = () =>
  useQuery({ queryKey: ['sante'], queryFn: () => api.get<Sante>('/api/sante') })

export const useReglages = () =>
  useQuery({
    queryKey: ['reglages'],
    queryFn: () => api.get<Reglages>('/api/reglages'),
    staleTime: 5 * 60 * 1000, // les vocabulaires ne bougent pas en cours de session
  })
