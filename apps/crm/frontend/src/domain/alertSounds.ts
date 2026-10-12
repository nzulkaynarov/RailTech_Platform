/**
 * Звуки уведомлений о сообщении лида (бенчмарк Slack/Intercom: выбор звука в профиле).
 * Синтез Web Audio: без файлов-ресурсов, мягкая огибающая (атака 10 мс, затухание) вместо
 * «писка» прямоугольного сигнала. Выбор хранится в localStorage этого браузера.
 */

export type SoundId = "chime" | "bell" | "drop" | "marimba" | "none";

type Note = {
  /** Частота, Гц; `glideTo` — плавный переход частоты к концу ноты. */
  hz: number;
  glideTo?: number;
  /** Начало от момента воспроизведения и длительность, с. */
  at: number;
  len: number;
  wave: OscillatorType;
  /** Пиковая громкость 0…1 (до общего множителя `VOLUME`). */
  peak: number;
};

export const SOUNDS: Record<Exclude<SoundId, "none">, Note[]> = {
  // Двухнотный «дин-дон» (ми → ля): нейтральный, как в мессенджерах.
  chime: [
    { hz: 659.25, at: 0, len: 0.5, wave: "triangle", peak: 0.9 },
    { hz: 880, at: 0.12, len: 0.7, wave: "triangle", peak: 0.8 },
  ],
  // Колокольчик: основной тон и обертон, долгое затухание.
  bell: [
    { hz: 1046.5, at: 0, len: 1.1, wave: "sine", peak: 0.8 },
    { hz: 2093, at: 0, len: 0.6, wave: "sine", peak: 0.25 },
  ],
  // Капля: короткий восходящий тон.
  drop: [{ hz: 520, glideTo: 980, at: 0, len: 0.18, wave: "sine", peak: 1 }],
  // Маримба: два коротких деревянных удара (до → соль).
  marimba: [
    { hz: 523.25, at: 0, len: 0.25, wave: "sine", peak: 1 },
    { hz: 783.99, at: 0.1, len: 0.3, wave: "sine", peak: 0.9 },
  ],
};

export const SOUND_IDS: SoundId[] = ["chime", "bell", "drop", "marimba", "none"];
export const DEFAULT_SOUND: SoundId = "chime";
const VOLUME = 0.18;
const PREF_KEY = "crm.alertSound";

export function readSound(): SoundId {
  try {
    const value = window.localStorage.getItem(PREF_KEY);
    return SOUND_IDS.includes(value as SoundId) ? (value as SoundId) : DEFAULT_SOUND;
  } catch {
    return DEFAULT_SOUND;
  }
}

export function writeSound(id: SoundId): void {
  try {
    window.localStorage.setItem(PREF_KEY, id);
  } catch {
    // приватный режим — выбор просто не запомнится
  }
}

/** Сыграть звук; «Без звука» и отсутствие Web Audio — молча ничего. */
export function playSound(id: SoundId): void {
  if (id === "none") return;
  try {
    const ctx = new window.AudioContext();
    const start = ctx.currentTime;
    let end = 0;
    for (const note of SOUNDS[id]) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const t0 = start + note.at;
      const t1 = t0 + note.len;
      osc.type = note.wave;
      osc.frequency.setValueAtTime(note.hz, t0);
      if (note.glideTo) osc.frequency.exponentialRampToValueAtTime(note.glideTo, t1);
      gain.gain.setValueAtTime(0.0001, t0);
      gain.gain.exponentialRampToValueAtTime(note.peak * VOLUME, t0 + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, t1);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t0);
      osc.stop(t1 + 0.02);
      end = Math.max(end, note.at + note.len);
    }
    window.setTimeout(() => void ctx.close(), (end + 0.2) * 1000);
  } catch {
    // нет Web Audio или браузер не дал играть без жеста — пропускаем
  }
}
