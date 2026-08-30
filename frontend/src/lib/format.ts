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

/** Lecture d'un score : la couleur, et le mot. Les seuils viennent de
 *  `config.yaml` — l'interface ne les décide pas.
 *
 *  `trait` est une valeur CSS et non une classe Tailwind : un trait de SVG
 *  se colore par attribut, pas par classe utilitaire. `fond` et `texte`
 *  servent aux pastilles et aux barres, qui restent en HTML.
 */
export type Verdict = { trait: string; fond: string; texte: string; libelle: string }

export function verdictScore(score: number | null, bon = 75, moyen = 50): Verdict {
  if (score === null || score === undefined) {
    return {
      trait: 'var(--color-encre-300)',
      fond: 'bg-craie-200',
      texte: 'text-encre-400',
      libelle: 'pas encore scorée',
    }
  }
  if (score >= bon) {
    return {
      trait: 'var(--color-verdict-fort)',
      fond: 'bg-[var(--color-verdict-fort)]',
      texte: 'text-[var(--color-verdict-fort)]',
      libelle: 'correspond bien',
    }
  }
  if (score >= moyen) {
    return {
      trait: 'var(--color-verdict-moyen)',
      fond: 'bg-[var(--color-verdict-moyen)]',
      texte: 'text-[var(--color-verdict-moyen)]',
      libelle: 'à regarder',
    }
  }
  return {
    trait: 'var(--color-verdict-faible)',
    fond: 'bg-[var(--color-verdict-faible)]',
    texte: 'text-[var(--color-verdict-faible)]',
    libelle: 'éloignée du profil',
  }
}

export const nombreFr = (n: number): string => new Intl.NumberFormat('fr-FR').format(n)
