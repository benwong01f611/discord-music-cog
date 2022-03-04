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
from discord.ext import commands

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
    "ERROR: Sign in to confirm your age\nThis video may be inappropriate for some users.": "此影片設有年齡限制！",
    "Video unavailable": "影片不可用！",
    "ERROR: Private video\nSign in if you've been granted access to this video": "此影片為私人影片！"
}

# Insert authors' id in here, user in this set are allowed to use command "runningservers"
authors = (,)

class VoiceError(Exception):
    pass

class YTDLError(Exception):
    pass

class FFMPEGSource(discord.PCMVolumeTransformer):
    def __init__(self, ctx: commands.Context, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5, seek=None):
        super().__init__(source, volume)
        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        try:
            self.duration = self.parse_duration(int(data.get('duration')))
        except:
            self.duration = "不明"
        try:
            self.duration_raw = self.parse_duration_raw(int(data.get('duration')))
        except:
            self.duration = "不明"
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
            duration.append(f"{days} 天")
        if hours > 0:
            duration.append(f"{hours} 時")
        if minutes > 0:
            duration.append(f"{minutes} 分")
        if seconds > 0:
            duration.append(f"{seconds} 秒")

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

    def __init__(self, ctx: commands.Context, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5, seek=None):
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
            self.duration = "不明"
        try:
            self.duration_raw = self.parse_duration_raw(int(data.get('duration')))
        except:
            self.duration_raw = "不明"
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
    async def create_source(self, ctx: commands.Context, search: str, *, loop: asyncio.BaseEventLoop = None, requester=None, seek=None):
        loop = loop or asyncio.get_event_loop()

        # Extract data with youtube-dl
        partial = functools.partial(self.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        # Return error if nothing can be found
        if data is None:
            return await self.respond(ctx.ctx, f"找不到任何匹配的內容或項目：`{search}`")

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
               return await self.respond(ctx.ctx, f"找不到任何匹配的內容或項目：`{search}`")

        # Retrieve the video details
        webpage_url = process_info['webpage_url']
        partial = functools.partial(self.ytdl.extract_info, webpage_url, download=False)
        processed_info = await loop.run_in_executor(None, partial)

        if processed_info is None:
            return await self.respond(ctx.ctx, f"C無法取得該內容或項目：`{webpage_url}`")
        if 'entries' not in processed_info:
            info = processed_info
        else:
            info = None
            while info is None:
                try:
                    info = processed_info['entries'].pop(0)
                except IndexError:
                    return await self.respond(ctx.ctx, f"找不到任何匹配的內容或項目：`{webpage_url}`")
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
            duration.append(f"{days} 天")
        if hours > 0:
            duration.append(f"{hours} 時")
        if minutes > 0:
            duration.append(f"{minutes} 分")
        if seconds > 0:
            duration.append(f"{seconds} 秒")

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
        embed = (discord.Embed(title='正在播放',
                               description=f"```css\n{self.source.title}\n```",
                               color=discord.Color.blurple())
                 .add_field(name='影片長度', value=(self.source.duration if status == "play" else YTDLSource.parse_duration_raw(int(time.time() - self.starttime - self.pause_duration)) + "/" + self.source.duration_raw))
                 .add_field(name='影片播放者', value=self.requester.mention))
        # If it is not a file, it is a youtube video
        if not self.isFile:
            embed.add_field(name='影片上傳者', value=f"[{self.source.uploader}]({self.source.uploader_url})")
            embed.add_field(name='影片網址', value=f"[影片網址 / Click Here]({self.source.url})")
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
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
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

    def recreate_bg_task(self, ctx):
        self.__init__(self.bot, ctx)

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
                    self.message = await self.current.source.channel.send(embed=self.current.create_embed("play"))
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
                        duration = "不明"
                    queue += f"`{i+1}.` **{title}** ({duration})\n"
                else:
                    try:
                        duration = YTDLSource.parse_duration_raw(song['duration'])
                    except:
                        duration = "不明"
                    queue += f"`{i+1}.` [**{song['title']}**]({url}{song[song_id]}) ({duration})\n"
        else:
            queue = "No songs in queue..."
        embed = (discord.Embed(
                    title=header,
                    description=description)
                .add_field(name=f"**{len(data)} 曲目：** - {YTDLSource.parse_duration(self.getTotalDuration(data))}", value=queue)
                .set_footer(text=f"目前頁面：{page}/{pages}")
            )
        return embed

    # Function for responding to the user
    # reply=True will cause the bot to reply to the user (discord function)
    async def respond(self, ctx, message: str=None, embed: discord.Embed=None, reply: bool=False):
        if reply:
            return await ctx["message"].reply(message, embed=embed, mention_author=False)
        else:
            if isinstance(ctx, dict):
                return await ctx["channel"].send(message, embed=embed)
            else:
                return await ctx.send(message, embed=embed)

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    # Get the voice state from dictionary, create if it does not exist
    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state
        # When invoking this function, check whether the audio player task is done
        # If it is done, recreate the task
        if state.audio_player and state.audio_player.done():
            state.recreate_bg_task(ctx)
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
    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('該指令無法在私訊中使用！')
        return True

    # Before invoking any commands, get the voice state first
    # Update the context object also
    async def cog_before_invoke(self, ctx: commands.Context):
        self.get_voice_state(ctx)._ctx = ctx
        ctx.voice_state = self.get_voice_state(ctx)
        ctx.debug = ctx.voice_state.debug
        ctx.ctx = {"channel": ctx.channel, "message": ctx.message}

    # Return a meaningful message to user when error occurs
    # If debug log is enabled, return the traceback for debugging use. The debug message is encoded in base64 in case leaking the directory info
    async def cog_command_error(self, ctx, error):
        formatted_error = traceback.format_exc()
        if str(error) == "該指令無法在私訊中使用！":
            return await ctx.send("該指令無法在私訊中使用！")
        await ctx.send(f"錯誤：{error}")
        if ctx.voice_state:
            if ctx.voice_state.debug["debug_log"]:
                await ctx.send("Debug file", file=discord.File(io.BytesIO(base64.b64encode(formatted_error.encode("utf-8"))), f"{ctx.guild.id}_error.txt"))

    @commands.command(name='join', invoke_without_subcommand=True)
    async def _join(self, ctx: commands.Context):
        # Joins the channel

        # If the user is not in any voice channel, don't join
        if not ctx.author.voice or not ctx.author.voice.channel:
            await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入一個語音頻道！", color=0xff0000), reply=True)
            return False

        # If the bot is in the voice channel, check whether it is in the same voice channel or not
        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 機器人已經在一個語音頻道！", color=0xff0000), reply=True)
                return False
            else:
                await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 機器人已經在你的語音頻道！", color=0xff0000), reply=True)
                return False
        
        destination = ctx.author.voice.channel

        # Check permission
        if not destination.permissions_for(ctx.me).connect:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 機器人沒有權限加入該語音頻道！", color=0xff0000), reply=True)

        # Connect to the channel
        ctx.voice_state.voice = await destination.connect()
        await self.respond(ctx.ctx, embed=discord.Embed(title=":white_check_mark: 機器人已進入頻道！", color=0x1eff00), reply=True)

        # If the channel is a stage channel, wait for 1 second and try to unmute itself
        if isinstance(ctx.voice_state.voice.channel, discord.StageChannel):
            try:
                await asyncio.sleep(1)
                await ctx.me.edit(suppress=False)
            except:
                # Unable to unmute itself, ask admin to invite the bot to speak (auto)
                await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 機器人需要修改禁音權限！", color=0xff0000), reply=True)
        # Clear all music file
        if os.path.isdir(f"./tempMusic/{ctx.guild.id}"):
            shutil.rmtree(f"./tempMusic/{ctx.guild.id}")

    @commands.command(name='summon')
    async def _summon(self, ctx: commands.Context, *, channel=None):
        # Summon the bot to other channel or the current channel

        # Didn't join a channel or specify a channel to join
        if not channel and not ctx.author.voice:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你必須指定或進入一個語音頻道！", color=0xff0000), reply=True)
        channel_find = None
        # Try to find the channel
        try:
            channel_find = ctx.guild.get_channel(int(channel))
        except:
            try:
                channel_find = ctx.guild.get_channel(int(channel[2:-1]))
            except:
                if channel_find is None and not ctx.author.voice:
                    return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 找不到該頻道！", color=0xff0000), reply=True)
        if channel_find is None:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 找不到該頻道！", color=0xff0000), reply=True)
        # Only allow members with "Move member" permission to use this command
        if not ctx.author.guild_permissions.move_members:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 只有擁有\"移動成員\"權限的用戶才能使用本指令！", color=0xff0000), reply=True)
        
        destination = channel_find or ctx.author.voice.channel

        # Check permission
        if not destination.permissions_for(ctx.me).connect:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 機器人沒有權限加入該語音頻道！", color=0xff0000), reply=True)
        
        # Move to the specific channel and update internal memory
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            msg = await self.respond(ctx.ctx, embed=discord.Embed(title=f":white_check_mark: 機器人已進入 {destination.name}！", color=0x1eff00), reply=True)
            ctx.voice_state.voice = msg.guild.voice_client
        else:
            # Not in any channel, use connect instead
            ctx.voice_state.voice = await destination.connect()
            msg = await self.respond(ctx.ctx, embed=discord.Embed(title=f":white_check_mark: 機器人已進入 {destination.name}！", color=0x1eff00), reply=True)
        # If the channel is a stage channel, wait for 1 second and try to unmute itself
        if isinstance(ctx.voice_state.voice.channel, discord.StageChannel):
            try:
                await asyncio.sleep(1)
                await ctx.me.edit(suppress=False)
            except:
                await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 機器人需要修改禁音權限！", color=0xff0000), reply=True)

    @commands.command(name='leave', aliases=['disconnect', 'dc'])
    async def _leave(self, ctx: commands.Context):
        # Clears the queue and leave the channel

        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)

            if not ctx.voice_state.voice:
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 機器人並沒有連接到任何頻道！", color=0xff0000), reply=True)

        await self.respond(ctx.ctx, embed=discord.Embed(title=":white_check_mark: 機器人已離開頻道！", color=0x1eff00), reply=True)
        # Leaves the channel and delete the data from memory
        await ctx.voice_state.stop(leave=True)
        del self.voice_states[ctx.guild.id]

    @commands.command(name='volume', aliases=['v'])
    async def _volume(self, ctx: commands.Context, volume=None):
        # If the parameter is set, try to parse it as an integer
        try:
            if volume is not None:
                volume = int(volume)
        except:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 請輸入有效數字！", color=0xff0000), reply=True)
        # Sets the volume of the player
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)
            
        # If the bot is not connected to any voice channel, return error
        if not ctx.voice_state:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 機器人並沒有連接到任何頻道！", color=0xff0000), reply=True)

        # If volume is not none, the user is updating the volume
        if volume is not None:
            # The volume should be 0 < volume < 100
            if 0 > volume or volume > 100:
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你只能設定`1~100`之間的音量！", color=0xff0000), reply=True)
            # The volume should be 0.00~1.00
            ctx.voice_state.volume = volume / 100
            await self.respond(ctx.ctx, embed=discord.Embed(title=f":white_check_mark: 已更改音樂音量至`{volume}`！", color=0x1eff00))
        else:
            # Return the current volume
            return await self.respond(ctx.ctx, embed=discord.Embed(title=f"目前音量: `{int(ctx.voice_state.volume*100)}`%", color=0x1eff00))

    @commands.command(name='now', aliases=['current', 'playing'])
    async def _now(self, ctx: commands.Context):
        # Display currently playing song
        if ctx.voice_state.current is None:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 這個伺服器沒有任何正在播放的音樂！", color=0xff0000), reply=True)
        await self.respond(ctx.ctx, embed=ctx.voice_state.current.create_embed("now"), reply=True)

    @commands.command(name='pause')
    async def _pause(self, ctx: commands.Context):
        # Pauses the player
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)
        # If the bot is playing, pause it
        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            await self.respond(ctx.ctx, embed=discord.Embed(title=":arrow_forward: 已暫停目前歌曲！", color=0x1eff00), reply=True)
            # Sets the pause time
            ctx.voice_state.current.pause_time = time.time()
            ctx.voice_state.current.paused = True
        else:
            await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 目前沒有任何歌曲正在播放！", color=0xff0000), reply=True)

    @commands.command(name='resume', aliases=['r'])
    async def _resume(self, ctx: commands.Context):
        # Resumes the bot
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)
        # If the bot is paused, resume it
        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()
            await self.respond(ctx.ctx, embed=discord.Embed(title=":pause_button: 已開始繼續目前歌曲！", color=0x1eff00), reply=True)
            # Updates internal data for handling song progress that was paused
            ctx.voice_state.current.pause_duration += time.time() - ctx.voice_state.current.pause_time
            ctx.voice_state.current.pause_time = 0
            ctx.voice_state.current.paused = False
        else:
            await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 目前沒有任何歌曲正在播放！", color=0xff0000), reply=True)

    @commands.command(name='stop')
    async def _stop(self, ctx: commands.Context):
        # Stops the bot and clears the queue
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error 
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)
        ctx.voice_state.songs.clear()

        if ctx.voice_state.is_playing:
            await ctx.voice_state.stop()
            ctx.voice_state.stopped = True
            await self.respond(ctx.ctx, embed=discord.Embed(title=":record_button: 已清除並停止所有音樂！", color=0x1eff00), reply=True)

    @commands.command(name='skip', aliases=['s'])
    async def _skip(self, ctx: commands.Context):
        # Skips the current song
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)
        if not ctx.voice_state.is_playing:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 這個伺服器沒有任何正在播放的音樂！", color=0xff0000), reply=True)

        await self.respond(ctx.ctx, embed=discord.Embed(title=":next_track: 已跳過當前音樂！", color=0x1eff00), reply=True)
        ctx.voice_state.skip()

    @commands.command(name='queue', aliases=["q"])
    async def _queue(self, ctx: commands.Context, *, page=None):
        # Shows the queue, add page number to view different pages
        if page is not None:
            try:
                page = int(page)
            except:
                page = 1
        else:
            page = 1
        if len(ctx.voice_state.songs) == 0 and ctx.voice_state.current is None:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 播放序列為空白！", color=0xff0000), reply=True)
        
        # Invoking queue while the bot is retrieving another song will cause error, wait for 1 second
        while ctx.voice_state.current is None or isinstance(ctx.voice_state.current, dict):
            await asyncio.sleep(1)
        return await self.respond(ctx.ctx, embed=self.queue_embed(ctx.voice_state.songs, page, f"正在播放", f"[**{ctx.voice_state.current.source.title}**]({ctx.voice_state.current.source.url}) (剩餘{YTDLSource.parse_duration(ctx.voice_state.current.source.duration_int - int(time.time() - ctx.voice_state.current.starttime - ctx.voice_state.current.pause_duration))})", "url"))

    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: commands.Context):
        # Shuffles the queue
        # If the user invoking this command is not in the same channel, return error
        if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)
        if len(ctx.voice_state.songs) == 0:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 這個伺服器沒有任何等待播放的音樂！", color=0xff0000), reply=True)

        ctx.voice_state.songs.shuffle()
        await self.respond(ctx.ctx, embed=discord.Embed(title=":cyclone: 已打亂所有等待播放的音樂排序！", color=0x1eff00), reply=True)

    @commands.command(name='remove')
    async def _remove(self, ctx: commands.Context, index=None):
        if index is None:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 請輸入有效的歌曲號碼！", color=0xff0000), reply=True)
        # Try to parse the index of the song that is going to be removed
        try:
            index = int(index)
        except:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 請輸入有效的歌曲號碼！", color=0xff0000), reply=True)
        # If the user invoking this command is not in the same channel, return error
        if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)
        if ctx.voice_state.voice.channel != ctx.author.voice.channel:
            return
        if len(ctx.voice_state.songs) == 0:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 這個伺服器沒有任何等待播放的音樂！", color=0xff0000), reply=True)

        ctx.voice_state.songs.remove(index - 1)
        await self.respond(ctx.ctx, embed=discord.Embed(title=f":white_check_mark: 已刪除第`{index}`首歌！", color=0x1eff00), reply=True)

    @commands.command(name='loop')
    async def _loop(self, ctx: commands.Context):
        # Toggle the looping of the current song
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)
            if ctx.voice_state.voice.channel != ctx.author.voice.channel:
                return
        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        await self.respond(ctx.ctx, embed=discord.Embed(title="已" + ("啟用" if ctx.voice_state.loop else "關閉") + "歌曲循環", color=0x1eff00), reply=True)

    @commands.command(name='play', aliases=["p"])
    async def _play(self, ctx: commands.Context, *, search=None):
        # Plays a song, mostly from Youtube
        """Plays a song.
        If there are songs in the queue, this will be queued until the
        other songs finished playing.
        This command automatically searches from various sites if no URL is provided.
        A list of these sites can be found here: https://rg3.github.io/youtube-dl/supportedsites.html
        """

        if search == None:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 請提供關鍵字或URL以搜尋！", color=0xff0000), reply=True)
        # Joins the channel if it hasn't
        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)
        # Errors may occur while joining the channel, if the voice is None, don't continue
        if not ctx.voice_state.voice:
            return
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)

            if ctx.voice_client:
                if ctx.voice_client.channel != ctx.author.voice.channel:
                    return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 機器人已經在一個語音頻道！", color=0xff0000), reply=True)
            
        loop = self.bot.loop
        try:
            await self.respond(ctx.ctx, f"正在搜尋該曲目或網址：**{search}**")
            # Supports playing a playlist but it must be like https://youtube.com/playlist?
            if "/playlist?" in search:
                partial = functools.partial(YTDLSource.ytdl_playlist.extract_info, search, download=False)
                data = await loop.run_in_executor(None, partial)
                if data is None:
                    return await self.respond(ctx.ctx, embed=discord.Embed(title=f":x: 找不到任何匹配的內容或項目：`{search}`", color=0xff0000), reply=True)
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
                await self.respond(ctx.ctx, embed=discord.Embed(title=f":white_check_mark: 已將 `{songs+1}` 首歌曲加入至播放序列中", color=0x1eff00), reply=True)
            else:
                # Just a single song
                try:
                    partial = functools.partial(YTDLSource.ytdl.extract_info, search, download=False)
                    data = await loop.run_in_executor(None, partial)
                except Exception as e:
                    # Get the error message from dictionary, if it doesn't exist in dict, return the original error message
                    message = error_messages.get(str(e), str(e))
                    return await self.respond(ctx.ctx, embed=discord.Embed(title=f":x: 錯誤：{message}", color=0xff0000), reply=True)
                if "entries" in data:
                    if len(data["entries"]) > 0:
                        data = data["entries"][0]
                    else:
                        return await self.respond(ctx.ctx, embed=discord.Embed(title=f":x: 找不到任何匹配的內容或項目：`{search}`", color=0xff0000), reply=True)
                # Add the song to the pending list
                try:
                    duration = int(data["duration"])
                except:
                    duration = 0
                await ctx.voice_state.songs.put({"url": data["webpage_url"], "title": data["title"], "user": ctx.author, "duration": duration})
                await self.respond(ctx.ctx, embed=discord.Embed(title=f"已將歌曲 `{data['title']}` 加入至播放序列中", color=0x1eff00), reply=True)
            ctx.voice_state.stopped = False
        except YTDLError as e:
            await self.respond(ctx.ctx, embed=discord.Embed(title=f":x: 機器人處理該歌曲時發生錯誤：{str(e)}", color=0x1eff00), reply=True)
            
    @commands.command(name='search')
    async def search(self, ctx, *, keyword = None):
        # Search from Youtube and returns 10 songs
        if keyword == None:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 請提供關鍵字以搜尋！", color=0xff0000), reply=True)
        originalkeyword = keyword
        keyword = "ytsearch10:" + keyword
        data = YTDLSource.ytdl_playlist.extract_info(keyword, download=False)
        result = []
        # Get 10 songs from the result
        for entry in data["entries"]:
            try:
                duration = YTDLSource.parse_duration(int(entry.get('duration')))
            except:
                duration = "不明"
            result.append(
                {
                    "title": entry.get("title"),
                    "duration": duration,
                    "url": entry.get('webpage_url', "https://youtu.be/" + entry.get('id'))
                }
            )
        embed = discord.Embed(  title=f'`{originalkeyword}`的搜尋結果：',
                                description="請點擊反應來選擇搜索到的結果！",
                                color=discord.Color.green())
        # For each song, combine the details to a string
        for count, entry in enumerate(result):
            embed.add_field(name=f'{count+1}. {entry["title"]}', value=f'[影片網址 / Click Here]({entry["url"]})' + "\n影片時長：" + entry["duration"] + "\n", inline=False)
        # Send the message of the results
        message = await self.respond(ctx.ctx, embed=embed, reply=True)
        reaction_list = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        # Add reactions to that message
        for x in range(count + 1):
            await message.add_reaction(reaction_list[x])
        # Function for checking whether the responding user is the same user, the emoji is in the list, and the message is the same message
        def check(reaction, user):
            return user == ctx.message.author and str(reaction.emoji) in reaction_list and reaction.message == message

        try:
            # Wait for response, if no response after 1 minute, return message of timed out
            reaction, user = await self.bot.wait_for('reaction_add', timeout=60, check=check)
            # Edit the message to reduce its size
            await message.edit(embed=discord.Embed(title="已選擇結果：", description=result[reaction_list.index(reaction.emoji)]["title"], color=discord.Color.green()))
            # Invoke the play command
            if not ctx.author.voice or not ctx.author.voice.channel:
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入或指定一個語音頻道！", color=0xff0000), reply=True)

            if ctx.voice_client:
                if ctx.voice_client.channel != ctx.author.voice.channel:
                    return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 機器人已經在其他語音頻道！", color=0xff0000), reply=True)
            await self._play(ctx=ctx, search=result[reaction_list.index(reaction.emoji)]["url"])

        except asyncio.TimeoutError:
            # Timed out after 1 minute
            await message.edit(embed=discord.Embed(title='選擇時間已結束！', color=0xff0000))
        
    @commands.command(name='musicreload')
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
        await self.respond(ctx.ctx, embed=discord.Embed(title=":white_check_mark: 機器人己重新載入！", color=discord.Color.green()), reply=True)
    
    @commands.command(name="loopqueue", aliases=['lq'])
    async def loopqueue(self, ctx):
        # Loops the queue
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)
        
        # Inverse the boolean
        ctx.voice_state.loopqueue = not ctx.voice_state.loopqueue
        # The current song will also loop if loop queue enabled
        try:
            if ctx.voice_state.loopqueue:
                await ctx.voice_state.songs.put({"url": ctx.voice_state.current.source.url, "title": ctx.voice_state.current.source.title, "user": ctx.voice_state.current.source.requester, "duration": ctx.voice_state.current.source.duration_int})
        except:
            pass
        await self.respond(ctx.ctx, embed=discord.Embed(title="已" + ("啟用" if ctx.voice_state.loopqueue else "關閉") + "歌單循環", color=0x1eff00), reply=True)
    
    @commands.command(name="playfile", aliases=["pf"])
    async def playfile(self, ctx, *, title=None):
        # Plays uploaded file
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)
        # No file proviced
        if len(ctx.message.attachments) == 0:
            return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要提供一個檔案！", color=0xff0000), reply=True)
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
            return await self.respond(ctx.ctx, discord.Embed(title="無法新增此歌曲，或許這不是一個音訊檔案？", color=0xff0000), reply=True)
        # Displaying filename with _ will cause discord to format the text, replace them with \_ to avoid this problem
        await self.respond(ctx.ctx, embed=discord.Embed(title='已將歌曲 `{}` 加入至播放序列中'.format(title.replace("_", "\\_")), color=0x1eff00), reply=True)
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
            return await self.respond(ctx.ctx, embed=discord.Embed(title=f"正在使用音樂機器人的伺服器: {str(server_count)}", description=desc[:-1]))

    @commands.command(name="seek")
    async def seek(self, ctx, seconds=None):
        if not ctx.debug["debug"]:
            # If the user invoking this command is not in the same channel, return error
            if not ctx.author.voice or not ctx.author.voice.channel or (ctx.voice_state.voice and ctx.author.voice.channel != ctx.voice_state.voice.channel):
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)
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
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 無法抓取跳轉的秒數！", color=0xff0000), reply=True)
            if seconds is None:
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要輸入跳轉的秒數！", color=0xff0000), reply=True)
            ctx.voice_state.seeking = True
            ctx.voice_state.seek_time = seconds
            current = ctx.voice_state.current
            await ctx.voice_state.seek(seconds, "local@" in current.source.url)
            await self.respond(ctx.ctx, embed=discord.Embed(title=f":fast_forward: 已跳轉至{seconds}秒！", color=0x1eff00), reply=True)
        else:
            await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 目前沒有任何歌曲正在播放！", color=0xff0000), reply=True)
    
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
            elif options == "skip":
                await self._skip(ctx)
            elif options == "loop":
                await self._loop(ctx)
            elif options in ("loopqueue", "lq"):
                await self.loopqueue(ctx)
            elif options == "seek":
                await self.seek(ctx, args)
            elif options in ("playfile", "pf"):
                await self.playfile(ctx)
            elif options == "pause":
                await self._pause(ctx)
            elif options == "resume":
                await self._resume(ctx)
            elif options == "stop":
                await self._stop(ctx)
            """elif options == "playlist":
                import io
                file = f"./music/playlist_{ctx.guild.id}.json"
                if os.path.isfile(file):
                    data = json.loads(open(file, "r", encoding="utf-8").read())
                else:
                    data = {}
                data = json.dumps(data, indent=4, ensure_ascii=False)
                await ctx.send(file=discord.File(io.BytesIO(data.encode("utf-8")), f"playlist_{ctx.guild.id}.json"))"""

    @commands.command(name="playlist")
    async def playlist_func(self, ctx, *, args=None):
        file = f"./music/playlist_{ctx.author.id}.json"
        if os.path.isfile(file):
            data = json.loads(open(file, "r", encoding="utf-8").read())
        else:
            data = {}
        if args is None:
            if data == {}:
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你沒有任何播放清單！", color=0xff0000), reply=True)
            else:
                return await self.respond(ctx.ctx, embed=discord.Embed(title="播放清單", description="\n".join(list(data.keys()))), reply=True)
        args = args.split(" ")
        if args[0] not in data:
            if len(args) == 1 or (len(args) >= 2 and args[1] != "create"):
                return await self.respond(ctx.ctx, embed=discord.Embed(title=f":x: 找不到名為{args[0]}的播放清單！", color=0xff0000), reply=True)
        if len(args) == 1:
            playlist = data[args[0]]
            page = 1
            if len(data[args[0]]) == 0:
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你的播放清單為空白！", color=0xff0000), reply=True)
            await self.respond(ctx.ctx, embed=self.queue_embed(data[args[0]], page, f"播放清單 \"{args[0]}\"", "", "id"))
        elif args[1] == "create":
            if args[0] not in data:
                data[args[0]] = []
                await self.respond(ctx.ctx, embed=discord.Embed(title=f":white_check_mark: 播放清單`{args[0]}`已被建立！", color=0x1eff00), reply=True)
            else:
                return await self.respond(ctx.ctx, embed=discord.Embed(title=f":x: 播放清單`{args[0]}`已經存在！", color=0xff0000), reply=True)
        elif args[1] == "delete":
            del data[args[0]]
            await self.respond(ctx.ctx, embed=discord.Embed(title=f":white_check_mark: 播放清單`{args[0]}`已被刪除！", color=0x1eff00), reply=True)
        elif args[1] == "add":
            playlist = data[args[0]]
            if len(args) == 2:
                await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 請提供歌曲的URL！", color=0xff0000), reply=True)
            else:
                loop = self.bot.loop
                if "/playlist?" in args[2]:
                    partial = functools.partial(YTDLSource.ytdl_playlist.extract_info, args[2], download=False)
                    data_search = await loop.run_in_executor(None, partial)
                    if data_search is None:
                        return await self.respond(ctx.ctx, embed=discord.Embed(title=f":x: 找不到任何匹配的內容或項目：`{args[2]}`", color=0xff0000), reply=True)
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
                    await self.respond(ctx.ctx, embed=discord.Embed(title=f":white_check_mark: :white_check_mark: 已將`{songs+1}`首歌曲加入至`{args[0]}`", color=0x1eff00), reply=True)
                else:
                    # Just a single song
                    try:
                        partial = functools.partial(YTDLSource.ytdl.extract_info, args[2], download=False)
                        data_video = await loop.run_in_executor(None, partial)
                    except Exception as e:
                        # Get the error message from dictionary, if it doesn't exist in dict, return the original error message
                        message = error_messages.get(str(e), str(e))
                        return await self.respond(ctx.ctx, embed=discord.Embed(title=f"錯誤： {message}", color=0xff0000), reply=True) 
                    if "entries" in data_video:
                        if len(data_video["entries"]) > 0:
                            data_video = data_video["entries"][0]
                        else:
                            return await self.respond(ctx.ctx, embed=discord.Embed(title=f":x: 找不到任何匹配的內容或項目：`{args[2]}`", color=0xff0000), reply=True)
                    # Add the song to the pending list
                    playlist.append({"id": data_video["id"], "title": data_video["title"], "duration": int(data_video["duration"])})
                    await self.respond(ctx.ctx, embed=discord.Embed(title=f":white_check_mark: 已將歌曲 `{data_video['title']}` 加入至`{args[0]}`中", color=0x1eff00), reply=True)
        elif args[1] == "remove":
            if len(args) < 3:
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 請提供要移除的歌曲號碼！", color=0xff0000), reply=True)
            try:
                song = data[args[0]].pop(int(args[2])-1)
                await self.respond(ctx.ctx, embed=discord.Embed(title=f":white_check_mark: `{song['title']}`已從`{args[0]}`移除！", color=0x1eff00), reply=True)
            except:
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 無法移除歌曲，請提供有效的歌曲號碼！", color=0xff0000), reply=True)
        elif args[1] == "rename":
            if len(args) < 3 or args[2] == "":
                return await self.respond(ctx.ctx, embed=discord.Embed(title=f":x: 請為{args[0]}提供新的名字！", color=0xff0000), reply=True)
            if args[2] in data:
                return await self.respond(ctx.ctx, embed=discord.Embed(title=f":x: `{args[2]}`已經存在！.", color=0xff0000), reply=True)
            data[args[2]] = data[args[0]].copy()
            del data[args[0]]
            await self.respond(ctx.ctx, embed=discord.Embed(title=f"`{args[0]}` 已重新命名為`{args[2]}`", color=0xff0000), reply=True)
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
                    return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你需要先進入語音頻道或同一個語音頻道！", color=0xff0000), reply=True)
                if ctx.voice_client:
                    if ctx.voice_client.channel != ctx.author.voice.channel:
                        return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 機器人已經在一個語音頻道！", color=0xff0000), reply=True)
            if len(args) < 3 or args[2] == "":
                for songs, entry in enumerate(data[args[0]]):
                    try:
                        duration = int(entry["duration"])
                    except:
                        duration = 0
                    await ctx.voice_state.songs.put({"url": f"https://youtu.be/{entry['id']}", "title": entry["title"], "user": ctx.author, "duration": duration})
                ctx.voice_state.stopped = False
                return await self.respond(ctx.ctx, embed=discord.Embed(title=f":white_check_mark: 已將 `{songs+1}` 首歌曲加入至`{args[0]}`中", color=0x1eff00), reply=True)
            else:
                try:
                    index = int(args[2])-1
                    if index < 1 or index >= len(data[args[0]]):
                        raise Exception()
                except:
                    return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 請提供有效的歌曲號碼！", color=0xff0000), reply=True)
                entry = data[args[0]][index]
                try:
                    duration = int(entry["duration"])
                except:
                    duration = 0
                await ctx.voice_state.songs.put({"url": f"https://youtu.be/{entry['id']}", "title": entry["title"], "user": ctx.author, "duration": duration})
                ctx.voice_state.stopped = False
                return await self.respond(ctx.ctx, embed=discord.Embed(title=f"已從 `{args[0]}` 將歌曲 `{entry['title']}` 加入至播放序列中", color=0x1eff00), reply=True)
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
                return await self.respond(ctx.ctx, embed=discord.Embed(title=":x: 你的播放清單為空白！", color=0xff0000), reply=True)
            await self.respond(ctx.ctx, embed=self.queue_embed(data[args[0]], page, f"播放清單 \"{args[0]}\"", "", "id"))
        if not os.path.isdir("./music"):
            os.mkdir("./music")
        open(file, "w", encoding="utf-8").write(json.dumps(data))

def setup(bot):
    bot.add_cog(Music(bot))