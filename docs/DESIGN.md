# PartsBin — Design

Electronics component inventory + project documentation for Empire12 (Don & DeAnna).
Sister app to Garment Gallery (GarmentGallery2) — same architecture, auth, and exposure pattern.

- **Host:** `partsbin` VM 121 on pve4, partsbin.internal, Ubuntu 24.04, disk on pve4 local-lvm (NOT NVME-Pool Ceph)
- **URL:** https://parts.example.com (Shield nginx vhost → partsbin.internal; Cloudflare proxied wildcard in front, mTLS origin check)
- **Repo:** github.com/d3athstr/partsbin (private)

## Stack (mirrors GarmentGallery2)

- Backend: Flask 3 + SQLAlchemy + PostgreSQL 16, Flask-Login sessions, bcrypt,
  PyOTP TOTP 2FA, WebAuthn passkeys, invitation-gated registration. Gunicorn on 127.0.0.1:8000.
- Frontend: React 18 + Vite + Tailwind (dark theme), react-router, @tanstack/react-query, axios.
  Served as static build by the VM's local nginx; `/api` and `/uploads` proxied to gunicorn.
- Ingestion: Gmail API OAuth polling (don + deanna Gmail) + Claude API parsing → order review queue.
- Systemd: `partsbin.service` (gunicorn), `partsbin-ingest.timer` (30 min), `partsbin-token-monitor.timer` (6 h).

## Data model

- **User / Passkey / Invitation** — copied from GG (same columns/flows; app-native, no Authentik).
- **Component**: name, category (from fixed list below), specs JSONB (free-form key/value:
  resistance, capacitance, voltage, package, pinout…), manufacturer, mpn, description,
  qty_on_hand, min_qty (low-stock threshold), location (bin/drawer label), datasheet_url,
  image upload, tags (m2m), notes.
- **StockTransaction**: component_id, delta, reason (initial | order_received | project_use |
  adjustment), ref order_item/project, note, user, timestamp. `qty_on_hand` only changes via
  transactions (auditable history).
- **Project**: name, status (planning/active/on_hold/done), description, readme_md (rendered
  markdown documentation), repo_url, tags, files (images / PDFs / schematics / firmware),
  BOM = ProjectComponent(component, qty_planned, qty_used, note). "Consume" action decrements
  stock via transactions. Availability check flags BOM lines short on stock.
- **Order**: vendor (amazon/aliexpress/adafruit/mouser/digikey/other), vendor_order_no, status
  (ordered → shipped → delivered → received), order_date, tracking_no/carrier/url, gmail_account,
  gmail_message_ids, raw_subject, total.
- **OrderItem**: raw_title (as parsed from email), qty, unit_price, match_status (unmatched /
  suggested / confirmed / ignored), suggested_component_id (fuzzy match on name/mpn),
  component_id. On order "received", confirmed items increment stock (order_received transactions);
  items flagged "create new" spawn a pre-filled component form.
- **ProcessedMessage**: gmail message-id dedup table (idempotent polling).

### Component categories (fixed list, seeded)
Resistors, Capacitors, Inductors, Diodes, LEDs, Transistors & MOSFETs, ICs, Microcontrollers,
Dev Boards, Sensors, Displays, Servos & Motors, Motor Drivers, Batteries & Power, Voltage
Regulators, Connectors & Headers, Switches & Buttons, Relays, Wire & Cable, Prototyping,
RF Modules (WiFi/BLE/LoRa), Audio, Mechanical, Tools, Other.

## Email ingestion pipeline

1. `partsbin-ingest.timer` → `flask ingest run` every 30 min.
2. For each authorized Gmail account (don, deanna): Gmail API query
   `from:(amazon.com OR aliexpress.com OR adafruit.com OR mouser.com OR digikey.com) newer_than:14d`,
   skip message-ids already in ProcessedMessage.
3. Each new message → Claude API (claude-sonnet-5) extracts JSON:
   `{is_order, vendor, order_no, event: ordered|shipped|delivered, items:[{title, qty, unit_price}], tracking, carrier, eta}`.
   Non-order mail marked processed and skipped.
4. Orders upsert by (vendor, order_no): "ordered" creates order + items + fuzzy match suggestions;
   "shipped"/"delivered" update status/tracking. Nothing touches stock until a human confirms
   receipt in the review queue.
5. OAuth: reuses the Empire12 Voice GCP OAuth client (Testing mode). PartsBin keeps its own
   refresh tokens (`/etc/partsbin/google-tokens.json`, root-only). Re-auth: `GET
   /api/oauth/login/<user>?key=<ingest_key>` → Google consent → `/api/oauth/callback`.
   `partsbin-token-monitor.timer` keep-alive-refreshes tokens and emails the affected user their
   one-click re-auth link via Shield SMTP when a grant dies (testing-mode tokens expire ~7 days
   after consent), debounced 24 h — same pattern as voice-reauth-monitor.
6. Known gap: AliExpress notifications tied to Don's Apple ID go to iCloud mail. Fix is a one-time
   iCloud rule forwarding AliExpress mail to Don's Gmail (punch list).

## UI (dark, ISA-101-flavored status)

Status colors follow the house HP-HMI rule: **gray when OK** — amber for low stock
(qty ≤ min_qty), red for out-of-stock, no green pills.

Pages: Login (password → TOTP step, passkey button) / Register (invite code) / Dashboard
(low-stock + out-of-stock exceptions, pending review queue count, recent orders, token health) /
Inventory (filterable table: category, tag, location, text search incl. specs+mpn; inline qty ± ) /
Component detail (specs, stock history, datasheet link, used-in projects) / Projects list + detail
(markdown docs, files, BOM with availability) / Orders list + Order review (match queue) /
Settings (TOTP, passkeys, invitations, Gmail account cards with token status + re-auth links).

## Security / ops

- Secrets in `.env` on the VM (root:deploy 640), sourced from Vault `secret/<org>/partsbin/*`
  at deploy: flask secret, DB password, Google client id/secret, Anthropic API key, ingest key.
- Shield vhost identical to patterns.example.com.conf (LE cert, cloudflare-mTLS snippets,
  block-scanners). App itself enforces login on every /api route.
- Nightly backup: pg_dump + uploads tarball → CITADEL NFS /mnt/DATA/Home/BKUP/PARTSBIN/ (14-day
  retention), cron on the VM.
- qemu-guest-agent, Wazuh agent (≤ 4.9.2), NetBox VM + IP registration, PiHole DNS
  (partsbin + parts.example.com → partsbin.internal internal-direct? No — parts goes through
  Shield like patterns; only `partsbin.internal` A-record → .21).
