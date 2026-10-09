import { Icon } from "./icon";

export function EmptyState({
  icon,
  heading,
  body,
  actionLabel,
  onAction,
}: {
  icon: string;
  heading: string;
  body: string;
  /** Omit both of these for an empty state that only explains itself.
   * A button with nothing behind it is worse than no button: it invites
   * a click and then does nothing. */
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="flex flex-col items-center text-center py-10 px-4">
      <div className="w-16 h-16 rounded-full bg-primary-container/10 flex items-center justify-center mb-4">
        <Icon name={icon} className="text-[32px] text-primary" />
      </div>
      <h4 className="text-xl font-semibold text-on-background mb-1.5">{heading}</h4>
      <p className={`text-sm text-on-surface-variant max-w-sm ${onAction && actionLabel ? "mb-5" : ""}`}>
        {body}
      </p>
      {onAction && actionLabel ? (
        <button
          type="button"
          onClick={onAction}
          className="bg-primary-container text-on-primary text-sm font-medium py-3 px-6 rounded-lg hover:opacity-90 transition-opacity"
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}
