import { redirect } from "next/navigation";

export default function PortalInvoicesRedirect() {
  redirect("/dashboard/invoices");
}
