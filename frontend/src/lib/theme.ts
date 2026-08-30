/** Le thème clair ou sombre, retenu d'une session à l'autre.
 *
 *  Trois états et non deux : « système » suit le réglage de Windows et reste
 *  le défaut. Forcer un choix dès la première ouverture serait une décision
 *  qu'on prend à la place de l'utilisateur.
 */

export type Theme = 'clair' | 'sombre' | 'systeme'

const CLE = 'dreamjob.theme'

export function themeChoisi(): Theme {
  const brut = localStorage.getItem(CLE)
  return brut === 'clair' || brut === 'sombre' ? brut : 'systeme'
}

/** Ce qui s'affiche réellement, une fois « système » résolu. */
export function themeEffectif(choix: Theme = themeChoisi()): 'clair' | 'sombre' {
  if (choix !== 'systeme') return choix
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'sombre' : 'clair'
}

export function appliquerTheme(choix: Theme): void {
  if (choix === 'systeme') localStorage.removeItem(CLE)
  else localStorage.setItem(CLE, choix)
  document.documentElement.dataset.theme = themeEffectif(choix)
}

/** Suit le réglage du système tant que l'utilisateur n'a rien imposé.
 *  Renvoie de quoi se désabonner. */
export function suivreLeSysteme(auChangement: () => void): () => void {
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  const reagir = () => {
    if (themeChoisi() === 'systeme') {
      document.documentElement.dataset.theme = themeEffectif('systeme')
      auChangement()
    }
  }
  media.addEventListener('change', reagir)
  return () => media.removeEventListener('change', reagir)
}
