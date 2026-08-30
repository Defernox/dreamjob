import { useEffect, useState } from 'react'
import { appliquerTheme, suivreLeSysteme, themeChoisi, themeEffectif, type Theme } from '../lib/theme'

const SUIVANT: Record<Theme, Theme> = {
  systeme: 'clair',
  clair: 'sombre',
  sombre: 'systeme',
}

const INFOS: Record<Theme, string> = {
  systeme: 'Thème : celui du système — cliquez pour forcer le clair',
  clair: 'Thème : clair — cliquez pour passer au sombre',
  sombre: 'Thème : sombre — cliquez pour revenir au réglage du système',
}

/** Bascule clair / sombre / système, dans l'en-tête.
 *
 *  Un seul bouton qui tourne entre trois états plutôt qu'un menu : le
 *  réglage se change rarement et ne mérite pas un panneau. L'icône montre ce
 *  qui est AFFICHÉ, la pastille indique que le système décide.
 */
export function BasculeTheme() {
  const [choix, setChoix] = useState<Theme>(themeChoisi)
  const [, redessiner] = useState(0)

  // Le système peut changer d'avis pendant que l'application est ouverte —
  // Windows bascule en sombre au coucher du soleil.
  useEffect(() => suivreLeSysteme(() => redessiner((n) => n + 1)), [])

  const affiche = themeEffectif(choix)

  return (
    <button
      type="button"
      onClick={() => {
        const prochain = SUIVANT[choix]
        appliquerTheme(prochain)
        setChoix(prochain)
      }}
      title={INFOS[choix]}
      aria-label={INFOS[choix]}
      className="relative ml-auto p-2 rounded-lg text-encre-300 transition-colors
                 hover:text-white hover:bg-white/5"
    >
      {affiche === 'sombre' ? <Lune /> : <Soleil />}
      {choix === 'systeme' && (
        <span
          className="absolute bottom-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-ambre-500"
          aria-hidden="true"
        />
      )}
    </button>
  )
}

const Soleil = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" aria-hidden="true">
    <circle cx="12" cy="12" r="4.5" />
    <path d="M12 2v2M12 20v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" />
  </svg>
)

const Lune = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5Z" />
  </svg>
)
