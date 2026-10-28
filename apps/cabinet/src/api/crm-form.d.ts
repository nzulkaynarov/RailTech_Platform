/**
 * Сгенерировано scripts/gen-crm-form-types.mjs из packages/contracts/openapi/crm.yaml — не править руками.
 */

export interface paths {
    "/api/v1/leads/web": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Web Lead
         * @description Форма «Запрос» со страницы входа Cabinet → лид CRM с источником `web` (ARCHITECTURE §17).
         *
         *     Без аутентификации. Нужны телефон или e-mail и `consent: true` (согласие на обработку ПДн,
         *     Q-12). Ошибки: 422 `validation_failed` с `details.reason` (`consent_required` |
         *     `form_token_invalid` | `form_too_fast` | `form_token_expired` | `contact_required` |
         *     `invalid_phone` | `invalid_email`), 429 `rate_limited`.
         *     Повторный запрос известного контакта дополняет существующую карточку.
         */
        post: operations["web_lead"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/leads/web/token": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Web Lead Token
         * @description Токен формы «Запрос»: получить при показе формы, отправить в `form_token`.
         *
         *     Без аутентификации. Отправка раньше `min_fill_seconds` или после `expires_at` отклоняется.
         */
        get: operations["web_lead_token"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * ErrorDetails
         * @description Подробности ошибки; кроме описанных полей бывают контекстные (`assigned_user_name`, …).
         */
        ErrorDetails: {
            /**
             * Errors
             * @description ошибки валидации запроса по полям
             */
            errors?: {
                [key: string]: unknown;
            }[] | null;
            /**
             * Field
             * @description поле формы, к которому относится ошибка
             */
            field?: string | null;
            /** @description подкод конкретного случая */
            reason?: components["schemas"]["Reason"] | null;
        } & {
            [key: string]: unknown;
        };
        /** ErrorOut */
        ErrorOut: {
            /**
             * Code
             * @description класс ошибки: conflict, validation_failed, not_found, …
             */
            code: string;
            details: components["schemas"]["ErrorDetails"];
            /**
             * Message
             * @description для логов; пользователю — текст по code/details.reason
             */
            message: string;
        };
        /**
         * Reason
         * @description Подкоды `details.reason` — контракт с фронтом: значения не переименовывать.
         * @enum {string}
         */
        Reason: "email_taken" | "invalid_email" | "invalid_phone" | "telegram_taken" | "telegram_linked_elsewhere" | "telegram_unknown" | "telegram_not_linked" | "telegram_refused" | "bot_not_configured" | "wrong_password" | "same_password" | "weak_password" | "inactive_colleague" | "lead_taken" | "take_first" | "deal_not_closed" | "not_lead_owner" | "already_with_bot" | "no_open_handoff" | "snooze_range" | "service_request_closed" | "file_too_large" | "file_empty" | "file_type" | "kb_markdown_only" | "kb_format" | "document_indexing" | "setup_done" | "setup_code_invalid" | "setup_code_expired" | "setup_locked" | "invalid_bot_token" | "telegram_unavailable" | "secrets_key_missing" | "bot_not_running" | "channel_not_configured" | "channel_send_failed" | "assist_disabled" | "assist_budget" | "assist_unavailable" | "assist_empty" | "assist_no_history" | "deal_won_final" | "deal_owned_by_erp" | "no_consent" | "reply_in_progress" | "delivery_unknown" | "delivery_unconfirmed" | "litellm_unavailable" | "model_key_required" | "model_in_config" | "erp_not_configured" | "erp_invalid_url" | "erp_unauthorized" | "erp_unavailable" | "erp_bad_response" | "erp_rate_limited" | "client_not_in_erp" | "erp_inn_conflict" | "erp_pairing_code_invalid" | "erp_pairing_code_expired" | "erp_pairing_code_used" | "erp_pairing_unsupported" | "erp_https_required" | "erp_bootstrap_rejected" | "erp_bootstrap_closed" | "erp_bootstrap_unavailable" | "smtp_not_configured" | "smtp_invalid_host" | "smtp_unavailable" | "smtp_auth_failed" | "smtp_tls_failed" | "smtp_rejected" | "offsite_key_invalid" | "offsite_folder_invalid" | "offsite_not_configured" | "offsite_delivery_failed" | "lead_exists" | "client_exists" | "contact_required" | "form_token_invalid" | "form_too_fast" | "form_token_expired" | "rate_limited" | "consent_required" | "ai_spend_period" | "service_not_switchable" | "telegram_paused" | "sso_not_configured" | "platform_access_denied" | "eds_access_denied" | "user_not_provisioned" | "user_inactive" | "erp_email_conflict" | "won_decided_by_erp" | "handoff_no_consent" | "consent_via_bot" | "name_required" | "phone_invalid" | "timezone_unknown" | "signature_invalid" | "avatar_empty" | "avatar_too_large" | "avatar_unsupported_type" | "avatar_type_mismatch" | "deputy_is_self" | "deputy_period_reversed" | "deputy_period_past" | "deputy_period_too_long" | "deputy_not_colleague" | "not_a_deputy" | "reset_token_invalid" | "ticket_subject_unknown" | "ticket_text_empty" | "ticket_text_too_long" | "ticket_page_invalid" | "ticket_status_unknown" | "ticket_status_transition" | "ticket_reply_empty" | "ticket_reply_too_long" | "ticket_rate_limited" | "article_title_empty" | "article_title_too_long" | "article_body_empty" | "article_body_too_long" | "article_language_unknown" | "article_status_unknown" | "contact_channel_required" | "request_not_allowed" | "request_key_reused" | "erp_request_conflict" | "request_not_failed" | "request_not_retryable";
        /**
         * WebFormToken
         * @description Токен формы «Запрос»: выдаётся вместе с формой, отправляется в `form_token`.
         */
        WebFormToken: {
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /** Min Fill Seconds */
            min_fill_seconds: number;
            /** Token */
            token: string;
        };
        /**
         * WebLeadAccepted
         * @description 202: запрос принят. `lead_id` пустой — запрос отброшен антиспамом (honeypot).
         */
        WebLeadAccepted: {
            /** Lead Id */
            lead_id: number | null;
        };
        /**
         * WebLeadIn
         * @description Форма «Запрос» со страницы входа Cabinet: вложений в первой версии нет (Q-12).
         *
         *     `consent` — согласие на обработку персональных данных, обязательно `true` (Q-12): иначе
         *     422 `consent_required`. `website` — honeypot: человек поле не видит; заполнено — запрос
         *     принят, лид не создан.
         */
        WebLeadIn: {
            /** Company */
            company?: string | null;
            /**
             * Consent
             * @description Согласие на обработку персональных данных; обязательно true (иначе 422 consent_required).
             * @default false
             */
            consent: boolean;
            /** Email */
            email?: string | null;
            /** Form Token */
            form_token: string;
            /**
             * Language
             * @default ru
             * @enum {string}
             */
            language: "ru" | "uz" | "en";
            /** Name */
            name: string;
            /** Phone */
            phone?: string | null;
            /** Text */
            text: string;
            /** Website */
            website?: string | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    web_lead: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WebLeadIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WebLeadAccepted"];
                };
            };
            /** @description Ошибка валидации */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
    web_lead_token: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WebFormToken"];
                };
            };
            /** @description Ошибка валидации */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorOut"];
                };
            };
        };
    };
}
