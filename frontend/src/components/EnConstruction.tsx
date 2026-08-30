export function EnConstruction({ titre, etape, contenu }: {
  titre: string
  etape: string
  contenu: string[]
}) {
  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-semibold mb-1">{titre}</h1>
      <p className="text-sm text-encre-500 mb-6">Livré à l'{etape}.</p>
      <ul className="space-y-1.5 text-sm text-encre-600">
        {contenu.map((c) => (
          <li key={c} className="flex gap-2">
            <span className="text-craie-300">—</span>
            {c}
          </li>
        ))}
      </ul>
    </div>
  )
}
