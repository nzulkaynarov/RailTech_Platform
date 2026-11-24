import {
  Calendar,
  Landmark,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Ban,
  Bold,
  Check,
  ChevronDown,
  CircleAlert,
  Copy,
  Ellipsis,
  FileText,
  Italic,
  Link,
  List,
  ListOrdered,
  Package,
  Mail,
  Maximize2,
  Megaphone,
  Minimize2,
  Minus,
  Monitor,
  Pin,
  Plus,
  RefreshCw,
  Send,
  Settings,
  Star,
  Table,
  Type,
  Underline,
  Wrench,
  Users,
  Wallet,
  X,
  type LucideIcon,
  type LucideProps,
} from "lucide-react";
import type { ComponentType } from "react";

/**
 * Значки интерфейса — один набор, Lucide (стандарт интерфейса §5): 16 px, линия 1,75; декоративные (`aria-hidden`), имя
 * даёт кнопка. В модулях значки берутся отсюда, а не из `@ant-design/icons`. Значки каркаса (рельс, шапка) — `icons.tsx`.
 */
export type IconProps = Omit<LucideProps, "ref"> & { spin?: boolean };
export type IconComponent = ComponentType<IconProps>;

function make(Shape: LucideIcon, filled = false): IconComponent {
  return function Icon({ spin = false, className, ...props }: IconProps) {
    return (
      <Shape
        size={16}
        strokeWidth={1.75}
        aria-hidden="true"
        focusable={false}
        {...(filled ? { fill: "currentColor" } : {})}
        className={[spin ? "pf-icon-spin" : "", className ?? ""].join(" ").trim() || undefined}
        {...props}
      />
    );
  };
}

export const ArrowLeftIcon = make(ArrowLeft);
export const ArrowUpIcon = make(ArrowUp);
export const ArrowDownIcon = make(ArrowDown);
export const PinIcon = make(Pin);
export const PinFilledIcon = make(Pin, true);
export const WalletIcon = make(Wallet);
export const ListIcon = make(List);
export const UnderlineIcon = make(Underline);
export const UsersIcon = make(Users);
export const TableIcon = make(Table);
export const RefreshIcon = make(RefreshCw);
export const BanIcon = make(Ban);
export const StarIcon = make(Star);
export const StarFilledIcon = make(Star, true);
export const ShrinkIcon = make(Minimize2);
export const ExpandIcon = make(Maximize2);
export const GearIcon = make(Settings);
export const SendIcon = make(Send);
export const AddIcon = make(Plus);
export const RemoveIcon = make(Minus);
export const ListOrderedIcon = make(ListOrdered);
export const MegaphoneIcon = make(Megaphone);
export const MailIcon = make(Mail);
export const LinkIcon = make(Link);
export const ItalicIcon = make(Italic);
export const BoldIcon = make(Bold);
export const TextSizeIcon = make(Type);
export const FileTextIcon = make(FileText);
export const AlertIcon = make(CircleAlert);
export const ChevronDownIcon = make(ChevronDown);
export const MonitorIcon = make(Monitor);
export const CopyIcon = make(Copy);
export const CheckMarkIcon = make(Check);
export const MoreIcon = make(Ellipsis);
export const CalendarIcon = make(Calendar);
export const BankIcon = make(Landmark);
export const PackageIcon = make(Package);
export const WrenchIcon = make(Wrench);
export const CloseIcon = make(X);
