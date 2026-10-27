export interface TimezoneOption {
  value: string;
  label: string;
}

const FALLBACK = [
  "Asia/Tashkent",
  "Asia/Samarkand",
  "Asia/Almaty",
  "Europe/Moscow",
  "Europe/London",
  "UTC",
];

function offsetLabel(zone: string): string {
  try {
    const part = new Intl.DateTimeFormat("en", { timeZone: zone, timeZoneName: "shortOffset" })
      .formatToParts(new Date())
      .find((p) => p.type === "timeZoneName");
    return part ? part.value.replace("GMT", "UTC") : "";
  } catch {
    return "";
  }
}

/** Пояса IANA для выбора (имя и смещение); текущее значение профиля всегда в списке, даже если браузер его не знает. */
export function timezoneOptions(current: string): TimezoneOption[] {
  let zones: string[] = FALLBACK;
  try {
    const all = (
      Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
    ).supportedValuesOf?.("timeZone");
    if (all && all.length > 0) zones = all.includes("UTC") ? all : [...all, "UTC"];
  } catch {
    zones = FALLBACK;
  }
  const set = new Set(zones);
  if (current) set.add(current);
  return [...set].sort().map((zone) => {
    const offset = offsetLabel(zone);
    return { value: zone, label: offset ? `${zone} (${offset})` : zone };
  });
}
