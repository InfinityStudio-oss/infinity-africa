import { DocsShell } from "@/components/docs/docs-shell";

export const metadata = {
  title: {
    template: "%s | InfinityPay Developer Docs",
    default: "InfinityPay Developer Docs",
  },
  description: "REST API reference and integration guides for the InfinityPay payments platform.",
};

export default function DevelopersLayout({ children }: { children: React.ReactNode }) {
  return <DocsShell>{children}</DocsShell>;
}
