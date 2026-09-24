/** A Material Symbols Outlined glyph — see the stylesheet link in
 * app/layout.tsx. `filled` switches the icon to its solid variant (used for
 * the active sidebar item, matching the Stitch reference).
 *
 * The glyph is a font ligature, so the span's text content is the icon's
 * name. Two consequences are handled here and in app/layout.tsx:
 *
 * 1. Until the icon font loads, that name renders as readable words
 *    ("smartphone", "qr_code_scanner"). The .icons-pending guard set before
 *    first paint hides it; see globals.css.
 * 2. Screen readers would otherwise announce the raw name. Every icon here
 *    is decorative — icon-only buttons carry their own aria-label — so the
 *    span is aria-hidden by default. Pass `label` for the rare icon that
 *    genuinely carries meaning on its own.
 */
export function Icon({
  name,
  className = "",
  filled = false,
  label,
}: {
  name: string;
  className?: string;
  filled?: boolean;
  label?: string;
}) {
  return (
    <span
      className={`material-symbols-outlined ${className}`}
      style={filled ? { fontVariationSettings: "'FILL' 1" } : undefined}
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
    >
      {name}
    </span>
  );
}
