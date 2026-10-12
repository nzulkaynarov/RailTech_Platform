import { afterEach, describe, expect, it } from "vitest";

import { DEFAULT_SOUND, SOUNDS, SOUND_IDS, readSound, writeSound } from "./alertSounds";
import { t } from "../i18n/ru";

describe("alert sounds", () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  it("defaults to a soft chime and remembers the choice", () => {
    expect(readSound()).toBe(DEFAULT_SOUND);
    writeSound("bell");
    expect(readSound()).toBe("bell");
  });

  it("ignores unknown stored values", () => {
    window.localStorage.setItem("crm.alertSound", "siren");
    expect(readSound()).toBe(DEFAULT_SOUND);
  });

  it.each(Object.entries(SOUNDS))("%s has a soft envelope and audible range", (_id, notes) => {
    for (const note of notes) {
      expect(note.peak).toBeLessThanOrEqual(1);
      expect(note.len).toBeGreaterThan(0.1);
      expect(note.hz).toBeGreaterThan(200);
      expect(note.hz).toBeLessThan(2500);
    }
  });

  it("every option has a Russian label", () => {
    for (const id of SOUND_IDS) expect(t.notify.sounds[id]).toBeTruthy();
  });
});
