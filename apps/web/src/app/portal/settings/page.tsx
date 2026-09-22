import { redirect } from "next/navigation";

export default function PortalSettingsRedirect() {
  redirect("/dashboard/settings");
}
