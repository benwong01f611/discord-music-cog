import asyncio
import functools
import itertools
import math
import random
import os
import time

import discord
import yt_dlp as youtube_dl
from async_timeout import timeout
from discord.ext import commands

import subprocess
import shutil
import re
import traceback
import json
import base64
import io

language = "en" # en/tc
useEmbed = False
loc = json.load(open(f"music_{language}.json","r",encoding="utf-8"))
# Silence useless bug reports messages
youtube_dl.utils.bug_reports_message = lambda: ''

# Error messages for returning meaningfull error message to user
error_messages = {
    "ERROR: Sign in to confirm your age\nThis video may be inappropriate for some users.": loc["error"]["age_restriction"],
    "Video unavailable": loc["error"]["unavailable"],
    "ERROR: Private video\nSign in if you've been granted access to this video": loc["error"]["private"]
}

# Insert authors' id in here, user in this set are allowed to use command "runningservers"
authors = (,)

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

# Parse the duration to xx days xx hours xx minutes xx seconds
def parse_duration(duration: int):
    minutes, seconds = divmod(duration, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    duration = []
    if days > 0:
        duration.append(f"{days} {loc['day']}")
    if hours > 0:
        duration.append(f"{hours} {loc['hour']}")
    if minutes > 0:
        duration.append(f"{minutes} {loc['minute']}")
    if seconds > 0:
        duration.append(f"{seconds} {loc['second']}")

    return " ".join(duration)

# Parse the duration to 00:00:00:00
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

# Function for responding to the user
async def respond(ctx, message: str=None, color=discord.Embed.Empty, embed: discord.Embed=None, view: discord.ui.View=None):
    if embed is not None and message is not None:
        raise AttributeError("Message is not None when embed is also not None")
    if embed is None:
        embed = discord.Embed(title=message, color=color)
    try:
        return await ctx.reply(embed=embed, mention_author=False, view=view)
    except:
        return await ctx.respond(embed=embed, view=view) # Slash

# Check is user in guild is in voice channel, if yes returns True and the channel object, otherwise return False
def isUserInChannel(user):
    return not (not user.voice or not user.voice.channel)

def isBotInChannel(ctx):
    return (ctx.voice_client is not None)

def isBotAndUserInSameChannel(ctx, user):
    if isUserInChannel(user) and isBotInChannel(ctx):
        return (user.voice.channel.id == ctx.voice_client.channel.id)
    else:
        return False

async def checkUserAndBotChannel(ctx):
    if isBotInChannel(ctx):
        if isBotAndUserInSameChannel(ctx, ctx.author):
            return True
        else:
            await respond(ctx, loc["messages"]["enter_before_play"], color=0xff0000)
            return False
    else:
        await respond(ctx,loc["messages"]["not_connected"], color=0xff0000)
        return False

async def _join(ctx, from_cmd=False, author=None):
    # Joins the channel

    # If the user is not in any voice channel, don't join
    if not isUserInChannel(author):
        await respond(ctx, loc["messages"]["enter_before_play"], color=0xff0000)
        return False
    
    #await respond(ctx, loc["messages"]["already_in_same_voice"], color=0xff0000)
    # If the bot is in the voice channel, check whether it is in the same voice channel or not

    if isBotInChannel(ctx):
        await respond(ctx, loc["messages"]["already_in_voice"], color=0xff0000)
        return False
    
    destination = author.voice.channel

    # Check permission
    if not destination.permissions_for(ctx.me).connect:
        return await respond(ctx, loc["messages"]["join_no_permission"], color=0xff0000)

    # Connect to the channel
    try:
        async with timeout(10):
            ctx.voice_state.voice = await destination.connect()
    except asyncio.TimeoutError:
        await respond(ctx, loc["messages"]["cannot_join_unk"], color=0xff0000)
        return False
    
    if from_cmd:
        await respond(ctx, loc["messages"]["joined"].format(destination), color=0x1eff00)

    # If the channel is a stage channel, wait for 1 second and try to unmute itself
    if isinstance(ctx.voice_state.voice.channel, discord.StageChannel):
        try:
            await asyncio.sleep(1)
            await ctx.me.edit(suppress=False)
        except:
            # Unable to unmute itself, ask admin to invite the bot to speak (auto)
            await respond(ctx, loc["messages"]["require_mute"], color=0xff0000)
    # Clear all music file
    if os.path.isdir(f"./tempMusic/{ctx.guild.id}"):
        shutil.rmtree(f"./tempMusic/{ctx.guild.id}")
    await ctx.guild.change_voice_state(channel=destination, self_mute=False, self_deaf=True)

async def _play(ctx, search, loop, search_msg=None):
    if isBotInChannel(ctx):
        if isBotAndUserInSameChannel(ctx, ctx.author):
            pass
        else:
            return await respond(ctx, loc["messages"]["enter_before_play"], color=0xff0000)
    else:
        await _join(ctx, author=ctx.author)
        # Errors may occur while joining the channel, if the voice is None, don't continue
        if not ctx.voice_state.voice:
            return await respond(ctx, loc["messages"]["cannot_join_unk"], color=0xff0000)
    
    try:
        if search_msg is None:
            searching_msg = await respond(ctx, loc["messages"]["searching"].format(search))
        else:
            searching_msg = search_msg
        # Supports playing a playlist but it must be like https://youtube.com/playlist?
        if "/playlist?" in search and ("youtu.be" in search or "youtube.com" in search):
            partial = functools.partial(SongSource.ytdl_playlist.extract_info, search, download=False)
            data = await loop.run_in_executor(None, partial)
            if data is None:
                await editMessage(searching_msg, discord.Embed(title=loc["not_found"].format(search), color=0xff0000))
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
            #await respond(ctx, loc["messages"]["added_multiple_song"].format(songs+1), color=0x1eff00)
            await editMessage(searching_msg, discord.Embed(title=loc["messages"]["added_multiple_song"].format(songs+1), color=0x1eff00))
        else:
            # Just a single song
            try:
                domain = search.split("/")[2]
            except:
                domain = "youtube"
            if "youtube" not in domain and "youtu.be" not in domain:
                # Direct link or other site
                try:
                    partial = functools.partial(SongSource.ytdl.extract_info, search, download=False)
                    data = await loop.run_in_executor(None, partial)
                    if "entries" in data:
                        if len(data["entries"]) > 0:
                            data = data["entries"][0]
                        else:
                            return await editMessage(searching_msg, discord.Embed(title=loc["not_found"].format(search), color=0xff0000))
                            #return await respond(ctx, loc["not_found"].format(search), color=0xff0000)
                    title = data["title"]
                    if "duration" in data:
                        await ctx.voice_state.songs.put({"url": search, "title": title, "user": ctx.author, "duration": int(float(data["duration"]))})
                    else:
                        await ctx.voice_state.songs.put({"url": search, "title": title, "user": ctx.author, "duration": int(float(subprocess.check_output(f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{search}\"", shell=True).decode("ascii").replace("\r", "").replace("\n", "")))})
                except:
                    return await editMessage(searching_msg, discord.Embed(title=loc["messages"]["cannot_add_invalid_file"], color=0xff0000))
                return await editMessage(searching_msg, discord.Embed(title=loc["messages"]["added_song"].format(title.replace("_", "\\_")), color=0x1eff00))
                #await respond(ctx, loc["messages"]["added_song"].format(title.replace("_", "\\_")), color=0x1eff00)
            else:
                try:
                    partial = functools.partial(SongSource.ytdl.extract_info, search, download=False)
                    data = await loop.run_in_executor(None, partial)
                except Exception as e:
                    # Get the error message from dictionary, if it doesn't exist in dict, return the original error message
                    message = error_messages.get(str(e), str(e))
                    return await editMessage(searching_msg, discord.Embed(title=loc["messages"]["error"].format(message), color=0xff0000))
                if "entries" in data:
                    if len(data["entries"]) > 0:
                        data = data["entries"][0]
                    else:
                        return await editMessage(searching_msg, discord.Embed(title=loc["not_found"].format(search), color=0xff0000))
                # Add the song to the pending list
                try:
                    duration = int(data["duration"])
                except:
                    duration = 0
                await ctx.voice_state.songs.put({"url": data["webpage_url"], "title": data["title"], "user": ctx.author, "duration": duration})
                await editMessage(searching_msg, discord.Embed(title=loc["messages"]["added_song"].format(data['title']), color=0x1eff00))
        ctx.voice_state.stopped = False
    except YTDLError as e:
        await editMessage(searching_msg, discord.Embed(title=loc["messages"]["error"].format(str(e)), color=0x1eff00))

# Return a discord.Embed() object, provides 5 songs from the queue/playlist depending on the page requested
# Parameter "page" greater than the pages that the queue has will set the page to the last page
# Invalid parameter "page" will display the first page

def queue_embed(data, page, header, description, song_id):
    # Get the total duration from the queue or playlist
    def getTotalDuration(data):
        total_duration = 0
        for song in data:
            total_duration += song["duration"]
        return total_duration
        
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
                    duration = parse_duration(song['duration'])
                except:
                    duration = loc["unknown"]
                queue += loc["queue_embed"]["queue_row_local"].format(i+1, title, duration)
            else:
                try:
                    duration = parse_duration_raw(song['duration'])
                except:
                    duration = loc["unknown"]
                queue += loc["queue_embed"]["queue_row"].format(i+1, song["title"], url, song[song_id], duration)
    else:
        queue = loc["queue_embed"]["empty"]
    embed = (discord.Embed(
                title=header,
                description=description)
            .add_field(name=loc["queue_embed"]["embed_body"].format(len(data), parse_duration(getTotalDuration(data))), value=queue)
            .set_footer(text=loc["queue_embed"]["page"].format(page, pages))
        )
    return embed

async def editMessage(message, embed):
    try:
        await message.edit(embed=embed)
    except:
        await message.edit_original_response(embed=embed)

class VoiceError(Exception):
    pass

class YTDLError(Exception):
    pass

class SongSource(discord.PCMVolumeTransformer):
    ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)
    ytdl_playlist = youtube_dl.YoutubeDL(YTDL_OPTIONS_PLAYLIST)
    def __init__(self, ctx, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5, ffmpeg=True, seek=None):
        super().__init__(source, volume)

        self.requester = ctx.author if ffmpeg else data.get('requester')
        self.channel = ctx.channel
        self.data = data
        self.title = data.get('title')
        if data.get("duration") == "Unknown":
            self.duration_int = 0
        else:
            self.duration_int = int(data.get('duration'))
        try:
            self.duration = parse_duration(int(data.get('duration')))
        except:
            self.duration = loc["unknown"]
        try:
            self.duration_raw = parse_duration_raw(int(data.get('duration')))
        except:
            self.duration_raw = loc["unknown"]
        
        if ffmpeg:
            self.url = data.get('url')
        else:
            self.uploader = data.get('uploader')
            self.uploader_url = data.get('uploader_url')
            date = data.get('upload_date')
            self.upload_date = date[6:8] + '.' + date[4:6] + '.' + date[0:4]
            self.thumbnail = data.get('thumbnail')
            self.description = data.get('description')
            self.tags = data.get('tags')
            self.url = data.get('webpage_url')
            self.views = data.get('view_count')
            self.likes = data.get('like_count')
            self.dislikes = data.get('dislike_count')
            self.stream_url = data.get('url')
    
    @classmethod
    async def create_source(self, ctx, keyword: str, *, loop: asyncio.BaseEventLoop = None, requester=None, seek=None, src:str ="", duration:int = 0):
        loop = loop or asyncio.get_event_loop()

        # Extract data with youtube-dl
        partial = functools.partial(self.ytdl.extract_info, keyword, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        if src == "ffmpeg":
            partial = functools.partial(self.ytdl.extract_info, keyword, download=False)
            data = await loop.run_in_executor(None, partial)
            info = {
                "url": data["url"],
                "webpage_url": data["webpage_url"],
                "title": data["title"],
                "duration": duration,
                "requester": requester
            }
        else:
            # Return error if nothing can be found
            if data is None:
                return await respond(ctx, loc["not_found"].format(keyword))

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
                    return await respond(ctx, loc["not_found"].format(keyword))

            # Retrieve the video details
            webpage_url = process_info['webpage_url']
            partial = functools.partial(self.ytdl.extract_info, webpage_url, download=False)
            processed_info = await loop.run_in_executor(None, partial)

            if processed_info is None:
                return await respond(ctx, loc["cannot_obtain"].format(webpage_url))

            if 'entries' not in processed_info:
                info = processed_info
            else:
                info = None
                while info is None:
                    try:
                        info = processed_info['entries'].pop(0)
                    except IndexError:
                        return await respond(ctx, loc["not_found"].format(webpage_url))
            # requester for saving the user who plays this song, shown in command now
            info["requester"] = requester
        
        # If seeking, ask ffmpeg to start from a specific position, else simply return the object
        if seek is not None:
            seek_option = FFMPEG_OPTIONS.copy()
            seek_option['before_options'] += " -ss " + parse_duration_raw(seek)
            return self(ctx, discord.FFmpegPCMAudio(info['url'], **seek_option), data=info, ffmpeg=(src == "ffmpeg"))
        else:
            return self(ctx, discord.FFmpegPCMAudio(info['url'], **FFMPEG_OPTIONS), data=info, ffmpeg=(src == "ffmpeg"))

class Song:
    __slots__ = ('source', 'requester', 'starttime', 'pause_time', 'pause_duration', 'paused', 'isFile', 'isDirectLink', 'time_invoke_seek')

    # starttime stores when does the song start
    # pause_duration stores how long does the song being paused, updates when the song resumes
    # pause_time stores when does the song paused, used for calculating the pause_duration
    def __init__(self, source, isFile=False, isDirectLink=False): 
        self.source = source
        self.requester = source.requester
        self.starttime = None
        self.pause_duration = 0
        self.pause_time = 0
        self.paused = False
        self.isFile = isFile
        self.isDirectLink = isDirectLink
        self.time_invoke_seek = -1

    def create_embed(self, status: str):
        # If a new song is being played, it will simply display how long the song is
        # But if the command now is being executed, it will show how long the song has been played
        if self.paused:
            self.pause_duration += time.time() - self.pause_time
            self.pause_time = time.time()
        embed = (discord.Embed(title=loc["song_embed"]["title"],
                                description=loc["song_embed"]["description"].format(self.source.title),
                                color=discord.Color.blurple())
                    .add_field(name=loc["song_embed"]["video_length"], value=(self.source.duration if status == "play" or self.source.duration == "Unknown" else parse_duration_raw(int(time.time() - self.starttime - self.pause_duration)) + "/" + self.source.duration_raw))
                    .add_field(name=loc["song_embed"]["video_player"], value=self.requester.mention))
        
        # If it is not a file, it is a youtube video
        if not self.isFile:
            embed.add_field(name=loc["song_embed"]["uploader"], value=loc["song_embed"]["uploader_body"].format(self.source.uploader, self.source.uploader_url))
            embed.add_field(name=loc["song_embed"]["video_url"], value=loc["song_embed"]["video_url_body"].format(self.source.url))
            embed.set_image(url=self.source.thumbnail)
        if self.isDirectLink:
            embed.add_field(name=loc["song_embed"]["video_url"], value=loc["song_embed"]["video_url_body"].format(self.source.url))

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

        # Create task for checking is the bot alone
        self.listener_task = self.bot.loop.create_task(self.check_user_listening())

        self.forbidden = False

        self.cog = cog

        self.message = None

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
    async def seek(self, seconds, isLocal, isDirectLink):
        # Stop the current playing song
        self.voice.stop()
        # Recreate ffmpeg object
        if isLocal or isDirectLink:
            self.current = await self.create_song_source(self._ctx, self.current.source.url, title=self.current.source.title, requester=self.current.source.requester, seek=seconds, duration=self.current.source.duration_int)
        else:
            self.current = await self.create_song_source(self._ctx, self.current.source.url, requester=self.current.source.requester, seek=seconds)
        # Update volume
        self.current.source.volume = self._volume
        # Play the seeked song
        self.voice.play(self.current.source, after=self.play_next_song)
        self.current.time_invoke_seek = time.time()
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
            if not isinstance(self.current, dict) and not isinstance(self.current, str) and self.current and self.current.source.volume != self._volume:
                self.current.source.volume = self._volume
    
    async def create_song_source(self, ctx, url, title=None, requester=None, seek=None, duration=None):
        try:
            domain = url.split("/")[2]
        except:
            domain = ""
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
                return Song(SongSource(ctx, discord.FFmpegPCMAudio(url, before_options="-ss " + parse_duration_raw(seek)), data={'duration': duration, 'title': title, 'url': "local@" + url, 'requester': requester}, seek=seek), True)
            else:
                return Song(SongSource(ctx, discord.FFmpegPCMAudio(url), data={'duration': duration, 'title': title, 'url': "local@" + url, 'requester': requester}), True)
        elif "youtube" in domain or "youtu.be" in domain:
            try:
                result = Song(await SongSource.create_source(ctx, url, loop=self.bot.loop, requester=requester, seek=seek))
            except Exception as e:
                await ctx.channel.send(str(e))
                return "error"
            return result
        else:
            # Direct Link or other source
            try:
                result = Song(await SongSource.create_source(ctx, url, loop=self.bot.loop, requester=requester, seek=seek, src="ffmpeg", duration=duration), True, True)
            except Exception as e:
                await ctx.channel.send("Error: " + str(e))
                return "error"
            return result

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
                #if "local@" in self.current.source.url:
                try:
                    domain = self.current["url"].split("/")[2]
                except:
                    domain = ""
                if "youtube" in domain or "youtu.be" in domain:
                    self.current = await self.create_song_source(self._ctx, self.current.source.url, requester=self.current.source.requester)
                else:
                    self.current = await self.create_song_source(self._ctx, self.current.source.url, title=self.current.source.title, requester=self.current.source.requester, duration=self.current.source.duration_int)
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
                            self.next_song = await self.songs.get()
                            # If the url contains local@, it is a local file
                            #if "local@" in self.current["url"]:
                            try:
                                domain = self.current["url"].split("/")[2]
                            except:
                                domain = ""
                            if "youtube" in domain or "youtu.be" in domain:
                                self.current = await self.create_song_source(self._ctx, self.next_song["url"], requester=self.next_song["user"])
                            else:
                                # Direct link
                                self.current = await self.create_song_source(self._ctx, self.next_song["url"], title=self.next_song["title"], requester=self.next_song["user"], duration=self.next_song["duration"])
                            if self.current != "error":
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
                                #if "local@" in self.current["url"]:
                                try:
                                    domain = self.current["url"].split("/")[2]
                                except:
                                    domain = ""
                                if "youtube" in domain or "youtu.be" in domain:
                                    self.current = await self.create_song_source(self._ctx, self.current["url"], requester=self.current["user"])
                                else: # External, add duration and title from data
                                    self.current = await self.create_song_source(self._ctx, self.current["url"], title=self.current["title"], requester=self.current["user"], duration=self.current["duration"])
                                if self.current != "error":
                                    self.skipped = False
                                    self.stopped = False
                        except asyncio.TimeoutError:
                            return await self.stop(leave=True)
                    else:
                        # Looping, get the looped song
                        #if "local@" in self.current.source.url:
                        try:
                            domain = self.current.source.url.split("/")[2]
                        except:
                            domain = ""
                        if "youtube" in domain or "youtu.be" in domain:
                            self.current = await self.create_song_source(self._ctx, self.current.source.url, requester=self.current.source.requester)
                        else:
                            self.current = await self.create_song_source(self._ctx, self.current.source.url, title=self.current.source.title, requester=self.current.source.requester, duration=self.current.source.duration_int)
            if self.current != "error":
                # Save the temporary data for current song
                songData = {
                    "url": self.current.source.url,
                    "title": self.current.source.title,
                    "user": self.current.source.requester,
                    "duration": self.current.source.duration_int
                }
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
                # If loop queue, put the current song back to the end of the queue
                if not self.stopped and self.loopqueue:
                    await self.songs.put(songData)

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
        if leave:
            if self.audio_player and not self.audio_player.done():
                self.audio_player.cancel()
                try:
                    await self.message.delete()
                except:
                    pass
            if self.listener_task and not self.listener_task.done():
                self.listener_task.cancel()
            if self.volume_updater and not self.volume_updater.done():
                self.volume_updater.cancel()
                self.volume_updater = None
        self.stopped = True
    
    async def update(self):
        await self.message.edit(view=PlayerControlView(self.bot, self))

class SearchMenu(discord.ui.Select):
    def __init__(self, bot, options_raw, cog, ctx):
        self.bot = bot
        self.cog = cog
        self.ctx = ctx
        reaction_list = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        options = [discord.SelectOption(label=data["title"], description=loc["search_menu"]["video_length"].format(data['duration']), value=str(data["index"]), emoji=reaction_list[data["index"]]) for data in options_raw]
        options.append(discord.SelectOption(label=loc["search_menu"]["cancel"], description=loc["search_menu"]["cancel_desc"], value="11", emoji="❌"))
        self.data = options_raw
        self.completed = False
        super().__init__(
            placeholder=loc["search_menu"]["placeholder"],
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction):
        if int(self.values[0]) == 11: # Cancel
            self.completed = True
            return await interaction.message.edit(embed=discord.Embed(title=loc["search_menu"]["cancelled_search"], description=None, color=discord.Color.green()), view=None)
        # Edit the message to reduce its size
        await interaction.message.edit(embed=discord.Embed(title=loc["search_menu"]["result"], description=self.data[int(self.values[0])]["title"], color=discord.Color.green()), view=None)
        #await interaction.response.send_message(loc["search_menu"]["chose"].format(self.data[int(self.values[0])]["title"]))
        
        # Invoke the play command
        search = self.data[int(self.values[0])]["url"]

        if not self.ctx.author.voice or not self.ctx.author.voice.channel:
            return await respond(interaction.message, loc["messages"]["enter_before_play"], color=0xff0000)
        voice_client = (await self.bot.fetch_guild(interaction.guild_id)).voice_client
        if voice_client:
            if voice_client.channel != self.ctx.author.voice.channel:
                return await respond(interaction.message, loc["messages"]["already_in_voice"], color=0xff0000)

        ctx = self.ctx
        search = self.data[int(self.values[0])]["url"]
        await _play(ctx, search, self.bot.loop, search_msg=interaction.message)
        self.completed = True

class SearchView(discord.ui.View):
    def __init__(self, bot, data, ctx, cog):
        self.bot = bot
        self.ctx = ctx
        self.data = data
        self.cog = cog
        super().__init__(timeout=3)
        self.add_item(SearchMenu(self.bot, data, cog, ctx))
    async def on_timeout(self):
        if not self.children[0].completed:
            await self.message.edit(embed=discord.Embed(title=loc["search_menu"]["search_end"], color=0xff0000), view=None)

class PlayerControlView(discord.ui.View):
    def __init__(self, bot, voice_state):
        self.bot = bot
        self.voice_state = voice_state
        super().__init__(timeout=None)
        if self.voice_state.current.paused:
            self.children[0].emoji = "▶"
            self.children[0].label = loc["btn_label"]["resume"]
        else:
            self.children[0].emoji = "⏸"
            self.children[0].label = loc["btn_label"]["pause"]
        
        self.children[3].label = loc["loop"]["disable_loop"] if self.voice_state._loop else loc["loop"]["enable_loop"]
        self.children[4].label = loc["loop"]["disable_loopqueue"] if self.voice_state.loopqueue else loc["loop"]["enable_loopqueue"]
    
    @discord.ui.button(label=loc["btn_label"]["pause"], style=discord.ButtonStyle.primary, custom_id="0", emoji="⏸", disabled=False)
    async def pause(self, button, interaction):
        if interaction.user not in self.voice_state.voice.channel.members:
            return await interaction.response.send_message(loc["messages"]["not_in_same_voice"], ephemeral=True)
        await interaction.response.defer()
        if self.voice_state.is_playing and self.voice_state.voice.is_playing():
            self.voice_state.voice.pause()
            # Sets the pause time
            self.voice_state.current.pause_time = time.time()
            self.voice_state.current.paused = True
        elif self.voice_state.is_playing and self.voice_state.voice.is_paused():
            self.voice_state.voice.resume()
            # Updates internal data for handling song progress that was paused
            self.voice_state.current.pause_duration += time.time() - self.voice_state.current.pause_time
            self.voice_state.current.pause_time = 0
            self.voice_state.current.paused = False
        await self.update(interaction)

    @discord.ui.button(label=loc["btn_label"]["skip"], style=discord.ButtonStyle.primary, custom_id="1", emoji="⏭", disabled=False)
    async def skip(self, button, interaction):
        if interaction.user not in self.voice_state.voice.channel.members:
            return await interaction.response.send_message(loc["messages"]["not_in_same_voice"], ephemeral=True)
        await interaction.response.defer()
        self.voice_state.skip()
    
    @discord.ui.button(label=loc["btn_label"]["stop"], style=discord.ButtonStyle.primary, custom_id="2", emoji="⏹", disabled=False)
    async def stop(self, button, interaction):
        if interaction.user not in self.voice_state.voice.channel.members:
            return await interaction.response.send_message(loc["messages"]["not_in_same_voice"], ephemeral=True)
        await interaction.response.defer()
        self.voice_state.songs.clear()

        if self.voice_state.is_playing:
            await self.voice_state.stop()
            self.voice_state.stopped = True

    @discord.ui.button(label=loc["btn_label"]["loop"], style=discord.ButtonStyle.primary, custom_id="3", emoji="🔂", disabled=False)
    async def loop(self, button, interaction):
        if interaction.user not in self.voice_state.voice.channel.members:
            return await interaction.response.send_message(loc["messages"]["not_in_same_voice"], ephemeral=True)
        await interaction.response.defer()
        self.voice_state.loop = not self.voice_state.loop
        await self.update(interaction)
    
    @discord.ui.button(label=loc["btn_label"]["loopqueue"], style=discord.ButtonStyle.primary, custom_id="4", emoji="🔁", disabled=False)
    async def loopqueue(self, button, interaction):
        if interaction.user not in self.voice_state.voice.channel.members:
            return await interaction.response.send_message(loc["messages"]["not_in_same_voice"], ephemeral=True)
        await interaction.response.defer()
        self.voice_state.loopqueue = not self.voice_state.loopqueue
        await self.update(interaction)
    
    @discord.ui.button(label=loc["btn_label"]["queue"], style=discord.ButtonStyle.primary, custom_id="5", emoji="📜", disabled=False)
    async def queue(self, button, interaction):
        # Shows the queue, add page number to view different pages
        page = 1
        if len(self.voice_state.songs) == 0 and self.voice_state.current is None:
            if useEmbed:
                return interaction.response.send_message(embed=discord.Embed(title=loc["messages"]["empty_queue"], color=0xff0000))
            return await interaction.response.send_message(loc["messages"]["empty_queue"])
        
        # Invoking queue while the bot is retrieving another song will cause error, wait for 1 second
        while self.voice_state.current is None or isinstance(self.voice_state.current, dict):
            await asyncio.sleep(1)
        return await interaction.response.send_message(embed=queue_embed(
            self.voice_state.songs,
            page,
            loc["queue_embed"]["title"],
            loc["queue_embed"]["body"].format(self.voice_state.current.source.title, self.voice_state.current.source.url, parse_duration(self.voice_state.current.source.duration_int - int(time.time() - self.voice_state.current.starttime - self.voice_state.current.pause_duration))),
            "url"
        ))
    
    async def update(self, interaction):
        if self.voice_state.current.paused:
            self.children[0].emoji = "▶"
            self.children[0].label = loc["btn_label"]["resume"]
        else:
            self.children[0].emoji = "⏸"
            self.children[0].label = loc["btn_label"]["pause"]
        
        self.children[3].label = loc["loop"]["disable_loop"] if self.voice_state._loop else loc["loop"]["enable_loop"]
        self.children[4].label = loc["loop"]["disable_loopqueue"] if self.voice_state.loopqueue else loc["loop"]["enable_loopqueue"]
        await interaction.message.edit(view=self)

class Music(commands.Cog):
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

    # Before invoking any commands, get the voice state first
    # Update the context object also
    async def cog_before_invoke(self, ctx):
        # All commands from this cog cannot be used in DM
        if not ctx.guild:
            return await ctx.send(loc["error"]["no_pm"])
        self.get_voice_state(ctx)._ctx = ctx
        ctx.voice_state = self.get_voice_state(ctx)

    # Return a meaningful message to user when error occurs
    async def cog_command_error(self, ctx, error):
        formatted_error = traceback.format_exc()
        await ctx.send("Stacktrace", file=discord.File(io.BytesIO(traceback.format_exc().encode("utf-8")), f"error.txt"))
        if not (str(error) == "Application Command raised an exception: AttributeError: 'NoneType' object has no attribute 'is_finished'"):
            await ctx.send(loc["error"]["error_msg"].format(str(error)))
    
    @commands.slash_command(description=loc["descriptions"]["join"])
    async def join(self, ctx):
        await _join(ctx, from_cmd=True, author=ctx.author)
    
    @commands.slash_command(aliases=['disconnect', 'dc'], description=loc["descriptions"]["leave"])
    async def leave(self, ctx):
        # Clears the queue and leave the channel
        if not (await checkUserAndBotChannel(ctx)):
            return
        await ctx.voice_state.stop(leave=True)
        # Leaves the channel and delete the data from memory
        del self.voice_states[ctx.guild.id]
        await respond(ctx, loc["messages"]["left"])

    @commands.slash_command(aliases=['v'], description=loc["descriptions"]["volume"])
    async def volume(self, ctx, volume:discord.Option(int, loc["descriptions"]["volume"]) = None):
        # If the parameter is set, try to parse it as an integer
        try:
            if volume is not None:
                volume = int(volume)
        except:
            return await respond(ctx, loc["messages"]["volume_invalid"], color=0xff0000)
        # Sets the volume of the player
        if not (await checkUserAndBotChannel(ctx)):
            return
        if volume is not None:
            # The volume should be 0 < volume < 200
            if 0 > volume or volume > 200:
                return await respond(ctx, loc["messages"]["volume_invalid_range"], color=0xff0000)
            # The volume should be divided by 100
            ctx.voice_state.volume = volume / 100
            await respond(ctx, loc["messages"]["updated_volume"].format(volume), color=0x1eff00)
        else:
            # Return the current volume
            return await respond(ctx, loc["messages"]["current_volume"].format(int(ctx.voice_state.volume*100)), color=0x1eff00)

    @commands.slash_command(description=loc["descriptions"]["now"])
    async def now(self, ctx):
        # Display currently playing song
        if ctx.voice_state.current is None:
            return await respond(ctx, loc["messages"]["no_playing"], color=0xff0000)
        await respond(ctx, embed=ctx.voice_state.current.create_embed("now"))

    @commands.slash_command(description=loc["descriptions"]["pause"])
    async def pause(self, ctx):
        # Pauses the player
        if not (await checkUserAndBotChannel(ctx)):
            return
        # If the bot is playing, pause it
        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            # Sets the pause time
            ctx.voice_state.current.pause_time = time.time()
            ctx.voice_state.current.paused = True
            await respond(ctx, loc["messages"]["paused"])
        else:
            await respond(ctx, loc["messages"]["no_playing"], color=0xff0000)
        if ctx.voice_state.message:
            await ctx.voice_state.update()

    @commands.slash_command(aliases=['r'], description=loc["descriptions"]["resume"])
    async def resume(self, ctx):
        # Resumes the bot
        if not (await checkUserAndBotChannel(ctx)):
            return
        # If the bot is paused, resume it
        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()
            # Updates internal data for handling song progress that was paused
            ctx.voice_state.current.pause_duration += time.time() - ctx.voice_state.current.pause_time
            ctx.voice_state.current.pause_time = 0
            ctx.voice_state.current.paused = False
            await respond(ctx, loc["messages"]["resumed"])
        else:
            await respond(ctx, loc["messages"]["no_paused"], color=0xff0000)
        if ctx.voice_state.message:
            await ctx.voice_state.update()

    @commands.slash_command(description=loc["descriptions"]["stop"])
    async def stop(self, ctx):
        # Stops the bot and clears the queue
        if not (await checkUserAndBotChannel(ctx)):
            return
        ctx.voice_state.songs.clear()
        if ctx.voice_state.is_playing:
            await ctx.voice_state.stop()
            ctx.voice_state.stopped = True
            await respond(ctx, loc["messages"]["stop"])
    
    @commands.slash_command(aliases=['s'], description=loc["descriptions"]["skip"])
    async def skip(self, ctx):
        # Skips the current song
        if not (await checkUserAndBotChannel(ctx)):
            return
        if not ctx.voice_state.is_playing:
            return await respond(ctx, loc["messages"]["no_playing"], color=0xff0000)
        ctx.voice_state.skip()
        await respond(ctx, loc["messages"]["skipped"])
        
    @commands.slash_command(aliases=["q"], description=loc["descriptions"]["queue"])
    async def queue(self, ctx, *, page:discord.Option(int, loc["descriptions"]["queue"])=None):
        # Shows the queue, add page number to view different pages
        if not (await checkUserAndBotChannel(ctx)):
            return
        try:
            page = int(page)
        except:
            page = 1
        if len(ctx.voice_state.songs) == 0 and ctx.voice_state.current is None:
            return await respond(ctx, loc["messages"]["empty_queue"], color=0xff0000)
        
        # Invoking queue while the bot is retrieving another song will cause error, wait for 1 second
        while ctx.voice_state.current is None or isinstance(ctx.voice_state.current, dict):
            await asyncio.sleep(1)
        return await respond(ctx, embed=queue_embed(
            ctx.voice_state.songs,
            page,
            loc["queue_embed"]["title"],
            loc["queue_embed"]["body"].format(ctx.voice_state.current.source.title, ctx.voice_state.current.source.url, parse_duration(ctx.voice_state.current.source.duration_int - int(time.time() - ctx.voice_state.current.starttime - ctx.voice_state.current.pause_duration))),
            "url"
        ))
       
    @commands.slash_command(description=loc["descriptions"]["shuffle"])
    async def shuffle(self, ctx):
        # Shuffles the queue
        if not (await checkUserAndBotChannel(ctx)):
            return
        ctx.voice_state.songs.shuffle()
        await respond(ctx, loc["messages"]["shuffled"])

    @commands.slash_command(description=loc["descriptions"]["remove"])
    async def remove(self, ctx, index:discord.Option(int, loc["descriptions"]["remove"], required=True)):
        if not (await checkUserAndBotChannel(ctx)):
            return
        # Try to parse the index of the song that is going to be removed
        try:
            index = int(index)
        except:
            return await respond(ctx, loc["messages"]["invalid_song_number"], color=0xff0000)
        # If the user invoking this command is not in the same channel, return error
        if len(ctx.voice_state.songs) == 0:
            return await respond(ctx, loc["messages"]["empty_queue"], color=0xff0000)
        name = ctx.voice_state.songs[index - 1]
        ctx.voice_state.songs.remove(index - 1)

        await ctx.message.add_reaction('🗑️')

    @commands.slash_command(description=loc["descriptions"]["loop"])
    async def loop(self, ctx):
        # Toggle the looping of the current song
        if not (await checkUserAndBotChannel(ctx)):
            return
        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        await respond(ctx, loc["messages"][("enable" if ctx.voice_state.loop else "disable") + "_loop"])
        if ctx.voice_state.message:
            await ctx.voice_state.update()

    @commands.slash_command(aliases=["p"], description=loc["descriptions"]["play"])
    async def play(self, ctx, search:discord.Option(str, loc["descriptions"]["play"], required=True)):
        # Plays a song, mostly from Youtube
        """Plays a song.
        If there are songs in the queue, this will be queued until the
        other songs finished playing.
        This command automatically searches from various sites if no URL is provided.
        A list of these sites can be found here: https://rg3.github.io/youtube-dl/supportedsites.html
        """

        if search == None:
            return await respond(ctx, loc["messages"]["provide_url"], color=0xff0000)
        
        await _play(ctx, search, self.bot.loop)
            
    @commands.slash_command(description=loc["descriptions"]["search"])
    async def search(self, ctx, keyword:discord.Option(str, loc["descriptions"]["search"], required=True)):
        # Search from Youtube and returns 10 songs
        if keyword == None:
            return await respond(ctx, loc["messages"]["play_no_keyword"], color=0xff0000)
        originalkeyword = keyword
        keyword = "ytsearch10:" + keyword
        data = SongSource.ytdl_playlist.extract_info(keyword, download=False)
        result = []
        # Get 10 songs from the result
        for index, entry in enumerate(data["entries"]):
            try:
                duration = parse_duration(int(entry.get('duration')))
            except:
                duration = loc["unknown"]
            result.append({
                "title": entry.get("title"),
                "duration": duration,
                "url": entry.get('webpage_url', "https://youtu.be/" + entry.get('id')),
                "index": index
            })
        embed = discord.Embed(  title=loc["messages"]["search_title"].format(originalkeyword),
                                description=loc["messages"]["search_desc"],
                                color=discord.Color.green())
        # For each song, combine the details to a string
        for count, entry in enumerate(result):
            embed.add_field(name=f'{count+1}. {entry["title"]}', value=loc["messages"]["search_row"].format(entry["url"], entry["duration"]), inline=False)
        # Send the message of the results
        view = SearchView(self.bot, result, ctx, self)

        await respond(ctx, embed=embed, view=view)

    @commands.slash_command(description=loc["descriptions"]["musicreload"])
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
        await respond(ctx, loc["messages"]["reloaded"], color=discord.Color.green())
    
    @commands.slash_command(aliases=['lq'], description=loc["descriptions"]["loopqueue"])
    async def loopqueue(self, ctx):
        if not (await checkUserAndBotChannel(ctx)):
            return
        # Inverse the boolean
        ctx.voice_state.loopqueue = not ctx.voice_state.loopqueue
        # The current song will also loop if loop queue enabled
        try:
            if ctx.voice_state.loopqueue:
                await ctx.voice_state.songs.put({"url": ctx.voice_state.current.source.url, "title": ctx.voice_state.current.source.title, "user": ctx.voice_state.current.source.requester, "duration": ctx.voice_state.current.source.duration_int})
        except:
            pass
        
        await respond(ctx, loc["messages"][("enable" if ctx.voice_state.loopqueue else "disable") + "_loopqueue"])
        if ctx.voice_state.message:
            await ctx.voice_state.update()
    
    @commands.slash_command(aliases=["pf"], description=loc["descriptions"]["playfile"])
    async def playfile(self, ctx, attachment:discord.Option(discord.Attachment, loc["descriptions"]["playfile"], required=True), title=None):
        # Plays uploaded file
        if isBotInChannel(ctx):
            if isBotAndUserInSameChannel(ctx, ctx.author):
                pass
            else:
                return await respond(ctx, loc["messages"]["enter_before_play"], color=0xff0000)
        else:
            await _join(ctx, author=ctx.author)
            # Errors may occur while joining the channel, if the voice is None, don't continue
            if not ctx.voice_state.voice:
                return await respond(ctx, loc["messages"]["cannot_join_unk"], color=0xff0000)
        
        # Creates temporary folder for storing the audio file
        if not os.path.isdir("./tempMusic"):
            os.mkdir("./tempMusic")
        if not os.path.isdir("./tempMusic/" + str(ctx.guild.id)):
            os.mkdir("./tempMusic/" + str(ctx.guild.id))
        # Path is ./tempMusic/<guild_id>/<current_time>.<extension>
        filename = "./tempMusic/"+ str(ctx.guild.id) + "/" + str(int(time.time() * 10000000)) + "." + attachment.filename.split(".")[-1]
        # Saves the attachment
        await attachment.save(filename)
        # User can provide a title for the uploaded file
        if not title:
            title = attachment.filename
        # Tries to put it in queue, if it cannot parse the duration
        try:
            await ctx.voice_state.songs.put({"url": "local@" + filename, "title": title, "user": ctx.author, "duration": int(float(subprocess.check_output(f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{filename}\"", shell=True).decode("ascii").replace("\r", "").replace("\n", "")))})
        except:
            return await respond(ctx, loc["messages"]["cannot_add_invalid_file"], color=0xff0000)
        # Displaying filename with _ will cause discord to format the text, replace them with \_ to avoid this problem
        await respond(ctx, loc["messages"]["added_song"].format(title.replace("_", "\\_")), color=0x1eff00)
        ctx.voice_state.stopped = False

    @commands.slash_command(aliases=["rs"])
    async def runningservers(self, ctx):
        # Check whether the user id is in the author list
        if ctx.author.id in authors:
            # Count how many servers are connected to a voice channel
            server_count, desc = 0, ''
            for guild_id, voice_state in self.voice_states.items():
                if voice_state.voice:
                    server_count += 1
                    desc += f'{self.bot.get_guild(guild_id).name} / {guild_id}\n'
            return await respond(ctx, embed=discord.Embed(title=loc["messages"]["runningservers"].format(str(server_count)), description=desc[:-1]))

    @commands.slash_command(description=loc["descriptions"]["seek"])
    async def seek(self, ctx, seconds:discord.Option(str, loc["descriptions"]["seek"])=None):
        if not (await checkUserAndBotChannel(ctx)):
            return
        
        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.seeking = True
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
                return await respond(ctx, loc["messages"]["parse_second_failed"], color=0xff0000)
            if seconds is None:
                return await respond(ctx, loc["messages"]["no_second_parse"], color=0xff0000)
            ctx.voice_state.seek_time = seconds
            current = ctx.voice_state.current
            try:
                domain = current.source.url.split("/")[2]
            except:
                domain = ""
            await ctx.voice_state.seek(seconds, "local@" in current.source.url, not ("youtube" in domain or "youtu.be" in domain))
            await respond(ctx, loc["messages"]["seekto"].format(seconds), color=0x1eff00)
        else:
            await respond(ctx, loc["messages"]["no_playing"], color=0xff0000)

    @commands.slash_command(description=loc["descriptions"]["musicversion"])
    async def musicversion(self, ctx):
        await respond(ctx, embed=discord.Embed(title=loc["cog_name"]).
        add_field(name=loc["author"], value="<@127312771888054272>").
        add_field(name=loc["cog_github"], value=loc["cog_github_link"])
        .add_field(name=loc["cog_language"], value=language)
        .set_thumbnail(url="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png"))

def setup(bot):
    bot.add_cog(Music(bot))
