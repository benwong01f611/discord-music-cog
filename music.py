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

# Silence useless bug reports messages
youtube_dl.utils.bug_reports_message = lambda: ''


class VoiceError(Exception):
    pass


class YTDLError(Exception):
    pass


class YTDLSource(discord.PCMVolumeTransformer):
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

    def __init__(self, ctx: commands.Context, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)

        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data

        self.uploader = data.get('uploader')
        self.uploader_url = data.get('uploader_url')
        date = data.get('upload_date')
        self.upload_date = date[6:8] + '.' + date[4:6] + '.' + date[0:4]
        self.title = data.get('title')
        self.thumbnail = data.get('thumbnail')
        self.description = data.get('description')
        self.duration = self.parse_duration(int(data.get('duration')))
        self.duration_raw = self.parse_duration_raw(int(data.get('duration')))
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
    async def create_source(self, ctx: commands.Context, search: str, *, loop: asyncio.BaseEventLoop = None):
        loop = loop or asyncio.get_event_loop()

        partial = functools.partial(self.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        if data is None:
            raise YTDLError('找不到任何匹配的內容或項目：`{}`'.format(search))

        if 'entries' not in data:
            process_info = data
        else:
            process_info = None
            for entry in data['entries']:
                if entry:
                    process_info = entry
                    break

            if process_info is None:
                raise YTDLError('找不到任何匹配的內容或項目：`{}`'.format(search))

        webpage_url = process_info['webpage_url']
        partial = functools.partial(self.ytdl.extract_info, webpage_url, download=False)
        processed_info = await loop.run_in_executor(None, partial)

        if processed_info is None:
            raise YTDLError('無法取得該內容或項目：`{}`'.format(webpage_url))

        if 'entries' not in processed_info:
            info = processed_info
        else:
            info = None
            while info is None:
                try:
                    info = processed_info['entries'].pop(0)
                except IndexError:
                    raise YTDLError('找不到任何匹配的內容或項目：`{}`'.format(webpage_url))

        return self(ctx, discord.FFmpegPCMAudio(info['url'], **self.FFMPEG_OPTIONS), data=info)

    @staticmethod
    def parse_duration(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration = []
        if days > 0:
            duration.append('{} 天'.format(days))
        if hours > 0:
            duration.append('{} 時'.format(hours))
        if minutes > 0:
            duration.append('{} 分'.format(minutes))
        if seconds > 0:
            duration.append('{} 秒'.format(seconds))

        return ', '.join(duration)
    
    @staticmethod
    def parse_duration_raw(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        
        durations = []
        if days > 0:
            durations.append(str(days))
        if hours > 0:
            durations.append(("0" if days and hours < 10 else "") + '{}'.format(hours))
        durations.append(("0" if hours and minutes < 10 else "") + '{}'.format(minutes))
        durations.append(("0" if seconds < 10 else "") + '{}'.format(seconds))
        
        return ':'.join(durations)

class Song:
    __slots__ = ('source', 'requester', 'starttime', 'pause_time', 'pause_duration', 'paused')

    def __init__(self, source: YTDLSource): 
        self.source = source
        self.requester = source.requester
        self.starttime = None
        self.pause_duration = 0
        self.pause_time = 0
        self.paused = False

    def create_embed(self, status: str):
        # If a new song is being played, it will simply display how long the song is
        # But if the command now is being executed, it will show how long the song has been played
        if self.paused:
            self.pause_duration += time.time() - self.pause_time
            self.pause_time = time.time()
        embed = (discord.Embed(title='正在播放',
                               description='```css\n{0.source.title}\n```'.format(self),
                               color=discord.Color.blurple())
                 .add_field(name='影片長度', value=(self.source.duration if status == "play" else YTDLSource.parse_duration_raw(int(time.time() - self.starttime - self.pause_duration)) + "/" + self.source.duration_raw))
                 .add_field(name='影片播放者', value=self.requester.mention)
                 .add_field(name='影片上傳者', value='[{0.source.uploader}]({0.source.uploader_url})'.format(self))
                 .add_field(name='影片網址', value='[影片網址 / Click Here]({0.source.url})'.format(self))
                 .set_thumbnail(url=self.source.thumbnail))

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
        self.skip_votes = set()

        self.audio_player = bot.loop.create_task(self.audio_player_task())
        self.skipped = False
        self.pause_time = 0.0
        self.pause_duration = 0.0

        self.loopqueue = False

    def recreate_bg_task(self, ctx):
        self.__init__(self.bot, ctx)

    def __del__(self):
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

    async def update_volume(self):
        # If it is not playing, dont check
        while self.is_playing:
            # Without sleep, it will cause lag (at least it lagged on my laptop hahahahahah)
            await asyncio.sleep(1)
            # If the volume is updated, update it
            if not isinstance(self.current, dict) and self.current and self.current.source.volume != self._volume:
                self.current.source.volume = self._volume
    
    async def create_song_source(self, ctx, url):
        return Song(await YTDLSource.create_source(ctx, url, loop=self.bot.loop))
    
    async def audio_player_task(self):
        while True:
            self.next.clear()

            if not self.loop:
                # Try to get the next song within 3 minutes.
                # If no song will be added to the queue in time,
                # the player will disconnect due to performance
                # reasons.
                try:
                    async with timeout(180):  # 3 minutes
                        # If it is skipped, clear the current song
                        if self.skipped:
                            self.current = None
                        self.current = await self.songs.get()
                        self.current = await self.create_song_source(self._ctx, self.current["url"])
                        # If loop queue, put the current song back to the end of the queue
                        if self.loopqueue:
                            await self.songs.put({"url": self.current.source.url, "title": self.current.source.title})
                        self.skipped = False
                        self.stopped = False
                except asyncio.TimeoutError:
                    await self.stop()
                    return
            else:
                # Loop but skipped, proceed to next song and keep looping
                if self.skipped or self.stopped:
                    self.current = None
                    try:
                        async with timeout(180):  # 3 minutes
                            self.current = await self.songs.get()
                            self.current = await self.create_song_source(self._ctx, self.current["url"])
                            self.skipped = False
                            self.stopped = False
                    except asyncio.TimeoutError:
                        await self.stop()
                        return
                self.current = await self.create_song_source(self._ctx, self.current.source.url)
            self.current.source.volume = self._volume
            self.voice.play(self.current.source, after=self.play_next_song)
            self.current.starttime = time.time()
            await self.current.source.channel.send(embed=self.current.create_embed("play"))
            # Create task for updating volume
            self.bot.loop.create_task(self.update_volume())
            await self.next.wait()

    def play_next_song(self, error=None):
        if error:
            raise VoiceError(str(error))
        if not self.loop:
            self.current = None
        self.next.set()

    def skip(self):
        self.skip_votes.clear()
        self.skipped = True
        if self.is_playing:
            self.voice.stop()

    async def stop(self):
        self.songs.clear()
        self.current = None
        if self.voice:
            await self.voice.disconnect()
            self.voice = None


class Music(commands.Cog):
    async def respond(self, ctx: commands.Context, message: str=None, embed: discord.Embed=None, reply: bool=False):
        if reply:
            return await ctx.message.reply(message, embed=embed)
        else:
            return await ctx.send(message, embed=embed)
    
    async def retrieveSong(self, ctx, url, playlist, pos):
        loop = asyncio.get_event_loop()
        partial = functools.partial(YTDLSource.ytdl.extract_info, url, download=False)
        processed_info = await loop.run_in_executor(None, partial)
        if processed_info is None:
            raise YTDLError('無法獲取該內容或項目：`{}`'.format(url))

        if 'entries' not in processed_info:
            info = processed_info
        else:
            info = None
            while info is None:
                try:
                    info = processed_info['entries'].pop(0)
                except IndexError:
                    raise YTDLError('找不到任何匹配的內容或項目：`{}`'.format(url))
        playlist.append([pos, Song(YTDLSource(ctx, discord.FFmpegPCMAudio(info['url'], **YTDLSource.FFMPEG_OPTIONS), data=info))])
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state
        if state.audio_player.done():
            state.recreate_bg_task(ctx)
        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('該指令無法在私訊中使用！')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    #async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
    #    await ctx.send('An error occurred: {}'.format(str(error)))


    @commands.command(name='join', invoke_without_subcommand=True)
    async def _join(self, ctx: commands.Context):
        """Joins a voice channel."""

        destination = ctx.author.voice.channel
        if ctx.voice_state.voice:
            await self.respond(ctx, embed=discord.Embed(title=":white_check_mark: 機器人已更換頻道！",color=0x1eff00), reply=True)
            await ctx.voice_state.voice.move_to(destination)
        else:
            await self.respond(ctx, embed=discord.Embed(title=":white_check_mark: 機器人已進入頻道！",color=0x1eff00), reply=True)
            ctx.voice_state.voice = await destination.connect()
        if isinstance(ctx.author.voice.channel, discord.StageChannel):
            try:
                await asyncio.sleep(1)
                await ctx.me.edit(suppress=False)
            except:
                await self.respond(ctx, embed=discord.Embed(title=":x: 機器人需要修改禁音權限！",color=0xff0000), reply=True)

    @commands.command(name='summon')
    async def _summon(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        """Summons the bot to a voice channel.

        If no channel was specified, it joins your channel.
        """

        if not channel and not ctx.author.voice:
            await self.respond(ctx, embed=discord.Embed(title=":x: 你必須指定或進入一個語音頻道！",color=0xff0000), reply=True)

        destination = channel or ctx.author.voice.channel
        if ctx.voice_state.voice:
            await self.respond(ctx, embed=discord.Embed(title=f":white_check_mark: 機器人已進入 {destination.name}！",color=0x1eff00), reply=True)
            await ctx.voice_state.voice.move_to(destination)
        else:
            await self.respond(ctx, embed=discord.Embed(title=f":white_check_mark: 機器人已進入 {destination.name}！",color=0x1eff00), reply=True)
            ctx.voice_state.voice = await destination.connect()
        if isinstance(ctx.author.voice.channel, discord.StageChannel):
            try:
                await asyncio.sleep(1)
                await ctx.me.edit(suppress=False)
            except:
                await self.respond(ctx, embed=discord.Embed(title=":x: 機器人需要修改禁音權限！",color=0xff0000), reply=True)

    @commands.command(name='leave', aliases=['disconnect', 'dc'])
    async def _leave(self, ctx: commands.Context):
        """Clears the queue and leaves the voice channel."""

        if not ctx.voice_state.voice:
            return await self.respond(ctx, embed=discord.Embed(title=":x: 機器人並沒有連接到任何頻道！",color=0xff0000), reply=True)

        await self.respond(ctx, embed=discord.Embed(title=":white_check_mark: 機器人已離開頻道！",color=0x1eff00), reply=True)
        await ctx.voice_state.stop()
        del self.voice_states[ctx.guild.id]

    @commands.command(name='volume', aliases=['v'])
    async def _volume(self, ctx: commands.Context, *, volume: int):
        """Sets the volume of the player."""

        if not ctx.voice_state:
            return await self.respond(ctx, embed=discord.Embed(title=":x: 機器人並沒有連接到任何頻道！！",color=0xff0000), reply=True)

        if 0 > volume or volume > 100:
            return await self.respond(ctx, embed=discord.Embed(title=":x: 你只能設定`1~100`之間的音量！",color=0xff0000), reply=True)

        ctx.voice_state.volume = volume / 100
        await self.respond(ctx, embed=discord.Embed(title=f":white_check_mark: 已更改音樂音量至`{volume}`！",color=0x1eff00))

    @commands.command(name='now', aliases=['current', 'playing'])
    async def _now(self, ctx: commands.Context):
        """Displays the currently playing song."""
        if(ctx.voice_state.current is None):
            return await self.respond(ctx, embed=discord.Embed(title=":x: 這個伺服器沒有任何正在播放的音樂！",color=0xff0000), reply=True)
        await self.respond(ctx, embed=ctx.voice_state.current.create_embed("now"), reply=True)

    @commands.command(name='pause')
    async def _pause(self, ctx: commands.Context):
        """Pauses the currently playing song."""

        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            await self.respond(ctx,embed=discord.Embed(title=":arrow_forward: 已暫停目前歌曲！",color=0x1eff00), reply=True)
            ctx.voice_state.current.pause_time = time.time()
            ctx.voice_state.current.paused = True
        else:
            await self.respond(ctx,embed=discord.Embed(title=":x: 目前沒有任何歌曲正在播放！",color=0xff0000), reply=True)

    @commands.command(name='resume', aliases=['r'])
    async def _resume(self, ctx: commands.Context):
        """Resumes a currently paused song."""

        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()
            await self.respond(ctx,embed=discord.Embed(title=":pause_button: 已開始繼續目前歌曲！",color=0x1eff00), reply=True)
            ctx.voice_state.current.pause_duration += time.time() - ctx.voice_state.current.pause_time
            ctx.voice_state.current.pause_time = 0
            ctx.voice_state.current.paused = False
        else:
            await self.respond(ctx,embed=discord.Embed(title=":x: 目前沒有任何歌曲正在播放！",color=0xff0000), reply=True)

    @commands.command(name='stop')
    async def _stop(self, ctx: commands.Context):
        """Stops playing song and clears the queue."""

        ctx.voice_state.songs.clear()

        if ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            ctx.voice_state.stopped = True
            await self.respond(ctx,embed=discord.Embed(title=":record_button: 已清除並停止所有音樂！",color=0x1eff00), reply=True)

    @commands.command(name='skip', aliases=['s'])
    async def _skip(self, ctx: commands.Context):
        """Vote to skip a song. The requester can automatically skip.
        3 skip votes are needed for the song to be skipped.
        """

        if not ctx.voice_state.is_playing:
            return await self.respond(ctx,embed=discord.Embed(title=":x: 這個伺服器沒有任何正在播放的音樂！",color=0xff0000), reply=True)

        await self.respond(ctx,embed=discord.Embed(title=":x: 已跳過當前音樂！",color=0x1eff00), reply=True)
        ctx.voice_state.skip()

    @commands.command(name='queue', aliases=["q"])
    async def _queue(self, ctx: commands.Context, *, page: int = 1):
        """Shows the player's queue.

        You can optionally specify the page to show. Each page contains 10 elements.
        """

        if len(ctx.voice_state.songs) == 0:
            await self.respond(ctx,embed=discord.Embed(title=":x: 這個伺服器沒有任何等待播放的音樂！",color=0xff0000), reply=True)

        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)

        start = (page - 1) * items_per_page
        end = start + items_per_page

        queue = ''
        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            queue += '`{0}.` [**{1[title]}**]({1[url]})\n'.format(i + 1, song)

        await self.respond(ctx, embed=discord.Embed(description='**{} 曲目：**\n\n{}'.format(len(ctx.voice_state.songs), queue))
                 .set_footer(text='目前頁面：{}/{}'.format(page, pages)), reply=True)

    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: commands.Context):
        """Shuffles the queue."""

        if len(ctx.voice_state.songs) == 0:
            await self.respond(ctx, embed=discord.Embed(title=":x: 這個伺服器沒有任何等待播放的音樂！",color=0xff0000), reply=True)

        ctx.voice_state.songs.shuffle()
        await self.respond(ctx, embed=discord.Embed(title=":cyclone: 已打亂所有等待播放的音樂排序！",color=0x1eff00), reply=True)

    @commands.command(name='remove')
    async def _remove(self, ctx: commands.Context, index: int):
        """Removes a song from the queue at a given index."""

        if len(ctx.voice_state.songs) == 0:
            await self.respond(ctx,embed=discord.Embed(title=":x: 這個伺服器沒有任何等待播放的音樂！",color=0xff0000), reply=True)

        ctx.voice_state.songs.remove(index - 1)
        await self.respond(ctx,embed=discord.Embed(title=f":white_check_mark: 已刪除第`{index}`首歌！",color=0x1eff00), reply=True)

    @commands.command(name='loop')
    async def _loop(self, ctx: commands.Context):
        """Loops the currently playing song.

        Invoke this command again to unloop the song.
        """
        if not ctx.voice_state:
            return await self.respond(ctx,embed=discord.Embed(title=":x: 機器人並沒有連接到任何頻道！",color=0xff0000), reply=True)

        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        ctx.voice_state.ctx = ctx
        await self.respond(ctx,embed=discord.Embed(title="已" + ("啟用" if ctx.voice_state.loop else "關閉") + "歌曲循環",color=0x1eff00), reply=True)

    @commands.command(name='play', aliases=["p"])
    async def _play(self, ctx: commands.Context, *, search: str):
        """Plays a song.

        If there are songs in the queue, this will be queued until the
        other songs finished playing.

        This command automatically searches from various sites if no URL is provided.
        A list of these sites can be found here: https://rg3.github.io/youtube-dl/supportedsites.html
        """

        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)
        
        loop = self.bot.loop
        try:
            await self.respond(ctx, '正在搜尋該曲目或網址：**{}**'.format(search))
            if "/playlist?" in search:
                await self.respond(ctx, embed=discord.Embed(title=f":white_check_mark: 正在建立伺服器歌單，請稍後！",color=0x1eff00))
                partial = functools.partial(YTDLSource.ytdl_playlist.extract_info, search, download=False)
                data = await loop.run_in_executor(None, partial)
                if data is None:
                    raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))
                entries = data["entries"]
                playlist = []
                for pos, song in enumerate(entries):
                    # Youtube only, guess no one would play other than Youtube, if yes, fuck off please
                    url = "https://www.youtube.com/watch?v=" + song["id"]
                    title = song["title"]
                    playlist.append({"pos": pos, "url": url, "title": title})
                # Sort the playlist variable to match with the order in YouTube
                playlist.sort(key=lambda song: song["pos"])
                # Add all songs to the pending list
                for songs, entry in enumerate(playlist):
                    await ctx.voice_state.songs.put({"url": entry["url"], "title": entry["title"]})
                await self.respond(ctx,embed=discord.Embed(title='已將 `{}` 首歌曲加入至播放清單中'.format(str(songs)),color=0x1eff00), reply=True)
            else:
                # Just a normal song
                partial = functools.partial(YTDLSource.ytdl.extract_info, search, download=False)
                data = await loop.run_in_executor(None, partial)
                if "entries" in data:
                    data = data["entries"][0]
                await ctx.voice_state.songs.put({"url": data["webpage_url"], "title": data["title"]})
                await self.respond(ctx, embed=discord.Embed(title='已將歌曲 `{}` 加入至播放清單中'.format(data["title"]),color=0x1eff00), reply=True)
            ctx.voice_state.stopped = False
        except YTDLError as e:
            await self.respond(ctx,embed=discord.Embed(title='機器人處理該歌曲時發生錯誤：{}'.format(str(e)),color=0x1eff00), reply=True)
            
    @commands.command(name='search')
    async def search(self, ctx, *, keyword: str):
        originalkeyword = keyword
        keyword = "ytsearch10:" + keyword
        data = YTDLSource.ytdl_playlist.extract_info(keyword, download=False)
        result = []
        for entry in data["entries"]:
            result.append(
                {
                    "title": entry.get("title"),
                    "duration": YTDLSource.parse_duration(int(entry.get('duration'))),
                    "url": entry.get('webpage_url', "https://www.youtube.com/watch?v=" + entry.get('id'))
                }
            )
        embed = discord.Embed(  title=f'`{originalkeyword}`的搜尋結果：',
                                description="請點擊反應來選擇搜索到的結果！",
                                color=discord.Color.green())
        for count, entry in enumerate(result):
            embed.add_field(name=f'{count+1}. {entry["title"]}', value=f'[影片網址 / Click Here]({entry["url"]})' + "\n影片時長：" + entry["duration"] + "\n", inline=False)
        message = await self.respond(ctx, embed=embed, reply=True)
        reaction_list = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for x in range(count + 1):
            await message.add_reaction(reaction_list[x])
        
        def check(reaction, user):
            return user == ctx.message.author and str(reaction.emoji) in reaction_list

        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=60, check=check)
            await message.edit(embed=discord.Embed(title="已選擇結果：", description=result[reaction_list.index(reaction.emoji)]["title"], color=discord.Color.green()))
            if not ctx.author.voice or not ctx.author.voice.channel:
                return await self.respond(ctx,embed=discord.Embed(title=":x: 你需要先進入或指定一個語音頻道！",color=0xff0000), reply=True)

            if ctx.voice_client:
                if ctx.voice_client.channel != ctx.author.voice.channel:
                    return await self.respond(ctx,embed=discord.Embed(title=":x: 機器人已經在其他語音頻道！",color=0xff0000), reply=True)
            await self._play(ctx=ctx, search=result[reaction_list.index(reaction.emoji)]["url"])

        except asyncio.TimeoutError:
            await self.respond(ctx,embed=discord.Embed(title='選擇時間已結束！',color=0xff0000), reply=True)
        
    @commands.command(name='musicreload')
    async def musicreload(self, ctx):
        await ctx.voice_state.stop()
        try:
            await ctx.me.voice.disconnect()
        except:
            pass
        del self.voice_states[ctx.guild.id]
        await self.respond(ctx, embed=discord.Embed(title=":white_check_mark: 機器人己重新載入！", color=discord.Color.green()), reply=True)
    
    @commands.command(name="loopqueue", aliases=['lq'])
    async def loopqueue(self, ctx):
        if not ctx.voice_state:
            return await self.respond(ctx, embed=discord.Embed(title=':x: 機器人並沒有連接到任何頻道！',color=0xff0000), reply=True)
        
        ctx.voice_state.loopqueue = not ctx.voice_state.loopqueue
        # The current song will also loop if loop queue enabled
        if ctx.voice_state.loopqueue:
            await ctx.voice_state.songs.put({"url": ctx.voice_state.current.source.url, "title": ctx.voice_state.current.source.title})
        await self.respond(ctx,"已" + ("啟用" if ctx.voice_state.loopqueue else "關閉") + "歌單循環")
    
    @_join.before_invoke
    @_play.before_invoke
    async def ensure_voice_state(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            await self.respond(ctx,embed=discord.Embed(title=":x: 你需要先進入或指定一個語音頻道！",color=0xff0000), reply=True)

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                await self.respond(ctx,embed=discord.Embed(title=":x: 機器人已經在一個語音頻道！",color=0xff0000), reply=True)

def setup(bot):
    bot.add_cog(Music(bot))