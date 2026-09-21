# @infinity/shared

Shared TypeScript constants and enums used across InfinityPay frontend
surfaces (`apps/web`): collection methods, disbursement methods, transaction
statuses, invoice statuses, payment link statuses, and webhook event names.
Values mirror the CHECK constraints in `supabase/migrations`.

Consumed as a workspace package:

```ts
import { CollectionMethod, TransactionStatus } from "@infinity/shared";
```

## Note on the backend

`apps/api` is Python, so it cannot import this package directly. Its
equivalent enums live in `apps/api/app/schemas/enums.py` and must be kept in
sync with this package by hand until a codegen step is introduced.
