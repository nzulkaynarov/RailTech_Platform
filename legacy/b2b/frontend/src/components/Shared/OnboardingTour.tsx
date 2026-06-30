import { useState } from "react"
import { useTranslation } from "react-i18next"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  X,
  ChevronRight,
  ChevronLeft,
  Package,
  FileSpreadsheet,
  Calculator,
  BarChart3,
  Rocket,
} from "lucide-react"

interface OnboardingTourProps {
  open: boolean
  onClose: () => void
  onNavigate?: (page: string) => void
}

const stepIcons = [Package, FileSpreadsheet, Calculator, Rocket, BarChart3]

/** Tour steps map 1:1 to a page id the user is taught about.
 * Keeping this in the component (not i18n) because it's structural, not text. */
const stepTargets: (string | null)[] = [
  'products',        // step 0 — Catalog
  'sourcing-import', // step 1 — Excel import
  'crm-quotes',      // step 2 — Quotes builder
  'crm-deals',       // step 3 — Deals pipeline
  null,              // step 4 — (analytics page cut in Move 1; step shows its blurb, no nav)
]

export function OnboardingTour({ open, onClose, onNavigate }: OnboardingTourProps) {
  const { t } = useTranslation()
  const [currentStep, setCurrentStep] = useState(0)

  if (!open) return null

  const StepIcon = stepIcons[currentStep]
  const isLastStep = currentStep === stepIcons.length - 1
  const stepTarget = stepTargets[currentStep]

  function handleNext() {
    if (isLastStep) {
      setCurrentStep(0)
      onClose()
    } else {
      setCurrentStep((s) => s + 1)
    }
  }

  function handlePrev() {
    if (currentStep > 0) {
      setCurrentStep((s) => s - 1)
    }
  }

  function handleSkip() {
    setCurrentStep(0)
    onClose()
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-50 bg-black/20"
        onClick={handleSkip}
      />

      {/* Tour Card */}
      <Card
        className={cn(
          "fixed bottom-20 left-1/2 z-50 max-w-md w-full -translate-x-1/2",
          "shadow-lg"
        )}
      >
        <CardContent className="relative flex flex-col gap-4">
          {/* Close button */}
          <Button
            variant="ghost"
            size="icon-xs"
            className="absolute right-0 top-0"
            aria-label={t('tour.close')}
            onClick={handleSkip}
          >
            <X className="size-4" />
          </Button>

          {/* Icon + Content */}
          <div className="flex items-start gap-4 pr-6">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <StepIcon className="size-5" />
            </div>
            <div className="flex flex-col gap-1">
              <h3 className="text-sm font-semibold leading-tight">
                {t(`tour.steps.${currentStep}.title`)}
              </h3>
              <p className="text-sm text-muted-foreground">
                {t(`tour.steps.${currentStep}.description`)}
              </p>
            </div>
          </div>

          {/* Step counter */}
          <div className="text-xs text-muted-foreground">
            {currentStep + 1}/{stepIcons.length}
          </div>

          {/* Progress dots */}
          <div className="flex items-center justify-center gap-1.5">
            {stepIcons.map((_, i) => (
              <span
                key={i}
                className={cn(
                  "size-1.5 rounded-full transition-colors",
                  i === currentStep ? "bg-primary" : "bg-muted-foreground/30"
                )}
              />
            ))}
          </div>

          {/* Navigation buttons */}
          <div className="flex items-center justify-between">
            <Button variant="ghost" size="sm" onClick={handleSkip}>
              {t('tour.skip')}
            </Button>
            <div className="flex items-center gap-2">
              {stepTarget && onNavigate && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    onNavigate(stepTarget)
                    onClose()
                    setCurrentStep(0)
                  }}
                >
                  {t('tour.goTo')}
                </Button>
              )}
              {currentStep > 0 && (
                <Button variant="outline" size="sm" onClick={handlePrev}>
                  <ChevronLeft className="size-4" />
                  {t('tour.back')}
                </Button>
              )}
              <Button size="sm" onClick={handleNext}>
                {isLastStep ? t('tour.done') : t('tour.next')}
                {!isLastStep && <ChevronRight className="size-4" />}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </>
  )
}
