import { permanentRedirect } from "next/navigation";

/**
 * The SMS workspace moved under Notifications on 2026-11-01, when email
 * notification settings became a Super Admin control and two sibling
 * top-level entries for the same job stopped making sense.
 *
 * This route stays because the old one is in browser histories, in
 * bookmarks and in links people have sent each other, and breaking those
 * buys nothing. A permanent redirect rather than a page, so the address
 * bar ends up on the real URL instead of leaving two live paths for the
 * same screen.
 */
export default function SuperAdminSmsRedirect() {
  permanentRedirect("/super-admin/notifications/sms");
}
