# SongWalk Launch Brief

SongWalk is a retro-inspired music dropbox for friends, collaborators, and families who need to share libraries without the noise of mainstream cloud storage. The new `SongWalk` brand keeps the same battle-tested `songshare` backend but wraps it in a polished AV-style skin, a fresh logo, and a single-cross-platform quick-share script that covers both local Python and Docker deployments.

## Why SongWalk?

- **Instant sharing**: create a library, drag in files, grab a UUID-backed share URL, and send it to anyone. The public landing page never lists libraries, and each share URL is scoped by UUID.
- **Owner dashboard separation**: local HTTPS access to `/owner/<token>` keeps admin workflows away from public browsing.
- **Zero setup tunnel**: the combined PowerShell/Bash launcher starts SongWalk, polls for readiness, spins up a Cloudflare Quick Tunnel, and prints the public link plus the private owner URL.
- **Build story**: launched from [tekonline.com.au](https://www.tekonline.com.au), this release showcases how a hobbyist app can recover the feel of a vintage media player while solving modern sharing headaches.

## Quick start

1. Clone the repo and install deps if you are running locally.
2. Run `powershell -ExecutionPolicy Bypass -File .\deploy\quick-share.ps1` (Windows) or `bash ./deploy/quick-share.sh` (Linux/macOS).
3. Choose “docker” or “python” when prompted; the launcher will start SongWalk, wait for the HTTP port, then bring up the Quick Tunnel.
4. Copy the “Public URL” output and send `/s/<library-id>` links to collaborators. The launcher also prints the private owner dashboard path for management.

Optional: set `SONGSHARE_BASE_URL` if you are proxying through nginx or another reverse proxy. The repo already includes a sample `deploy/nginx/songshare.conf`.

## Spread the word

- Publish this post on Tekonline, with before/after screenshots and a short demo video showing the quick-share script in action.
- Promote the launch via relevant communities: /r/selfhosted, /r/homelab, Hacker News (Show HN), and small music production forums.
- Create short clips (X, Mastodon, LinkedIn) that highlight the quick-start flow and the new SongWalk logo.
- Mention the repo URL `github.com/jcianci12/SongWalk` and call out the logo-focused README hero banner that now ships with the repo.

## Call to action

Try SongWalk today, send me feedback on Tekonline or GitHub discussions, and share the public `trycloudflare.com` URL with your friends to prove that sharing music can be instant again.

