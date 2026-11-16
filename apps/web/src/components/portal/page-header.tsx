/**
 * The heading block at the top of a portal or admin page.
 *
 * It renders directly on the app's slate-blue gradient, never inside a
 * card - all 52 call sites put it at the top of the page - so it takes
 * light ink. It previously used the card tokens (`on-background` for the
 * title, `on-surface-variant` for the description), which were correct
 * while the app was pale and became unreadable the moment the background
 * went dark: measured against the gradient, the title sat at 2.1:1 and
 * the description at **1.01:1**, which is invisible rather than merely
 * low-contrast.
 *
 * The replacements were measured over the whole sweep of the gradient,
 * not just its lightest end: white title 7.5 / 6.5 / 5.8:1, description
 * 5.9 / 5.2 / 4.6:1, all above the 4.5:1 minimum for body text.
 */
export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="flex flex-col md:flex-row md:items-end justify-between gap-4">
      <div className="min-w-0">
        <h2 className="text-3xl font-bold tracking-tight on-gradient">{title}</h2>
        <p className="text-lg on-gradient-muted mt-1">{description}</p>
      </div>
      {action}
    </header>
  );
}
