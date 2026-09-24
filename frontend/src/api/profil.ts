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
  /** Où j'en suis aujourd'hui, en une ligne. Ouvre la lettre de motivation. */
  situation_actuelle: string
  /** Laissé vide, la lettre a interdiction d'annoncer une disponibilité. */
  disponibilite: string
  /** 0 = non renseigné : la séniorité n'est alors pas notée, pas notée zéro. */
  annees_experience: number
  /** Vide = non renseigné : la lettre n'accorde alors aucun adjectif. Jamais déduit du prénom. */
  accord: '' | 'masculin' | 'feminin'
  resume: string
  secteurs: string[]
  langues: Langue[]
  skills: Skill[]
  experiences: Experience[]
  formations: Formation[]
  pays_acceptes: string[]
  contrats_acceptes: string[]
  /** Extraits annotés de vos propres lettres, montrés au modèle comme exemples de style. */
  exemples_style: string
  /** Sujet ntfy du résumé du matin. Vide : pas de notification. */
  ntfy_sujet: string
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
