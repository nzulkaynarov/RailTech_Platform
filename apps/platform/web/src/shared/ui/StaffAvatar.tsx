import { useState } from "react";

/**
 * Аватар сотрудника: фото (`Me.avatar_url`, отдаёт BFF) вместо инициалов; нет фото или оно не загрузилось — инициалы
 * на светло-синем круге (токены рейла). Картинка декоративна: имя сотрудника всегда есть рядом в тексте.
 */
export function StaffAvatar({
  initials,
  src,
  size = 36,
  fontSize = 12,
  border = true,
}: {
  initials: string;
  src?: string | null;
  size?: number;
  fontSize?: number;
  border?: boolean;
}) {
  // Запоминаем адрес, который не загрузился: новая версия фото (другой адрес) пробуется заново.
  const [brokenSrc, setBrokenSrc] = useState<string | null>(null);
  const showPhoto = Boolean(src) && brokenSrc !== src;
  return (
    <span
      aria-hidden="true"
      className="pf-avatar"
      data-photo={showPhoto ? "true" : "false"}
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        border: border ? "2px solid #91caff" : undefined,
        background: "#e6f4ff",
        color: "#0958d9",
        fontWeight: 600,
        fontSize,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
        boxSizing: "border-box",
        flex: "0 0 auto",
      }}
    >
      {showPhoto ? (
        <img
          src={src ?? undefined}
          alt=""
          width={size}
          height={size}
          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
          onError={() => {
            setBrokenSrc(src ?? null);
          }}
        />
      ) : (
        initials
      )}
    </span>
  );
}
