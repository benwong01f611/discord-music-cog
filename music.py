import asyncio
import functools
import itertools
import math
import random
import os
import time

import discord
import youtube_dl
from async_timeout import timeout
from discord.ext import commands, bridge

import subprocess
import shutil
import re
import traceback
import json
import base64
import io

# Silence useless bug reports messages
youtube_dl.utils.bug_reports_message = lambda: ''

# Error messages for returning meaningfull error message to user
error_messages = {
    "ERROR: Sign in to confirm your age\nThis video may be inappropriate for some users.": "This video is age-restricted",
    "Video unavailable": "Video Unavailable",
    "ERROR: Private video\nSign in if you've been granted access to this video": "This video is private video"
}

# Insert authors' id in here, user in this set are allowed to use command "runningservers"
authors = (,)

class VoiceError(Exception):
    pass

class YTDLError(Exception):
    pass

class FFMPEGSource(discord.PCMVolumeTransformer):
    def __init__(self, ctx, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5, seek=None):
        super().__init__(source, volume)
        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        try:
            self.duration = self.parse_duration(int(data.get('duration')))
        except:
            self.duration = "Unknown"
        try:
            self.duration_raw = self.parse_duration_raw(int(data.get('duration')))
        except:
            self.duration = "Unknown"
        self.duration_int = int(data.get('duration'))

    def __str__(self):
        return f"**{self.title}**"

    # Parse the duration to xx days xx hours xx minutes xx seconds
    @staticmethod
    def parse_duration(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration = []
        if days > 0:
            duration.append(f"{days} days")
        if hours > 0:
            duration.append(f"{hours} hours")
        if minutes > 0:
            duration.append(f"{minutes} minutes")
        if seconds > 0:
            duration.append(f"{seconds} seconds")

        return " ".join(duration)
    
    # Parse the duration to 00:00:00:00
    @staticmethod
    def parse_duration_raw(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        
        durations = []
        if days > 0:
            durations.append(str(days))
        if hours > 0:
            durations.append(("0" if days and hours < 10 else "") + f"{hours}")
        durations.append(("0" if hours and minutes < 10 else "") + f"{minutes}")
        durations.append(("0" if seconds < 10 else "") + f"{seconds}")
        
        return ':'.join(durations)

class YTDLSource(discord.PCMVolumeTransformer):
    # Commandline options for youtube-dl and ffmpeg
    YTDL_OPTIONS_PLAYLIST = {
        'format': 'bestaudio/best',
        'extractaudio': True,
        'audioformat': 'mp3',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
        'extract_flat': 'in_playlist',
    }
    YTDL_OPTIONS = {
        'format': 'bestaudio/best',
        'extractaudio': True,
        'audioformat': 'mp3',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
    }
    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn',
    }

    ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)
    ytdl_playlist = youtube_dl.YoutubeDL(YTDL_OPTIONS_PLAYLIST)

    def __init__(self, ctx, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5, seek=None):
        super().__init__(source, volume)

        self.requester = data.get('requester')
        self.channel = ctx.channel
        self.data = data

        self.uploader = data.get('uploader')
        self.uploader_url = data.get('uploader_url')
        date = data.get('upload_date')
        self.upload_date = date[6:8] + '.' + date[4:6] + '.' + date[0:4]
        self.title = data.get('title')
        self.thumbnail = data.get('thumbnail')
        self.description = data.get('description')
        try:
            self.duration = self.parse_duration(int(data.get('duration')))
        except:
            self.duration = "Unknown"
        try:
            self.duration_raw = self.parse_duration_raw(int(data.get('duration')))
        except:
            self.duration_raw = "Unknown"
        self.duration_int = int(data.get('duration'))
        self.tags = data.get('tags')
        self.url = data.get('webpage_url')
        self.views = data.get('view_count')
        self.likes = data.get('like_count')
        self.dislikes = data.get('dislike_count')
        self.stream_url = data.get('url')

    def __str__(self):
        return '**{0.title}** by **{0.uploader}**'.format(self)

    @classmethod
    async def create_source(self, ctx, search: str, *, loop: asyncio.BaseEventLoop = None, requester=None, seek=None):
        loop = loop or asyncio.get_event_loop()

        # Extract data with youtube-dl
        partial = functools.partial(self.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        # Return error if nothing can be found
        if data is None:
            return await self.respond(ctx.ctx, f"Couldn\'t find anything that matches `{search}`")

        # process_info retrieves the first entry of the returned data, but the data could be the entry itself
        if 'entries' not in data:
            process_info = data
        else:
            process_info = None
            for entry in data['entries']:
                if entry:
                    process_info = entry
                    break

            if process_info is None:
               return await self.respond(ctx.ctx, f"Couldn\'t find anything that matches `{search}`")

        # Retrieve the video details
        webpage_url = process_info['webpage_url']
        partial = functools.partial(self.ytdl.extract_info, webpage_url, download=False)
        processed_info = await loop.run_in_executor(None, partial)

        if processed_info is None:
            return await self.respond(ctx.ctx, f"Couldn\'t fetch `{webpage_url}`")

        if 'entries' not in processed_info:
            info = processed_info
        else:
            info = None
            while info is None:
                try:
                    info = processed_info['entries'].pop(0)
                except IndexError:
                    return await self.respond(ctx.ctx, f"Couldn\'t retrieve any matches for `{webpage_url}`")
        # requester for saving the user who plays this song, shown in command now
        info["requester"] = requester
        # If seeking, ask ffmpeg to start from a specific position, else simply return the object
        if seek is not None:
            seek_option = self.FFMPEG_OPTIONS.copy()
            seek_option['before_options'] += " -ss " + self.parse_duration_raw(seek)
            return self(ctx, discord.FFmpegPCMAudio(info['url'], **seek_option), data=info)
        else:
            return self(ctx, discord.FFmpegPCMAudio(info['url'], **self.FFMPEG_OPTIONS), data=info)

    # Parse the duration to xx days xx hours xx minutes xx seconds
    @staticmethod
    def parse_duration(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration = []
        if days > 0:
            duration.append(f"{days} days")
        if hours > 0:
            duration.append(f"{hours} hours")
        if minutes > 0:
            duration.append(f"{minutes} minutes")
        if seconds > 0:
            duration.append(f"{seconds} seconds")

        return " ".join(duration)
    
    # Parse the duration to 00:00:00:00
    @staticmethod
    def parse_duration_raw(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        
        durations = []
        if days > 0:
            durations.append(str(days))
        if hours > 0:
            durations.append(("0" if days and hours < 10 else "") + f"{hours}")
        durations.append(("0" if hours and minutes < 10 else "") + f"{minutes}")
        durations.append(("0" if seconds < 10 else "") + f"{seconds}")
        
        return ':'.join(durations)

class Song:
    __slots__ = ('source', 'requester', 'starttime', 'pause_time', 'pause_duration', 'paused', 'isFile')

    # starttime stores when does the song start
    # pause_duration stores how long does the song being paused, updates when the song resumes
    # pause_time stores when does the song paused, used for calculating the pause_duration
    def __init__(self, source, isFile=False): 
        self.source = source
        self.requester = source.requester
        self.starttime = None
        self.pause_duration = 0
        self.pause_time = 0
        self.paused = False
        self.isFile = isFile

    def create_embed(self, status: str):
        # If a new song is being played, it will simply display how long the song is
        # But if the command now is being executed, it will show how long the song has been played
        if self.paused:
            self.pause_duration += time.time() - self.pause_time
            self.pause_time = time.time()
        embed = (discord.Embed(title='Now playing',
                               description=f"```css\n{self.source.title}\n```",
                               color=discord.Color.blurple())
                 .add_field(name='Duration', value=(self.source.duration if status == "play" else YTDLSource.parse_duration_raw(int(time.time() - self.starttime - self.pause_duration)) + "/" + self.source.duration_raw))
                 .add_field(name='Requested by', value=self.requester.mention))
        # If it is not a file, it is a youtube video
        if not self.isFile:
            embed.add_field(name='Uploader', value=f"[{self.source.uploader}]({self.source.uploader_url})")
            embed.add_field(name='URL', value=f"[Click]({self.source.url})")
            embed.set_thumbnail(url=self.source.thumbnail)

        return embed


class SongQueue(asyncio.Queue):
    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(itertools.islice(self._queue, item.start, item.stop, item.step))
        else:
            return self._queue[item]

    def __iter__(self):
        return self._queue.__iter__()

    def __len__(self):
        return self.qsize()

    def clear(self):
        self._queue.clear()

    def shuffle(self):
        random.shuffle(self._queue)

    def remove(self, index: int):
        del self._queue[index]


class VoiceState:
    def __init__(self, bot: commands.Bot, ctx, cog):
        self.bot = bot
        self._ctx = ctx

        self.current = None
        self.voice = None
        self.next = asyncio.Event()
        self.songs = SongQueue()

        self._loop = False
        self._volume = 0.5

        self.audio_player = bot.loop.create_task(self.audio_player_task())
        self.skipped = False
        self.pause_time = 0.0
        self.pause_duration = 0.0

        self.loopqueue = False
        self.seeking = False
        self.guild_id = ctx.guild.id

        self.voice_state_updater = bot.loop.create_task(self.update_voice_state())
        self.timer = 0
        self.volume_updater = None
        self.listener_task = None

        self.debug = {"debug": False, "channel": None, "debug_log": False}

        # Create task for checking is the bot alone
        self.listener_task = self.bot.loop.create_task(self.check_user_listening())

        self.forbidden = False

        self.cog = cog

    def recreate_bg_task(self, ctx, cog):
        self.__init__(self.bot, ctx, cog)

    def __del__(self):
        if self.audio_player:
            self.audio_player.cancel()

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value: bool):
        self._loop = value

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = value

    @property
    def is_playing(self):
        return self.voice and self.current
    
    # Function for seeking
    async def seek(self, seconds, isLocal):
        # Recreate ffmpeg object
        if isLocal:
            self.current = await self.create_song_source(self._ctx, self.current.source.url, title=self.current.source.title, requester=self.current.source.requester, seek=seconds)
        else:
            self.current = await self.create_song_source(self._ctx, self.current.source.url, requester=self.current.source.requester, seek=seconds)
        # Update volume
        self.current.source.volume = self._volume
        # Stop the current playing song
        self.voice.stop()
        # Play the seeked song
        self.voice.play(self.current.source, after=self.play_next_song)
        # Update the starttime since the song was seeked
        self.current.starttime = time.time() - self.seek_time
        self.volume_updater.cancel()
        self.volume_updater = self.bot.loop.create_task(self.update_volume())

    async def update_volume(self):
        # If it is not playing, dont check, also the task will be recreated when new song is being played
        while self.is_playing:
            # Without sleep, it will cause lag (at least it lagged on my laptop)
            await asyncio.sleep(1)
            # If the volume is updated, update it
            if not isinstance(self.current, dict) and self.current and self.current.source.volume != self._volume:
                self.current.source.volume = self._volume
    
    async def create_song_source(self, ctx, url, title=None, requester=None, seek=None):
        if "local@" in url:
            # It is a local file
            url = url[6:]
            try:
                # Try to get the duration of the uploaded file
                duration = str(int(float(subprocess.check_output(f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{url}\"", shell=True).decode("ascii").replace("\r", "").replace("\n", ""))))
            except:
                return "error"
            # Return the song object with ffmpeg
            if seek is not None:
                return Song(FFMPEGSource(ctx, discord.FFmpegPCMAudio(url, before_options="-ss " + YTDLSource.parse_duration_raw(seek)), data={'duration': duration, 'title': title, 'url': "local@" + url, 'requester': requester}, seek=seek), True)
            else:
                return Song(FFMPEGSource(ctx, discord.FFmpegPCMAudio(url), data={'duration': duration, 'title': title, 'url': "local@" + url, 'requester': requester}), True)
        else:
            return Song(await YTDLSource.create_source(ctx, url, loop=self.bot.loop, requester=requester, seek=seek))

    async def check_user_listening(self):
        while True:
            await asyncio.sleep(1)
            try:
                # If there is only 1 member in the voice channel, starts the checking task
                if self.voice and len(self.voice.channel.members) == 1:
                    self.timer = 0
                    # 180 seconds = 3 minutes, if the bot is alone for 3 minutes it will leave the channel
                    while self.timer != 180:
                        await asyncio.sleep(1)
                        self.timer += 1
                        try:
                            # If there are at least 2 members in the channel or being kicked out of the channel, reset the timer and break the loop
                            if len(self.voice.channel.members) > 1 or self.me not in self.voice.channel.members:
                                self.timer = 0
                                break
                        except: pass
                    # Leave the channel and stop everything
                    # Case 1: only 1 member in the channel and the member is the bot itself
                    # Case 2: the bot is kicked out from the channel
                    if (len(self.voice.channel.members) == 1 and self.me in self.voice.channel.members) or self.me not in self.voice.channel.members:
                        await self.stop(leave=True)
                        break
            except: pass
                
    # Update voice state guild object in background
    async def update_voice_state(self):
        await asyncio.sleep(3)
        while self.voice:
            await asyncio.sleep(1)
            guild = self.bot.get_guild(self.guild_id)
            if guild is None:
                print("[ERROR] Couldn't retrieve guild " + str(self.guild_id))
            else:
                # If the bot is kicked, the voice_client should be None
                if guild.voice_client:
                    self.voice = guild.voice_client
                else:
                    await self.stop(leave=True)
                    self.voice = None
                self.me = guild.me

    async def audio_player_task(self):
        while True:
            self.next.clear()
            if self.forbidden:
                if "local@" in self.current.source.url:
                    self.current = await self.create_song_source(self._ctx, self.current.source.url, title=self.current.source.title, requester=self.current.source.requester)
                else:
                    self.current = await self.create_song_source(self._ctx, self.current.source.url, requester=self.current.source.requester)
            else:
                if not self.loop:
                    # Try to get the next song within 2 minutes.
                    # If no song will be added to the queue in time,
                    # the player will disconnect due to performance
                    # reasons.
                    try:
                        async with timeout(120):  # 2 minutes
                            # If it is skipped, clear the current song
                            if self.skipped:
                                self.current = None
                            # Get the next song
                            self.current = await self.songs.get()
                            # If the url contains local@, it is a local file
                            if "local@" in self.current["url"]:
                                self.current = await self.create_song_source(self._ctx, self.current["url"], title=self.current["title"], requester=self.current["user"])
                            else:
                                self.current = await self.create_song_source(self._ctx, self.current["url"], requester=self.current["user"])
                            if self.current != "error":
                                # If loop queue, put the current song back to the end of the queue
                                if self.loopqueue:
                                    await self.songs.put({"url": self.current.source.url, "title": self.current.source.title, "user": self.current.source.requester, "duration": self.current.source.duration_int})
                                self.skipped = False
                                self.stopped = False
                    except asyncio.TimeoutError:
                        return await self.stop(leave=True)
                else:
                    # Loop but skipped, proceed to next song and keep looping
                    if self.skipped or self.stopped:
                        self.current = None
                        try:
                            async with timeout(120):  # 2 minutes
                                self.current = await self.songs.get()
                                if "local@" in self.current["url"]:
                                    self.current = await self.create_song_source(self._ctx, self.current["url"], title=self.current["title"], requester=self.current["user"])
                                else:
                                    self.current = await self.create_song_source(self._ctx, self.current["url"], requester=self.current["user"])
                                if self.current != "error":
                                    self.skipped = False
                                    self.stopped = False
                        except asyncio.TimeoutError:
                            return await self.stop(leave=True)
                    else:
                        # Looping, get the looped song
                        if "local@" in self.current.source.url:
                            self.current = await self.create_song_source(self._ctx, self.current.source.url, title=self.current.source.title, requester=self.current.source.requester)
                        else:
                            self.current = await self.create_song_source(self._ctx, self.current.source.url, requester=self.current.source.requester)
            if self.current != "error":
                self.current.source.volume = self._volume
                await asyncio.sleep(0.25)
                self.start_time = time.time()
                self.current.starttime = time.time()
                if not self.forbidden:
                    self.message = await self.current.source.channel.send(embed=self.current.create_embed("play"), view=PlayerControlView(self.bot, self))
                self.forbidden = False
                self.voice.play(self.current.source, after=self.play_next_song)
                # Create task for updating volume
                self.volume_updater = self.bot.loop.create_task(self.update_volume())
                await self.next.wait()
                # Delete the message of the song playing
                if not self.forbidden:
                    try:
                        await self.message.delete()
                    except:
                        pass

    def play_next_song(self, error=None):
        end_time = time.time()
        play_duration = end_time - self.start_time
        if play_duration < 1 and self.current.source.duration_int != 1:
            self.forbidden = True
            self.next.set()
            return
        else:
            self.forbidden = False
        if error:
            print(f"Song finished with error: {str(error)}")
        # If it is not looping or seeking, clear the current song
        if not self.loop and not self.seeking:
            self.current = None
        # If it is not seeking, send a signal for await self.next.wait() to stop
        if not self.seeking:
            self.next.set()
        else:
            self.seeking = False

    def skip(self):
        # Skip the song by stopping the current song
        self.skipped = True
        if self.is_playing:
            self.voice.stop()

    async def stop(self, leave=False):
        # Clear the queue
        self.songs.clear()
        self.current = None
        if self.volume_updater and not self.volume_updater.done():
            self.volume_updater.cancel()
        self.volume_updater = None
        if self.voice:
            # Stops the voice
            self.voice.stop()
            # If the bot should leave, then leave and cleanup things
            if leave:
                if self.voice_state_updater and not self.voice_state_updater.done():
                    self.voice_state_updater.cancel()
                self.voice_state_updater = None
                try:
                    await self.voice.disconnect()
                except:
                    pass
                self.voice = None
        if self.audio_player and not self.audio_player.done():
            self.audio_player.cancel()
            try:
                await self.message.delete()
            except:
                pass
        if leave:
            if self.listener_task and not self.listener_task.done():
                self.listener_task.cancel()

class SearchMenu(discord.ui.Select):
    def __init__(self, bot, options_raw, cog, ctx):
        self.bot = bot
        self.cog = cog
        self.ctx = ctx
        reaction_list = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        options = [discord.SelectOption(label=data["title"], description=f"Duration: {data['duration']}", value=data["index"], emoji=reaction_list[data["index"]]) for data in options_raw]
        options.append(discord.SelectOption(label="Cancel", description="Cancel the search", value=11, emoji="❌"))
        self.data = options_raw
        self.completed = False
        super().__init__(
            placeholder="Select the desired song...",
            min_values=1,
            max_values=1,
            options=options
        )
    async def respond(self, message_reply, message: str=None, embed: discord.Embed=None, reply: bool=True, view=None):
        if reply:
                return await message_reply.reply(message, embed=embed, mention_author=False, view=view)
        else:
                return await message_reply.channel.send(message, embed=embed, view=view)
    async def join(self, ctx, interaction_message):
        destination = ctx.author.voice.channel

        # Check permission
        if not destination.permissions_for(ctx.me).connect:
            return await self.respond(interaction_message, "No permission to join the voice channel!")
        # Connect to the channel
        ctx.voice_state.voice = await destination.connect()
        await self.respond(interaction_message, f"Joined **{destination}**.")
        
        # If the channel is a stage channel, wait for 1 second and try to unmute itself
        if isinstance(ctx.voice_state.voice.channel, discord.StageChannel):
            try:
                await asyncio.sleep(1)
                await ctx.me.edit(suppress=False)
            except:
                # Unable to unmute itself, ask admin to invite the bot to speak (auto)
                await self.respond(interaction_message, "I have no permission to speak! Please invite me to speak.")
        # Clear all music file
        if os.path.isdir(f"./tempMusic/{ctx.guild.id}"):
            shutil.rmtree(f"./tempMusic/{ctx.guild.id}")
        await ctx.me.edit(deafen=True)

    async def callback(self, interaction):
        if int(self.values[0]) == 11:
            return await interaction.message.edit(embed=discord.Embed(title="Cancelled", description=None, color=discord.Color.green()), view=None)
        # Edit the message to reduce its size
        await interaction.message.edit(embed=discord.Embed(title="Selected:", description=self.data[int(self.values[0])]["title"], color=discord.Color.green()), view=None)
        await interaction.response.send_message("Selected " + self.data[int(self.values[0])]["title"])
        
        
        
        # Invoke the play command

        if not self.ctx.author.voice or not self.ctx.author.voice.channel:
            return await self.respond(interaction.message, 'You are not connected to any voice channel.')
        voice_client = (await self.bot.fetch_guild(interaction.guild_id)).voice_client
        if voice_client:
            if voice_client.channel != self.ctx.author.voice.channel:
                return await  self.respond(interaction.message, 'Bot is already in a voice channel.')
        #await self.cog._play(ctx=self.ctx, search=self.data[int(self.values[0])]["url"])
        ctx = self.ctx
        search = self.data[int(self.values[0])]["url"]
        if search == None:
            return await self.respond(interaction.message, "Please provide keywords or URL to play a song.")
        # Joins the channel if it hasn't
        if not ctx.voice_state.voice:
            ctx.from_play = True
            await self.join(ctx, interaction.message)
        # Errors may occur while joining the channel, if the voice is None, don't continue
        if not ctx.voice_state.voice:
            return
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(interaction.message, "You are not connected to any voice channel or the same voice channel.")

            if ctx.voice_client:
                if ctx.voice_client.channel != ctx.author.voice.channel:
                    return await self.respond(interaction.message, "Bot is already in a voice channel.")
        
        loop = self.bot.loop
        try:
            await self.respond(interaction.message, f"Searching for: **{search}**", reply=False)
            # Supports playing a playlist but it must be like https://youtube.com/playlist?
            if "/playlist?" in search:
                partial = functools.partial(YTDLSource.ytdl_playlist.extract_info, search, download=False)
                data = await loop.run_in_executor(None, partial)
                if data is None:
                    return await self.respond(interaction.message, f"Couldn\'t find anything that matches `{search}`")
                entries = data["entries"]
                playlist = []
                for pos, song in enumerate(entries):
                    # Youtube only, guess no one would play other than Youtube
                    url = "https://youtu.be/" + song["id"]
                    title = song["title"]
                    playlist.append({"pos": pos, "url": url, "title": title, "duration": int(song["duration"])})
                # Sort the playlist variable to match with the order in YouTube
                playlist.sort(key=lambda song: song["pos"])
                # Add all songs to the pending list
                for songs, entry in enumerate(playlist):
                    try:
                        duration = int(song["duration"])
                    except:
                        duration = 0
                    await ctx.voice_state.songs.put({"url": entry["url"], "title": entry["title"], "user": ctx.author, "duration": duration})
                await self.respond(interaction.message, f"Enqueued {songs+1} songs")
            else:
                # Just a single song
                try:
                    partial = functools.partial(YTDLSource.ytdl.extract_info, search, download=False)
                    data = await loop.run_in_executor(None, partial)
                except Exception as e:
                    # Get the error message from dictionary, if it doesn't exist in dict, return the original error message
                    message = error_messages.get(str(e), str(e))
                    return await self.respond(interaction.message, f"Error: {message}")
                if "entries" in data:
                    if len(data["entries"]) > 0:
                        data = data["entries"][0]
                    else:
                        return await self.respond(interaction.message, f"Couldn\'t find anything that matches `{search}`")
                # Add the song to the pending list
                try:
                    duration = int(data["duration"])
                except:
                    duration = 0
                await ctx.voice_state.songs.put({"url": data["webpage_url"], "title": data["title"], "user": ctx.author, "duration": duration})
                await self.respond(interaction.message, f"Enqueued {data['title']}")
            ctx.voice_state.stopped = False
        except YTDLError as e:
            await self.respond(interaction.message, f"An error occurred while processing this request: {str(e)}")
        self.completed = True

class SearchView(discord.ui.View):
    def __init__(self, bot, data, ctx, cog):
        self.bot = bot
        self.ctx = ctx
        self.data = data
        self.cog = cog
        super().__init__(timeout=60)
        self.add_item(SearchMenu(self.bot, data, cog, ctx))
    async def on_timeout(self):
        if not self.children[0].completed:
            await self.message.edit(embed=discord.Embed(title="Timed out", description=None, color=0xff0000), view=None)

class PlayerControlView(discord.ui.View):
    def __init__(self, bot, voice_state):
        self.bot = bot
        self.voice_state = voice_state
        super().__init__(timeout=None)

        self.children[4].label = "{} Looping".format("Disable" if self.voice_state._loop else "Enable")
        self.children[5].label = "{} Loop Queue".format("Disable" if self.voice_state.loopqueue else "Enable")
    
    @discord.ui.button(label="Pause", style=discord.ButtonStyle.primary, custom_id="0", emoji="⏸", disabled=False)
    async def pause(self, button, interaction):
        await interaction.response.defer()
        if self.voice_state.is_playing and self.voice_state.voice.is_playing():
            self.voice_state.voice.pause()
            # Sets the pause time
            self.voice_state.current.pause_time = time.time()
            self.voice_state.current.paused = True
        self.children[1].disabled = False
        button.disabled = True
        await interaction.message.edit(view=self)
    
    @discord.ui.button(label="Resume", style=discord.ButtonStyle.primary, custom_id="1", emoji="▶", disabled=True)
    async def resume(self, button, interaction):
        await interaction.response.defer()
        if self.voice_state.is_playing and self.voice_state.voice.is_paused():
            self.voice_state.voice.resume()
            # Updates internal data for handling song progress that was paused
            self.voice_state.current.pause_duration += time.time() - self.voice_state.current.pause_time
            self.voice_state.current.pause_time = 0
            self.voice_state.current.paused = False
        self.children[0].disabled = False
        button.disabled = True
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary, custom_id="2", emoji="⏭", disabled=False)
    async def skip(self, button, interaction):
        await interaction.response.defer()
        self.voice_state.skip()
        #await interaction.message.edit(view=self)
    
    @discord.ui.button(label="Stop", style=discord.ButtonStyle.primary, custom_id="3", emoji="⏹", disabled=False)
    async def stop(self, button, interaction):
        await interaction.response.defer()
        self.voice_state.songs.clear()

        if self.voice_state.is_playing:
            await self.voice_state.stop()
            self.voice_state.stopped = True
        #await interaction.message.edit(view=self)

    @discord.ui.button(label="Loop", style=discord.ButtonStyle.primary, custom_id="4", emoji="🔂", disabled=False)
    async def loop(self, button, interaction):
        await interaction.response.defer()
        self.voice_state.loop = not self.voice_state.loop
        self.children[4].label = "{} Looping".format("Disable" if self.voice_state._loop else "Enable")
        self.children[5].label = "{} Loop Queue".format("Disable" if self.voice_state.loopqueue else "Enable")
        await interaction.message.edit(view=self)
    
    @discord.ui.button(label="Loop Queue", style=discord.ButtonStyle.primary, custom_id="5", emoji="🔂", disabled=False)
    async def loopqueue(self, button, interaction):
        await interaction.response.defer()
        self.voice_state.loopqueue = not self.voice_state.loopqueue
        try:
            if self.voice_state.loopqueue:
                await self.voice_state.songs.put({"url": self.voice_state.current.source.url, "title": self.voice_state.current.source.title, "user": self.voice_state.current.source.requester, "duration": self.voice_state.current.source.duration_int})
        except:
            pass
        self.children[4].label = "{} Looping".format("Disable" if self.voice_state._loop else "Enable")
        self.children[5].label = "{} Loop Queue".format("Disable" if self.voice_state.loopqueue else "Enable")
        await interaction.message.edit(view=self)

class Music(commands.Cog):
    # Get the total duration from the queue or playlist
    def getTotalDuration(self, data):
        total_duration = 0
        for song in data:
            total_duration += song["duration"]
        return total_duration
    
    # Return a discord.Embed() object, provides 5 songs from the queue/playlist depending on the page requested
    # Parameter "page" greater than the pages that the queue has will set the page to the last page
    # Invalid parameter "page" will display the first page
    def queue_embed(self, data, page, header, description, song_id):
        items_per_page = 5
        pages = math.ceil(len(data) / items_per_page)
        if page < 1:
            page = 1
        page = min(pages, page)
        start = (page - 1) * items_per_page
        end = start + items_per_page
        queue = ''
        url = "https://youtu.be/" if song_id == "id" else ""
        # If data has children, iterates through all children and create the body
        if len(data):
            for i, song in enumerate(data[start:end], start=start):
                if "local@" in song[song_id]:
                    title = song['title'].replace('_', '\\_')
                    try:
                        duration = YTDLSource.parse_duration(song['duration'])
                    except:
                        duration = "Unknown"
                    queue += f"`{i+1}.` **{title}** ({duration})\n"
                else:
                    try:
                        duration = YTDLSource.parse_duration_raw(song['duration'])
                    except:
                        duration = "Unknown"
                    queue += f"`{i+1}.` [**{song['title']}**]({url}{song[song_id]}) ({duration})\n"
        else:
            queue = "No songs in queue..."
        embed = (discord.Embed(
                    title=header,
                    description=description)
                .add_field(name=f"**{len(data)} tracks** - {YTDLSource.parse_duration(self.getTotalDuration(data))}", value=queue)
                .set_footer(text=f"Viewing page {page}/{pages}")
            )
        return embed

    # Function for responding to the user
    # reply=True will cause the bot to reply to the user (discord function)
    async def respond(self, ctx, message: str=None, embed: discord.Embed=None, reply: bool=True, view=None):
        if isinstance(ctx, dict): 
            if reply:
                if isinstance(ctx["ctx"], discord.ext.bridge.context.BridgeExtContext): # Prefix
                    return await ctx["ctx"].reply(message, embed=embed, mention_author=False, view=view)
                else:
                    return await ctx["ctx"].respond(message, embed=embed, view=view)

            else:
                return await ctx["channel"].send(message, embed=embed, view=view)
                    
        else: # Debugging
            if reply:
                if isinstance(ctx, discord.ext.bridge.context.BridgeExtContext): # Prefix
                    return await ctx.reply(message, embed=embed, mention_author=False, view=view)
                else:
                    return await ctx.respond(message, embed=embed, view=view)
            else:
                if isinstance(ctx, discord.ext.bridge.context.BridgeExtContext): # Prefix
                    return await ctx.send(message, embed=embed, view=view)
                else:
                    return await ctx.respond(message, embed=embed, view=view)
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    # Get the voice state from dictionary, create if it does not exist
    def get_voice_state(self, ctx):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx, self)
            self.voice_states[ctx.guild.id] = state
        # When invoking this function, check whether the audio player task is done
        # If it is done, recreate the task
        if state.audio_player and state.audio_player.done():
            state.recreate_bg_task(ctx, self)
        return state

    # Stop all async tasks for each voice state
    def cog_unload(self):
        for state in self.voice_states.values():
            # Leave the channel first or else unexpected behaviour will occur
            self.bot.loop.create_task(state.stop(leave=True))
        voice_states = self.voice_states.keys()
        # Remove all voice states from the memory
        for voicestate in voice_states:
            del self.voice_states[voicestate]
        try:
            shutil.rmtree("./tempMusic")
        except:
            pass

    # All commands from this cog cannot be used in DM
    def cog_check(self, ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage("This command can't be used in DM channels.")
        return True

    # Before invoking any commands, get the voice state first
    # Update the context object also
    async def cog_before_invoke(self, ctx):
        self.get_voice_state(ctx)._ctx = ctx
        ctx.voice_state = self.get_voice_state(ctx)
        ctx.debug = ctx.voice_state.debug
        ctx.ctx = {"channel": ctx.channel, "message": ctx.message, "ctx":ctx}

    # Return a meaningful message to user when error occurs
    # If debug log is enabled, return the traceback for debugging use. The debug message is encoded in base64 in case leaking the directory info
    async def cog_command_error(self, ctx, error):
        formatted_error = traceback.format_exc()
        if str(error) == "This command can't be used in DM channels.":
            return await ctx.send("This command can't be used in DM channels.")
        await ctx.send(f"Error: {error}")
        if hasattr(ctx, "voice_state") and ctx.voice_state:
            if ctx.voice_state.debug["debug_log"]:
                await ctx.send("Debug file", file=discord.File(io.BytesIO(base64.b64encode(formatted_error.encode("utf-8"))), f"{ctx.guild.id}_error.txt"))

    @bridge.bridge_command(name='join', invoke_without_subcommand=True, description="Joins the current voice channel")
    async def _join(self, ctx):
        # Joins the channel

        # If the user is not in any voice channel, don't join
        if not ctx.author.voice or not ctx.author.voice.channel:
            await self.respond(ctx.ctx, "You are not connected to any voice channel.")
            return False
        
        # If the bot is in the voice channel, check whether it is in the same voice channel or not
        if ctx.voice_client:
            if ctx.voice_client.channel.id != ctx.author.voice.channel.id:
                await self.respond(ctx.ctx, "Bot is already in a voice channel.")
                return False
            else:
                if not ctx.from_play:
                    await self.respond(ctx.ctx, "Bot is already in your voice channel.")
                    return False
                return True

        destination = ctx.author.voice.channel

        # Check permission
        if not destination.permissions_for(ctx.me).connect:
            return await self.respond(ctx.ctx, "No permission to join the voice channel!")

        # Connect to the channel
        ctx.voice_state.voice = await destination.connect()
        await self.respond(ctx.ctx, f"Joined **{destination}**.")
        
        # If the channel is a stage channel, wait for 1 second and try to unmute itself
        if isinstance(ctx.voice_state.voice.channel, discord.StageChannel):
            try:
                await asyncio.sleep(1)
                await ctx.me.edit(suppress=False)
            except:
                # Unable to unmute itself, ask admin to invite the bot to speak (auto)
                await self.respond(ctx.ctx, "I have no permission to speak! Please invite me to speak.")
        # Clear all music file
        if os.path.isdir(f"./tempMusic/{ctx.guild.id}"):
            shutil.rmtree(f"./tempMusic/{ctx.guild.id}")
        await ctx.me.edit(deafen=True)

    @bridge.bridge_command(name='summon', description="Summon the bot to current voice channel (Requires Move Member permission)")
    #async def _summon(self, ctx, *, channel:discord.Option(discord.VoiceChannel, "Summon the bot to current voice channel (Requires Move Member permission)")=None):
    async def _summon(self, ctx, *, channel=None):
        # Summon the bot to other channel or the current channel

        # Didn't join a channel or specify a channel to join
        if not channel and not ctx.author.voice:
            return await self.respond(ctx.ctx, 'You are neither connected to a voice channel nor specified a channel to join.')
        channel_find = None
        # Try to find the channel
        try:
            channel_find = ctx.guild.get_channel(int(channel))
        except:
            try:
                channel_find = ctx.guild.get_channel(int(channel[2:-1]))
            except:
                if channel_find is None and not ctx.author.voice:
                    return await self.respond(ctx.ctx, "Unable to find the specific channel.")
        if channel_find is None:
            return await self.respond(ctx.ctx, "Unable to find the specific channel.")
        # Only allow members with "Move member" permission to use this command
        if not ctx.author.guild_permissions.move_members:
            return await self.respond(ctx.ctx, "Only members with \"Move Member\" permission are allowed to use this command.")
        
        destination = channel_find or ctx.author.voice.channel

        # Check permission
        if not destination.permissions_for(ctx.me).connect:
            return await self.respond(ctx.ctx, "No permission to join the voice channel!")

        # Move to the specific channel and update internal memory
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            msg = await self.respond(ctx.ctx, f"Switched from **{ctx.voice_state.voice.channel.name}** to **{destination.name}**.")
            ctx.voice_state.voice = msg.guild.voice_client
        else:
            # Not in any channel, use connect instead
            ctx.voice_state.voice = await destination.connect()
            msg = await self.respond(ctx.ctx, f"Joined **{destination.name}**.")
        # If the channel is a stage channel, wait for 1 second and try to unmute itself
        if isinstance(ctx.voice_state.voice.channel, discord.StageChannel):
            try:
                await asyncio.sleep(1)
                await ctx.me.edit(suppress=False)
            except:
                await self.respond(ctx.ctx, "I have no permission to speak! Please invite me to speak")

    @bridge.bridge_command(name='leave', aliases=['disconnect', 'dc'], description="Leave the voice channel")
    async def _leave(self, ctx):
        # Clears the queue and leave the channel

        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")

            if not ctx.voice_state.voice:
                return await self.respond(ctx.ctx, 'Not connected to any voice channel.')
        if isinstance(ctx, discord.ext.bridge.context.BridgeExtContext):
            await ctx.message.add_reaction('⏹')
        else:
            await self.respond(ctx.ctx, "Left channel")
        # Leaves the channel and delete the data from memory
        await ctx.voice_state.stop(leave=True)
        del self.voice_states[ctx.guild.id]

    @bridge.bridge_command(name='volume', aliases=['v'], description="Show/Adjust the volume of the bot")
    #async def _volume(self, ctx, volume:discord.Option(int, "Volume (0-100)")=None):
    async def _volume(self, ctx, volume=None):
        # If the parameter is set, try to parse it as an integer
        try:
            if volume is not None:
                volume = int(volume)
        except:
            return await self.respond(ctx.ctx, "Unable to parse the volume.")
        # Sets the volume of the player
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")
        
        # If the bot is not connected to any voice channel, return error
        if not ctx.voice_state.voice:
            return await self.respond(ctx.ctx, 'Not connected to any voice channel')

        # If volume is not none, the user is updating the volume
        if volume is not None:
            # The volume should be 0 < volume < 100
            if 0 > volume or volume > 100:
                return await self.respond(ctx.ctx, 'Volume must be between 0 and 100.')
            # The volume should be 0.00~1.00
            ctx.voice_state.volume = volume / 100
            await self.respond(ctx.ctx, f"Volume of the player set to {volume}%")
        else:
            # Return the current volume
            return await self.respond(ctx.ctx, f"Current volume: {int(ctx.voice_state.volume*100)}%")

    @bridge.bridge_command(name='now', aliases=['current', 'playing'], description="Display current song")
    async def _now(self, ctx):
        # Display currently playing song
        if ctx.voice_state.current is None:
            return await self.respond(ctx.ctx, "There is no songs playing right now.")
        await self.respond(ctx.ctx, embed=ctx.voice_state.current.create_embed("now"))

    @bridge.bridge_command(name='pause', description="Pause the song")
    async def _pause(self, ctx):
        # Pauses the player
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")
        # If the bot is playing, pause it
        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            if isinstance(ctx, discord.ext.bridge.context.BridgeExtContext):
                await ctx.message.add_reaction('⏸')
            else:
                await self.respond(ctx.ctx, "Music paused.")
            
            # Sets the pause time
            ctx.voice_state.current.pause_time = time.time()
            ctx.voice_state.current.paused = True
        else:
            await self.respond(ctx.ctx, "There is no songs playing right now or the music is already paused.")

    @bridge.bridge_command(name='resume', aliases=['r'], description="Resume paused song")
    async def _resume(self, ctx):
        # Resumes the bot
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")
        # If the bot is paused, resume it
        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()
            if isinstance(ctx, discord.ext.bridge.context.BridgeExtContext):
                await ctx.message.add_reaction('▶')
            else:
                await self.respond(ctx.ctx, "Music resumed.")
            # Updates internal data for handling song progress that was paused
            ctx.voice_state.current.pause_duration += time.time() - ctx.voice_state.current.pause_time
            ctx.voice_state.current.pause_time = 0
            ctx.voice_state.current.paused = False
        else:
            await self.respond(ctx.ctx, "There is no songs paused right now.") 

    @bridge.bridge_command(name='stop', description="Remove all songs in queue and stop the bot")
    async def _stop(self, ctx):
        # Stops the bot and clears the queue
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")
        ctx.voice_state.songs.clear()

        if ctx.voice_state.is_playing:
            await ctx.voice_state.stop()
            ctx.voice_state.stopped = True
            if isinstance(ctx, discord.ext.bridge.context.BridgeExtContext):
                await ctx.message.add_reaction('⏹')
            else:
                await self.respond(ctx.ctx, "Music stopped.")

    @bridge.bridge_command(name='skip', aliases=['s'], description="Skip current song")
    async def _skip(self, ctx):
        # Skips the current song
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")
        if not ctx.voice_state.is_playing:
            return await self.respond(ctx.ctx, 'Not playing any music right now...')
        
        if isinstance(ctx, discord.ext.bridge.context.BridgeExtContext):
            await ctx.message.add_reaction('⏭')
        else:
            await self.respond(ctx.ctx, "Music skipped.")
        ctx.voice_state.skip()

    @bridge.bridge_command(name='queue', aliases=["q"], description="Show song queue")
    #async def _queue(self, ctx, *, page:discord.Option(int, "Page number")=None):
    async def _queue(self, ctx, *, page=None):
        # Shows the queue, add page number to view different pages
        if page is not None:
            try:
                page = int(page)
            except:
                page = 1
        else:
            page = 1
        if len(ctx.voice_state.songs) == 0 and ctx.voice_state.current is None:
            return await self.respond(ctx.ctx, 'Empty queue.')
        
        # Invoking queue while the bot is retrieving another song will cause error, wait for 1 second
        while ctx.voice_state.current is None or isinstance(ctx.voice_state.current, dict):
            await asyncio.sleep(1)
        return await self.respond(ctx.ctx, embed=self.queue_embed(ctx.voice_state.songs, page, f"Currently Playing", f"[**{ctx.voice_state.current.source.title}**]({ctx.voice_state.current.source.url}) ({YTDLSource.parse_duration(ctx.voice_state.current.source.duration_int - int(time.time() - ctx.voice_state.current.starttime - ctx.voice_state.current.pause_duration))} Left)", "url"))
    
    @bridge.bridge_command(name='shuffle', description="Shuffle the song queue")
    async def _shuffle(self, ctx):
        # Shuffles the queue
        # If the user invoking this command is not in the same channel, return error
        if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
            return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")
        if len(ctx.voice_state.songs) == 0:
            return await self.respond(ctx.ctx, 'Empty queue.')

        ctx.voice_state.songs.shuffle()
        if isinstance(ctx, discord.ext.bridge.context.BridgeExtContext):
            await ctx.message.add_reaction('🔀')
        else:
            await self.respond(ctx.ctx, "Song queue shuffled.")

    @bridge.bridge_command(name='remove', description="Remove a song from queue")
    #async def _remove(self, ctx, index:discord.Option(int, "Index of the song")=None):
    async def _remove(self, ctx, index=None):
        if index is None:
            return await self.respond(ctx.ctx, "Please provide a valid song number in queue to remove.")
        # Try to parse the index of the song that is going to be removed
        try:
            index = int(index)
        except:
            return await self.respond(ctx.ctx, "Please provide a valid song number in queue to remove.")
        # If the user invoking this command is not in the same channel, return error
        if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
            return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")
        if ctx.voice_state.voice.channel != ctx.author.voice.channel:
            return
        if len(ctx.voice_state.songs) == 0:
            return await self.respond(ctx.ctx, 'Empty queue.')

        ctx.voice_state.songs.remove(index - 1)
        
        if isinstance(ctx, discord.ext.bridge.context.BridgeExtContext):
            await ctx.message.add_reaction('✅')
        else:
            await self.respond(ctx.ctx, "Song removed.")

    @bridge.bridge_command(name='loop', description="Toggle looping for current song")
    async def _loop(self, ctx):
        # Toggle the looping of the current song
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")
            if ctx.voice_state.voice.channel != ctx.author.voice.channel:
                return

        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        await self.respond(ctx.ctx, ("Enabled" if ctx.voice_state.loop else "Disabled") + " looping")

    @bridge.bridge_command(name='play', aliases=["p"], description="Plays a song or a playlist")
    #async def _play(self, ctx, *, search:discord.Option(str, "URL or keyword")=None):
    async def _play(self, ctx, *, search=None):
        # Plays a song, mostly from Youtube
        """Plays a song.
        If there are songs in the queue, this will be queued until the
        other songs finished playing.
        This command automatically searches from various sites if no URL is provided.
        A list of these sites can be found here: https://rg3.github.io/youtube-dl/supportedsites.html
        """
        
        if search == None:
            return await self.respond(ctx.ctx, "Please provide keywords or URL to play a song.")
        # Joins the channel if it hasn't
        if not ctx.voice_state.voice:
            ctx.from_play = True
            await ctx.invoke(self._join)
        # Errors may occur while joining the channel, if the voice is None, don't continue
        if not ctx.voice_state.voice:
            return
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")

            if ctx.voice_client:
                if ctx.voice_client.channel != ctx.author.voice.channel:
                    return await self.respond(ctx.ctx, "Bot is already in a voice channel.")
        
        loop = self.bot.loop
        try:
            await self.respond(ctx.ctx, f"Searching for: **{search}**", reply=False)
            # Supports playing a playlist but it must be like https://youtube.com/playlist?
            if "/playlist?" in search:
                partial = functools.partial(YTDLSource.ytdl_playlist.extract_info, search, download=False)
                data = await loop.run_in_executor(None, partial)
                if data is None:
                    return await self.respond(ctx.ctx, f"Couldn\'t find anything that matches `{search}`")
                entries = data["entries"]
                playlist = []
                for pos, song in enumerate(entries):
                    # Youtube only, guess no one would play other than Youtube
                    url = "https://youtu.be/" + song["id"]
                    title = song["title"]
                    playlist.append({"pos": pos, "url": url, "title": title, "duration": int(song["duration"])})
                # Sort the playlist variable to match with the order in YouTube
                playlist.sort(key=lambda song: song["pos"])
                # Add all songs to the pending list
                for songs, entry in enumerate(playlist):
                    try:
                        duration = int(song["duration"])
                    except:
                        duration = 0
                    await ctx.voice_state.songs.put({"url": entry["url"], "title": entry["title"], "user": ctx.author, "duration": duration})
                await self.respond(ctx.ctx, f"Enqueued {songs+1} songs")
            else:
                # Just a single song
                try:
                    partial = functools.partial(YTDLSource.ytdl.extract_info, search, download=False)
                    data = await loop.run_in_executor(None, partial)
                except Exception as e:
                    # Get the error message from dictionary, if it doesn't exist in dict, return the original error message
                    message = error_messages.get(str(e), str(e))
                    return await self.respond(ctx.ctx, f"Error: {message}")
                if "entries" in data:
                    if len(data["entries"]) > 0:
                        data = data["entries"][0]
                    else:
                        return await self.respond(ctx.ctx, f"Couldn\'t find anything that matches `{search}`")
                # Add the song to the pending list
                try:
                    duration = int(data["duration"])
                except:
                    duration = 0
                await ctx.voice_state.songs.put({"url": data["webpage_url"], "title": data["title"], "user": ctx.author, "duration": duration})
                await self.respond(ctx.ctx, f"Enqueued {data['title']}")
            ctx.voice_state.stopped = False
        except YTDLError as e:
            await self.respond(ctx.ctx, f"An error occurred while processing this request: {str(e)}")
            
    @bridge.bridge_command(name='search', description="Search a song from Youtube")
    #async def search(self, ctx, *, keyword:discord.Option(str, "Keyword")=None):
    async def search(self, ctx, *, keyword=None):
        # Search from Youtube and returns 10 songs
        if keyword == None:
            return await self.respond(ctx.ctx, "Please provide keywords to search for songs.")
        originalkeyword = keyword
        keyword = "ytsearch10:" + keyword
        data = YTDLSource.ytdl_playlist.extract_info(keyword, download=False)
        result = []
        # Get 10 songs from the result
        for index, entry in enumerate(data["entries"]):
            try:
                duration = YTDLSource.parse_duration(int(entry.get('duration')))
            except:
                duration = "Unknown"
            result.append(
                {
                    "title": entry.get("title"),
                    "duration": duration,
                    "url": entry.get('webpage_url', "https://youtu.be/" + entry.get('id')),
                    "index": index
                }
            )
        embed = discord.Embed(  title=f'Search results of {originalkeyword}',
                                description="Please select the search result by selecting the option in the menu",
                                color=discord.Color.green())
        # For each song, combine the details to a string
        for count, entry in enumerate(result):
            embed.add_field(name=f'{count+1}. {entry["title"]}', value=f'[Link]({entry["url"]})' + "\nDuration: " + entry["duration"] + "\n", inline=False)
        # Send the message of the results
        view = SearchView(self.bot, result, ctx, self)

        message = await self.respond(ctx.ctx, embed=embed, view=view)
        if isinstance(message, discord.Interaction):
            message = await message.original_message()
        view.message = message
    
    @bridge.bridge_command(name='musicreload', description="Reload the music bot")
    async def musicreload(self, ctx):
        # Disconnect the bot and delete voice state from internal memory in case something goes wrong
        try:
            await ctx.voice_state.stop(leave=True)
        except:
            pass
        try:
            await ctx.voice_client.disconnect()
        except:
            pass
        try:
            await ctx.voice_client.clean_up()
        except:
            pass
        del self.voice_states[ctx.guild.id]
        await self.respond(ctx.ctx, "Music bot reloaded.")

    @bridge.bridge_command(name="loopqueue", aliases=['lq'], description="Toggle looping for current queue")
    async def loopqueue(self, ctx):
        # Loops the queue
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")
        
        # Inverse the boolean
        ctx.voice_state.loopqueue = not ctx.voice_state.loopqueue
        # The current song will also loop if loop queue enabled
        try:
            if ctx.voice_state.loopqueue:
                await ctx.voice_state.songs.put({"url": ctx.voice_state.current.source.url, "title": ctx.voice_state.current.source.title, "user": ctx.voice_state.current.source.requester, "duration": ctx.voice_state.current.source.duration_int})
        except:
            pass
        await self.respond(ctx.ctx, ("Enabled" if ctx.voice_state.loopqueue else "Disabled") + " queue looping")

    @commands.command(name="playfile", aliases=["pf"], description="Plays an uploaded file")
    async def playfile(self, ctx, *, title=None):
        # Plays uploaded file
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")
        # No file proviced
        if len(ctx.message.attachments) == 0:
            return await self.respond(ctx.ctx, "No file provided!")
        # Joins the channel before playing
        if not ctx.voice_state.voice:
            state = await ctx.invoke(self._join)
            if state:
                return
        # Creates temporary folder for storing the audio file
        import os
        if not os.path.isdir("./tempMusic"):
            os.mkdir("./tempMusic")
        if not os.path.isdir("./tempMusic/" + str(ctx.guild.id)):
            os.mkdir("./tempMusic/" + str(ctx.guild.id))
        # Path is ./tempMusic/<guild_id>/<current_time>.<extension>
        filename = "./tempMusic/"+ str(ctx.guild.id) + "/" + str(int(time.time() * 10000000)) + "." + ctx.message.attachments[0].filename.split(".")[-1]
        # Saves the attachment
        await ctx.message.attachments[0].save(filename)
        # User can provide a title for the uploaded file
        if not title:
            title = ctx.message.attachments[0].filename
        # Tries to put it in queue, if it cannot parse the duration
        try:
            await ctx.voice_state.songs.put({"url": "local@" + filename, "title": title, "user": ctx.author, "duration": int(float(subprocess.check_output(f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{filename}\"", shell=True).decode("ascii").replace("\r", "").replace("\n", "")))})
        except:
            return await self.respond(ctx.ctx, "Unable to add this song, maybe it is not an audio file?")
        # Displaying filename with _ will cause discord to format the text, replace them with \_ to avoid this problem
        await self.respond(ctx.ctx, 'Enqueued {}'.format(title.replace("_", "\\_")))
        ctx.voice_state.stopped = False
    
    @commands.command(name="runningservers", aliases=["rs"])
    async def runningservers(self, ctx):
        # Check whether the user id is in the author list
        if ctx.author.id in authors:
            # Count how many servers are connected to a voice channel
            server_count, desc = 0, ''
            for guild_id, voice_state in self.voice_states.items():
                if voice_state.voice:
                    server_count += 1
                    desc += f'{self.bot.get_guild(guild_id).name} / {guild_id}\n'
            return await self.respond(ctx.ctx, embed=discord.Embed(title=f"Servers running music bot: {str(server_count)}", description=desc[:-1]))

    @bridge.bridge_command(name="seek", description="Seek to a specific point")
    #async def seek(self, ctx, seconds:discord.Option(str, "Number of seconds, fast forward, backward or in this format: 1h2m3s")=None):
    async def seek(self, ctx, seconds=None):
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")
        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            try:
                # Google this regular expression by yourself
                # It will parse which hour, minute, second to seek to
                regexp = re.compile("([0-9]*h)?([0-9]*m)?([0-9]*s)?")
                if regexp.match(seconds).group() != "":
                    hour_regexp = re.compile("([0-9]+h)").search(seconds)
                    hour_regexp = int(hour_regexp.group()[0:-1]) if hour_regexp is not None else 0

                    minute_regexp = re.compile("([0-9]+m)").search(seconds)
                    minute_regexp = int(minute_regexp.group()[0:-1]) if minute_regexp is not None else 0

                    second_regexp = re.compile("([0-9]+s)").search(seconds)
                    second_regexp = int(second_regexp.group()[0:-1]) if second_regexp is not None else 0

                    seconds = hour_regexp * 60 * 60 + minute_regexp * 60 + second_regexp
                elif seconds[0] == "+":
                    # Fast forward by x seconds
                    if ctx.voice_state.current.paused:
                        ctx.voice_state.current.pause_duration += time.time() - ctx.voice_state.current.pause_time
                        ctx.voice_state.current.pause_time = time.time()
                    seconds = int(time.time() - ctx.voice_state.current.starttime - ctx.voice_state.current.pause_duration) + int(seconds[1:])
                elif seconds[0] == "-":
                    # Backward by x seconds
                    if ctx.voice_state.current.paused:
                        ctx.voice_state.current.pause_duration += time.time() - ctx.voice_state.current.pause_time
                        ctx.voice_state.current.pause_time = time.time()
                    seconds = max((int(time.time() - ctx.voice_state.current.starttime - ctx.voice_state.current.pause_duration) - int(seconds[1:])), 0)
                else:
                    seconds = int(seconds)
            except:
                return await self.respond(ctx.ctx, "Unable to parse seconds to seek!")
            if seconds is None:
                return await self.respond(ctx.ctx, "Please provide seconds to seek to!")
            ctx.voice_state.seeking = True
            ctx.voice_state.seek_time = seconds
            current = ctx.voice_state.current
            await ctx.voice_state.seek(seconds, "local@" in current.source.url)
            await self.respond(ctx.ctx, f"Seeked to {seconds}s")
        else:
            await self.respond(ctx.ctx, "There is no songs playing right now.")
    
    @commands.command(name="musicdebug")
    async def musicdebug(self, ctx, guildid=None, options=None, *, args=None):
        # Debug menu
        if ctx.author.id in authors:
            guild = None
            if guildid == "here":
                guild, guildid = ctx.guild, ctx.guild.id
            elif guildid == "help":
                return await self.respond(ctx, "```Usage: musicdebug <guildid> <options> <args>\nOptions:\n    None: Display Voice State details\n    \"queue\": Display queue\n        args: page number\n    \"song\": Display song details\n    \"channel\": Display connected channel details\n        args: \"permission\": View permissions of the voice channel\n              \"join <channel_id>\": Join channel\n              \"disconnect\": Leave channel\n    \"reload\": Perform musicreload on that server\n    \"log\": Toggle sending log on cog error```")
            else:
                if guildid is not None:
                    try:
                        guild = self.bot.get_guild(int(guildid))
                    except:
                        pass
            if guild is None:
                return await self.respond(ctx, f"Guild {guildid} not found!")
            else:
                ctx.guild = guild
            if int(guildid) in self.voice_states:
                voice_state = self.voice_states[int(guildid)]
            else:
                ctx.guild.id = int(guildid)
                voice_state = self.get_voice_state(ctx)
            
            ctx.debug["channel"] = ctx.channel
            ctx.voice_state = voice_state
            ctx.debug["debug"] = True
            if options is None:
                embed = discord.Embed(title=f"Server details - {guild.name}")
                embed.add_field(name="Voice Channel Name", value="None" if guild.voice_client is None else guild.voice_client.channel.name, inline=False)
                embed.add_field(name="Voice Channel ID", value="None" if guild.voice_client is None else guild.voice_client.channel.id, inline=False)
                embed.add_field(name="Text Channel Name", value="None" if voice_state._ctx is None else voice_state._ctx.channel.name, inline=False)
                embed.add_field(name="Text Channel ID", value="None" if voice_state._ctx is None else voice_state._ctx.channel.id, inline=False)
                embed.add_field(name="Latency", value="None" if guild.voice_client is None else f"{guild.voice_client.latency*1000} ms", inline=False)
                embed.add_field(name="Average Latency (20 HEARTBEAT)", value="None" if guild.voice_client is None else f"{guild.voice_client.average_latency*1000} ms", inline=False)
                embed.add_field(name="Current Song", value=voice_state.current, inline=False)
                embed.add_field(name="Number of Songs in Queue", value=len(voice_state.songs), inline=False)
                embed.add_field(name="Loop", value=voice_state._loop, inline=False)
                embed.add_field(name="Loop Queue", value=voice_state.loopqueue, inline=False)
                embed.add_field(name="Paused", value="None" if voice_state.current is None else voice_state.current.paused, inline=False)
                embed.add_field(name="Volume", value=str(voice_state._volume * 100) + "%", inline=False)
                embed.add_field(name="Duration of no user in voice channel", value=f"{voice_state.timer} s")
                return await self.respond(ctx, embed=embed)
            elif options == "queue":
                items_per_page = 5
                pages = math.ceil(len(voice_state.songs) / items_per_page)
                if args is None:
                    page = 1
                else:
                    try:
                        page = int(args)
                    except:
                        page = 1
                if page < 1:
                    page = 1
                page = min(pages, page)
                start = (page - 1) * items_per_page
                end = start + items_per_page
                embed = discord.Embed(title=f"Song queue: {len(voice_state.songs)} songs, Page {page}/{pages}")
                for i, song in enumerate(voice_state.songs[start:end], start=start):
                    song_compact = song.copy()
                    song_compact["user"] = {"username": song_compact["user"].name + "#" + song_compact["user"].discriminator, "id": song_compact["user"].id}
                    embed.add_field(name=i+1, value=song_compact, inline=False)
                return await self.respond(ctx, embed=embed)
            elif options == "song":
                embed = discord.Embed(title="Current Song")
                if voice_state.current is None:
                    embed.description = "No song"
                else:
                    song = voice_state.current
                    embed.add_field(name="Title", value=song.source.title, inline=False)
                    embed.add_field(name="Requester", value=song.requester.mention, inline=False)
                    embed.add_field(name="Progress", value=YTDLSource.parse_duration_raw(int(time.time() - song.starttime - song.pause_duration)), inline=False)
                    embed.add_field(name="Duration", value=song.source.duration_raw, inline=False)
                    embed.add_field(name="URL", value=song.source.url, inline=False)
                    embed.add_field(name="Is File", value=song.isFile, inline=False)
                return await self.respond(ctx, embed=embed)
            elif options == "channel":
                if args is not None:
                    args_list = args.split(" ")
                    if args_list[0] == "join":
                        if len(args_list) == 2:
                            ctx.debug["channel"] = args_list[1]
                            return await self._summon(ctx, channel=ctx.debug["channel"])
                    elif args_list[0] in ("disconnect", "dc", "leave"):
                        return await self._leave(ctx)
                
                if voice_state.voice:
                    channel = voice_state.voice.channel
                    def channel_details():
                        embed = discord.Embed(title=f"Channel {channel.name}", description=f"ID: {channel.id}")
                        embed.add_field(name="Bitrate", value=channel.bitrate, inline=False)
                        members = []
                        for member in channel.members:
                            members.append(str({"id": member.id, "name": member.name + "#" + member.discriminator}))
                        memberstr = "\n".join(members)
                        embed.add_field(name="Members", value=memberstr, inline=False)
                        embed.add_field(name="User limit", value=channel.user_limit, inline=False)
                        embed.add_field(name="Permissions for bot", value="Add parameter \"permissions\" to view permissions", inline=False)
                        return embed
                    if args is not None and args == "permissions":
                        permissions = channel.permissions_for(ctx.me)
                        attributes = ["add_reactions", "administrator", "attach_files", "ban_members", "change_nickname", "connect", "create_instant_invite", "create_private_threads", "create_public_threads", "deafen_members", "embed_links", "external_emojis", "external_stickers", "kick_members", "manage_channels", "manage_emojis", "manage_emojis_and_stickers", "manage_events", "manage_guild", "manage_messages", "manage_nicknames", "manage_permissions", "manage_roles", "manage_threads", "manage_webhooks", "mention_everyone", "move_members", "mute_members", "priority_speaker", "read_message_history", "read_messages", "request_to_speak", "send_messages", "send_messages_in_threads", "send_tts_messages", "speak", "start_embedded_activities", "stream", "use_external_emojis", "use_external_stickers", "use_slash_commands", "use_voice_activation", "view_audit_log", "view_channel", "view_guild_insights"]
                        desc = ""
                        for attribute in attributes:
                            desc += attribute + ": " + (str(getattr(permissions, attribute)) if hasattr(permissions, attribute) else "?")
                            desc += "\n"
                        embed = discord.Embed(title=f"Permissions of Channel {channel.name}", description=f"ID: {channel.id}")
                        embed.add_field(name="Permission List", value=desc, inline=False)
                    else:
                        embed = channel_details()
                    await self.respond(ctx, embed=embed)
                else:
                    await self.respond(ctx, "Bot not connected to any voice channel.")
            elif options == "reload":
                try:
                    await voice_state.stop(leave=True)
                    await self.respond(ctx, "Stopped music and disconnected.")
                except:
                    await self.respond(ctx, "Unable to stop and leave.")
                try:
                    await guild.voice_client.disconnect()
                except:
                    await self.respond(ctx, "Unable to disconnect (mostly because of the bot has already disconnected from last action).")
                del self.voice_states[guildid]
                await self.respond(ctx, f"Music bot reloaded at guild {guild.name}, guild id {guildid}.")
            elif options == "log":
                ctx.voice_state.debug["debug_log"] = not ctx.voice_state.debug["debug_log"]
                await self.respond(ctx, "Debug log " + ("enabled." if ctx.voice_state.debug["debug_log"] else "disabled."))
            """elif options == "playlist":
                import io
                file = f"./music/playlist_{ctx.guild.id}.json"
                if os.path.isfile(file):
                    data = json.loads(open(file, "r", encoding="utf-8").read())
                else:
                    data = {}
                data = json.dumps(data, indent=4, ensure_ascii=False)
                await ctx.send(file=discord.File(io.BytesIO(data.encode("utf-8")), f"playlist_{ctx.guild.id}.json"))"""

    @bridge.bridge_command(name="playlist", description="Manage playlist")
    async def playlist_func(self, ctx, *, args=None):
        file = f"./music/playlist_{ctx.author.id}.json"
        if os.path.isfile(file):
            data = json.loads(open(file, "r", encoding="utf-8").read())
        else:
            data = {}
        if args is None:
            if data == {}:
                return await self.respond(ctx.ctx, "You do not have any playlist.")
            else:
                return await self.respond(ctx.ctx, embed=discord.Embed(title="Playlist", description="\n".join(list(data.keys()))))
        args = args.split(" ")
        if args[0] not in data:
            if len(args) == 1 or (len(args) >= 2 and args[1] != "create"):
                return await self.respond(ctx.ctx, f"Playlist {args[0]} not found.")
        if len(args) == 1:
            playlist = data[args[0]]
            page = 1
            if len(data[args[0]]) == 0:
                return await self.respond(ctx.ctx, 'Empty playlist.')
            await self.respond(ctx.ctx, embed=self.queue_embed(data[args[0]], page, f"Playlist \"{args[0]}\"", "", "id"))
        elif args[1] == "create":
            if args[0] not in data:
                data[args[0]] = []
                await self.respond(ctx.ctx, f"Playlist {args[0]} created.")
            else:
                return await self.respond(ctx.ctx, f"Playlist {args[0]} exists.")
        elif args[1] == "delete":
            del data[args[0]]
            await self.respond(ctx.ctx, f"Playlist {args[0]} deleted.")
        elif args[1] == "add":
            playlist = data[args[0]]
            if len(args) == 2:
                await self.respond(ctx.ctx, "Please provide URL of the song.")
            else:
                loop = self.bot.loop
                if "/playlist?" in args[2]:
                    partial = functools.partial(YTDLSource.ytdl_playlist.extract_info, args[2], download=False)
                    data_search = await loop.run_in_executor(None, partial)
                    if data_search is None:
                        return await self.respond(ctx.ctx, f"Couldn\'t find anything that matches `{args[2]}`")
                    entries = data_search["entries"]
                    playlist_search = []
                    for pos, song in enumerate(entries):
                        # Youtube only, guess no one would play other than Youtube, if yes, fuck off please
                        playlist_search.append({"pos": pos, "id": song["id"], "title": song["title"], "duration":int(song["duration"])})
                    # Sort the playlist variable to match with the order in YouTube
                    playlist_search.sort(key=lambda song: song["pos"])
                    # Add all songs to the pending list
                    for songs, entry in enumerate(playlist_search):
                        playlist.append({"id": entry["id"], "title": entry["title"], "duration": entry["duration"]})
                    await self.respond(ctx.ctx, f"Added {songs+1} songs to playlist **{args[0]}**")
                else:
                    # Just a single song
                    try:
                        partial = functools.partial(YTDLSource.ytdl.extract_info, args[2], download=False)
                        data_video = await loop.run_in_executor(None, partial)
                    except Exception as e:
                        # Get the error message from dictionary, if it doesn't exist in dict, return the original error message
                        message = error_messages.get(str(e), str(e))
                        return await self.respond(ctx.ctx, f"Error: {message}") 
                    if "entries" in data_video:
                        if len(data_video["entries"]) > 0:
                            data_video = data_video["entries"][0]
                        else:
                            return await self.respond(ctx.ctx, f"Couldn\'t find anything that matches `{args[2]}`")         
                    # Add the song to the pending list
                    playlist.append({"id": data_video["id"], "title": data_video["title"], "duration": int(data_video["duration"])})
                    await self.respond(ctx.ctx, f"Song **{data_video['title']}** added to playlist {args[0]}")
        elif args[1] == "remove":
            if len(args) < 3:
                return await self.respond(ctx.ctx, "Please provide the index of the song that you would like to remove from the playlist.")
            try:
                song = data[args[0]].pop(int(args[2])-1)
                await self.respond(ctx.ctx, f"Song **{song['title']}** removed from playlist **{args[0]}**.")
            except:
                return await self.respond(ctx.ctx, "Unable to remove song, please provide a valid song number.")
        elif args[1] == "rename":
            if len(args) < 3 or args[2] == "":
                return await self.respond(ctx.ctx, f"Please provide a new name for the playlist {args[0]}.")
            if args[2] in data:
                return await self.respond(ctx.ctx, f"Playlist \"{args[2]}\" exists.")
            data[args[2]] = data[args[0]].copy()
            del data[args[0]]
            await self.respond(ctx.ctx, f"Playlist \"{args[0]}\" renamed to \"{args[2]}\"")
        elif args[1] == "play":
            # Joins the channel if it hasn't
            if not ctx.voice_state.voice:
                await ctx.invoke(self._join)
            # Errors may occur while joining the channel, if the voice is None, don't continue
            if not ctx.voice_state.voice:
                return
            if not ctx.debug["debug"]:
                # If the user invoking this command is not in the same channel, return error
                if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                    return await self.respond(ctx.ctx, "You are not connected to any voice channel or the same voice channel.")
                if ctx.voice_client:
                    if ctx.voice_client.channel != ctx.author.voice.channel:
                        return await self.respond(ctx.ctx, "Bot is already in a voice channel.")
            if len(args) < 3 or args[2] == "":
                for songs, entry in enumerate(data[args[0]]):
                    try:
                        duration = int(entry["duration"])
                    except:
                        duration = 0
                    await ctx.voice_state.songs.put({"url": f"https://youtu.be/{entry['id']}", "title": entry["title"], "user": ctx.author, "duration": duration})
                ctx.voice_state.stopped = False
                return await self.respond(ctx.ctx, f"Added {songs+1} songs to queue from playlist **{args[0]}**")
            else:
                try:
                    index = int(args[2])-1
                    if index < 1 or index >= len(data[args[0]]):
                        raise Exception()
                except:
                    return await self.respond(ctx.ctx, "Please provide a valid index!")
                entry = data[args[0]][index]
                try:
                    duration = int(entry["duration"])
                except:
                    duration = 0
                await ctx.voice_state.songs.put({"url": f"https://youtu.be/{entry['id']}", "title": entry["title"], "user": ctx.author, "duration": duration})
                ctx.voice_state.stopped = False
                return await self.respond(ctx.ctx, f"Added {entry['title']} to queue from playlist **{args[0]}**")
            "Unfinished functions hehe"
            """elif args[1] in ("share", "export"):
                await self.respond(ctx.ctx, embed=discord.Embed(title=f"Playlist Share - {args[0]}", description=base64.b64encode("\n".join(data[args[0]]).encode("utf-8")).decode("utf-8")))
            elif args[1] == "import":
                if len(args) < 2:
                    return await self.respond(ctx.ctx, "Please provide the id of the playlist.")
                try:
                    songs = base64.b64decode(args[2].encode("utf-8")).decode("utf-8").split("\n")
                except:
                    return await self.respond(ctx.ctx, "Unable to find the playlist.")"""
        else:
            try:
                page = int(args[1])
            except:
                page = 1
            if len(data[args[0]]) == 0:
                return await self.respond(ctx.ctx, 'Empty playlist.')
            await self.respond(ctx.ctx, embed=self.queue_embed(data[args[0]], page, f"Playlist \"{args[0]}\"", "", "id"))
        if not os.path.isdir("./music"):
            os.mkdir("./music")
        open(file, "w", encoding="utf-8").write(json.dumps(data))

    @bridge.bridge_command(name="musicversion", description="Shows the current music cog version")
    async def musicversion(self, ctx):
        await self.respond(ctx.ctx, embed=discord.Embed(title="Discord Music Cog v1.8.1").add_field(name="Author", value="<@127312771888054272>").add_field(name="Cog Github Link", value="[Link](https://github.com/benwong01f611/discord-music-cog)"))

def setup(bot):
    bot.add_cog(Music(bot))