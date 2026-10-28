import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import type { Me, Release } from "../../shared/api/generated/model";
import { useGetAbout } from "../../shared/api/generated/platform-bff";
import { rolesText } from "../help/startKinds";

/** Версия меняется только с выкладкой: один запрос на сеанс, без повторов при каждом открытии меню. */
const STALE_MS = 10 * 60 * 1000;

export function useAbout(enabled = true) {
  return useGetAbout({ query: { staleTime: STALE_MS, gcTime: STALE_MS, enabled } });
}

/** «Платформа 2026.10.28 · 1a2b3c4»; локальная сборка — «Платформа · локальная сборка». */
export function releaseText(t: TFunction, release: Release | undefined): string | undefined {
  if (!release) return undefined;
  if (release.version === "dev") return t("help:about.localBuild");
  return release.sha
    ? t("help:about.versionWithSha", { version: release.version, sha: release.sha })
    : t("help:about.version", { version: release.version });
}

/** Версия Платформы строкой (или `undefined`, пока не известна). */
export function useReleaseText(enabled = true): string | undefined {
  const { t } = useTranslation("help");
  const about = useAbout(enabled);
  return releaseText(t, about.data?.release);
}

/** Браузер и система одной строкой: «Chrome 131 · macOS». Без отпечатка устройства — только семейство и мажорная версия. */
export function browserOf(userAgent: string): string {
  const pick = (pattern: RegExp) => pattern.exec(userAgent)?.[1];
  const edge = pick(/Edg\/(\d+)/);
  const chrome = pick(/Chrome\/(\d+)/);
  const firefox = pick(/Firefox\/(\d+)/);
  const safari = pick(/Version\/(\d+)[\d.]* (?:Mobile\/\S+ )?Safari/);
  const browser = edge
    ? `Edge ${edge}`
    : chrome
      ? `Chrome ${chrome}`
      : firefox
        ? `Firefox ${firefox}`
        : safari
          ? `Safari ${safari}`
          : "—";
  const os = /Android/.test(userAgent)
    ? "Android"
    : /iPhone|iPad/.test(userAgent)
      ? "iOS"
      : /Windows/.test(userAgent)
        ? "Windows"
        : /Mac OS X|Macintosh/.test(userAgent)
          ? "macOS"
          : /Linux/.test(userAgent)
            ? "Linux"
            : "";
  return os ? `${browser} · ${os}` : browser;
}

export interface SupportContext {
  me: Me;
  release: Release | undefined;
  userAgent: string;
  screen: { width: number; height: number };
  now: Date;
}

/**
 * Данные для поддержки: версия, роль, язык, браузер, экран, время. Без имени, почты, телефона и адреса страницы с
 * номерами объектов — только то, что помогает воспроизвести сбой.
 */
export function supportText(t: TFunction, context: SupportContext): string {
  const { me, release, userAgent, screen, now } = context;
  return [
    t("help:about.support.version", { value: releaseText(t, release) ?? "—" }),
    t("help:about.support.role", { value: rolesText(me) }),
    t("help:about.support.language", { value: me.language }),
    t("help:about.support.browser", { value: browserOf(userAgent) }),
    t("help:about.support.screen", {
      value: `${String(screen.width)}×${String(screen.height)}`,
    }),
    t("help:about.support.time", { value: now.toISOString() }),
  ].join("\n");
}
