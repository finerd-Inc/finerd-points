# Google Calendar (Claude: Google Calendar connector; ChatGPT: Google Calendar app)

- Events are **private, without guests**, all-day on the deadline, one popup reminder
  `reminder_days_before` days before (minutes = days × 1440). Titles name the benefit and card
  but never balances, member numbers or account numbers.
- Before creating, check the ledger's `calendar_events` for the subject; update instead of
  creating a second event.
- After creating or updating, **read the event back** (get event by id) and pass these mapped
  values to `ledger.py op --state confirmed --read-back`: `title` (the event summary), `date`
  (the all-day start date, YYYY-MM-DD), `reminder_minutes` (the popup override's minutes, or null
  when the event has no reminder override), `visibility` (must be "private"), `description` (it
  must still contain the `[finerd points op-…]` marker), `attendees` (must be empty) and `event_id`.
- To check whether an event already exists, use the event id from the ledger; after an unknown
  outcome, list the events on the deadline date itself (an explicit day range) and look for the
  marker in their descriptions. Default «upcoming» listings only cover the next days.
- Done: title gets «✓ » and the reminder override is removed (reminders: useDefault false,
  overrides empty). If the connector cannot remove reminders, keep «✓» and ask the person to
  turn the reminder off.
- Never delete events.
