import { Check } from "lucide-react";

type FlowStepperProps = {
  steps: readonly string[];
  activeStep: number;
  onStepClick?: (step: number) => void;
  ariaLabel: string;
};

export function FlowStepper({ steps, activeStep, onStepClick, ariaLabel }: FlowStepperProps) {
  return (
    <nav className="flex flex-wrap items-center gap-y-2 py-2.5 text-sm leading-none" aria-label={ariaLabel}>
      {steps.map((label, index) => {
        const isActive = activeStep === index;
        const isDone = activeStep > index;
        const className = `inline-flex items-center gap-1.5 whitespace-nowrap transition-colors ${
          isActive
            ? "font-semibold text-text-primary"
            : isDone
              ? "text-text-secondary hover:text-text-primary"
              : "text-text-tertiary hover:text-text-secondary"
        }`;
        const content = (
          <>
            {isDone ? (
              <Check className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            ) : (
              <span className="inline-flex h-4 min-w-4 items-center justify-center text-xs tabular-nums">
                {index + 1}
              </span>
            )}
            <span>{label}</span>
          </>
        );

        return (
          <span className="inline-flex items-center whitespace-nowrap" key={label}>
            {index > 0 ? (
              <span className="mx-3 select-none text-text-tertiary/45 sm:mx-4" aria-hidden="true">
                →
              </span>
            ) : null}
            {onStepClick ? (
              <button type="button" onClick={() => onStepClick(index)} className={className}>
                {content}
              </button>
            ) : (
              <span className={className}>{content}</span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
