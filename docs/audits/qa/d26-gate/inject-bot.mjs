// Клиент пишет боту через заглушку Bot API (127.0.0.1:18999): /start, язык, согласие, затем сообщение.
// Запуск: node docs/audits/qa/d26-gate/inject-bot.mjs <uid> <username> <имя> <текст сообщения>
import { inject, injectCb } from "./sc-base.mjs";
const [uid, uname, first, ...msg] = process.argv.slice(2);
const w = (ms) => new Promise((r) => setTimeout(r, ms));
await inject(+uid, "/start", uname, first); await w(3000);
await injectCb(+uid, "lang:ru", uname, first); await w(3000);
await injectCb(+uid, "consent:accept", uname, first); await w(3000);
await inject(+uid, msg.join(" "), uname, first); await w(3000);
