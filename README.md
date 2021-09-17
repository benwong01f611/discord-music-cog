# Music Extension for discord.py
This is a fork from a replit template. Some bugs were found during usage, therefore I decided to modify it.
## Features
- Play / Pause / Stop music
- Queue
- Add playlist to queue (it will takes a while to search all songs)
- Looping
- Volume
- Skipping
- Stopping
- Become speaker automatically in stage channel (if the bot has the permission to mute members)
- Command "now" shows the position of the song

## Differences
- Fixed looping causes exception
- Supports adding playlist to queue
- Added support for speaking in stage
- Added searching for video
- Setting new volume will have immediate effect instead of waiting for next song
- After the bot timed out (not getting any songs for 3 minutes), it will recreate the background task loop for checking queue
- Will become speaker automatically