import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = os.getenv("SONGWALK_SMTP_HOST", "smtp.purelymail.com")
SMTP_PORT = int(os.getenv("SONGWALK_SMTP_PORT", "465"))
SMTP_USERNAME = os.getenv("SONGWALK_SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SONGWALK_SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SONGWALK_SMTP_FROM", "songwalk@tekonline.com.au")
SMTP_FROM_NAME = os.getenv("SONGWALK_SMTP_FROM_NAME", "SongWalk")


def send_magic_link(email: str, link: str) -> bool:
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = "Your SongWalk library link"
    message["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    message["To"] = email

    html = f"""<html><body>
<h2>Welcome to SongWalk 🎵</h2>
<p>Click the button below to access your music library:</p>
<p style="text-align:center;">
  <a href="{link}" style="background-color:#2c82d3;color:white;padding:14px 28px;text-decoration:none;border-radius:6px;display:inline-block;font-size:16px;">
    Open Your Library
  </a>
</p>
<p>Or copy and paste this link:</p>
<p>{link}</p>
<p>This link expires in 24 hours.</p>
<p>— SongWalk</p>
</body></html>"""

    plain = f"""Welcome to SongWalk!

Click this link to access your music library:

{link}

This link expires in 24 hours.

— SongWalk"""

    message.attach(MIMEText(html, "html"))
    message.attach(MIMEText(plain, "plain"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)
        return True
    except Exception:
        return False
