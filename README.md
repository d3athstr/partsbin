# PartsBin

Electronics component inventory + project documentation for Empire12.
Live at **https://parts.example.com** · sister app to GarmentGallery2 (same architecture and auth).

Track stock of resistors, capacitors, LEDs, dev boards, sensors, LiPo batteries, servos, etc.;
document ESP32-and-friends projects (markdown + files + BOM tied to inventory); and auto-import
part orders by polling Don's & DeAnna's Gmail for Amazon / AliExpress / Adafruit / Mouser / Digikey
order emails, parsed with the Claude API into a human-confirmed review queue.

## Layout

```
backend/     Flask 3 + SQLAlchemy + PostgreSQL API (gunicorn on 127.0.0.1:8000)
             app/ingest/ = Gmail OAuth poller + Claude parser + fuzzy matcher + token monitor
frontend/    React 18 + Vite + Tailwind dark SPA (ISA-101 status palette: gray-when-OK)
deployment/  systemd units, nginx conf, setup.sh, backup.sh, .env.example
docs/        DESIGN.md (architecture + data model) · API.md (API contract)
```

## Production

- VM 121 `partsbin` on pve4 (Ubuntu 24.04, partsbin.internal, disk on local-lvm).
- Exposure: Cloudflare (proxied wildcard) → Shield nginx `parts.example.com` vhost (LE cert +
  Cloudflare mTLS origin check) → VM nginx → gunicorn. EdgeRouter DMZ_IN rule 175 allows
  Shield→VM:80.
- Auth: app-native — bcrypt + TOTP 2FA + WebAuthn passkeys, invitation-gated registration.
- Secrets: Vault `secret/<org>/partsbin/app`; Google OAuth client shared with the voice
  assistant (`<org>/voice/google-oauth`); tokens live only on the VM in `/etc/partsbin/`.
- Timers: `partsbin-ingest.timer` (30 min poll), `partsbin-token-monitor.timer` (6 h; emails a
  one-click re-auth link when a Google testing-mode token dies, ~every 7 days).
- Backups: nightly 02:15 pg_dump + uploads → CITADEL NFS `BKUP/PartsBin/`, 14-day retention.
- Monitoring: Wazuh agent 084; ops `webapp-monitor.sh` probes `/api/health`.

## Deploy / update

```bash
# from a checkout on ops
rsync -a --delete --exclude .git --exclude backend/venv --exclude node_modules ./ root@partsbin.internal:/opt/partsbin/
ssh root@partsbin.internal 'cd /opt/partsbin/frontend && npm ci && npm run build   # if frontend changed
                        systemctl restart partsbin'
```

Full bootstrap of a fresh VM: `deployment/setup.sh` (see `docs/DESIGN.md` for the manual steps
actually used for VM 121: Vault-sourced `.env`, DB role/db, systemd units, nginx).
