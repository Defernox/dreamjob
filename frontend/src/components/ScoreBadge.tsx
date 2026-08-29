import { couleurScore } from '../lib/format'

export function ScoreBadge({ score, seuils, taille = 'normal' }: {
  score: number | null
  seuils?: { bon: number; moyen: number }
  taille?: 'normal' | 'grand'
}) {
  const classes = taille === 'grand' ? 'w-14 h-14 text-xl' : 'w-11 h-11 text-sm'
  return (
    <div
      className={`${classes} ${couleurScore(score, seuils?.bon, seuils?.moyen)}
                  rounded-full flex items-center justify-center font-semibold shrink-0 tabular-nums`}
      title={score === null ? 'Pas encore scorée' : `Score ${score} sur 100`}
    >
      {score === null ? '—' : Math.round(score)}
    </div>
  )
}
