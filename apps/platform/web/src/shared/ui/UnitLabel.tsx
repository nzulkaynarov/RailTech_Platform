import { splitUnit } from "../lib/unit";

/** Видимая часть подписи без единицы; единица — только для экранного чтеца. */
export function UnitLabel({ label }: { label: string }) {
  const { text, unit } = splitUnit(label);
  if (!unit) return <>{label}</>;
  return (
    <>
      {text}
      <span className="pf-sr-only">, {unit}</span>
    </>
  );
}
