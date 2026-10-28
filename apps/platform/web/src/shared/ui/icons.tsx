import type { ReactNode } from "react";

/** Линейные иконки макета v3 (SPEC-v3 §5.1): 24×24, штрих 1.6. Декоративные — `aria-hidden`, имя даёт кнопка. */
function Icon({
  size = 22,
  stroke = 1.6,
  children,
}: {
  size?: number;
  stroke?: number;
  children: ReactNode;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export function DashboardIcon() {
  return (
    <Icon>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </Icon>
  );
}

export function CrmIcon() {
  return (
    <Icon>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" />
      <circle cx="17" cy="9" r="2.5" />
      <path d="M16 14.5c3 0 5.5 2.2 5.5 5.5" />
    </Icon>
  );
}

export function EdsIcon() {
  return (
    <Icon>
      <path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z" />
      <path d="M14 3v5h5M8.5 12.5h7M8.5 16h7" />
    </Icon>
  );
}

export function ErpIcon() {
  return (
    <Icon>
      <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" />
      <path d="M4 7.5l8 4.5 8-4.5M12 12v9" />
    </Icon>
  );
}

export function ChatsIcon() {
  return (
    <Icon>
      <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H9l-5 4z" />
    </Icon>
  );
}

export function AdminIcon() {
  return (
    <Icon>
      <path d="M12 3l7.5 3v6c0 4.5-3.2 7.8-7.5 9-4.3-1.2-7.5-4.5-7.5-9V6z" />
      <path d="M9 12l2 2 4-4" />
    </Icon>
  );
}

export function SearchIcon() {
  return (
    <Icon size={16} stroke={1.8}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4.5 4.5" />
    </Icon>
  );
}

export function BellIcon() {
  return (
    <Icon size={20}>
      <path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z" />
      <path d="M10 20a2 2 0 0 0 4 0" />
    </Icon>
  );
}

export function HelpIcon() {
  return (
    <Icon size={20}>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.6 9.4a2.5 2.5 0 0 1 4.8.9c0 1.6-2.4 2-2.4 3.5" />
      <path d="M12 17.2h.01" />
    </Icon>
  );
}

export function PanelIcon() {
  return (
    <Icon size={16} stroke={1.8}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M15 4v16" />
    </Icon>
  );
}

/** «‹‹» — свернуть подменю */
export function CollapseLeftIcon() {
  return (
    <Icon size={18}>
      <path d="M11 6l-6 6 6 6M19 6l-6 6 6 6" />
    </Icon>
  );
}

/** «››» — показать подменю */
export function ExpandRightIcon() {
  return (
    <Icon size={16} stroke={1.8}>
      <path d="M5 6l6 6-6 6M13 6l6 6-6 6" />
    </Icon>
  );
}

/** «›» — скрыть боковое окно */
export function ChevronRightIcon() {
  return (
    <Icon size={18}>
      <path d="M9 6l6 6-6 6" />
    </Icon>
  );
}

export function PlusIcon() {
  return (
    <Icon size={16} stroke={2}>
      <path d="M12 5v14M5 12h14" />
    </Icon>
  );
}

/** Галочка статуса «сделано»: 12 px в круге шкалы, 10 px в точке журнала. */
export function CheckIcon({ size = 12 }: { size?: number }) {
  return (
    <Icon size={size} stroke={2.5}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </Icon>
  );
}

export function CrossIcon({ size = 12 }: { size?: number }) {
  return (
    <Icon size={size} stroke={2.5}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Icon>
  );
}

export function MinusIcon({ size = 12 }: { size?: number }) {
  return (
    <Icon size={size} stroke={2.5}>
      <path d="M6 12h12" />
    </Icon>
  );
}

export function WarningIcon({ size = 18 }: { size?: number }) {
  return (
    <Icon size={size}>
      <path d="M12 4l9 16H3z" />
      <path d="M12 10v4.5M12 17.5v.01" />
    </Icon>
  );
}

/** Замок: системная роль — только чтение. */
export function LockIcon({ size = 14 }: { size?: number }) {
  return (
    <Icon size={size} stroke={2}>
      <rect x="5" y="11" width="14" height="9" rx="2" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </Icon>
  );
}
