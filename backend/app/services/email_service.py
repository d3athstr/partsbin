import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import current_app, has_app_context


def _log_error(msg):
    """Log via the Flask app logger when available, stderr otherwise"""
    if has_app_context():
        current_app.logger.error(msg)
    else:
        import sys
        print(msg, file=sys.stderr)


def get_smtp_config():
    """Get SMTP configuration from environment (SMTP relay)"""
    return {
        'host': os.getenv('SMTP_HOST', 'smtp.internal'),
        'port': int(os.getenv('SMTP_PORT', 25)),
        'from_addr': os.getenv('SMTP_FROM', 'parts@example.com'),
    }


def send_email(to_email, subject, html_body, text_body=None):
    """
    Send an email via SMTP.

    Args:
        to_email: Recipient email address
        subject: Email subject
        html_body: HTML content of the email
        text_body: Plain text fallback (optional)

    Returns:
        True if sent successfully, False otherwise
    """
    config = get_smtp_config()

    # Create message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = config['from_addr']
    msg['To'] = to_email

    # Add text part (fallback)
    if text_body:
        text_part = MIMEText(text_body, 'plain')
        msg.attach(text_part)

    # Add HTML part
    html_part = MIMEText(html_body, 'html')
    msg.attach(html_part)

    try:
        # Connect and send (no auth, no TLS for this relay)
        with smtplib.SMTP(config['host'], config['port']) as server:
            server.sendmail(config['from_addr'], to_email, msg.as_string())
        return True
    except Exception as e:
        _log_error(f'Failed to send email to {to_email}: {e}')
        return False


def send_invitation_email(to_email, invitation_code, inviter_name, note=None):
    """
    Send an invitation email with the registration code.

    Args:
        to_email: Recipient email address
        invitation_code: The invitation code
        inviter_name: Name of the person sending the invitation
        note: Optional personal message
    """
    site_url = os.getenv('SITE_URL', 'https://parts.example.com')
    register_url = f"{site_url}/register"

    subject = "You're invited to join PartsBin"

    # Build personal message section
    personal_note = ""
    if note:
        personal_note = f"""
        <p style="margin: 0 0 20px 0; padding: 15px; background-color: #f5f5f5; border-left: 4px solid #8ab4f8; font-style: italic;">
            "{note}"
        </p>
        """

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #0f1419; color: #e8eaed;">
    <table role="presentation" style="width: 100%; border-collapse: collapse;">
        <tr>
            <td style="padding: 40px 20px;">
                <table role="presentation" style="max-width: 600px; margin: 0 auto; background-color: #1a1f26; border-radius: 12px; overflow: hidden;">
                    <!-- Header -->
                    <tr>
                        <td style="padding: 30px 40px; text-align: center; border-bottom: 1px solid #3c4043;">
                            <h1 style="margin: 0; font-size: 24px; font-weight: 600; color: #e8eaed;">PartsBin</h1>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px;">
                            <h2 style="margin: 0 0 20px 0; font-size: 20px; color: #e8eaed;">You've Been Invited!</h2>

                            <p style="margin: 0 0 20px 0; line-height: 1.6; color: #9aa0a6;">
                                <strong style="color: #e8eaed;">{inviter_name}</strong> has invited you to join PartsBin, a private electronics component inventory and project tracker.
                            </p>

                            {personal_note}

                            <p style="margin: 0 0 15px 0; line-height: 1.6; color: #9aa0a6;">
                                Use the invitation code below to create your account:
                            </p>

                            <!-- Invitation Code Box -->
                            <div style="margin: 25px 0; padding: 20px; background-color: #252d36; border-radius: 8px; text-align: center;">
                                <p style="margin: 0 0 8px 0; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #9aa0a6;">Your Invitation Code</p>
                                <p style="margin: 0; font-size: 24px; font-family: 'Monaco', 'Menlo', 'Courier New', monospace; font-weight: 600; color: #8ab4f8; letter-spacing: 2px;">
                                    {invitation_code}
                                </p>
                            </div>

                            <!-- CTA Button -->
                            <div style="text-align: center; margin: 30px 0;">
                                <a href="{register_url}" style="display: inline-block; padding: 14px 32px; background-color: #8ab4f8; color: #0f1419; text-decoration: none; font-weight: 600; border-radius: 8px; font-size: 16px;">
                                    Create Your Account
                                </a>
                            </div>

                            <p style="margin: 20px 0 0 0; font-size: 13px; color: #9aa0a6; line-height: 1.5;">
                                If the button doesn't work, copy and paste this link into your browser:<br>
                                <a href="{register_url}" style="color: #8ab4f8; word-break: break-all;">{register_url}</a>
                            </p>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 20px 40px; border-top: 1px solid #3c4043; text-align: center;">
                            <p style="margin: 0; font-size: 12px; color: #9aa0a6;">
                                This invitation was sent from PartsBin.<br>
                                If you didn't expect this email, you can safely ignore it.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    # Plain text fallback
    text_body = f"""You've Been Invited to PartsBin!

{inviter_name} has invited you to join PartsBin, a private electronics component inventory and project tracker.

{f'Personal message: "{note}"' if note else ''}

Your Invitation Code: {invitation_code}

To create your account, visit: {register_url}

Enter the invitation code above during registration.

---
This invitation was sent from PartsBin.
If you didn't expect this email, you can safely ignore it.
"""

    return send_email(to_email, subject, html_body, text_body)


def send_reauth_email(to_email, account, reauth_url):
    """
    Send a one-click Gmail re-authorization email when a token grant dies.

    Args:
        to_email: Recipient email address
        account: PartsBin gmail account name (e.g. 'don')
        reauth_url: One-click re-auth link (includes the ingest key)
    """
    subject = f'PartsBin: Gmail access for "{account}" needs re-authorization'

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background-color: #0f1419; color: #e8eaed;">
    <table role="presentation" style="width: 100%; border-collapse: collapse;">
        <tr>
            <td style="padding: 40px 20px;">
                <table role="presentation" style="max-width: 600px; margin: 0 auto; background-color: #1a1f26; border-radius: 12px; overflow: hidden;">
                    <tr>
                        <td style="padding: 30px 40px; text-align: center; border-bottom: 1px solid #3c4043;">
                            <h1 style="margin: 0; font-size: 24px; font-weight: 600; color: #e8eaed;">PartsBin</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 40px;">
                            <h2 style="margin: 0 0 20px 0; font-size: 20px; color: #e8eaed;">Gmail re-authorization needed</h2>
                            <p style="margin: 0 0 20px 0; line-height: 1.6; color: #9aa0a6;">
                                PartsBin can no longer read order emails for the
                                <strong style="color: #e8eaed;">{account}</strong> Gmail account -
                                the Google grant has expired (testing-mode tokens last about 7 days).
                                Order ingestion is paused for this account until it is re-authorized.
                            </p>
                            <div style="text-align: center; margin: 30px 0;">
                                <a href="{reauth_url}" style="display: inline-block; padding: 14px 32px; background-color: #8ab4f8; color: #0f1419; text-decoration: none; font-weight: 600; border-radius: 8px; font-size: 16px;">
                                    Re-authorize Gmail Access
                                </a>
                            </div>
                            <p style="margin: 20px 0 0 0; font-size: 13px; color: #9aa0a6; line-height: 1.5;">
                                If the button doesn't work, copy and paste this link into your browser:<br>
                                <a href="{reauth_url}" style="color: #8ab4f8; word-break: break-all;">{reauth_url}</a>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_body = f"""PartsBin: Gmail re-authorization needed

PartsBin can no longer read order emails for the "{account}" Gmail account -
the Google grant has expired (testing-mode tokens last about 7 days).
Order ingestion is paused for this account until it is re-authorized.

Re-authorize here: {reauth_url}
"""

    return send_email(to_email, subject, html_body, text_body)
