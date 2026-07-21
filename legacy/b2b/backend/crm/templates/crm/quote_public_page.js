/* Wave A — public КП page behaviour. Loaded as an external static file (CSP script-src 'self').
 * No inline handlers, no inline script. Talks to the anonymous public endpoints under
 * /api/v1/public/quotes/<token>/ and progressively enhances the server-rendered page.
 *
 * The «viewed» BEACON (not the bare GET) is the genuine-open signal: email security scanners
 * pre-open links but do not execute JS, so this fires only in a real browser. */
(function () {
  "use strict";
  var body = document.body;
  var API = body.getAttribute("data-api-base");
  if (!API) return;

  var ERR = {
    CODE_REQUIRED: "Введите код из письма.",
    NO_ACTIVE_CODE: "Код не запрошен или истёк. Отправьте код заново.",
    CODE_EXPIRED: "Срок действия кода истёк. Отправьте код заново.",
    TOO_MANY_ATTEMPTS: "Слишком много попыток. Отправьте код заново.",
    INVALID_CODE: "Неверный код. Проверьте письмо и попробуйте ещё раз.",
    REASON_REQUIRED: "Укажите причину отклонения.",
    QUOTE_LINK_REVOKED: "Ссылка больше недействительна.",
    QUOTE_LINK_EXPIRED: "Срок действия предложения истёк.",
    NOT_FOUND: "Предложение не найдено.",
    THROTTLED: "Слишком часто. Подождите немного и попробуйте снова.",
    GENERIC: "Не удалось выполнить действие. Попробуйте позже."
  };

  function post(path, payload) {
    return fetch(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: payload ? JSON.stringify(payload) : "{}"
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (data) {
        return { ok: resp.ok, status: resp.status, data: data };
      });
    });
  }

  function msgFor(res) {
    if (res.status === 429) return ERR.THROTTLED;
    var code = res.data && res.data.detail;
    return (code && ERR[code]) || ERR.GENERIC;
  }

  function show(el) { if (el) el.hidden = false; }
  function hide(el) { if (el) el.hidden = true; }
  function $(id) { return document.getElementById(id); }

  /* ── View beacon (fire once on load) ── */
  post("viewed/", {}).catch(function () { /* telemetry is best-effort */ });

  /* ── Accept flow ── */
  var acceptPanel = $("accept-panel");
  var rejectPanel = $("reject-panel");
  var acceptMsg = $("accept-msg");
  var codeEntry = $("code-entry");

  var btnAccept = $("btn-accept");
  if (btnAccept) btnAccept.addEventListener("click", function () {
    hide(rejectPanel); show(acceptPanel);
    acceptPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });

  function requestCode(btn) {
    if (acceptMsg) { acceptMsg.className = "msg"; acceptMsg.textContent = "Отправляем код…"; }
    if (btn) btn.disabled = true;
    post("request-code/", {}).then(function (res) {
      if (btn) btn.disabled = false;
      if (res.ok) {
        show(codeEntry);
        if (acceptMsg) { acceptMsg.className = "msg ok"; acceptMsg.textContent = "Код отправлен. Проверьте почту (действует 15 минут)."; }
        var codeInput = $("code");
        if (codeInput) codeInput.focus();
      } else if (acceptMsg) {
        acceptMsg.className = "msg error"; acceptMsg.textContent = msgFor(res);
      }
    }).catch(function () {
      if (btn) btn.disabled = false;
      if (acceptMsg) { acceptMsg.className = "msg error"; acceptMsg.textContent = ERR.GENERIC; }
    });
  }

  var btnSendCode = $("btn-send-code");
  if (btnSendCode) btnSendCode.addEventListener("click", function () { requestCode(btnSendCode); });
  var btnResend = $("btn-resend-code");
  if (btnResend) btnResend.addEventListener("click", function () { requestCode(btnResend); });

  var btnConfirmAccept = $("btn-confirm-accept");
  if (btnConfirmAccept) btnConfirmAccept.addEventListener("click", function () {
    var codeInput = $("code");
    var code = codeInput ? codeInput.value.trim() : "";
    if (acceptMsg) { acceptMsg.className = "msg"; acceptMsg.textContent = "Проверяем код…"; }
    btnConfirmAccept.disabled = true;
    post("accept/", { code: code }).then(function (res) {
      btnConfirmAccept.disabled = false;
      if (res.ok) {
        hide(acceptPanel); hide($("cta"));
        var detail = $("accepted-detail");
        if (detail && res.data && res.data.contract_number && res.data.contract_number !== "—") {
          detail.textContent = "Спасибо! Договор № " + res.data.contract_number + " готовится к подписанию — с вами свяжется менеджер.";
        }
        show($("accepted-state"));
        $("accepted-state").scrollIntoView({ behavior: "smooth", block: "center" });
      } else if (acceptMsg) {
        acceptMsg.className = "msg error"; acceptMsg.textContent = msgFor(res);
      }
    }).catch(function () {
      btnConfirmAccept.disabled = false;
      if (acceptMsg) { acceptMsg.className = "msg error"; acceptMsg.textContent = ERR.GENERIC; }
    });
  });

  /* ── Reject flow ── */
  var btnReject = $("btn-reject");
  if (btnReject) btnReject.addEventListener("click", function () {
    hide(acceptPanel); show(rejectPanel);
    rejectPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
  var btnCancelReject = $("btn-cancel-reject");
  if (btnCancelReject) btnCancelReject.addEventListener("click", function () { hide(rejectPanel); });

  var btnConfirmReject = $("btn-confirm-reject");
  if (btnConfirmReject) btnConfirmReject.addEventListener("click", function () {
    var reasonInput = $("reason");
    var reason = reasonInput ? reasonInput.value.trim() : "";
    var rejectMsg = $("reject-msg");
    if (!reason) {
      if (rejectMsg) { rejectMsg.className = "msg error"; rejectMsg.textContent = ERR.REASON_REQUIRED; }
      return;
    }
    if (rejectMsg) { rejectMsg.className = "msg"; rejectMsg.textContent = "Отправляем…"; }
    btnConfirmReject.disabled = true;
    post("reject/", { reason: reason }).then(function (res) {
      btnConfirmReject.disabled = false;
      if (res.ok) {
        hide(rejectPanel); hide($("cta"));
        show($("rejected-state"));
        $("rejected-state").scrollIntoView({ behavior: "smooth", block: "center" });
      } else if (rejectMsg) {
        rejectMsg.className = "msg error"; rejectMsg.textContent = msgFor(res);
      }
    }).catch(function () {
      btnConfirmReject.disabled = false;
      if (rejectMsg) { rejectMsg.className = "msg error"; rejectMsg.textContent = ERR.GENERIC; }
    });
  });
})();
