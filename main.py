import asyncio
import hashlib
import re
import os
import random
import json
import string

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultAudio,
    InputTextMessageContent,
    SwitchInlineQueryChosenChat,
    BufferedInputFile
)
from aiogram.filters import Command, CommandStart
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter, TelegramAPIError

from yandex_music import ClientAsync
from yandex_music.exceptions import YandexMusicError

import aiosqlite
from dotenv import load_dotenv
import aiohttp
import aiofiles
import ujson

load_dotenv()

bot = Bot(os.getenv('BOT_TOKEN'))
dp = Dispatcher()


async def get_audio_url(audio: bytes):
    me = await bot.get_me()
    msg = await bot.send_audio(
        chat_id=me.id,
        audio=BufferedInputFile(audio, filename=f'{random.randint(10000, 99999)}.mp3')
    )
    file = await bot.get_file(msg.audio.file_id)
    return f'https://api.telegram.org/file/bot{bot.token}/{file.file_path}'


async def handle_user(user_id: int) -> dict:
    # returns user data
    # adds user to database if not exists
    async with aiosqlite.connect('db.sqlite3') as db:
        cursor = await db.cursor()
        await cursor.execute(f'SELECT * FROM users WHERE id = {user_id}')
        row = await cursor.fetchone()
        if row:
            return {'id': row[0], 'ym_id': row[1], 'ym_token': row[2]}
        else:
            await cursor.execute(f'INSERT INTO users (id, ym_id, ym_token) VALUES ({user_id}, NULL, NULL)')
            await db.commit()
            async with aiofiles.open('stats.json', 'r') as f:
                stats = ujson.loads(await f.read())
            stats['users'] += 1
            async with aiofiles.open('stats.json', 'w') as f:
                await f.write(ujson.dumps(stats))
            return {'id': user_id, 'ym_id': None, 'ym_token': None}


async def update_user(user_id: int, update_fields: dict):
    # update_fields - field to update
    async with aiosqlite.connect('db.sqlite3') as db:
        cursor = await db.cursor()
        await cursor.execute(
            f'UPDATE users SET {", ".join([f"{field} =?" for field in update_fields.keys()])} WHERE id = ?',
            (*update_fields.values(), user_id)
        )
        await db.commit()


# https://github.com/vsecoder/hikka_modules/blob/main/ymnow.py#L42
async def get_current_track(client: ClientAsync, token: str):
    device_info = {
        "app_name": "Chrome",
        "type": 1,
    }

    ws_proto = {
        "Ynison-Device-Id": "".join(
            [random.choice(string.ascii_lowercase) for _ in range(16)]
        ),
        "Ynison-Device-Info": json.dumps(device_info),
    }

    timeout = aiohttp.ClientTimeout(total=15, connect=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(
                url="wss://ynison.music.yandex.ru/redirector.YnisonRedirectService/GetRedirectToYnison",
                headers={
                    "Sec-WebSocket-Protocol": f"Bearer, v2, {json.dumps(ws_proto)}",
                    "Origin": "http://music.yandex.ru",
                    "Authorization": f"OAuth {token}",
                },
                timeout=10,
            ) as ws:
                recv = await ws.receive()
                data = json.loads(recv.data)

            if "redirect_ticket" not in data or "host" not in data:
                print(f"Invalid response structure: {data}")
                return {"success": False}

            new_ws_proto = ws_proto.copy()
            new_ws_proto["Ynison-Redirect-Ticket"] = data["redirect_ticket"]

            to_send = {
                "update_full_state": {
                    "player_state": {
                        "player_queue": {
                            "current_playable_index": -1,
                            "entity_id": "",
                            "entity_type": "VARIOUS",
                            "playable_list": [],
                            "options": {"repeat_mode": "NONE"},
                            "entity_context": "BASED_ON_ENTITY_BY_DEFAULT",
                            "version": {
                                "device_id": ws_proto["Ynison-Device-Id"],
                                "version": 9021243204784341000,
                                "timestamp_ms": 0,
                            },
                            "from_optional": "",
                        },
                        "status": {
                            "duration_ms": 0,
                            "paused": True,
                            "playback_speed": 1,
                            "progress_ms": 0,
                            "version": {
                                "device_id": ws_proto["Ynison-Device-Id"],
                                "version": 8321822175199937000,
                                "timestamp_ms": 0,
                            },
                        },
                    },
                    "device": {
                        "capabilities": {
                            "can_be_player": True,
                            "can_be_remote_controller": False,
                            "volume_granularity": 16,
                        },
                        "info": {
                            "device_id": ws_proto["Ynison-Device-Id"],
                            "type": "WEB",
                            "title": "Chrome Browser",
                            "app_name": "Chrome",
                        },
                        "volume_info": {"volume": 0},
                        "is_shadow": True,
                    },
                    "is_currently_active": False,
                },
                "rid": "ac281c26-a047-4419-ad00-e4fbfda1cba3",
                "player_action_timestamp_ms": 0,
                "activity_interception_type": "DO_NOT_INTERCEPT_BY_DEFAULT",
            }

            async with session.ws_connect(
                url=f"wss://{data['host']}/ynison_state.YnisonStateService/PutYnisonState",
                headers={
                    "Sec-WebSocket-Protocol": f"Bearer, v2, {json.dumps(new_ws_proto)}",
                    "Origin": "http://music.yandex.ru",
                    "Authorization": f"OAuth {token}",
                },
                timeout=10,
                method="GET",
            ) as ws:
                await ws.send_str(json.dumps(to_send))
                recv = await asyncio.wait_for(ws.receive(), timeout=10)
                ynison = json.loads(recv.data)
                track_index = ynison["player_state"]["player_queue"][
                    "current_playable_index"
                ]
                if track_index == -1:
                    print("No track is currently playing.")
                    return {"success": False}
                track = ynison["player_state"]["player_queue"]["playable_list"][
                    track_index
                ]

            await session.close()
            info = await client.tracks_download_info(track["playable_id"], True)
            track = await client.tracks(track["playable_id"])
            return {
                "paused": ynison["player_state"]["status"]["paused"],
                "duration_ms": ynison["player_state"]["status"]["duration_ms"],
                "progress_ms": ynison["player_state"]["status"]["progress_ms"],
                "entity_id": ynison["player_state"]["player_queue"]["entity_id"],
                "repeat_mode": ynison["player_state"]["player_queue"]["options"][
                    "repeat_mode"
                ],
                "entity_type": ynison["player_state"]["player_queue"]["entity_type"],
                "track": track,
                "info": info,
                "success": True,
            }

    except Exception as e:
        return {"success": False, "error": str(e), "track": None}


@dp.message(F.text.startswith('@all') & F.from_user.id == int(os.getenv('ADMIN_ID')))
async def mail(message: Message):
    text = message.html_text[4:]
    async with aiosqlite.connect('db.sqlite3') as db:
        cursor = await db.cursor()
        await cursor.execute('SELECT id FROM users')
        user_ids = [row[0] for row in await cursor.fetchall()]
    for user_id in user_ids:
        await asyncio.sleep(0.05)
        try:
            await bot.send_message(user_id, text, parse_mode='HTML')
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except TelegramAPIError as e:
            pass

@dp.inline_query()
async def inline_search(query: InlineQuery):
    usr = await handle_user(query.from_user.id)
    me = await bot.get_me()
    if query.query.strip() == '':
        if not usr['ym_token']:
            text = f'Чтобы обнаружить текущий трек, мне нужен твой токен Яндекс Музыки. ' \
                   f'Пожалуйста, открой бота @{me.username} ' \
                   f'и введи свой токен Яндекс Музыки с помощью команды <code>/token [токен]</code>.\n' \
                   f'<a href="https://yandex-music.readthedocs.io/en/main/token.html">🔮 Как получить токен 🔮</a>'
            content = InputTextMessageContent(message_text=text, parse_mode='html')
            result_id = hashlib.md5(text.encode()).hexdigest()
            result = InlineQueryResultArticle(
                id=result_id,
                title='Подключи токен Яндекс Музыки чтобы автоматически обнаруживать текущий трек',
                input_message_content=content
            )
            return await query.answer(
                results=[result],
                cache_time=20,
                is_personal=True
            )
        async with aiofiles.open('stats.json', 'r') as f:
            stats = ujson.loads(await f.read())
        stats['total_requests'] += 1
        async with aiofiles.open('stats.json', 'w') as f:
            await f.write(ujson.dumps(stats))
        client = await ClientAsync(token=usr['ym_token']).init()
        res = await get_current_track(client, usr['ym_token'])
        if not res['success']:
            return await query.answer(
                results=[],
                cache_time=20,
                is_personal=True
            )
        track = res['track'][0]
        title = track['title']
        artists = ', '.join([artist['name'] for artist in track['artists']])
        duration = track['duration_ms'] // 1000
        track_id = track['id']
        url = res['info'][0]['direct_link']
        result_id = hashlib.md5(f'now:{track_id}'.encode()).hexdigest()
        songlink = f'https://song.link/ya/{track_id}'
        song_button = InlineKeyboardButton(text='Ссылка на трек', url=songlink)
        bot_button = InlineKeyboardButton(text=f'@{me.username}', url=f'https://t.me/{me.username}')
        markup = InlineKeyboardMarkup(inline_keyboard=[[song_button], [bot_button]])
        result = InlineQueryResultAudio(
            id=result_id,
            title=title,
            parse_mode='html',
            audio_duration=duration,
            reply_markup=markup,
            audio_url=url,
            caption=f'<b>Сейчас играет:</b>\n🎧 <code>{artists} - {title}</code>',
            performer=artists
        )
        return await query.answer(
            results=[result],
            cache_time=5,
            is_personal=True
        )
    else:
        async with aiofiles.open('stats.json', 'r') as f:
            stats = ujson.loads(await f.read())
        stats['total_requests'] += 1
        async with aiofiles.open('stats.json', 'w') as f:
            await f.write(ujson.dumps(stats))
        client = await ClientAsync(token=os.getenv('DEFAULT_YM_TOKEN')).init()
        results = await client.search(query.query, type_='track')
        if not results:
            return await query.answer(
                results=[],
                cache_time=600,
                is_personal=False
            )
        if not results.tracks:
            print(results.text)
            return await query.answer(
                results=[],
                cache_time=600,
                is_personal=False
            )
        tracks = results.tracks.results[:4]
        outs = []
        for track in tracks:
            title = track.title
            artists = ', '.join([artist.name for artist in track.artists])
            duration = track.duration_ms // 1000
            track_id = track.track_id.split(':')[-1]
            dlinfo = await track.get_specific_download_info_async(codec='mp3', bitrate_in_kbps=320)
            url = await dlinfo.get_direct_link_async()
            result_id = hashlib.md5(f'search:{track_id}'.encode()).hexdigest()
            songlink = f'https://song.link/ya/{track_id}'
            song_button = InlineKeyboardButton(text='Ссылка на трек', url=songlink)
            bot_button = InlineKeyboardButton(text=f'@{me.username}', url=f'https://t.me/{me.username}')
            markup = InlineKeyboardMarkup(inline_keyboard=[[song_button], [bot_button]])
            result = InlineQueryResultAudio(
                id=result_id,
                title=title,
                parse_mode='html',
                audio_duration=duration,
                reply_markup=markup,
                audio_url=url,
                caption=f'<b>Трек по запросу "<ш>{results.text}</ш>":</b>\n🎧 <code>{artists} - {title}</code>',
                performer=artists
            )
            outs.append(result)
        return await query.answer(
            results=outs,
            cache_time=600,
            is_personal=False
        )


@dp.message(CommandStart())
async def start(message: Message):
    usr = await handle_user(message.from_user.id)
    me = await bot.get_me()
    if not usr['ym_token']:
        button = InlineKeyboardButton(
            text='Или нажми на эту кнопку и выбери чат :)',
            switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(
                query='',
                allow_user_chats=True,
                allow_bot_chats=True,
                allow_group_chats=True,
                allow_channel_chats=True)
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[[button]])
        await message.answer(
            f'<b>Привет 👋</b>\n'
            f'Я помогу тебе делиться с другими музыкой которую ты слушаешь 🎧\n\n'
            f'Напиши в любом чате <code>{me.username} [запрос]</code> и подожди несколько секунд, '
            f'пока появятся результаты.\n\n'
            f'Ты также можешь отправлять трек, который сейчас играет у тебя в Яндекс Музыке, '
            f'но для этого нужно добавить свой токен Яндекс Музыки. '
            f'Если захочешь пользоваться этой функцией, пожалуйста, укажи его, через <code>/token [токен]</code>.\n'
            f'<a href="https://yandex-music.readthedocs.io/en/main/token.html">🔮 Как получить токен 🔮</a>',
            parse_mode='html',
            disable_web_page_preview=True,
            reply_markup=markup
        )
    else:
        me = await bot.get_me()
        button = InlineKeyboardButton(
            text='Либо нажмите на эту кнопку и выберите чат :)',
            switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(
                query='',
                allow_user_chats=True,
                allow_bot_chats=True,
                allow_group_chats=True,
                allow_channel_chats=True)
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[[button]])
        await message.answer(
            '<b>Всё готово ✅</b>\n'
            f'Теперь в любом чате ты можешь написать (не отправляя) <code>@{me.username} </code>, '
            f'подождать пару секунд и там появится трек, который сейчас играет у тебя.\n\n'
            f'Ты всё ещё можешь пользоваться поиском, '
            'просто напиши <code>@{me.username} [запрос]</code> и подожди несколько секунд.\n\n'
            'Если захочешь удалить свой токен из базы данных бота, используй команду /reset.',
            reply_markup=markup,
            parse_mode='html'
        )


@dp.message(Command('reset'))
async def reset_token(message: Message):
    usr = await handle_user(message.from_user.id)
    await update_user(usr['id'], {'ym_token': None, 'ym_id': None})
    await message.answer(
        '<b>Готово ✅</b>\n'
        'Твой токен и ID стёрты из базы данных бота и больше не смогут использоваться.\n'
        'Это полезно если ты больше не хочешь пользоваться ботом, на случай если например бота взломают, или '
        'создатель сойдёт с ума и начнёт делать что-то плохое.\n'
        'Если захочешь продолжить пользоваться функцией распознавания текущего трека, '
        'тебе надо будет снова добавить свой токен.',
        parse_mode='html'
    )


@dp.message(F.text.regexp(r'^/token\s+(\S+)$'))
async def set_token(message: Message):
    me = await bot.get_me()
    usr = await handle_user(message.from_user.id)
    uid = -1
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    match = re.match(r'^/token\s+(\S+)$', message.text)
    token = match.group(1)

    try:
        client = ClientAsync(token=token)
        await client.init()
        uid = client.me.account.uid
    except YandexMusicError:
        await message.answer('Прости, твой токен не подходит 🙁\nПопробуй ещё раз, или напиши @LapisMYT.')
        return
    if uid != -1:
        await update_user(usr['id'], {'ym_token': token, 'ym_id': uid})
        await message.answer(
            f'Спасибо, твой токен сохранён 🎉\n'
            f'Твой ID Яндекс Музыки: <code>{uid}</code> '
            f'(не знаю зачем он тебе, но пусть будет)\n\n'
            f'Если захочешь удалить токен из базы данных боты, просто напиши /reset ^_^',
            parse_mode='html'
        )
    else:
        await update_user(usr['id'], {'ym_token': token})
        await message.answer(
            'Спасибо, твой токен сохранён 🎉\n\n'
            'Если захочешь удалить токен из базы данных бота, просто напиши /reset ^_^'
        )
    await message.answer(
        '<b>Всё готово ✅</b>\n'
        f'Теперь в любом чате ты можешь написать (не отправляя) <code>@{me.username} </code>, '
        f'подождать пару секунд и там появится трек, который сейчас играет у тебя.',
        parse_mode='html'
    )


async def main():
    async with aiosqlite.connect('db.sqlite3') as db:
        cursor = await db.cursor()
        await cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            ym_id TEXT,
            ym_token TEXT 
        )''')
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())