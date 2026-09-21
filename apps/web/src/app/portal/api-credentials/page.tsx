import { Suspense } from "react";

import { ApiCredentialsTabs } from "@/components/merchant/api-credentials-tabs";

export const metadata = {
  title: "API Credentials | InfinityPay",
};

export default function ApiCredentialsPage() {
  return (
    <Suspense fallback={null}>
      <ApiCredentialsTabs />
    </Suspense>
  );
}
