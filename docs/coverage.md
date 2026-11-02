# Coverage: what finerd points can really read, per source

Updated with every release. «Tested» means used on real data or a probe on that date;
«guide only» means a connector guide exists but nobody has run it yet.

| Source | What it gives | State |
|---|---|---|
| finerd (official MCP) | Card transactions (statement credits, annual fees, coverage by oldest transaction), verified program balances with dates, free-night counts where finerd tracks them | Tested 2026-11-02 on 7 cards and 12 programs |
| CSV export from any bank or finance app | Card transactions | Tested 2026-11-02 (synthetic export, headless Claude Code run) |
| Monarch (official MCP) | Card transactions | Guide only |
| Copilot Money (official MCP, read-only) | Card transactions | Guide only |
| Google Calendar | Private deadline events: create, update, read back, «✓» and reminder removal | Probe passed on Claude Code 2026-11-02; Claude chat and ChatGPT pending |
| Google Sheets | Ledger storage | Not probed yet; the ledger file is the storage on every platform until it is |
| The person | Balances, cards, open dates, credits banks never show (app wallets, hotel folios), redemptions | Works everywhere |
| Program websites | History and balances | Not in the main package; the separate program-adapters package is not released yet |

## Card credits the bank cannot show

Credits that live inside a merchant app or on a hotel bill never appear as bank transactions
(for example Uber Cash, hotel collection credits, IHG food-and-beverage vouchers). finerd points
asks the person about them and records the answer with its source.

## Platforms

| Platform | Skills | Scripts | Ledger storage | Calendar |
|---|---|---|---|---|
| Claude Code | Tested | Tested | Folder (tested) | Tested |
| Claude app / claude.ai | Pending probe | Pending probe | File (expected) | Pending probe |
| ChatGPT | Pending probe | Pending probe | File (expected) | Pending probe |
