import { describe, expect, it } from "vitest";

import type { LetterResolutionDraft } from "../../../shared/api/generated/model";
import {
  draftAsResolution,
  initialOffice,
  switchKind,
  toDraftBody,
  toOfficeBody,
  validateDraft,
  validateOffice,
} from "./officeModel";

const template = (kind: string) => `шаблон ${kind}`;
const person = (id: string) => ({ id, name: `Сотрудник ${id}`, initials: "СС" });
const draft = (patch: Partial<LetterResolutionDraft> = {}): LetterResolutionDraft => ({
  kind: "execute",
  responsible: person("7"),
  due: "2026-11-05",
  text: "Подготовить пояснения",
  co_executors: [person("8")],
  acquaint: [person("9")],
  drafted_by: person("3"),
  drafted_at: "2026-11-01T05:00:00Z",
  ...patch,
});

describe("резолюция делопроизводства: модель формы (P8b)", () => {
  it("без проекта: «К исполнению», шаблон текста, срок — подсказка EDS", () => {
    const values = initialOffice({ resolution_draft: null, suggested_due: "2026-11-11" }, template);
    expect(values).toMatchObject({
      kind: "execute",
      due: "2026-11-11",
      text: "шаблон execute",
      templated: true,
      responsibleId: "",
    });
  });

  it("с проектом: поля проекта, текст не шаблонный", () => {
    const values = initialOffice(
      { resolution_draft: draft(), suggested_due: "2026-11-11" },
      template,
    );
    expect(values).toMatchObject({
      kind: "execute",
      responsibleId: "7",
      due: "2026-11-05",
      text: "Подготовить пояснения",
      templated: false,
      coIds: ["8"],
      acquaintIds: ["9"],
    });
  });

  it("смена типа: шаблон меняется, пока текст не правили; «Для сведения» снимает исполнителя и срок", () => {
    const start = initialOffice({ resolution_draft: null, suggested_due: "2026-11-11" }, template);
    const reply = switchKind({ ...start, responsibleId: "7" }, "reply", template, "2026-11-11");
    expect(reply).toMatchObject({ text: "шаблон reply", responsibleId: "7", due: "2026-11-11" });
    const info = switchKind(reply, "info", template, "2026-11-11");
    expect(info).toMatchObject({ text: "шаблон info", responsibleId: "", due: "", coIds: [] });
    const edited = switchKind(
      { ...reply, text: "свой", templated: false },
      "execute",
      template,
      null,
    );
    expect(edited.text).toBe("свой");
  });

  it("проверка: ответственный и срок обязательны, кроме «Для сведения»; срок не в прошлом", () => {
    const base = initialOffice({ resolution_draft: null, suggested_due: null }, template);
    expect(validateOffice(base, "2026-11-01")).toEqual({
      responsible: "required",
      due: "required",
    });
    expect(
      validateOffice({ ...base, responsibleId: "7", due: "2026-10-31" }, "2026-11-01"),
    ).toEqual({ due: "past" });
    expect(validateOffice({ ...base, kind: "info" }, "2026-11-01")).toEqual({});
    expect(validateDraft({ ...base, due: "2026-10-31" }, "2026-11-01")).toEqual({ due: "past" });
    expect(validateDraft(base, "2026-11-01")).toEqual({});
  });

  it("тело резолюции: у «Для сведения» нет исполнителя и срока; ответственный не дублируется в соисполнителях", () => {
    const values = initialOffice({ resolution_draft: draft(), suggested_due: null }, template);
    expect(toOfficeBody({ ...values, coIds: ["7", "8", "8"] })).toEqual({
      kind: "execute",
      text: "Подготовить пояснения",
      responsible_id: "7",
      due: "2026-11-05",
      co_executor_ids: ["8"],
      acquaint_ids: ["9"],
    });
    expect(toOfficeBody({ ...values, kind: "info" })).toMatchObject({
      kind: "info",
      responsible_id: null,
      due: null,
      co_executor_ids: [],
    });
    expect(toDraftBody({ ...values, kind: "", text: " " })).toMatchObject({
      kind: null,
      text: null,
    });
  });

  it("«Утвердить проект» — только полный проект: без ответственного или в прошлом — нельзя", () => {
    expect(draftAsResolution({ resolution_draft: draft() }, "2026-11-01")).toMatchObject({
      responsible_id: "7",
    });
    expect(
      draftAsResolution({ resolution_draft: draft({ responsible: null }) }, "2026-11-01"),
    ).toBeNull();
    expect(draftAsResolution({ resolution_draft: draft() }, "2026-11-06")).toBeNull();
    expect(
      draftAsResolution(
        { resolution_draft: draft({ kind: "info", responsible: null, due: null }) },
        "2026-11-06",
      ),
    ).toMatchObject({ kind: "info" });
    expect(draftAsResolution({ resolution_draft: null }, "2026-11-01")).toBeNull();
  });
});
