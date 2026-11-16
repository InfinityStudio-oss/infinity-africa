/** The rounded white card every section on the portal sits in. */
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
      className={`min-w-0 bg-surface rounded-xl border border-surface-container-highest/60 shadow-ambient ${padded ? "p-6" : "overflow-hidden"} ${className}`}
    >
      {children}
    </section>
  );
}

export const thClass = "px-5 py-3 font-semibold";
export const tdClass = "px-5 py-3.5";
