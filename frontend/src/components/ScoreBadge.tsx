import { verdictScore } from '../lib/format'

const RAYON = 17
const CIRCONFERENCE = 2 * Math.PI * RAYON

/** Le score en anneau plutôt qu'en pastille pleine.
 *
 *  Une pastille ne donne qu'un chiffre ; l'anneau montre la proportion, donc
 *  se lit sans être lu. C'est l'élément le plus regardé de l'application —
 *  et il reprend la figure du viseur de la marque, ce qui n'est pas un hasard.
 */
export function ScoreBadge({ score, seuils, taille = 'normal' }: {
  score: number | null
  seuils?: { bon: number; moyen: number }
  taille?: 'normal' | 'grand'
}) {
  const cote = taille === 'grand' ? 60 : 46
  const verdict = verdictScore(score, seuils?.bon, seuils?.moyen)
  const valeur = score === null ? 0 : Math.max(0, Math.min(100, score))

  return (
    <div
      className="relative shrink-0"
      style={{ width: cote, height: cote }}
      title={score === null ? 'Pas encore scorée' : `Score ${Math.round(score)} sur 100`}
    >
      <svg viewBox="0 0 40 40" className="w-full h-full -rotate-90">
        <circle
          cx="20" cy="20" r={RAYON} fill="none"
          className="stroke-craie-200" strokeWidth="3.5"
        />
        {score !== null && (
          <circle
            cx="20" cy="20" r={RAYON} fill="none"
            stroke={verdict.trait} strokeWidth="3.5" strokeLinecap="round"
            strokeDasharray={CIRCONFERENCE}
            // L'arc part du haut grâce au -rotate-90 du SVG : sans cela il
            // démarrerait à trois heures, ce qui se lit mal.
            strokeDashoffset={CIRCONFERENCE * (1 - valeur / 100)}
          />
        )}
      </svg>
      <span
        className={`absolute inset-0 flex items-center justify-center font-semibold
                    tabular-nums ${taille === 'grand' ? 'text-lg' : 'text-[13px]'}`}
        style={{ color: score === null ? undefined : verdict.trait }}
      >
        {score === null ? <span className="text-encre-300">—</span> : Math.round(score)}
      </span>
    </div>
  )
}
