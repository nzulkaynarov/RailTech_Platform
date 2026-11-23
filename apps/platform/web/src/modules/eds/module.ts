import { RECORD_TAB_SET, type ModuleConfig } from "../types";

const EDS_ANY = [
  "eds.inbox",
  "eds.inbox.register",
  "eds.drafts",
  "eds.projects",
  "eds.payments",
  "eds.memo.create",
  "eds.memo.approve",
] as const;

export const eds: ModuleConfig = {
  code: "eds",
  sections: [
    {
      key: "documents",
      path: "/eds/documents",
      access: { anyOf: EDS_ANY },
      defaults: { panelOpen: false },
    },
    {
      key: "inbox",
      path: "/eds/inbox",
      detail: "/eds/inbox/:id",
      access: { anyOf: ["eds.inbox", "eds.inbox.register"] },
      // ЕД-7: «Резолюция» — вкладка окна списка; на карточке форма в центре, а окно — «Сведения», «Маршрут», «История»
      tabs: [{ key: "resolution" }, ...RECORD_TAB_SET],
      actionTo: "/eds/documents",
    },
    {
      // W18A-P2: письма общего ящика до регистрации — первая линия (делопроизводитель) разбирает: ВХ, лид или архив.
      key: "mail",
      path: "/eds/mail",
      detail: "/eds/mail/:id",
      // 0.3 (FR-10): и менеджер (`crm.leads`, свои письма), и директор (`crm.mail`, вся очередь без действий) — `MailScreen`.
      access: { anyOf: ["crm.leads.triage", "crm.leads", "crm.mail"] },
      defaults: { panelOpen: false },
    },
    {
      // W18A-P2-3: своё письмо общего ящика у сотрудника без раздела первой линии — «в работе» у него или адресовано
      // лично (решает CRM); из «Моих задач», как поручение.
      key: "mymail",
      path: "/eds/my-mail",
      detail: "/eds/my-mail/:id",
      access: { resource: "dashboard.queue" },
      hidden: true,
      defaults: { panelOpen: false },
      actionTo: "/dashboard/queue",
    },
    {
      key: "projects",
      path: "/eds/projects",
      detail: "/eds/projects/:id",
      access: { resource: "eds.projects" },
      // ЕД-7: «Сведения» и «История» бокового окна; договор и акт — действия в строках документов в центре.
      tabs: RECORD_TAB_SET,
      actionTo: "/eds/documents",
    },
    {
      key: "drafts",
      path: "/eds/drafts",
      detail: "/eds/drafts/:id",
      access: { resource: "eds.drafts" },
      tabs: RECORD_TAB_SET,
      actionTo: "/eds/documents",
    },
    {
      key: "approvals",
      path: "/eds/approvals",
      detail: "/eds/approvals/:id",
      access: { anyOf: ["eds.memo.approve", "eds.memo.create"] },
      tabs: RECORD_TAB_SET,
    },
    {
      key: "payments",
      path: "/eds/payments",
      detail: "/eds/payments/:id",
      access: { resource: "eds.payments" },
      // «Оплата» — вкладка окна списка (счёт и служебка к оплате); на карточке форма в центре (ЕД-7)
      tabs: [{ key: "payment" }, ...RECORD_TAB_SET],
      actionTo: "/eds/projects",
    },
    {
      // P8: «Зарегистрировать входящее» (SPEC-v3 §3.2a п. 1) — кнопка во «Входящих письмах»; регистрация ≠ резолюция.
      key: "register",
      path: "/eds/register",
      access: { resource: "eds.inbox.register", level: "full" },
      hidden: true,
      parent: "inbox",
      defaults: { panelOpen: false },
      actionTo: "/eds/inbox",
    },
    {
      // P8b: рабочий экран поручения по входящему (SPEC-v3 §3.2a п. 3–4) — из «Моих задач»; исполнитель — любой сотрудник,
      // письмо своего поручения он видит и без «Входящих» (решает EDS).
      key: "tasks",
      path: "/eds/tasks",
      detail: "/eds/tasks/:id",
      access: { resource: "dashboard.queue" },
      hidden: true,
      defaults: { panelOpen: false },
      actionTo: "/dashboard/queue",
    },
    {
      // ДОК-10: «Документы · Шаблоны · Договоры» для держателя зоны «Право» (юрист без раздела Настроек); остальным — вкладка
      // «Договоры» в «Настройки · Шаблоны».
      key: "contracttpl",
      path: "/eds/contract-templates",
      access: { anyOf: ["eds.visa.legal", "eds.projects"] },
      hidden: true,
      defaults: { panelOpen: false },
    },
    {
      key: "new",
      path: "/eds/new",
      access: { resource: "eds.memo.create" },
      hidden: true,
      defaults: { panelOpen: false },
      actionTo: "/eds/documents",
    },
  ],
};
