import { redirect } from "next/navigation";

export default function MerchantApiKeysRedirect() {
  redirect("/portal/api-credentials?tab=keys");
}
