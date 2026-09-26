import Link from "next/link";

import { Card } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";

const DOC_LINKS = [
  { label: "REST API Overview", href: "/developers", icon: "api", description: "Base URL, auth, and response envelope." },
  { label: "API Key Authentication", href: "/developers/authentication", icon: "vpn_key", description: "Sandbox vs. live keys and request signing." },
  { label: "Collections API", href: "/developers/collections", icon: "payments", description: "Infinity Payment Page, Mobile Money Push, Selcom Pesa, and Scan QR / TanQR." },
  { label: "Dynamic QR API", href: "/developers/dynamic-qr", icon: "qr_code", description: "Generate a scannable QR code — no phone number required." },
  { label: "Payment Links API", href: "/developers/payment-links", icon: "link", description: "Create, fetch, and expire payment links." },
  { label: "Invoices API", href: "/developers/invoices", icon: "description", description: "Create invoices and track payment status." },
  { label: "Transaction Status API", href: "/developers/transaction-status", icon: "search", description: "Look up any transaction by reference." },
  { label: "Webhooks", href: "/developers/webhooks", icon: "webhook", description: "Event types, status lifecycle, payloads, and signature verification." },
  { label: "Error Codes", href: "/developers/errors", icon: "error", description: "Full reference of API error codes." },
  { label: "Go-Live Checklist", href: "/developers/go-live-checklist", icon: "checklist", description: "What to confirm before sending real customer traffic." },
  { label: "Sandbox Examples", href: "/developers/sandbox", icon: "science", description: "Test credentials and canned sandbox responses." },
  { label: "cURL Examples", href: "/developers/curl-examples", icon: "terminal", description: "Copy-paste cURL requests for every endpoint." },
  { label: "JavaScript Example", href: "/developers/javascript-example", icon: "code", description: "Node.js integration walkthrough." },
  { label: "Python Example", href: "/developers/python-example", icon: "code", description: "Python integration walkthrough." },
];

export function DeveloperDocsView() {
  return (
    <div className="space-y-8">
      <PageHeader title="Developer Docs" description="Everything you need to integrate the InfinityPay API into your app." />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
        {DOC_LINKS.map((doc) => (
          <Link key={doc.href} href={doc.href}>
            <Card className="h-full hover:border-primary transition-colors">
              <div className="w-10 h-10 rounded-lg bg-primary-container/10 text-primary flex items-center justify-center mb-4">
                <Icon name={doc.icon} className="text-[22px]" />
              </div>
              <h3 className="font-semibold text-on-background mb-1">{doc.label}</h3>
              <p className="text-sm text-on-surface-variant">{doc.description}</p>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
