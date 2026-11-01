import { NotificationsTabs } from "@/components/super-admin/notifications-tabs";

/** Wraps both channels so the tab strip is identical on each and neither
 * page has to remember to render it. */
export default function NotificationsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-6">
      <NotificationsTabs />
      {children}
    </div>
  );
}
