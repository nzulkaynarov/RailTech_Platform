import { useQueryClient } from "@tanstack/react-query";
import { Button, Modal } from "antd";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { canSee } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import { getGetMeQueryKey, useFinishOnboarding } from "../../shared/api/generated/platform-bff";
import { rolesText, startKindsOf, useStartSteps } from "../help/startKinds";
import { isNewer } from "../help/changelog";
import { useWhatsNew } from "../help/whatsNew";

import "../help/help.css";

const SKIP_KEY = "rt-pf-onboarding-skipped";
const STEPS = ["rail", "menu", "bell", "help"] as const;
type StepKey = (typeof STEPS)[number];

function skippedThisSession(userId: string): boolean {
  try {
    return window.sessionStorage.getItem(SKIP_KEY) === userId;
  } catch {
    return false;
  }
}
function rememberSkip(userId: string): void {
  try {
    window.sessionStorage.setItem(SKIP_KEY, userId);
  } catch {
    // Без хранилища «Пропустить» действует до перезагрузки страницы.
  }
}

/** Объект, на который показывает шаг тура; нет на экране (узкий экран, подменю в Drawer) — карточка без привязки. */
function targetOf(step: StepKey): HTMLElement | null {
  const selector =
    step === "menu"
      ? '[data-tour="menu"] a[href="/dashboard/queue"], [data-tour="menu"]'
      : `[data-tour="${step}"]`;
  for (const element of document.querySelectorAll<HTMLElement>(selector)) {
    const rect = element.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) return element;
  }
  return null;
}

interface Place {
  top?: number;
  left?: number;
  right?: number;
  bottom?: number;
}

const CARD_WIDTH = 340;

function placeFor(step: StepKey, element: HTMLElement | null): Place {
  const narrow = window.innerWidth < 768;
  if (!element || narrow) return { left: 8, right: 8, bottom: narrow ? 72 : 16 };
  const rect = element.getBoundingClientRect();
  const maxTop = Math.max(8, window.innerHeight - 260);
  if (step === "rail" || step === "menu") {
    return { top: Math.min(Math.max(8, rect.top), maxTop), left: rect.right + 12 };
  }
  return {
    top: Math.min(rect.bottom + 12, maxTop),
    left: Math.max(8, Math.min(rect.right - CARD_WIDTH, window.innerWidth - CARD_WIDTH - 8)),
  };
}

function TourCard({
  steps,
  onSkip,
  onNever,
}: {
  steps: readonly StepKey[];
  onSkip: () => void;
  onNever: () => void;
}) {
  const { t } = useTranslation("help");
  const titleId = useId();
  const textId = useId();
  const card = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(0);
  const [place, setPlace] = useState<Place>({});
  const step = steps[index] ?? steps[0] ?? "rail";
  const last = index === steps.length - 1;

  // Фокус возвращается туда, откуда начали, когда тур закрыт.
  useEffect(() => {
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      const target =
        before && document.contains(before) ? before : document.getElementById("main-content");
      target?.focus();
    };
  }, []);

  // Подсветка объекта шага и положение карточки. При смене ширины каркас перестраивается (рейл слева <-> нижняя панель),
  // поэтому после изменения размера положение пересчитывается и ещё раз, когда разметка уже перестроена.
  useLayoutEffect(() => {
    let timer = 0;
    const highlight = () => {
      document.querySelectorAll(".pf-tour-target").forEach((node) => {
        node.classList.remove("pf-tour-target");
      });
      const element = targetOf(step);
      element?.classList.add("pf-tour-target");
      setPlace(placeFor(step, element));
    };
    const onResize = () => {
      highlight();
      window.clearTimeout(timer);
      timer = window.setTimeout(highlight, 250);
    };
    highlight();
    window.addEventListener("resize", onResize);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("resize", onResize);
      document.querySelectorAll(".pf-tour-target").forEach((node) => {
        node.classList.remove("pf-tour-target");
      });
    };
  }, [step]);

  // На каждом шаге фокус — на карточке: скринридер читает название и текст, Tab идёт по кнопкам.
  useEffect(() => {
    card.current?.focus();
  }, [index]);

  // Escape закрывает тур с любого места страницы.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onSkip();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onSkip]);

  const trap = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab" || !card.current) return;
    const items = [...card.current.querySelectorAll<HTMLElement>("button:not(:disabled)")];
    const first = items[0];
    const lastItem = items[items.length - 1];
    if (!first || !lastItem) return;
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === card.current)) {
      event.preventDefault();
      lastItem.focus();
    } else if (!event.shiftKey && active === lastItem) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div
      ref={card}
      role="dialog"
      aria-label={t("tour.label")}
      aria-describedby={`${titleId} ${textId}`}
      tabIndex={-1}
      className="pf-tour-card"
      style={place}
      onKeyDown={trap}
    >
      <p className="pf-tour-progress" aria-live="polite">
        {t("tour.progress", { current: index + 1, total: steps.length })}
      </p>
      <h2 id={titleId}>{t(`tour.steps.${step}.title`)}</h2>
      <p id={textId}>{t(`tour.steps.${step}.text`)}</p>
      <div className="pf-tour-buttons">
        <Button size="small" type="text" onClick={onNever}>
          {t("tour.never")}
        </Button>
        <Button size="small" onClick={onSkip}>
          {t("tour.skip")}
        </Button>
        {index > 0 ? (
          <Button
            size="small"
            onClick={() => {
              setIndex(index - 1);
            }}
          >
            {t("tour.prev")}
          </Button>
        ) : null}
        <Button
          size="small"
          type="primary"
          onClick={() => {
            if (last) onNever();
            else setIndex(index + 1);
          }}
        >
          {last ? t("tour.done") : t("tour.next")}
        </Button>
      </div>
    </div>
  );
}

/**
 * Первый вход (W15-H7, UX-оценка P1-2): карточка «Добро пожаловать, {имя}» с тем, что делать утром, и тур из четырёх
 * шагов: рейл, «Мои задачи», колокольчик, помощь. «Пропустить» скрывает приветствие до конца сеанса; «Больше не показывать»
 * и «Готово» сохраняют флаг в профиле CRM (`PUT /me/onboarding`) — он не зависит от браузера и устройства.
 */
export function Onboarding() {
  const { t } = useTranslation("help");
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const [hidden, setHidden] = useState(() => skippedThisSession(me.id));
  const [phase, setPhase] = useState<"welcome" | "tour">("welcome");
  const finish = useFinishOnboarding();
  const whatsNew = useWhatsNew();
  const kinds = startKindsOf(me);
  const steps = useStartSteps(kinds[0] ?? "default");
  const tourSteps = useMemo(
    () => STEPS.filter((key) => key !== "menu" || canSee(me, { resource: "dashboard.queue" })),
    [me],
  );

  if (me.onboarding_done || hidden) return null;

  const skip = () => {
    rememberSkip(me.id);
    setHidden(true);
  };
  const never = () => {
    rememberSkip(me.id);
    setHidden(true);
    queryClient.setQueryData(getGetMeQueryKey(), { ...me, onboarding_done: true });
    finish.mutate();
    // Новичку окно «Платформа обновлена» сразу после приветствия ни к чему (W-REL): записи до его прихода он видит в
    // «Что нового» с отметкой «Новое» у «?», а окно покажется со следующей выкладкой.
    if (whatsNew.latest && isNewer(me.whats_new_shown, whatsNew.latest)) {
      whatsNew.mark({ shown: whatsNew.latest });
    }
  };

  if (phase === "tour") return <TourCard steps={tourSteps} onSkip={skip} onNever={never} />;

  return (
    <Modal
      open
      onCancel={skip}
      maskClosable={false}
      title={t("welcome.title", { name: me.name })}
      closeIcon={null}
      footer={[
        <Button key="never" type="text" onClick={never}>
          {t("welcome.never")}
        </Button>,
        <Button key="skip" onClick={skip}>
          {t("welcome.skip")}
        </Button>,
        <Button
          key="tour"
          type="primary"
          onClick={() => {
            setPhase("tour");
          }}
        >
          {t("welcome.tour")}
        </Button>,
      ]}
    >
      <p style={{ margin: 0 }}>{t("welcome.role", { role: rolesText(me) })}</p>
      <p style={{ margin: "8px 0 0" }}>{t("welcome.lead")}</p>
      <ol className="pf-welcome-steps">
        {steps.slice(0, 4).map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
    </Modal>
  );
}
