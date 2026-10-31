import { Button, Select } from "antd";
import { type ReactNode, useState } from "react";

import { companyToday } from "../shared/lib/dates";
import { STATUS_KINDS, STATUS_TONE, STATUS_TONES } from "../shared/lib/statuses";
import { formatDocNumber } from "../shared/lib/docNumber";
import { useFormat } from "../shared/lib/useFormat";
import { Checklist } from "../shared/ui/Checklist";
import { Consequence } from "../shared/ui/Consequence";
import { ContextPanel } from "../shared/ui/ContextPanel";
import { CounterCard, CounterGrid } from "../shared/ui/CounterCard";
import { DateField, DateRangeField } from "../shared/ui/DateField";
import { DefinitionList } from "../shared/ui/DefinitionList";
import { DocNumber } from "../shared/ui/DocNumber";
import { DocList, DocRow } from "../shared/ui/DocRow";
import { EmptyState } from "../shared/ui/EmptyState";
import { FileField } from "../shared/ui/FileField";
import { FormField } from "../shared/ui/FormParts";
import { Forbidden } from "../shared/ui/Forbidden";
import { History } from "../shared/ui/History";
import { MoneyText } from "../shared/ui/MoneyText";
import { PageHeader } from "../shared/ui/PageHeader";
import { QueueList } from "../shared/ui/QueueList";
import { RequestSteps } from "../shared/ui/RequestSteps";
import { SoonButton } from "../shared/ui/SoonButton";
import { SourceBanner } from "../shared/ui/SourceBanner";
import { StatusTag } from "../shared/ui/StatusTag";
import "./showcase.css";

/**
 * Витрина общих компонентов Платформы (PLT-13): `/dev/ui`, только в dev-сборке (`import.meta.env.DEV` в router.tsx —
 * в прод-бандл не попадает). Данные вымышленные. Витрина — для проверки глазами, скриншотов и axe; компоненты живут в
 * `shared/ui`.
 */

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="dev-section" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`} className="dev-h2">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Statuses() {
  return (
    <Section id="status" title="StatusTag: карты статусов SPEC-v3 §2.4">
      <div className="dev-tones" aria-label="Цвета тегов">
        {STATUS_TONES.map((tone) => (
          <StatusTag key={tone} tone={tone}>
            {tone}
          </StatusTag>
        ))}
      </div>
      <div className="dev-statuses">
        {STATUS_KINDS.map((kind) => (
          <div key={kind} className="pf-card dev-card">
            <div className="pf-hint">{kind}</div>
            <div className="dev-tags">
              {Object.keys(STATUS_TONE[kind]).map((status) => (
                <StatusTag key={status} kind={kind} status={status} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

function Steps() {
  return (
    <Section id="steps" title="RequestSteps: путь заявки в 7 шагов">
      <div className="pf-card dev-card dev-stack">
        <RequestSteps stage="REQUEST" number="ЗВ-2026-104" />
        <RequestSteps stage="QUOTE" number="ЗВ-2026-104" />
        <RequestSteps stage="PAYMENT" number="ПР-2026-104" />
        <RequestSteps stage="DONE" number="ПР-2026-099" />
        <RequestSteps stage="LOST" step={4} number="ЗВ-2026-097" />
      </div>
    </Section>
  );
}

function Blocks() {
  return (
    <Section id="blocks" title="Consequence, History, Checklist, DefinitionList">
      <div className="dev-columns">
        <div className="dev-stack">
          <Consequence
            items={[
              "Специалисты получат задание в «Расчёт · Мои расчёты» и сообщение в чат проекта.",
              "Клиенту бот напишет: «Заявка принята, считаем».",
              "Готовый расчёт вернётся к вам черновиком КП.",
            ]}
          />
          <div className="pf-card dev-card">
            <div className="pf-hint dev-caption">ИСТОРИЯ ДОГОВОРА ДОГ-2026/104</div>
            <History
              label="История договора ДОГ-2026/104"
              items={[
                {
                  state: "done",
                  title: "Редакция согласована клиентом в кабинете",
                  meta: "25.10 · Рустамов А.К.",
                },
                { state: "done", title: "Выставлен у оператора", meta: "26.10 · Дилноза К." },
                {
                  state: "waiting",
                  title: "Ждёт подписанный скан",
                  meta: "ответственный: Дилноза К.",
                },
                { state: "todo", title: "Счёт на предоплату" },
              ]}
            />
          </div>
        </div>
        <div className="dev-stack">
          <div className="pf-card dev-card">
            <div className="pf-hint dev-caption">ПРОВЕРКА ПЕРЕД ОТПРАВКОЙ</div>
            <Checklist
              label="Проверка перед отправкой"
              items={[
                { state: "ok", label: "Виза снабженца · цены и сроки", meta: "Азиз · 22.10" },
                { state: "ok", label: "Виза гл. инженера · услуги", meta: "Бахтиёр · 23.10" },
                { state: "fail", label: "Маржа 18,0 % ниже 22 % по резолюции" },
                { state: "pending", label: "Срок клиента до 30.11 выдержан" },
              ]}
            />
          </div>
          <div className="pf-card dev-card">
            <DefinitionList
              items={[
                { label: "Клиент", value: "АО «Демо-Транс»" },
                { label: "ИНН", value: <span className="pf-num">300 000 001</span> },
                { label: "Контакт", value: "Рустамов А.К. · может принимать решения" },
                { label: "E-mail", value: null },
              ]}
            />
          </div>
        </div>
      </div>
    </Section>
  );
}

function Panel() {
  const [tab, setTab] = useState("approval");
  return (
    <Section id="panel" title="ContextPanel: боковое окно 440 px (закреплённое)">
      <div className="dev-panel">
        <ContextPanel
          open
          docked
          panelMode="docked"
          id="dev-panel"
          label="Боковое окно"
          hideLabel="Скрыть боковое окно"
          onHide={() => undefined}
          activeTab={tab}
          onTabChange={setTab}
          tabs={[
            { key: "approval", label: "Одобрение" },
            { key: "chat", label: "Чат проекта" },
            { key: "docs", label: "Документы" },
          ]}
        >
          <div className="dev-stack">
            <Checklist
              items={[
                { state: "ok", label: "Виза снабженца", meta: "Азиз · 22.10" },
                { state: "pending", label: "Виза гл. инженера" },
              ]}
            />
            <Button type="primary" block>
              Одобрить КП → Исходящие
            </Button>
            <Consequence
              items={[
                "КП получит исходящий номер и PDF.",
                "Клиенту уйдёт ссылка в выбранные каналы.",
                "Когда клиент примет КП, откроется проект.",
              ]}
            />
          </div>
        </ContextPanel>
      </div>
    </Section>
  );
}

function Lists() {
  const format = useFormat();
  return (
    <Section id="lists" title="QueueList, CounterCard, DocRow">
      <div className="dev-stack">
        <CounterGrid>
          <CounterCard
            label="Входящие без резолюции"
            value={1}
            source="EDS · Входящие"
            to="/dev/ui"
          />
          <CounterCard label="КП на одобрение" value={1} source="EDS · Черновик" to="/dev/ui" />
          <CounterCard
            label="Служебные записки"
            value={1}
            source="EDS · На согласовании"
            to="/dev/ui"
          />
          <CounterCard
            label="Проекты в работе"
            value={1204}
            source="1 ждёт оплаты · 1 в отгрузке"
            to="/dev/ui"
          />
        </CounterGrid>
        <QueueList
          title="Что сделать сейчас"
          headingLevel={3}
          items={[
            {
              id: "1",
              badge: { tone: "red", label: "срок сегодня" },
              title: "Наложить резолюцию на письмо ВХ-104/26",
              caption: "АО «Демо-Транс» · заявка ЗВ-2026-104 · от менеджера · вчера 09:24",
              to: "/dev/ui",
            },
            {
              id: "2",
              badge: { tone: "gold", label: "завтра" },
              title: "Одобрить КП-2026/118 (черновик)",
              caption: "Депо «Демо» · расчёт готов, визы собраны · маржа 23,4 %",
              to: "/dev/ui",
            },
            {
              id: "3",
              badge: { tone: "purple", label: "служебка" },
              title: "Согласовать СЗ-2026/031 · Закупка воды в офис, 450 000 сум",
              caption: "от офис-менеджера · создана из чата #офис · 2 вложения",
              to: "/dev/ui",
            },
          ]}
        />
        <DocList
          title="Документы проекта"
          headingLevel={3}
          extra={<Button size="small">+ Добавить документ</Button>}
        >
          <DocRow
            number="КП-2026/115"
            type="Исходящие · v2"
            status={<StatusTag kind="quote" status="accepted" />}
            note="24.10 · Рустамов А.К. в кабинете"
            action={<Button size="small">Открыть</Button>}
          />
          <DocRow
            number="СЧ-2026/142"
            type="Счёт на предоплату 50 %"
            status={<StatusTag kind="invoice" status="proof_received" />}
            note={`${format.money(67200000)} · выставлен 27.10 · клиент приложил ПП № 418`}
            action={
              <Button size="small" type="primary">
                Подтвердить оплату
              </Button>
            }
          />
          <DocRow
            number="АКТ-2026/—"
            type="Акт выполненных работ"
            status={<StatusTag tone="default">После ПНР</StatusTag>}
            note="подготовит бухгалтер по отчёту гл. инженера"
          />
        </DocList>
      </div>
    </Section>
  );
}

function Formats() {
  const format = useFormat();
  const moment = new Date("2026-10-24T06:50:00Z");
  return (
    <Section id="formats" title="Суммы, даты, номера">
      <div className="pf-card dev-card">
        <DefinitionList
          items={[
            { label: "Сумма", value: <MoneyText value={134400000} /> },
            { label: "Итого с НДС", value: <MoneyText value="134400000.00" strong /> },
            { label: "С копейками", value: <MoneyText value="1200.5" /> },
            { label: "Без валюты", value: <MoneyText value={61000000} currency={false} /> },
            { label: "Возврат", value: <MoneyText value={-450000} /> },
            { label: "Маржа", value: <span className="pf-num">{format.percent(30)}</span> },
            { label: "Дата", value: format.date(moment) },
            { label: "Дата и время", value: format.date(moment, "datetime") },
            { label: "Длинная дата", value: format.date(moment, "long") },
            { label: "В ленте", value: format.activity(moment, new Date("2026-10-25T05:00:00Z")) },
            {
              label: "Номера",
              value: (
                <span className="dev-numbers">
                  <DocNumber number="ЗВ-2026-104" base="/eds/projects" />
                  <DocNumber
                    number={formatDocNumber({ kind: "quote", year: 2026, seq: 115, version: 2 })}
                  />
                  <DocNumber number={formatDocNumber({ kind: "incoming", year: 2026, seq: 104 })} />
                </span>
              ),
            },
          ]}
        />
      </div>
    </Section>
  );
}

function States() {
  return (
    <Section id="states" title="EmptyState, Forbidden, SourceBanner, PageHeader">
      <div className="dev-stack">
        <div className="pf-card">
          <EmptyState
            level={3}
            title="Решений от вас пока не требуется"
            text="Новые письма приходят из CRM, черновики КП — из ERP, служебки — от сотрудников."
            action={<Button>Все проекты</Button>}
          />
        </div>
        <Forbidden embedded roles={["Директор", "Бухгалтер"]} />
        <SourceBanner sources={{ crm: "ok", erp: "unavailable" }} onRetry={() => undefined} />
        <SourceBanner sources={{ crm: "unavailable", erp: "unavailable" }} />
        <div className="pf-card dev-card">
          <PageHeader
            title="ПР-2026-104 · Датчики ADZ, блоки БКЗ-24В"
            subtitle="АО «Демо-Транс» · 134,4 млн сум с НДС"
            extra={<SoonButton>Написать клиенту</SoonButton>}
          />
        </div>
      </div>
    </Section>
  );
}

const DEMO_FILE = new File([new Uint8Array(1_572_864)], "schet-demo.pdf", {
  type: "application/pdf",
});

function Fields() {
  const [due, setDue] = useState("2026-11-05");
  const [range, setRange] = useState({ from: "2026-10-01", to: "2026-10-31" });
  const [files, setFiles] = useState<File[]>([DEMO_FILE]);
  const [level, setLevel] = useState("read");
  return (
    <Section id="fields" title="DateField, DateRangeField, FileField, Select (UX-2a)">
      <div className="dev-stack">
        <div className="pf-card dev-card dev-fields">
          <FormField id="dev-due" label="Срок расчёта" hint="Не раньше сегодня по Ташкенту">
            <DateField
              id="dev-due"
              value={due}
              min={companyToday()}
              aria-describedby="dev-due-hint"
              onChange={setDue}
            />
          </FormField>
          <div className="dev-row">
            <DateRangeField
              idFrom="dev-from"
              idTo="dev-to"
              labelFrom="С даты"
              labelTo="По дату"
              fieldClassName="pf-fp-field"
              value={range}
              onChange={setRange}
            />
          </div>
          <FormField
            id="dev-files"
            label="Вложения"
            hint="PDF, изображения, документы Office — до 25 МБ"
          >
            <FileField
              id="dev-files"
              multiple
              maxSize={25 * 1024 * 1024}
              value={files}
              aria-describedby="dev-files-hint"
              onChange={setFiles}
            />
          </FormField>
          <FormField id="dev-level" label="Уровень доступа">
            <Select
              id="dev-level"
              value={level}
              onChange={setLevel}
              options={[
                { value: "full", label: "Полный доступ" },
                { value: "read", label: "Только чтение" },
                { value: "hidden", label: "Скрыто" },
              ]}
            />
          </FormField>
        </div>
      </div>
    </Section>
  );
}

export function Component() {
  return (
    <div className="dev-page">
      <main className="dev-main">
        <PageHeader
          title="Витрина общих компонентов"
          subtitle="PLT-13 · только dev-сборка · данные вымышленные"
        />
        <Statuses />
        <Steps />
        <Blocks />
        <Panel />
        <Lists />
        <Formats />
        <States />
        <Fields />
      </main>
    </div>
  );
}
