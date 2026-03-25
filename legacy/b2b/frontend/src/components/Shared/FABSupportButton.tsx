import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { MessageSquare, Phone, Send, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function FABSupportButton() {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const speedDialOptions = [
    {
      labelKey: "fab.telegram",
      icon: Send,
      action: () => window.open("https://t.me/railtech_support", "_blank"),
    },
    {
      labelKey: "fab.call",
      sublabel: "+998 71 200-00-00",
      icon: Phone,
      action: () => window.open("tel:+998712000000"),
    },
    {
      labelKey: "fab.writeManager",
      icon: MessageSquare,
      action: () => window.open("mailto:support@railtech.uz"),
    },
  ];

  const handleClickOutside = useCallback(
    (event: MouseEvent) => {
      if (
        isOpen &&
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    },
    [isOpen]
  );

  useEffect(() => {
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [handleClickOutside]);

  return (
    <TooltipProvider>
      <div ref={containerRef} className="fixed bottom-6 right-6 z-50 flex flex-col items-end gap-3">
        {/* Speed Dial Options */}
        <div className="flex flex-col items-end gap-2">
          {speedDialOptions.map((option, index) => {
            const label = t(option.labelKey);
            return (
              <div
                key={option.labelKey}
                className={cn(
                  "flex items-center gap-2 transition-all duration-300",
                  isOpen
                    ? "translate-y-0 opacity-100"
                    : "pointer-events-none translate-y-4 opacity-0"
                )}
                style={{
                  '--fab-delay': isOpen
                    ? `${(speedDialOptions.length - 1 - index) * 75}ms`
                    : '0ms',
                  transitionDelay: 'var(--fab-delay)',
                } as React.CSSProperties}
              >
                {/* Tooltip label */}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="default"
                      size="icon"
                      className="h-10 w-10 shrink-0 rounded-full shadow-lg transition-transform hover:scale-110"
                      aria-label={label}
                      onClick={() => {
                        option.action();
                        setIsOpen(false);
                      }}
                    >
                      <option.icon className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="left">
                    {label}
                    {option.sublabel && (
                      <span className="ml-1 text-xs opacity-70">
                        {option.sublabel}
                      </span>
                    )}
                  </TooltipContent>
                </Tooltip>
              </div>
            );
          })}
        </div>

        {/* Main FAB */}
        <Button
          variant="default"
          size="icon"
          className="h-14 w-14 rounded-full shadow-lg transition-transform hover:scale-105"
          aria-label={t('fab.support')}
          onClick={() => setIsOpen((prev) => !prev)}
        >
          <div
            className={cn(
              "transition-transform duration-300",
              isOpen ? "rotate-90" : "rotate-0"
            )}
          >
            {isOpen ? <X className="h-6 w-6" /> : <MessageSquare className="h-6 w-6" />}
          </div>
        </Button>
      </div>
    </TooltipProvider>
  );
}
