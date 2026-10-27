import type { TFunction } from "i18next";

/**
 * Слова к кодам журнала аудита CRM (`action`, `entity_type`): код приходит из API, слова — из словаря `audit`
 * (ru/uz/en). Неизвестный код показывается как есть, а не пропадает. Ключ действия — `группа.глагол`, где лишние
 * точки заменены на «_» (`integrations.erp.pair` -> `integrations.erp_pair`): иначе i18next вложил бы ключ глубже.
 */
export const AUDIT_ACTIONS = [
  "auth.login",
  "auth.login_failed",
  "sso.exchange",
  "lead.take",
  "lead.reply",
  "lead.note",
  "lead.snooze",
  "lead.unsnooze",
  "lead.return_to_bot",
  "lead.close_won",
  "lead.close_lost",
  "lead.make_customer",
  "lead.consent_recorded",
  "lead.new_deal",
  "lead.assign",
  "lead.acknowledge",
  "lead.assist",
  "lead.create",
  "lead.create_web",
  "lead.web_request",
  "lead.merge",
  "lead.updated",
  "deal.create",
  "deal.update",
  "deal.open",
  "deal.won",
  "deal.lost",
  "user.create",
  "user.update",
  "user.reset_password",
  "user.reset_password_email",
  "user.change_password",
  "user.notify",
  "user.bootstrap_admin",
  "user.invite",
  "user.hand_over",
  "setup.admin_created",
  "system.backup_requested",
  "platform_access.granted",
  "platform_access.revoked",
  "platform_role.create",
  "platform_role.update",
  "platform_role.delete",
  "client.create",
  "client.update",
  "client.link_telegram",
  "client.unlink_telegram",
  "client.erp_handoff",
  "client.erp_handoff_done",
  "client.erp_handoff_failed",
  "client.close_request",
  "client.contact_create",
  "client.contact_update",
  "client.contact_delete",
  "document.upload",
  "document.update",
  "kb.upload",
  "kb.update",
  "kb.reingest",
  "kb.product",
  "kb.gap_resolve",
  "kb.gap_ignore",
  "kb.gap_reopen",
  "settings.update",
  "model.test",
  "model.update",
  "model.reset",
  "model.provider_key",
  "reply_template.create",
  "reply_template.update",
  "reply_template.delete",
  "sandbox.message",
  "sandbox.reset",
  "integrations.telegram_token",
  "integrations.erp",
  "integrations.erp.pair",
  "integrations.erp.rotate",
  "integrations.smtp",
  "export.leads",
  "export.clients",
  "export.deals",
  "external_service.disable",
  "external_service.enable",
] as const;

export const AUDIT_ENTITIES = [
  "user",
  "platform_role",
  "settings",
  "integration",
  "integration_secret",
  "external_service",
  "model",
  "provider",
  "system",
  "lead",
  "client",
  "deal",
  "document",
  "kb_document",
  "kb_gap",
  "product",
  "service_request",
  "reply_template",
  "sandbox",
  "export",
] as const;

export function actionKey(code: string): string {
  const dot = code.indexOf(".");
  if (dot < 0) return code;
  return `${code.slice(0, dot)}.${code.slice(dot + 1).replaceAll(".", "_")}`;
}

export function actionLabel(t: TFunction, code: string): string {
  return t(`audit:actions.${actionKey(code)}`, { defaultValue: code });
}

export function entityLabel(t: TFunction, type: string): string {
  return t(`audit:entities.${type}`, { defaultValue: type });
}
