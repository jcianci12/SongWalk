# The Problems SongWalk Had to Solve

Every project looks simple from a distance.

"A little app for sharing music with friends" sounds straightforward enough. Upload some MP3s, generate a link, press play, done. But once SongWalk started taking shape, the real work was not just building a music library. The real work was solving all the awkward, practical problems that make small self-hosted apps frustrating in the first place.

This is the part people usually do not see: the pile of edge cases, trade-offs, and "that seemed easy until we actually tried to do it" moments that sit underneath something that is supposed to feel effortless.

SongWalk had to solve those problems if it was ever going to be more than a nice mock-up.

## Problem 1: Sharing Had to Be Fast, Not Theoretical

The whole point of SongWalk is simple: create a library, drop in tracks, copy a share link, and send it to someone immediately.

That sounds obvious, but most self-hosted tools quietly assume the person running them is happy to spend half an hour setting up DNS, reverse proxies, SSL, firewall rules, and yet another account with yet another tunnelling service before anyone else can even open the page.

That was not good enough.

SongWalk needed a "share first" flow, not a "configure for a while and maybe share later" flow. That is why the repo is built around quick local startup, Docker support, and Cloudflare Quick Tunnel integration. The goal was to make public sharing something you could do in minutes, not an infrastructure side quest.

The challenge there was not just starting the app. It was making the public host visible inside the app itself, handling tunnel rotation, and keeping that process simple enough that a normal person would actually use it.

## Problem 2: Public Sharing Could Not Mean Public Exposure

Once you make something easy to share, you immediately create a second problem: how do you avoid turning the whole thing into an accidental directory listing of everyone's music?

That is where SongWalk had to be careful.

The app uses UUID-backed library URLs so each library has its own share path, but that alone is not enough. The root page also had to avoid enumerating libraries when the app was being accessed from a public host. The codebase now treats direct localhost access differently from tunnelled or proxied access for exactly that reason.

That distinction matters. On your own machine, it is useful for the home page to act like a launch pad. On the public internet, that same convenience becomes unnecessary risk.

So one of the core problems SongWalk had to solve was context: when should the app behave like a local control panel, and when should it behave like a neutral public landing page? That sounds like a UI choice, but it is really a security and product design decision.

## Problem 3: Owner Access and Shared Access Needed to Be Separate

There is a big difference between "someone can open this library" and "someone can manage the whole system."

SongWalk needed that distinction to be clear in both the interface and the routing model. Shared libraries live at public `/s/<library-id>` URLs. Management lives behind a separate private owner path. That owner URL gets written locally so the person running SongWalk can keep control, while the public side stays focused on the libraries being shared.

Without that separation, the whole app would feel fragile. Every link would raise the question of whether you were exposing too much. By splitting owner access from share access, SongWalk becomes easier to reason about. You know which URL is safe to send and which one is not.

That trust is part of the product.

## Problem 4: URLs Had to Stay Correct Behind Proxies and Tunnels

This sounds boring until it breaks.

A self-hosted app can look perfectly fine on `localhost` and still generate completely wrong links the second it sits behind nginx, a reverse proxy, or a public tunnel. Suddenly the app thinks it lives on `http://127.0.0.1`, or it drops HTTPS, or it builds share links that only work on the local machine.

SongWalk had to handle forwarded host and scheme headers properly, trust the right number of proxy hops, and still avoid treating public traffic as local traffic. That is why the app uses proxy-aware configuration and why local-only features are deliberately restricted to direct loopback access.

This was one of those problems that is invisible when solved well and maddening when solved badly. If share links are wrong, the whole product promise falls apart.

## Problem 5: Importing Music Had to Feel Practical, Not Fragile

Dragging local files into a library is only one part of how people collect music now. Real-world sharing also means links, playlists, downloads, and inconsistent metadata from all over the place.

So SongWalk had to solve a messier problem: how do you import from sources like YouTube and Spotify without turning the app into a brittle wrapper around command-line tools?

That meant:

- Handling `yt-dlp`, `youtube-dl`, `spotdl`, and `ffmpeg`
- Dealing with environments where those tools are missing
- Turning long-running imports into background jobs instead of blocking the page
- Surfacing progress so the user knows whether something is actually happening
- Collecting the produced files and feeding them back into the library cleanly

This is the kind of feature that looks like one button in the UI and turns into a surprising amount of engineering once you account for failure states, dependency checks, downloader output, timeouts, and cleanup.

## Problem 6: Metadata in the Wild Is a Mess

Music files are messy. File names are messy. Tags are messy. Some tracks have the right title but no album. Some have an uploader name jammed into the title. Some come in clean, some come in half-broken, and some come in as pure chaos.

If SongWalk was going to feel good to use, it could not just store files. It had to help make them presentable.

That is why the app normalises metadata after import, tries to split artist and title intelligently, and uses MusicBrainz to fill in missing release details and cover art when there is enough information to make a confident match.

This was an important problem to solve because a shared library lives or dies on readability. A good library invites browsing. A bad one looks like a downloads folder.

## Problem 7: The App Had to Stay Simple Even as the Feature Set Grew

There is a trap waiting for projects like this. Every new requirement makes sense on its own:

- Public sharing
- Owner controls
- Tunnel support
- Reverse proxy support
- Library downloads
- Metadata editing
- Smart imports
- Search
- Cover art

The danger is that the app starts feeling like a control panel instead of a music library.

SongWalk had to keep solving real problems without losing the reason it exists in the first place. That meant keeping the interface familiar, keeping the core actions obvious, and resisting the urge to let the infrastructure story dominate the experience.

In other words, the technical complexity had to stay under the hood.

## Problem 8: It Had to Be Self-Hosted Without Feeling Hostile

Plenty of self-hosted software is powerful. Far less of it is welcoming.

SongWalk had to bridge that gap. It needed to work for the person who wants to run `python -m songshare`, for the person who prefers Docker, and for the person who just wants the thing online and shareable without reading a small novel first.

That is why packaging, startup flow, dependency bundling, and quick-share scripts matter so much here. Ease of use was not a cosmetic extra. It was one of the main engineering goals.

If a self-hosted app is technically capable but annoying to launch, most people will never experience what makes it good.

## The Real Build Story

The interesting part of SongWalk was never just "make a place to upload songs." The interesting part was making something that feels easy while solving all the hidden problems around trust, routing, public exposure, metadata, imports, and setup friction.

That is the real shape of the project.

Underneath the retro skin and the nostalgic idea is a very practical set of engineering decisions: separate the private side from the public side, make sharing fast, respect proxy reality, clean up bad metadata, and reduce setup pain wherever possible.

If SongWalk works the way it should, most of that effort disappears into the background. That is usually the sign the hard parts were the right hard parts to focus on.
