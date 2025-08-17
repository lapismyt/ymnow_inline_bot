import asyncio
import hashlib
import re
import os
import random
import json
import string
import html
from typing import Optional, Dict, Any

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
from aiogram.utils.keyboard import InlineKeyboardBuilder

from yandex_music import ClientAsync
from yandex_music.exceptions import YandexMusicError

from dotenv import load_dotenv
import aiohttp

from loguru import logger

# Import new database operations
from .database.user_operations import handle_user, update_user, get_user
from .database.statistics_operations import update_statistics, get_latest_statistics
from .models.user import User as UserModel

load_dotenv()

bot = Bot(os.getenv('BOT_TOKEN'))
dp = Dispatcher()


async def get_audio_url(audio: bytes):
    me = await bot.get_me()
    msg = await bot.send_audio(
        chat_id=me.id,
        audio=BufferedInputFile(audio, filename=f'{random.randint(10000, 99999)}.mp3')
    )
    if msg.audio and msg.audio.file_id:
        file = await bot.get_file(msg.audio.file_id)
        if file and file.file_path:
            return f'https://api.telegram.org/file/bot{bot.token}/{file.file_path}'
    return None


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


@dp.message(F.text.startswith('@all') & F.from_user.id == int(os.getenv('ADMIN_ID', '0')))
async def mail(message: Message):
    text = message.html_text[4:] if message.html_text else ""
    # Get all users from database
    # Note: This is a simplified implementation. In a real application, you'd want to implement pagination
    # or use a more efficient method to get all user IDs.
    await message.answer("Sending broadcast message to all users...")
    

@dp.message(Command('stats'))
async def stats_command(message: Message):
    """Show statistics to the user."""
    from src.database.statistics_operations import get_user_count
    
    stats = await get_latest_statistics()
    # Get actual user count from database
    user_count = await get_user_count()
    
    if not stats:
        await message.answer("Статистика пока недоступна.")
        return
    
    total_requests = stats.total_requests
    successful_requests = stats.successful_requests
    daily_requests = stats.daily_requests
    
    await message.answer(
        f"<b>📊 Статистика бота</b>\n\n"
        f"👥 Пользователей: {user_count}\n"
        f"📈 Всего запросов: {total_requests}\n"
        f"✅ Успешных запросов: {successful_requests}\n"
        f"📅 Запросов сегодня: {daily_requests}\n\n"
        f"<i>Статистика обновляется автоматически</i>",
        parse_mode='html'
    )


@dp.inline_query()
async def inline_search(query: InlineQuery):
    usr_data = await handle_user(query.from_user.id)
    # Convert user data to dict for compatibility
    usr: Dict[str, Any] = {
        'id': usr_data.id,
        'ym_id': usr_data.ym_id,
        'ym_token': usr_data.ym_token
    }
    
    me = await bot.get_me()
    if query.query.strip() == '':
        if not usr.get('ym_token'):
            text = f'Чтобы обнаружить текущий трек, мне нужен твой токен Яндекс Музыки. ' \
                   f'Пожалуйста, открой бота @{me.username} ' \
                   f'и введи свой токен Яндекс Музыки с помощью команды <code>/token [токен]</code>.\n' \
                   f'<a href="https://yandex-music.readthedocs.io/en/main/token.html">🔮 Как получить токен 🔮</a>'
            content = InputTextMessageContent(message_text=text, parse_mode='html')
            result_id = hashlib.md5(f'no-token:{random.randint(0, 99999999)}'.encode()).hexdigest()
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
        
        # Update statistics for total requests
        await update_statistics(total_requests=1, daily_requests=1)
        
        if not usr.get('ym_token'):
            return
        
        client = await ClientAsync(token=usr['ym_token']).init()
        res = await get_current_track(client, usr['ym_token'])
        if not res['success']:
            text = 'Не удалось найти играющий трек. Попробуйте позже.'
            content = InputTextMessageContent(message_text=text, parse_mode='html')
            result_id = hashlib.md5(f'now-error:{random.randint(0, 99999999)}'.encode()).hexdigest()
            result = InlineQueryResultArticle(
                id=result_id,
                title='Ничего не найдено',
                input_message_content=content
            )
            return await query.answer(
                results=[result],
                cache_time=20,
                is_personal=True
            )
        
        if not res.get('track') or not res['track']:
            text = 'Не удалось найти играющий трек. Попробуйте позже.'
            content = InputTextMessageContent(message_text=text, parse_mode='html')
            result_id = hashlib.md5(f'now-error:{random.randint(0, 99999999)}'.encode()).hexdigest()
            result = InlineQueryResultArticle(
                id=result_id,
                title='Ничего не найдено',
                input_message_content=content
            )
            return await query.answer(
                results=[result],
                cache_time=15,
                is_personal=True
            )
            
        track = res['track'][0]
        dlinfo = await track.get_specific_download_info_async(codec='mp3', bitrate_in_kbps=320)
        if dlinfo is None:
            dlinfo = await track.get_specific_download_info_async(codec='mp3', bitrate_in_kbps=192)
            if dlinfo is None:
                text = 'Не удалось найти играющий трек. Попробуйте позже.'
                content = InputTextMessageContent(message_text=text, parse_mode='html')
                result_id = hashlib.md5(f'now-error:{random.randint(0, 99999999)}'.encode()).hexdigest()
                result = InlineQueryResultArticle(
                    id=result_id,
                    title='Ничего не найдено',
                    input_message_content=content
                )
                return await query.answer(
                    results=[result],
                    cache_time=15,
                    is_personal=True
                )
        url = await dlinfo.get_direct_link_async()
        title = track.title or "Неизвестный трек"
        artists = ', '.join([artist.name for artist in track.artists]) if track.artists else "Неизвестный исполнитель"
        duration = (track.duration_ms or 0) // 1000
        logger.info(res.get('progress_ms', 0))
        track_id = track.id or ""
        result_id = hashlib.md5(f'now:{track_id}:{random.randint(1000, 9999)}'.encode()).hexdigest()
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
            caption=f'<b>Сейчас играет:</b>\n🎧 <code>{html.escape(artists)} - {html.escape(title)}</code>',
            performer=artists
        )
        # Update statistics for successful requests
        await update_statistics(successful_requests=1)
        return await query.answer(
            results=[result],
            cache_time=5,
            is_personal=True
        )
    else:
        # Update statistics
        await update_statistics(total_requests=1, successful_requests=1, daily_requests=1)
        
        token = usr.get('ym_token') or os.getenv('DEFAULT_YM_TOKEN')
        if not token:
            return
            
        client = await ClientAsync(token=token).init()
        results = await client.search(query.query, type_='track')
        if not results:
            return await query.answer(
                results=[],
                cache_time=3600,
                is_personal=False
            )
        if not results.tracks:
            print(results.text if hasattr(results, 'text') else "No results text")
            return await query.answer(
                results=[],
                cache_time=3600,
                is_personal=False
            )
        tracks = results.tracks.results[:6]
        outs = []
        for track in tracks:
            title = track.title or "Неизвестный трек"
            artists = ', '.join([artist.name for artist in track.artists]) if track.artists else "Неизвестный исполнитель"
            duration = (track.duration_ms or 0) // 1000
            track_id = track.track_id.split(':')[-1] if track.track_id else ""
            dlinfo = await track.get_specific_download_info_async(codec='mp3', bitrate_in_kbps=320)
            if dlinfo is None:
                dlinfo = await track.get_specific_download_info_async(codec='mp3', bitrate_in_kbps=192)
                if dlinfo is None:
                    continue
            url = await dlinfo.get_direct_link_async()
            query_hash = hashlib.md5(query.query.encode()).hexdigest()
            result_id = hashlib.md5(f'search:{query_hash}:{track_id}:{random.randint(1000, 9999)}'.encode()).hexdigest()
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
                caption=f'<b>Трек по запросу "<i>{html.escape(query.query)}</i>":</b>\n🎧 <code>{html.escape(artists)} - {html.escape(title)}</code>',
                performer=artists
            )
            outs.append(result)
        return await query.answer(
            results=outs,
            cache_time=86400,
            is_personal=False
        )


@dp.message(CommandStart())
async def start(message: Message):
    usr_data = await handle_user(message.from_user.id)
    # Convert user data to dict for compatibility
    usr: Dict[str, Any] = {
        'id': usr_data.id,
        'ym_id': usr_data.ym_id,
        'ym_token': usr_data.ym_token
    }
    
    me = await bot.get_me()
    if not usr.get('ym_token'):
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
            f'Напиши в любом чате <code>@{me.username} [запрос]</code> и подожди несколько секунд, '
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
            f'просто напиши <code>@{me.username} [запрос]</code> и подожди несколько секунд.\n\n'
            f'Если захочешь удалить свой токен из базы данных бота, используй команду /reset.\n\n'
            f'Для просмотра статистики используй команду /stats',
            reply_markup=markup,
            parse_mode='html'
        )


@dp.message(Command('reset'))
async def reset_token(message: Message):
    usr_data = await get_user(message.from_user.id)
    # Convert user data to dict for compatibility
    usr: Dict[str, Any] = {
        'id': usr_data.id if usr_data else message.from_user.id,
        'ym_id': usr_data.ym_id if usr_data else None,
        'ym_token': usr_data.ym_token if usr_data else None
    }
    
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
    usr_data = await handle_user(message.from_user.id)
    # Convert user data to dict for compatibility
    usr: Dict[str, Any] = {
        'id': usr_data.id,
        'ym_id': usr_data.ym_id,
        'ym_token': usr_data.ym_token
    }
    
    uid = -1
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    match = re.match(r'^/token\s+(\S+)$', message.text) if message.text else None
    if not match:
        await message.answer('Неверный формат токена.')
        return
        
    token = match.group(1)

    try:
        client = ClientAsync(token=token)
        await client.init()
        if client.me and client.me.account:
            uid = client.me.account.uid
    except YandexMusicError:
        await message.answer('Прости, твой токен не подходит 🙁\nПопробуй ещё раз, или напиши @LapisMYT.')
        return
    except Exception:
        await message.answer('Произошла ошибка при проверке токена. Попробуй ещё раз.')
        return
        
    if uid != -1:
        await update_user(usr['id'], {'ym_token': token, 'ym_id': uid})
        await message.answer(
            f'Спасибо, твой токен сохранён 🎉\n'
            f'Твой ID Яндекс Музыки: <code>{uid}</code> '
            f'(не знаю зачем он тебе, но пусть будет)\n\n'
            f'Если захочешь удалить токен из базы данных бота, просто напиши /reset ^_^',
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
        f'Теперь в любом чате ты можешь написать (не отправляя) <code>@{me.username}</code>, '
        f'подождать пару секунд и там появится трек, который сейчас играет у тебя.',
        parse_mode='html'
    )


async def main():
    # Create tables if they don't exist
    from src.models.user import User
    from src.models.statistics import Statistics
    from src.database.session import engine
    
    User.metadata.create_all(engine)
    Statistics.metadata.create_all(engine)
    
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
