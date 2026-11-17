import { useOperatorLogo, useProductName } from "../lib/useProductName";

/**
 * Марка оператора (ДВ-3): логотип своей компании, без него — буквы названия на плитке основного цвета. Имя для чтения
 * экраном — у ссылки или подписи рядом, поэтому сама марка для него скрыта.
 */
export function OperatorMark({ size = 36 }: { size?: number }) {
  const logo = useOperatorLogo();
  const { initials } = useProductName();
  const box = { width: size, height: size, borderRadius: 8, flex: "none" as const };
  if (logo) {
    return (
      <img
        src={logo}
        alt=""
        aria-hidden="true"
        style={{
          ...box,
          objectFit: "contain",
          background: "#fff",
          padding: 2,
          boxSizing: "border-box",
        }}
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      style={{
        ...box,
        background: "var(--rt-color-primary-default)",
        color: "#fff",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontWeight: 700,
        fontSize: size >= 36 ? 14 : 12,
      }}
    >
      {initials}
    </span>
  );
}
