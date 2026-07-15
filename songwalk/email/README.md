# SongWalk Email

## Provider
PurelyMail SMTP — managed at purelymail.com

## Credentials
- SMTP: smtp.purelymail.com:465 (SSL)
- Username: jon@tekonline.com.au
- From: songwalk@tekonline.com.au

## DNS
songwalk@tekonline.com.au is a PurelyMail alias.
To send from this address, it must be verified in PurelyMail dashboard.

## Magic Link Flow
1. POST /api/auth/send-link {email}
2. Email sent with signed itsdangerous token
3. GET /auth/verify?token=xxx
4. Library created (or existing returned), user redirected
