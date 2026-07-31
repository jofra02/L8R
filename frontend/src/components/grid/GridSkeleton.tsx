export function GridSkeletonRows({ columns, rows = 8 }: { columns: number; rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, i) => (
        <tr key={i} className="border-b border-border-subtle">
          {Array.from({ length: columns }, (_, c) => (
            <td key={c} className="px-3 py-2.5">
              <div
                className="h-3.5 rounded bg-elevated animate-pulse"
                style={{ width: `${55 + ((i * 7 + c * 13) % 40)}%` }}
              />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}
