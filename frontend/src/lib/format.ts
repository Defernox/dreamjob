/** Formats français : dates, ancienneté, score. Un seul endroit pour tout. */

import { format, formatDistanceToNowStrict, parseISO } from 'date-fns'
import { fr } from 'date-fns/locale'

/** L'API renvoie de l'UTC ; on l'interprète comme tel avant tout affichage. */
function versDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const normalise = /[zZ]|[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`
  const d = parseISO(normalise)
  return isNaN(d.getTime()) ? null : d
}

/** 28/08/2026 — le format attendu par France Travail. */
export function dateFr(iso: string | null | undefined): string {
  const d = versDate(iso)
  return d ? format(d, 'dd/MM/yyyy') : '—'
}

export function dateHeureFr(iso: string | null | undefined): string {
  const d = versDate(iso)
  return d ? format(d, 'dd/MM/yyyy à HH:mm', { locale: fr }) : '—'
}

/** « il y a 22 heures », « il y a 3 jours ». */
export function anciennete(iso: string | null | undefined): string {
  const d = versDate(iso)
  return d ? `il y a ${formatDistanceToNowStrict(d, { locale: fr })}` : '—'
}

/** Couleur de la pastille de score. Les seuils viennent de config.yaml. */
export function couleurScore(score: number | null, bon = 75, moyen = 50): string {
  if (score === null || score === undefined) return 'bg-slate-300 text-slate-700'
  if (score >= bon) return 'bg-emerald-500 text-white'
  if (score >= moyen) return 'bg-amber-500 text-white'
  return 'bg-slate-400 text-white'
}

export const nombreFr = (n: number): string => new Intl.NumberFormat('fr-FR').format(n)
