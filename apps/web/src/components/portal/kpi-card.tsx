import { Icon } from "./icon";

/** "brand" renders on the app's dark green primary color instead of the
 * default surface card — opt-in only, so every existing KpiCard usage
 * elsewhere keeps its current look. */
export function KpiCard({
  icon,
  iconClassName = "text-primary",
  label,
  value,
  caption,
  captionClassName = "text-outline",
  trendIcon,
  variant = "default",
}: {
  icon: string;
  iconClassName?: string;
  label: string;
  value: string;
  caption?: string;
  captionClassName?: string;
  trendIcon?: string;
  variant?: "default" | "brand";
}) {
  if (variant === "brand") {
    return (
      <div className="min-w-0 bg-primary rounded-xl p-4 shadow-ambient">
        <div className="flex items-center gap-2 text-on-primary/80 mb-2">
          <Icon name={icon} className="text-[18px] text-on-primary" />
          <span className="text-sm font-medium">{label}</span>
        </div>
        <div className="text-lg sm:text-2xl font-semibold text-on-primary break-words">{value}</div>
        {caption && (
          <div className="text-xs mt-1 font-medium flex items-center gap-1 text-on-primary/70">
            {trendIcon && <Icon name={trendIcon} className="text-[14px]" />}
            {caption}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="min-w-0 bg-surface text-on-surface rounded-xl p-4 border border-surface-container-highest/60 shadow-ambient">
      <div className="flex items-center gap-2 text-on-surface-variant mb-2">
        <Icon name={icon} className={`text-[18px] ${iconClassName}`} />
        <span className="text-sm font-medium">{label}</span>
      </div>
      <div className="text-lg sm:text-2xl font-semibold text-on-background break-words">{value}</div>
      {caption && (
        <div className={`text-xs mt-1 font-medium flex items-center gap-1 ${captionClassName}`}>
          {trendIcon && <Icon name={trendIcon} className="text-[14px]" />}
          {caption}
        </div>
      )}
    </div>
  );
}
