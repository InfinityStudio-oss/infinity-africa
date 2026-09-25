// Deliberately OUTSIDE /super-admin. That tree's layout redirects an
// unverified admin here, so hosting these pages inside it would be an
// infinite redirect. Nothing from the Super Admin console renders until a
// second factor has been presented.
export const metadata = {
  title: "Two-factor authentication | InfinityPay",
  robots: { index: false, follow: false },
};

export default function AdminMfaLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-md rounded-2xl bg-surface p-6 shadow-lg sm:p-8">{children}</div>
    </div>
  );
}
