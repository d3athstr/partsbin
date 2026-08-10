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


RUN_DIR = '/run/partsbin'
ACCOUNT_MARKER = '.partsbin-account'


def session_account(profile_dir=None):
    """Which PartsBin gmail_account this stored Amazon session belongs to.

    Orders are per-user, and so are Amazon accounts. Fetching DeAnna's order
    numbers with Don's session returns a page that renders perfectly and
    contains no items - indistinguishable from an archived order unless you
    check who owns the order first. Recording the owner here lets the importer
    refuse to cross accounts instead of burning requests to learn nothing.
    """
    path = os.path.join(profile_dir or PROFILE_DIR, ACCOUNT_MARKER)
    try:
        with open(path) as fh:
            name = fh.read().strip()
            if name:
                return name
    except OSError:
        pass
    return os.getenv('AMAZON_SESSION_ACCOUNT', 'don')


def _write_account_marker(account):
    with open(os.path.join(PROFILE_DIR, ACCOUNT_MARKER), 'w') as fh:
        fh.write(account.strip() + '\n')


def _ensure_profile_dir():
    """Profile holds live Amazon session cookies - root-only, like the Google tokens."""
    os.makedirs(PROFILE_DIR, mode=0o700, exist_ok=True)
    os.chmod(PROFILE_DIR, 0o700)


def _clear_stale_lock():
    """Drop Chromium's singleton locks when no Chromium actually holds them.

    A crashed or killed run leaves SingletonLock behind, and the next launch
    dies with "Opening in existing browser session ... profile is already in
    use". That exception then unwinds through the display teardown, so the
    symptom shows up as a VNC password failure rather than anything mentioning
    the profile. Only safe because this profile is single-use by this script.
    """
    if subprocess.run(['pgrep', '-f', f'--user-data-dir={PROFILE_DIR}'],
                      capture_output=True).returncode == 0:
        return False
    cleared = []
    for name in ('SingletonLock', 'SingletonCookie', 'SingletonSocket'):
        path = os.path.join(PROFILE_DIR, name)
        if os.path.lexists(path):
            os.unlink(path)
            cleared.append(name)
    if cleared:
        print('[info] cleared stale profile lock:', ', '.join(cleared))
    return bool(cleared)


class _Display:
    """Xvfb + x11vnc + noVNC.

    x11vnc ALWAYS stays on loopback; only websockify's HTTP port is bindable
    elsewhere, so the raw VNC protocol is never exposed and the noVNC page is
    still gated by the one-time password. bind='127.0.0.1' means an SSH tunnel
    is the only door; bind='0.0.0.0' publishes on the VM's LAN for a client
    that can already route here (e.g. Don's MacBook through the travel-router
    tunnel) but has no ops SSH key to build a tunnel with.
    """

    def __init__(self, password, bind='127.0.0.1'):
        self.password = password
        self.bind = bind
        self.procs = []
        self.pwfile = None
        self.vnclog = None

    def __enter__(self):
        self.procs.append(subprocess.Popen(
            ['Xvfb', DISPLAY, '-screen', '0', SCREEN, '-nolisten', 'tcp'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        time.sleep(2)

        # Password file lives OUTSIDE the profile and is per-run. It used to be
        # PROFILE_DIR/.vncpw, so a second run's teardown deleted the file the
        # first run's x11vnc was still authenticating against - every password
        # then failed, with no hint as to why.
        os.makedirs(RUN_DIR, mode=0o700, exist_ok=True)
        self.pwfile = os.path.join(RUN_DIR, f'vncpw-{os.getpid()}')
        subprocess.run(['x11vnc', '-storepasswd', self.password, self.pwfile],
                       check=True, capture_output=True)
        os.chmod(self.pwfile, 0o600)
        # stderr kept: sending it to DEVNULL is what made the auth failure
        # opaque the first time round.
        self.vnclog = open(os.path.join(RUN_DIR, 'x11vnc.log'), 'wb')
        self.procs.append(subprocess.Popen(
            ['x11vnc', '-display', DISPLAY, '-rfbport', str(VNC_PORT),
             '-rfbauth', self.pwfile, '-localhost', '-forever', '-shared', '-noxdamage'],
            stdout=self.vnclog, stderr=subprocess.STDOUT))
        time.sleep(1)

        self.procs.append(subprocess.Popen(
            ['websockify', '--web', '/usr/share/novnc',
             f'{self.bind}:{NOVNC_PORT}', f'127.0.0.1:{VNC_PORT}'],
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
        try:
            self.vnclog.close()
        except Exception:
            pass
        if self.pwfile and os.path.exists(self.pwfile):
            os.unlink(self.pwfile)


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
    """Signed-out is a REDIRECT, so the landing URL is the only honest signal.

    Do not scan the page HTML for 'ap_signin': Amazon embeds that string in the
    nav of fully signed-in pages, so a content check false-negatives forever
    while the user is demonstrably logged in and staring at their orders.
    """
    url = (page.url or '').lower()
    return not any(m in url for m in SIGNED_OUT_MARKERS)


def cmd_login(args):
    from playwright.sync_api import sync_playwright

    _ensure_profile_dir()
    _clear_stale_lock()
    # Lowercase+digits only: this gets typed by hand into a noVNC canvas,
    # where clipboard paste is unreliable. Mixed case and punctuation are a
    # tax for no security gain on a loopback-only, minutes-long window.
    password = args.password or ('pb' + ''.join(
        secrets.choice('abcdefghijkmnpqrstuvwxyz23456789') for _ in range(6)))
    lan = args.bind not in ('127.0.0.1', 'localhost')

    print('=' * 68)
    print('  Amazon interactive login — partsbin VM has no display, so the')
    print('  browser is published over noVNC.')
    print()
    if lan:
        print('  Open in any browser on the Empire12 LAN (or through the')
        print('  travel-router tunnel — no SSH key needed):')
        print()
        print(f'      http://partsbin.internal:{NOVNC_PORT}/vnc.html')
    else:
        print('  From YOUR machine run:')
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

    with _Display(password, bind=args.bind):
        env = dict(os.environ, DISPLAY=DISPLAY)
        os.environ.update(env)
        with sync_playwright() as pw:
            ctx = _context(pw, headless=False)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(HOME, wait_until='domcontentloaded', timeout=60000)

            # Type the email in from here so the human only has to enter the
            # secrets. Everything typed into noVNC is typed by hand - paste
            # into the canvas does not reliably work - so every field we can
            # fill is one less chance of a typo on a timed window.
            if args.email:
                for sel in ('input[type="email"]', '#ap_email_login', '#ap_email',
                            'input[name="email"]'):
                    try:
                        field = page.locator(sel).first
                        if field.is_visible(timeout=3000):
                            field.fill(args.email)
                            print(f'[info] pre-filled {args.email}; press Continue, '
                                  'then enter your password')
                            break
                    except Exception:
                        continue

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
                _write_account_marker(args.account)
                print(f'\n[ok] signed in — session saved to {PROFILE_DIR} '
                      f'for account {args.account!r}')
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
                  f'| account: {session_account()}',
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
    p.add_argument('--bind', default='127.0.0.1',
                   help='noVNC bind address; 0.0.0.0 publishes on the LAN for a '
                        'client with no SSH key (default 127.0.0.1)')
    p.add_argument('--password', default=None,
                   help='VNC password (default: generated, easy to hand-type)')
    p.add_argument('--email', default=os.getenv('AMAZON_LOGIN_EMAIL'),
                   help='pre-fill the Amazon sign-in email field')
    p.add_argument('--account', default=os.getenv('AMAZON_SESSION_ACCOUNT', 'don'),
                   help="PartsBin gmail_account this Amazon login belongs to "
                        "(don|deanna). Recorded so the importer never fetches "
                        "one person's orders with the other's session.")
    p.set_defaults(func=cmd_login)
    sub.add_parser('check', help='headless: is the session still valid?').set_defaults(func=cmd_check)
    sub.add_parser('logout', help='destroy the stored profile').set_defaults(func=cmd_logout)
    args = ap.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
