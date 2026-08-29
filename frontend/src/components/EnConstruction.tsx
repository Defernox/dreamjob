export function EnConstruction({ titre, etape, contenu }: {
  titre: string
  etape: string
  contenu: string[]
}) {
  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-semibold mb-1">{titre}</h1>
      <p className="text-sm text-slate-500 mb-6">Livré à l'{etape}.</p>
      <ul className="space-y-1.5 text-sm text-slate-600">
        {contenu.map((c) => (
          <li key={c} className="flex gap-2">
            <span className="text-slate-300">—</span>
            {c}
          </li>
        ))}
      </ul>
    </div>
  )
}
