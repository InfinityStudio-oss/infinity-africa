import { AuthSplitLayout } from "@/components/auth/auth-split-layout";
import { LoginForm } from "@/components/auth/login-form";

export const metadata = {
  title: "Log In | InfinityPay",
};

export default function LoginPage() {
  return (
    <AuthSplitLayout>
      <h1 className="text-2xl font-bold text-on-surface">Log in</h1>
      <p className="mt-2 text-sm text-on-surface-variant">Sign in to your InfinityPay merchant account.</p>
      <LoginForm variant="public" />
    </AuthSplitLayout>
  );
}
