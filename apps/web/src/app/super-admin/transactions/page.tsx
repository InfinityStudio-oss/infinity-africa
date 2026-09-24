import { PageHeader } from "@/components/portal/page-header";
import { ExportTransactionsCsvButton } from "@/components/super-admin/export-transactions-csv-button";
import { TransactionsFilters } from "@/components/super-admin/transactions-filters";
import { TransactionsTable } from "@/components/super-admin/transactions-table";
import { listAdminMerchants, listAdminTransactions } from "@/lib/admin/live-api";

export const metadata = {
  title: "Transactions | InfinityPay Super Admin",
};

interface SuperAdminTransactionsPageProps {
  searchParams: Promise<{
    merchant_id?: string;
    type?: string;
    status?: string;
    provider_reference?: string;
    transaction_id?: string;
    date_from?: string;
    date_to?: string;
  }>;
}

export default async function SuperAdminTransactionsPage({ searchParams }: SuperAdminTransactionsPageProps) {
  const filters = await searchParams;

  const [transactions, merchants] = await Promise.all([
    listAdminTransactions({
      merchantId: filters.merchant_id,
      type: filters.type,
      status: filters.status,
      providerReference: filters.provider_reference,
      transactionId: filters.transaction_id,
      dateFrom: filters.date_from,
      dateTo: filters.date_to,
    }),
    listAdminMerchants(),
  ]);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Transactions"
        description="The full platform ledger — every collection, withdrawal, fee, refund, and reversal across all businesses."
        action={<ExportTransactionsCsvButton transactions={transactions} />}
      />

      <TransactionsFilters
        merchants={merchants}
        initial={{
          merchantId: filters.merchant_id,
          type: filters.type,
          status: filters.status,
          providerReference: filters.provider_reference,
          transactionId: filters.transaction_id,
          dateFrom: filters.date_from,
          dateTo: filters.date_to,
        }}
      />

      <TransactionsTable transactions={transactions} />
    </div>
  );
}
