/** Подписи текстов меню клиента и запроса номера (бэкенд: `schemas/settings_client.py`). */
import type { BotTextLabel } from "./settings";

const menu = (command: string, who: string): BotTextLabel => ({
  label: `Меню: /${command}`,
  when: `Подпись команды в кнопке «Меню» Telegram — ${who}.`,
});

export const clientBotTexts: Record<string, BotTextLabel> = {
  menu_start: menu("start", "у потенциальных клиентов"),
  menu_human: menu("human", "у потенциальных клиентов, пока лида не ведёт менеджер"),
  menu_lang: menu("lang", "у всех"),
  menu_help: menu("help", "у потенциальных клиентов"),
  menu_delete: menu("delete", "у всех"),
  menu_docs: menu("docs", "у клиентов"),
  menu_request: menu("request", "у клиентов"),
  menu_status: menu("status", "у клиентов"),
  client_only: {
    label: "Команда только для клиентов",
    when: "Потенциальный клиент вызвал /docs, /request или /status.",
  },
  docs_list: { label: "Список документов", when: "Над кнопками документов по команде /docs." },
  docs_empty: { label: "Документов нет", when: "Клиент вызвал /docs, а документов у него нет." },
  request_prompt: {
    label: "Просьба описать запрос",
    when: "Клиент вызвал /request — бот ждёт описание одним сообщением.",
  },
  request_created: {
    label: "Запрос создан",
    when: "Описание запроса получено, запрос передан менеджеру. {number} — номер запроса.",
  },
  request_status_open: {
    label: "Статус: запрос в работе",
    when: "Клиент вызвал /status, есть открытый запрос. {number}, {date}, {summary} — из запроса.",
  },
  request_status_none: {
    label: "Статус: открытых запросов нет",
    when: "Клиент вызвал /status, открытых запросов нет.",
  },
  phone_request: {
    label: "Просьба поделиться номером",
    when: "Один раз: когда лид квалифицирован или попросил менеджера (Поведение бота → «Спрашивать номер»).",
  },
  phone_share_button: {
    label: "Кнопка «Поделиться номером»",
    when: "Под просьбой поделиться номером; отправляет номер самого клиента.",
  },
  phone_skip_button: { label: "Кнопка «Не сейчас»", when: "Под просьбой поделиться номером." },
  phone_saved: { label: "Номер сохранён", when: "Клиент поделился своим номером кнопкой." },
  phone_skipped: { label: "Номер не дали", when: "Клиент нажал «Не сейчас». Больше не спросим." },
  phone_not_own: {
    label: "Чужой контакт",
    when: "Клиент прислал чужой контакт — сохраняем только его собственный номер.",
  },
};
