/**
 * «Открыть» в карточках Подключений (OPS-CONSOLE): куда идти в кабинет внешнего сервиса. Только ссылки в новой
 * вкладке — учётные данные Платформа не передаёт. Справочник — данные: провайдер добавляется строкой, без правки
 * экранов. Адреса — публичные страницы входа сервисов.
 */

export interface ServiceLink {
  /** Ключ подписи в `integrations:links.*` */
  label: string;
  href: string;
}

/** Консоли провайдеров моделей по типу ключа (`AiModel.provider`). */
export const MODEL_PROVIDER_CONSOLES: Readonly<Record<string, string>> = {
  anthropic: "https://console.anthropic.com/",
  openai: "https://platform.openai.com/",
  gemini: "https://aistudio.google.com/",
  mistral: "https://console.mistral.ai/",
  deepseek: "https://platform.deepseek.com/",
  groq: "https://console.groq.com/",
  openrouter: "https://openrouter.ai/settings/keys",
};

/** Почта: провайдер — по домену SMTP-сервера; админка ящиков и сам почтовый ящик. */
const MAIL_PROVIDERS: readonly {
  key: string;
  domains: readonly string[];
  admin: string;
  mail: string;
}[] = [
  {
    key: "yandex",
    domains: ["yandex.ru", "yandex.com", "yandex.net", "ya.ru"],
    admin: "https://admin.yandex.ru/",
    mail: "https://mail.yandex.ru/",
  },
  {
    key: "google",
    domains: ["gmail.com", "google.com", "googlemail.com"],
    admin: "https://admin.google.com/",
    mail: "https://mail.google.com/",
  },
  {
    key: "mailru",
    domains: ["mail.ru"],
    admin: "https://biz.mail.ru/",
    mail: "https://e.mail.ru/",
  },
];

function hostMatches(host: string, domain: string): boolean {
  const clean = host.trim().toLowerCase().replace(/\.$/, "");
  return clean === domain || clean.endsWith(`.${domain}`);
}

export function mailLinks(host: string): ServiceLink[] {
  const provider = MAIL_PROVIDERS.find((p) => p.domains.some((d) => hostMatches(host, d)));
  if (!provider) return [];
  return [
    { label: `mail.${provider.key}.admin`, href: provider.admin },
    { label: `mail.${provider.key}.mail`, href: provider.mail },
  ];
}

export function modelProviderLinks(
  providers: readonly (string | null | undefined)[],
): ServiceLink[] {
  const seen = new Set<string>();
  const links: ServiceLink[] = [];
  for (const raw of providers) {
    const provider = (raw ?? "").toLowerCase();
    const href = MODEL_PROVIDER_CONSOLES[provider];
    if (!href || seen.has(provider)) continue;
    seen.add(provider);
    links.push({ label: `models.${provider}`, href });
  }
  return links;
}

const BOT_USERNAME = /^[A-Za-z][A-Za-z0-9_]{3,31}$/;

export function telegramLinks(username: string | null | undefined): ServiceLink[] {
  const links: ServiceLink[] = [{ label: "telegram.botfather", href: "https://t.me/BotFather" }];
  const name = (username ?? "").replace(/^@/, "");
  if (BOT_USERNAME.test(name)) links.push({ label: "telegram.bot", href: `https://t.me/${name}` });
  return links;
}

const DRIVE_ID = /^[A-Za-z0-9_-]{10,200}$/;

/** Внешняя копия бэкапов: папка на Яндекс Диске или на общем диске Google. */
export function offsiteLinks(offsite: {
  provider: string;
  folder_path: string;
  default_folder_path: string;
  folder_id: string;
}): ServiceLink[] {
  if (offsite.provider === "yandex") {
    const folder = (offsite.folder_path || offsite.default_folder_path).replace(/^\/+|\/+$/g, "");
    const path = folder
      .split("/")
      .filter(Boolean)
      .map((part) => encodeURIComponent(part))
      .join("/");
    return [
      {
        label: "offsite.yandex",
        href: path
          ? `https://disk.yandex.ru/client/disk/${path}`
          : "https://disk.yandex.ru/client/disk",
      },
    ];
  }
  if (offsite.provider === "gdrive" && DRIVE_ID.test(offsite.folder_id)) {
    return [
      {
        label: "offsite.gdrive",
        href: `https://drive.google.com/drive/folders/${offsite.folder_id}`,
      },
    ];
  }
  return [];
}
