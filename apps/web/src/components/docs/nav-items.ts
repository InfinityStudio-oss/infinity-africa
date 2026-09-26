export interface DocsNavItem {
  label: string;
  href: string;
}

export interface DocsNavGroup {
  label: string;
  items: DocsNavItem[];
}

export const DOCS_NAV: DocsNavGroup[] = [
  {
    label: "Getting Started",
    items: [
      { label: "REST API Overview", href: "/developers" },
      { label: "API Key Authentication", href: "/developers/authentication" },
      { label: "Merchant Onboarding Requirements", href: "/developers/onboarding-requirements" },
    ],
  },
  {
    label: "API Reference",
    items: [
      { label: "Collections API", href: "/developers/collections" },
      { label: "Dynamic QR API", href: "/developers/dynamic-qr" },
      { label: "Payment Links API", href: "/developers/payment-links" },
      { label: "Invoices API", href: "/developers/invoices" },
      { label: "Transaction Status API", href: "/developers/transaction-status" },
      { label: "Webhooks", href: "/developers/webhooks" },
    ],
  },
  {
    label: "Reference",
    items: [
      { label: "Error Codes", href: "/developers/errors" },
      { label: "Go-Live Checklist", href: "/developers/go-live-checklist" },
    ],
  },
  {
    label: "Examples",
    items: [
      { label: "Sandbox Examples", href: "/developers/sandbox" },
      { label: "cURL Examples", href: "/developers/curl-examples" },
      { label: "JavaScript Example", href: "/developers/javascript-example" },
      { label: "Python Example", href: "/developers/python-example" },
    ],
  },
];
