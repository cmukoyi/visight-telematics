"""
Quick test script for SendGrid email sending.
Run from the gps-tracker directory:
    python test_email.py <to_email> [sendgrid_api_key]

If no API key argument is given, it reads SENDGRID_API_KEY from the environment.
"""
import sys
import os

# Allow running from the gps-tracker directory without installing the app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

# --- Config ---
to_email = sys.argv[1] if len(sys.argv) > 1 else "test@example.com"
api_key  = sys.argv[2] if len(sys.argv) > 2 else os.getenv("SENDGRID_API_KEY", "")

if not api_key:
    print("❌  No SendGrid API key supplied.\n"
          "    Usage: python test_email.py <to_email> <api_key>\n"
          "    Or set SENDGRID_API_KEY in your environment.")
    sys.exit(1)

os.environ["SENDGRID_API_KEY"] = api_key

# --- Import after env is set ---
from app.services.email_service import EmailService, SENDGRID_AVAILABLE

if not SENDGRID_AVAILABLE:
    print("❌  sendgrid package is not installed. Run: pip install sendgrid")
    sys.exit(1)

service = EmailService()
print(f"use_sendgrid : {service.use_sendgrid}")
print(f"from_email   : {service.from_email}")
print(f"to_email     : {to_email}")
print()

result = service._send_via_sendgrid(
    to_email=to_email,
    subject="[BLE Tracker] Email test",
    text_content="This is a plain-text test email — click tracking should be disabled.",
    html_content=(
        "<p>This is a <b>HTML test email</b>.</p>"
        "<p><a href='https://maps.google.com/?q=-1.2921,36.8219'>Open in Google Maps</a></p>"
    )
)

if result:
    print("✅  Email sent successfully.")
else:
    print("❌  Email sending failed — check the error above.")
    sys.exit(1)
