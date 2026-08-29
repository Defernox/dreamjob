import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type Langue = { code: string; libelle: string; niveau: string }
export type Skill = { nom: string; niveau: string; ancree: boolean }
export type Experience = {
  entreprise: string
  poste: string
  lieu: string
  debut: string
  fin: string
  description: string
  tags: string[]
}
export type Formation = {
  etablissement: string
  diplome: string
  annee: string
  lieu: string
  details: string
}

export type Profil = {
  id: number
  prenom: string
  nom: string
  email: string
  telephone: string
  ville: string
  pays: string
  linkedin: string
  titre_vise: string
  resume: string
  secteurs: string[]
  langues: Langue[]
  skills: Skill[]
  experiences: Experience[]
  formations: Formation[]
  pays_acceptes: string[]
  contrats_acceptes: string[]
  cv_source_path: string
  cv_importe_le: string | null
  updated_at: string | null
}

export type ResultatImport = {
  profil: Profil
  depuis_cache: boolean
  modele: string
  fichier: string
  caracteres_lus: number
  avertissements: string[]
}

export const useProfil = () =>
  useQuery({ queryKey: ['profil'], queryFn: () => api.get<Profil>('/api/profil') })

export function useEnregistrerProfil() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (profil: Partial<Profil>) => api.put<Profil>('/api/profil', profil),
    onSuccess: (profil) => qc.setQueryData(['profil'], profil),
  })
}

export function useImporterCv() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fichier: File) => {
      const donnees = new FormData()
      donnees.append('fichier', fichier)
      return api.upload<ResultatImport>('/api/profil/importer', donnees)
    },
    onSuccess: (resultat) => qc.setQueryData(['profil'], resultat.profil),
  })
}
