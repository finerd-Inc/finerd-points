# Program and bank email senders

A sender domain covers its subdomains. This list is reviewed: a change needs a code owner. No shared or consumer mail domains (gmail.com,
outlook.com and the like), no wildcards beyond a program's own subdomains.

It is used in two ways, both only with the person's own mailbox:

**1. Finding which programs the person has (at setup, `points` skill).** Only after the person says
whose accounts belong in the ledger and confirms the mailbox is their own (another person's
programs only with that person's agreement). Search only by these sender domains and a date range
(default: the last 24 months). Use only the sender address of each result to suggest «possible
programs»; never open a message, an attachment or a link, and never search by free text. A sender
match proves nothing (senders can be forged, and marketing mail comes to people who are not
members): show the suggestions as candidates and record a program only when the person confirms it
and that it is theirs. If the mail connector returns message text (subjects or snippets count) for
a sender-and-date search, or the mailbox is shared with someone not covered by the ledger, do not
run the search: say so, and let the person list their programs instead.

With the Gmail connector: call `search_threads` with `view: "THREAD_VIEW_METADATA_ONLY"` (it returns
sender, recipients and date, no subject and no snippet — checked 16 November 2026) and a query of only
sender domains and a date, for example `from:(hyatt.com OR marriott.com OR aa.com) after:2024/11/16`;
page through `pageToken`. From each message take only the domain of the sender, and only when the
sender is not the person; ignore display names and recipients; never call `get_thread` or open a
message. If the connector offers no such view, do not search.

**2. Reading a program email the person asks you to read** (`balances`, `expirations`): only these
fields — program, member nickname (never the member number), balance with its date, expiry date and
rule, certificate type and expiry, status tier and progress, redemption points, fees and route or
property. Never read other mail. Never fetch a one-time code from email.

| Program family | Sender domains |
|---|---|
| American Express | americanexpress.com, aexp.com |
| Chase | chase.com |
| Bank of America | bankofamerica.com, ealerts.bankofamerica.com |
| Bilt | biltrewards.com, bilt.com |
| Citi | citi.com |
| Capital One | capitalone.com |
| World of Hyatt | hyatt.com |
| Hilton Honors | hilton.com, h1.hilton.com |
| IHG One Rewards | ihg.com, mc.ihg.com |
| Marriott Bonvoy | marriott.com, email-marriott.com |
| Accor ALL | accor.com, all.accor.com |
| Atmos Rewards / Alaska | alaskaair.com, atmosrewards.com |
| American AAdvantage | aa.com, info.email.aa.com |
| Delta SkyMiles | delta.com, t.delta.com |
| United MileagePlus | united.com |
| Air Canada Aeroplan | aircanada.com, aeroplan.com |
| Flying Blue | flyingblue.com, airfrance.fr, klm.com |
| Qatar Airways Privilege Club | qatarairways.com |
| British Airways Club | britishairways.com, ba.com |
| AwardWallet | awardwallet.com |
