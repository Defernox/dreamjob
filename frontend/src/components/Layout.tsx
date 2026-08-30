import { NavLink, Outlet } from 'react-router-dom'
import { useStatistiques } from '../api/offres'
import { BandeauSante } from './BandeauSante'
import { BasculeTheme } from './BasculeTheme'
import { Marque } from './Marque'

const onglets = [
  { to: '/offres', libelle: 'Offres' },
  { to: '/candidatures', libelle: 'Candidatures' },
  { to: '/profil', libelle: 'Profil' },
]

export function Layout() {
  const { data: stats } = useStatistiques()
  const nouvelles = stats?.nouvelles ?? 0

  return (
    <div className="min-h-screen flex flex-col">
      {/* En-tête sombre : il ancre la page et détache le contenu, qui est
          clair. Une barre blanche sur fond clair laissait l'application
          sans repère visuel — tout flottait à la même profondeur. */}
      <header className="bg-barre text-barre-texte">
        <div className="mx-auto max-w-[1600px] px-6 h-14 flex items-center gap-8">
          <span className="flex items-center gap-2.5 font-semibold text-[17px] tracking-tight">
            <Marque />
            DreamJob
          </span>
          <nav className="flex gap-1">
            {onglets.map((o) => (
              <NavLink
                key={o.to}
                to={o.to}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded-lg text-sm font-medium transition-colors
                   flex items-center gap-2 ${
                     isActive
                       ? 'bg-white/10 text-white'
                       : 'text-encre-300 hover:text-white hover:bg-white/5'
                   }`
                }
              >
                {o.libelle}
                {/* Le badge ne vit que sur Offres, et disparaît une fois les
                    offres consultées : consulter une offre la marque comme vue. */}
                {o.to === '/offres' && nouvelles > 0 && (
                  <span
                    className="px-1.5 py-0.5 rounded-full bg-ambre-500 text-white text-xs
                               font-semibold tabular-nums leading-none"
                    title={`${nouvelles} offre(s) que vous n'avez pas encore ouverte(s)`}
                  >
                    {nouvelles > 99 ? '99+' : nouvelles}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>
          <BasculeTheme />
        </div>
      </header>
      <BandeauSante />
      <main className="flex-1 w-full mx-auto max-w-[1600px] px-6 py-7">
        <Outlet />
      </main>
    </div>
  )
}
