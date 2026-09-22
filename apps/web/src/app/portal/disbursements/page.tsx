import { redirect } from "next/navigation";

export default function PortalDisbursementsRedirect() {
  redirect("/dashboard/withdrawals");
}
