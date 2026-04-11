import * as React from "react"
import { CheckIcon, type LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

interface SelectableCardProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onSelect"> {
  icon: LucideIcon
  label: string
  description?: string
  selected?: boolean
}

const SelectableCard = React.forwardRef<HTMLButtonElement, SelectableCardProps>(
  (
    { icon: Icon, label, description, selected = false, className, ...props },
    ref,
  ) => (
    <button
      ref={ref}
      type="button"
      data-slot="selectable-card"
      data-selected={selected ? "true" : "false"}
      aria-pressed={selected}
      className={cn(
        "relative flex flex-col items-center rounded-lg border-2 p-4 text-center outline-none transition-all",
        "focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "border-primary bg-primary/5"
          : "border-border hover:border-muted-foreground/30",
        className,
      )}
      {...props}
    >
      {selected && (
        <div className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <CheckIcon className="h-3 w-3" />
        </div>
      )}
      <div
        className={cn(
          "flex h-10 w-10 items-center justify-center rounded-lg",
          selected
            ? "bg-primary/10 text-primary"
            : "bg-muted text-muted-foreground",
        )}
      >
        <Icon className="h-5 w-5" />
      </div>
      <h3 className="mt-2 text-sm font-semibold text-foreground">{label}</h3>
      {description && (
        <p className="mt-1 text-xs text-muted-foreground leading-snug">
          {description}
        </p>
      )}
    </button>
  ),
)
SelectableCard.displayName = "SelectableCard"

export { SelectableCard }
