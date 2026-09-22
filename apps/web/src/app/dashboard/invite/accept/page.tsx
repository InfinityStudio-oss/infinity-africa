import { AuthSplitLayout } from "@/components/auth/auth-split-layout";
import { AcceptInviteForm } from "@/components/auth/accept-invite-form";

export const metadata = {
  title: "Accept Invitation | InfinityPay",
};

/**
 * Public — deliberately does not call requireCurrentUser(). A freshly
 * invited staff member has no password yet, so they can't be signed in
 * when they land here; Supabase Auth's invite link itself establishes a
 * short-lived session (read client-side from the URL by AcceptInviteForm)
 * that's only good for setting a password, not for using the rest of the
 * portal. See apps/api's create_my_merchant_user (redirect_to) and
 * accept_my_merchant_invite (the linkage step this form calls after the
 * password is set).
 */
export default function MerchantInviteAcceptPage() {
  return (
    <AuthSplitLayout>
      <h1 className="text-2xl font-bold text-on-surface">Set your password</h1>
      <p className="mt-2 text-sm text-on-surface-variant">
        Welcome to InfinityPay. Choose a password to finish setting up your account.
      </p>
      <AcceptInviteForm />
    </AuthSplitLayout>
  );
}
