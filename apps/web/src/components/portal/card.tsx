/** The panel every section on both portals sits in.
 *
 * `app-panel` carries the frosted treatment — translucent pale surface,
 * backdrop blur, hairline light border, 12px radius — defined once in
 * globals.css and scoped to the two shells. It is a class rather than
 * utilities because backdrop-filter and the solid fallback cannot be
 * expressed as Tailwind colour tokens.
 *
 * `bg-surface text-on-surface` stay for a card rendered outside either
 * shell (auth pages, the public site), where `app-panel` does not apply
 * and the original opaque treatment is still the right one.
 */
export function Card({
  children,
  className = "",
  padded = true,
  id,
}: {
  children: React.ReactNode;
  className?: string;
  padded?: boolean;
  id?: string;
}) {
  return (
    <section
      id={id}
      className={`app-panel min-w-0 bg-surface text-on-surface rounded-xl border border-surface-container-highest/60 shadow-ambient ${padded ? "p-6" : "overflow-hidden"} ${className}`}
    >
      {children}
    </section>
  );
}

export const thClass = "px-5 py-3 font-semibold";
export const tdClass = "px-5 py-3.5";
