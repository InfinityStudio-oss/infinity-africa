import { Icon } from "@/components/portal/icon";

/** Super admin KPI cards put the icon in a top-right box (vs. the merchant
 * portal's icon-left row) and support a tinted "warning" variant for
 * platform-health metrics like Failed Transactions. `variant="brand"` is
 * opt-in (default unchanged, so /admin/* pages keep their current look
 * unless a page explicitly asks for it) — `tone="warning"` still takes
 * priority over it, so a genuinely alarming number (e.g. open high-risk
 * alerts > 0) keeps its yellow warning treatment instead of being hidden
 * under brand green.
 *
 * The icon is bare, not in a tinted rounded box. The box was a pale
 * square - white at 10% on the navy card, deep blue at 10% on the pale
 * one - and at this size it read as a sticker pasted onto the card
 * rather than part of it. The merchant portal's KpiCard has never had
 * one; this is the Super Admin card catching up, and it keeps the
 * top-right placement that distinguishes the two. The icon is also
 * muted, because on a KPI card the figure is the content and the icon
 * is a label for it. */
export function AdminKpiCard({
  icon,
  label,
  value,
  caption,
  captionClassName = "text-on-surface-variant",
  trendIcon,
  tone = "default",
  variant = "default",
}: {
  icon: string;
  label: string;
  value: string;
  caption?: string;
  captionClassName?: string;
  trendIcon?: string;
  tone?: "default" | "warning";
  variant?: "default" | "brand";
}) {
  if (tone === "warning") {
    return (
      <div className="bg-[#FEFCE8] border border-[#FEF08A] rounded-lg p-4 shadow-ambient flex flex-col justify-between relative overflow-hidden">
        <div className="absolute right-0 top-0 w-16 h-16 bg-[#FEF08A]/30 rounded-bl-full" />
        <div className="flex justify-between items-start mb-2.5 relative">
          <span className="text-[11px] font-semibold text-[#854D0E] uppercase tracking-wider">{label}</span>
          <Icon name={icon} className="text-[20px] text-[#854D0E]/70 shrink-0" />
        </div>
        <div className="relative">
          <div className="text-xl font-bold text-[#854D0E]">{value}</div>
          {caption && <div className="text-[11px] text-[#A16207] mt-0.5">{caption}</div>}
        </div>
      </div>
    );
  }

  if (variant === "brand") {
    return (
      <div className="bg-primary rounded-lg p-4 shadow-ambient flex flex-col justify-between">
        <div className="flex justify-between items-start mb-2.5">
          <span className="text-[11px] font-semibold text-on-primary/70 uppercase tracking-wider">{label}</span>
          <Icon name={icon} className="text-[20px] text-on-primary/55 shrink-0" />
        </div>
        <div>
          <div className="text-xl font-bold text-on-primary">{value}</div>
          {caption && (
            <div className="text-[11px] mt-0.5 flex items-center gap-1 text-on-primary/70">
              {trendIcon && <Icon name={trendIcon} className="text-[12px]" />}
              {caption}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="app-panel bg-surface rounded-lg p-4 border border-surface-container-highest/60 shadow-ambient flex flex-col justify-between hover:-translate-y-1 transition-transform duration-200">
      <div className="flex justify-between items-start mb-2.5">
        <span className="text-[11px] font-semibold text-on-surface-variant uppercase tracking-wider">{label}</span>
        <Icon name={icon} className="text-[20px] text-primary/55 shrink-0" />
      </div>
      <div>
        <div className="text-xl font-bold text-on-surface">{value}</div>
        {caption && (
          <div className={`text-[11px] mt-0.5 flex items-center gap-1 ${captionClassName}`}>
            {trendIcon && <Icon name={trendIcon} className="text-[12px]" />}
            {caption}
          </div>
        )}
      </div>
    </div>
  );
}
