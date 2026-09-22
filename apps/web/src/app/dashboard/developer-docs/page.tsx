import { redirect } from "next/navigation";

export default function MerchantDeveloperDocsRedirect() {
  redirect("/portal/api-credentials?tab=docs");
}
