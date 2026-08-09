#!/usr/bin/env python3
"""Amazon browser session for order-item recovery on a HEADLESS host.

Amazon redacted its order confirmation emails around 2026-07-15 ("Ordered: 5
Electronics items" - no titles, prices, ASINs or product links anywhere in the
payload, and the shipment mail is redacted too). The legacy Order History
Report at /gp/b2b/reports is gone: Amazon 302s unauthenticated requests for
real pages to /ax/claim sign-in, but that path returns a bare 404. So the only
remaining source of item detail is the authenticated web session.

This module owns that session and nothing else - fetching and parsing live in
amazon_orders.py. The split matters because the session is the fragile part:
it needs a human roughly as often as the Gmail OAuth tokens do.

The host has no display, so the one-time interactive login runs a REAL headed
Chromium inside Xvfb, published over x11vnc -> websockify -> noVNC. Don opens
it as an ordinary web page through an SSH tunnel, signs in (password, OTP,
whatever Amazon asks), and the profile persists on disk. Every later run is
plain headless against that same profile.

Why a persistent profile rather than an exported cookie jar: the session is
created from this VM's IP and this Chromium's fingerprint, so it keeps
matching them. A jar minted on Don's laptop and replayed from a DMZ VM is a
much louder signal to Amazon's risk engine.

    login    one-time (or re-auth) interactive sign-in via noVNC
    check    headless: is the stored session still signed in?
    logout   destroy the profile

Deliberately NOT reusing Home Assistant's alexa_media cookie jar. That session
is live and refreshed, so it was tempting, but coupling parts inventory to the
smart home means tripping Amazon's risk engine here takes out Alexa in the
house too.
"""
import argparse
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time

PROFILE_DIR = os.getenv('AMAZON_PROFILE_DIR', '/etc/partsbin/amazon-profile')
DISPLAY = os.getenv('AMAZON_LOGIN_DISPLAY', ':91')
VNC_PORT = int(os.getenv('AMAZON_LOGIN_VNC_PORT', '5901'))
NOVNC_PORT = int(os.getenv('AMAZON_LOGIN_NOVNC_PORT', '6081'))
SCREEN = '1280x900x24'

# A signed-out amazon.com bounces to /ap/signin or /ax/claim; a signed-in one
# renders the nav greeting. Checking for the sign-in markers is the reliable
# direction - the greeting text varies by locale and A/B test.
SIGNED_OUT_MARKERS = ('/ap/signin', '/ax/claim', 'ap_signin')
HOME = 'https://www.amazon.com/gp/css/order-history'

UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/151.0.0.0 Safari/537.36')


def _ensure_profile_dir():
    """Profile holds live Amazon session cookies - root-only, like the Google tokens."""
    os.makedirs(PROFILE_DIR, mode=0o700, exist_ok=True)
    os.chmod(PROFILE_DIR, 0o700)


class _Display:
    """Xvfb + x11vnc + noVNC, all bound to loopback (SSH tunnel is the door)."""

    def __init__(self, password):
        self.password = password
        self.procs = []

    def __enter__(self):
        self.procs.append(subprocess.Popen(
            ['Xvfb', DISPLAY, '-screen', '0', SCREEN, '-nolisten', 'tcp'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        time.sleep(2)

        pwfile = os.path.join(PROFILE_DIR, '.vncpw')
        subprocess.run(['x11vnc', '-storepasswd', self.password, pwfile],
                       check=True, capture_output=True)
        os.chmod(pwfile, 0o600)
        self.procs.append(subprocess.Popen(
            ['x11vnc', '-display', DISPLAY, '-rfbport', str(VNC_PORT),
             '-rfbauth', pwfile, '-localhost', '-forever', '-shared', '-noxdamage'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        time.sleep(1)

        self.procs.append(subprocess.Popen(
            ['websockify', '--web', '/usr/share/novnc',
             f'127.0.0.1:{NOVNC_PORT}', f'127.0.0.1:{VNC_PORT}'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        time.sleep(1)
        return self

    def __exit__(self, *exc):
        for p in reversed(self.procs):
            try:
                p.send_signal(signal.SIGTERM)
                p.wait(timeout=5)
            except Exception:
                p.kill()
        pwfile = os.path.join(PROFILE_DIR, '.vncpw')
        if os.path.exists(pwfile):
            os.unlink(pwfile)


def _context(playwright, headless):
    return playwright.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=headless,
        user_agent=UA,
        viewport={'width': 1280, 'height': 860},
        locale='en-US',
        timezone_id='America/New_York',
        args=['--disable-blink-features=AutomationControlled', '--no-sandbox'],
    )


def _is_signed_in(page):
    url = (page.url or '').lower()
    if any(m in url for m in SIGNED_OUT_MARKERS):
        return False
    try:
        html = page.content()[:200000].lower()
    except Exception:
        return False
    return not any(m in html for m in ('ap_signin', 'auth-portal-main-section'))


def cmd_login(args):
    from playwright.sync_api import sync_playwright

    _ensure_profile_dir()
    password = secrets.token_urlsafe(9)[:8]

    print('=' * 68)
    print('  Amazon interactive login — partsbin VM has no display, so the')
    print('  browser is published over noVNC. From YOUR machine run:')
    print()
    print(f'      ssh -N -L {NOVNC_PORT}:127.0.0.1:{NOVNC_PORT} root@partsbin.internal')
    print()
    print('  then open in any browser:')
    print()
    print(f'      http://127.0.0.1:{NOVNC_PORT}/vnc.html')
    print()
    print(f'  VNC password: {password}')
    print()
    print('  Sign in to Amazon in that window (password + OTP as prompted).')
    print(f'  Waiting up to {args.timeout // 60} minutes, then saving the session.')
    print('=' * 68, flush=True)

    with _Display(password):
        env = dict(os.environ, DISPLAY=DISPLAY)
        os.environ.update(env)
        with sync_playwright() as pw:
            ctx = _context(pw, headless=False)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(HOME, wait_until='domcontentloaded', timeout=60000)

            deadline = time.time() + args.timeout
            signed = False
            while time.time() < deadline:
                time.sleep(5)
                try:
                    if _is_signed_in(page):
                        # Confirm it sticks across a navigation, not just a
                        # post-login interstitial
                        page.goto(HOME, wait_until='domcontentloaded', timeout=60000)
                        time.sleep(2)
                        if _is_signed_in(page):
                            signed = True
                            break
                except Exception:
                    continue

            if signed:
                print('\n[ok] signed in — session saved to', PROFILE_DIR)
            else:
                print('\n[FAIL] still signed out when the window expired.')
            ctx.close()
    return 0 if signed else 1


def cmd_check(args):
    from playwright.sync_api import sync_playwright

    if not os.path.isdir(PROFILE_DIR):
        print('[FAIL] no profile at', PROFILE_DIR, '- run: amazon_session.py login')
        return 1
    with sync_playwright() as pw:
        ctx = _context(pw, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(HOME, wait_until='domcontentloaded', timeout=60000)
            time.sleep(2)
            ok = _is_signed_in(page)
            print(('[ok] session live' if ok else '[FAIL] signed out — re-run login'),
                  '| final url:', page.url[:110])
            return 0 if ok else 1
        finally:
            ctx.close()


def cmd_logout(args):
    if os.path.isdir(PROFILE_DIR):
        shutil.rmtree(PROFILE_DIR)
        print('removed', PROFILE_DIR)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('login', help='interactive sign-in over noVNC')
    p.add_argument('--timeout', type=int, default=900, help='seconds to wait (default 900)')
    p.set_defaults(func=cmd_login)
    sub.add_parser('check', help='headless: is the session still valid?').set_defaults(func=cmd_check)
    sub.add_parser('logout', help='destroy the stored profile').set_defaults(func=cmd_logout)
    args = ap.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
