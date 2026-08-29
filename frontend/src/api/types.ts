export type Sante = {
  ok: boolean
  racine: string
  base_donnees: string
  base_existe: boolean
  llm: { disponible: boolean; modele_extraction: string; modele_redaction: string; message: string | null }
  pdf: { disponible: boolean; chemin: string | null; message: string | null }
  modele_cv: { chemin: string; present: boolean }
  dossier_candidatures: string
  sources: { cle: string; libelle: string; actif: boolean; remarque: string }[]
}

export type Reglages = {
  scoring: {
    version: number
    poids: Record<string, number>
    poids_normalises: Record<string, number>
    seuils: { bon: number; moyen: number }
  }
  vocabulaires: { contrats: string[]; statuts: string[]; pays: string[] }
  recherche: {
    mots_cles: string[]
    pays: string[]
    contrats: string[]
    offres_max_par_source: number
  }
}
