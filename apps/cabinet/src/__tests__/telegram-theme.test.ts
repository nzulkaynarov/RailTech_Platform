import { contrastRatio } from '@/lib/contrast';
import { applyTelegramTheme, cabinetPalette, paletteProblems, telegramPalette } from '@/telegram/theme';
import type { TelegramThemeParams, TelegramWebApp } from '@/telegram/webapp';

/** Стандартные темы Telegram (Telegram Desktop / iOS по умолчанию) — те же, что в e2e `screens-mock`. */
const TELEGRAM_LIGHT: TelegramThemeParams = {
  bg_color: '#ffffff',
  secondary_bg_color: '#efeff3',
  section_bg_color: '#ffffff',
  text_color: '#000000',
  hint_color: '#707579',
  button_color: '#2481cc',
  button_text_color: '#ffffff',
  accent_text_color: '#2481cc',
  section_separator_color: '#e7e7e7',
  destructive_text_color: '#e53935',
};
const TELEGRAM_DARK: TelegramThemeParams = {
  bg_color: '#17212b',
  secondary_bg_color: '#232e3c',
  section_bg_color: '#17212b',
  text_color: '#f5f5f5',
  hint_color: '#708499',
  button_color: '#5288c1',
  button_text_color: '#ffffff',
  accent_text_color: '#6ab2f2',
  section_separator_color: '#111921',
  destructive_text_color: '#ec3942',
};

describe('тема Telegram в Mini App — только пары, проходящие AA (CAB-FIX-3)', () => {
  it('формула контраста совпадает с packages/ui-tokens', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 2);
    expect(contrastRatio('#ffffff', '#2481cc')).toBeCloseTo(4.13, 1);
  });

  it('наши палитры (светлая и тёмная) сами проходят все пары', () => {
    expect(paletteProblems(cabinetPalette('light'))).toEqual([]);
    expect(paletteProblems(cabinetPalette('dark'))).toEqual([]);
    expect(cabinetPalette('light')['--primary']).toBe('#1f2e4a');
    expect(cabinetPalette('dark')['--primary']).toBe('#82aaff');
  });

  it.each([
    ['светлая', TELEGRAM_LIGHT, 'light'],
    ['тёмная', TELEGRAM_DARK, 'dark'],
  ] as const)('стандартная %s: итоговая палитра без нарушений, кнопка Telegram с белым текстом не берётся', (_, params, scheme) => {
    const result = telegramPalette(params, scheme);
    expect(paletteProblems(result.palette)).toEqual([]);
    // белый на button_color — 4,1:1 (светлая) и 3,6:1 (тёмная): основной цвет остаётся нашим
    expect(result.rejected).toContain('button_color');
    expect(result.palette['--primary']).toBe(cabinetPalette(scheme)['--primary']);
    // фон и текст Telegram ложатся: Mini App выглядит как Telegram
    expect(result.applied['--background']).toBe(params.bg_color);
    expect(result.applied['--foreground']).toBe(params.text_color);
  });

  it('подпись hint_color ниже 4.5:1 на рамке — остаётся наша', () => {
    const light = telegramPalette(TELEGRAM_LIGHT, 'light');
    expect(contrastRatio(TELEGRAM_LIGHT.hint_color as string, TELEGRAM_LIGHT.secondary_bg_color as string)).toBeLessThan(4.5);
    expect(light.rejected).toContain('hint_color');
    expect(light.palette['--muted-foreground']).toBe(cabinetPalette('light')['--muted-foreground']);
  });

  it('тема, проходящая AA, берётся целиком, включая кнопку', () => {
    const result = telegramPalette(
      { ...TELEGRAM_LIGHT, secondary_bg_color: '#f6f6f8', button_color: '#1a5c96', hint_color: '#5c6166', accent_text_color: '#1a5c96', destructive_text_color: '#b3261e' },
      'light',
    );
    expect(result.rejected).toEqual([]);
    expect(result.applied['--primary']).toBe('#1a5c96');
    expect(result.applied['--primary-foreground']).toBe('#ffffff');
    expect(paletteProblems(result.palette)).toEqual([]);
  });

  it('битое значение и неизвестный формат пропускаются, #rgb разворачивается', () => {
    const result = telegramPalette({ bg_color: 'red', text_color: '#000' }, 'light');
    expect(result.applied['--background']).toBeUndefined();
    expect(result.applied['--foreground']).toBe('#000000');
  });

  it('applyTelegramTheme: принятые цвета — на <html>, отклонённые — не записываются; смена темы снимает прежние', () => {
    const root = document.createElement('div');
    const webApp = { colorScheme: 'dark', themeParams: TELEGRAM_DARK } as TelegramWebApp;
    applyTelegramTheme(webApp, root);
    expect(root.style.getPropertyValue('--background')).toBe('#17212b');
    expect(root.style.getPropertyValue('--muted')).toBe('#232e3c');
    expect(root.style.getPropertyValue('--primary')).toBe('');
    expect(root.style.getPropertyValue('--primary-foreground')).toBe('');
    expect(root).toHaveClass('dark');

    applyTelegramTheme({ colorScheme: 'light', themeParams: { text_color: '#000000' } } as TelegramWebApp, root);
    expect(root.style.getPropertyValue('--background')).toBe('');
    expect(root.style.getPropertyValue('--foreground')).toBe('#000000');
    expect(root).not.toHaveClass('dark');
  });
});
