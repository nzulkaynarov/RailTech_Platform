# Email setup — Yandex 360 + EmailLog

How transactional email is wired in production for `b2b.railtech.uz`.

## Provider

**Yandex 360** (мейл для домена `railtech.uz`). Mailbox `noreply@railtech.uz` is provisioned in [admin.yandex.ru](https://admin.yandex.ru) and authenticates with a **Yandex application password** — not the regular login password (Yandex SMTP rejects the latter).

## Configuration

### GitHub Actions secrets (Environment: `production`, repo `nzulkaynarov/RailTech_SaaS_B2B`)

| Secret | Value |
|---|---|
| `EMAIL_HOST` | `smtp.yandex.ru` |
| `EMAIL_HOST_USER` | `noreply@railtech.uz` |
| `EMAIL_HOST_PASSWORD` | 16-character app password from Yandex Passport → Безопасность → Пароли для приложений |

The deploy workflow (`.github/workflows/deploy-b2b.yml`) renders these into `/opt/railtech-b2b/.env` on every deploy. `EMAIL_PORT=587`, `EMAIL_USE_TLS=True`, and `DEFAULT_FROM_EMAIL=noreply@railtech.uz` are hardcoded in the workflow.

### Backend pipeline

- Single entry point: `notifications.emails.send_templated_email(template, context, to, channel, user)`.
- Three channels in `settings.EMAIL_CHANNELS`: `transactional`, `marketing`, `system`. All three currently share the SMTP config above; each can be overridden by `EMAIL_TX_*` / `EMAIL_MKT_*` / `EMAIL_SYS_*` env vars when needed.
- Templates live in `backend/templates/emails/{name}.{html,txt,_subject.txt}`. Active templates: `setup_password`, `invite_member`, `kyc_verified`, `role_application_approved`, `role_application_rejected`, `reset_password`.
- Every send is persisted in `notifications.EmailLog` (fields: `template`, `channel`, `subject`, `from_email`, `to_emails`, `user`, `body_text`, `body_html`, `status` SENT/FAILED, `error`, `created_at`). Visible in Unfold at `/admin/notifications/emaillog/`.

## DNS (on `railtech.uz`, NS = `dns1.yandex.net`, `dns2.yandex.net`)

| Record | State | Value |
|---|---|---|
| MX | ✅ | `mx.yandex.net.` (priority 10) |
| TXT `@` (SPF) | ✅ | `v=spf1 redirect=_spf.yandex.net` |
| TXT `mail._domainkey` (DKIM) | ✅ | RSA key published (rotate via Yandex 360 admin) |
| TXT `_dmarc` | ✅ | `v=DMARC1; p=none; rua=mailto:dmarc@railtech.uz; ruf=mailto:dmarc@railtech.uz; fo=1; adkim=r; aspf=r; pct=100` |

DMARC is in `p=none` (monitor) mode — aggregate + forensic reports go to `dmarc@railtech.uz`. Once a few weeks of reports show no legitimate sources failing alignment, you can tighten to `p=quarantine` or `p=reject`.

## Verifying a stuck send

1. `/admin/notifications/emaillog/` — filter by recipient or template, check `status` and `error`.
2. If `error` mentions `relay denied` / `authentication failed`: re-issue the Yandex app password (it may have been revoked when 2FA was reset).
3. SMTP handshake test on the VPS:
   ```bash
   ssh vps-eskiz
   docker exec railtech_backend_prod python - <<'PY'
   import os, smtplib, ssl
   with smtplib.SMTP(os.environ["EMAIL_HOST"], int(os.environ["EMAIL_PORT"]), timeout=15) as s:
       s.ehlo(); s.starttls(context=ssl.create_default_context()); s.ehlo()
       s.login(os.environ["EMAIL_HOST_USER"], os.environ["EMAIL_HOST_PASSWORD"])
       print("AUTH OK")
   PY
   ```
4. If "AUTH OK" but EmailLog still shows FAILED: the bug is in templating/dispatch, not SMTP. Check `notifications.emails` traceback in `docker logs railtech_backend_prod`.

## Conventions

- Don't email users from `admin@railtech.uz`; use `noreply@railtech.uz` (`DEFAULT_FROM_EMAIL`).
- Adding a new email template = HTML + TXT + `_subject.txt` files + a call to `send_templated_email`. EmailLog row is automatic.
- If a user reports "не получил письмо", check `EmailLog` first (every attempt is logged). Only then look at SMTP/DNS/spam.
- Watch for spam classification by Gmail/Yandex receivers — without DMARC and with a fresh sending domain, early mail can land in Спам/Промоакции. Mention this to the user when troubleshooting deliverability.
