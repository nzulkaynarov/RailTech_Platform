import { describe, expect, it } from "vitest";

import { EMPTY_FORM } from "./formModel";
import { type AutoFilled, NO_AUTO, applyCompany, applyPerson } from "./recipientPick";

const person = {
  id: "41",
  name: "Демо Клиентов",
  position: "Инженер",
  email: "d@a.example",
  is_primary: true,
};
const a = { id: "7", name: "A", inn: "1", email: "office@a.example" };
const b = { id: "12", name: "B", inn: null, email: null };

describe("recipient pickers", () => {
  it("company B without email leaves nothing of company A or its person", () => {
    let auto: AutoFilled = { person: null, companyEmail: a.email };
    let v = { ...EMPTY_FORM, ...applyCompany(EMPTY_FORM, a, NO_AUTO) };
    v = { ...v, ...applyPerson(v, person, auto) };
    auto = { ...auto, person };
    expect(v.recipientEmail).toBe("d@a.example");
    v = { ...v, ...applyCompany(v, b, auto) };
    expect(v).toMatchObject({ recipientEmail: "", recipientAttention: "", recipientContactId: "" });
  });
  it("clearing the person returns the company email; typed text stays", () => {
    const auto: AutoFilled = { person, companyEmail: a.email };
    const v = {
      ...EMPTY_FORM,
      recipientCompanyId: "7",
      recipientContactId: "41",
      recipientEmail: "d@a.example",
      recipientAttention: "Инженер Демо Клиентов",
    };
    expect(applyPerson(v, null, auto)).toMatchObject({
      recipientEmail: "office@a.example",
      recipientAttention: "",
    });
    expect(
      applyPerson({ ...v, recipientAttention: "Начальнику" }, null, auto).recipientAttention,
    ).toBe("Начальнику");
  });
  it("an email from an incoming letter stays only while no company was chosen", () => {
    const reply = { ...EMPTY_FORM, recipientEmail: "from@inbound.example" };
    expect(applyCompany(reply, b, NO_AUTO).recipientEmail).toBe("from@inbound.example");
    const chosen = { ...reply, recipientCompanyId: "7" };
    expect(applyCompany(chosen, b, NO_AUTO).recipientEmail).toBe("");
    expect(applyCompany(chosen, null, NO_AUTO).recipientEmail).toBe("");
  });
});
