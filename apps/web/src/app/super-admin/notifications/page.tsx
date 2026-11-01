import { permanentRedirect } from "next/navigation";

/**
 * Notifications has no landing page of its own — it is two tabs, and a
 * parent that showed a chooser would be a click between the sidebar and
 * the thing you came for.
 *
 * SMS is the default because it is the older surface and the one with
 * sending, cost and scheduling behind it; Email is a settings screen.
 */
export default function SuperAdminNotificationsIndex() {
  permanentRedirect("/super-admin/notifications/sms");
}
