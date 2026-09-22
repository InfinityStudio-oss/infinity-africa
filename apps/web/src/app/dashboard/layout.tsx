// Metadata-only layout — every page under app/dashboard/* (login, register,
// forgot/reset-password, invite/accept, and every authenticated portal page)
// already enforces its own auth check inline (requireCurrentUser/requireUser
// + redirect) and renders its own shell, so this adds no UI, only the
// noindex directive every one of those pages should share. See robots.ts's
// disallow list for the matching crawler-level block.
export const metadata = {
  robots: { index: false, follow: false },
};

export default function MerchantLayout({ children }: { children: React.ReactNode }) {
  return children;
}
