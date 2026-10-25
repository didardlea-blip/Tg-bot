import io
import os
import asyncio
import tempfile
import subprocess
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile, BotCommand, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from PIL import Image, ImageOps
import cv2
import numpy as np

TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Точное имя вашего файла с сеткой на GitHub
GRID_FILENAME = "IMG_7fd3603b-e3fa-4458-adc1-11039bf5ccb9.png"


class ModeState(StatesGroup):
    waiting_for_media = State()


def invert_image(image_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")
        inverted_img = ImageOps.invert(img)
        output_buffer = io.BytesIO()
        inverted_img.save(output_buffer, format="JPEG")
        return output_buffer.getvalue()


def add_grid_image_to_photo(image_bytes: bytes) -> bytes:
    """Накладывает сетку на фото, убирая белый фон."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        img = img.convert("RGBA")
        width, height = img.size
        
        if os.path.exists(GRID_FILENAME):
            with Image.open(GRID_FILENAME) as grid_img:
                grid_img = grid_img.convert("RGBA").resize((width, height))
                
                # Убираем белый фон
                datas = grid_img.getdata()
                new_data = []
                for item in datas:
                    if item[0] > 200 and item[1] > 200 and item[2] > 200:
                        new_data.append((255, 255, 255, 0))
                    else:
                        new_data.append(item)
                grid_img.putdata(new_data)
                
                img.alpha_composite(grid_img)
        
        rgb_img = img.convert("RGB")
        output_buffer = io.BytesIO()
        rgb_img.save(output_buffer, format="JPEG")
        return output_buffer.getvalue()


def add_grid_to_video(input_video_path: str, final_output_path: str):
    """Накладывает сетку на видео без белого фона и объединяет с оригинальным звуком через ffmpeg."""
    temp_silent_path = input_video_path + "_silent.mp4"
    
    cap = cv2.VideoCapture(input_video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0 or fps != fps:
        fps = 25.0
        
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(temp_silent_path, fourcc, fps, (width, height))
    
    grid_rgba = None
    if os.path.exists(GRID_FILENAME):
        with Image.open(GRID_FILENAME) as g_img:
            grid_rgba = g_img.convert("RGBA").resize((width, height))

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        if grid_rgba is not None:
            cv2_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_frame = Image.fromarray(cv2_rgb).convert("RGBA")
            
            grid_copy = grid_rgba.copy()
            datas = grid_copy.getdata()
            new_data = []
            for item in datas:
                if item[0] > 200 and item[1] > 200 and item[2] > 200:
                    new_data.append((255, 255, 255, 0))
                else:
                    new_data.append(item)
            grid_copy.putdata(new_data)
            
            pil_frame.alpha_composite(grid_copy)
            processed_rgb = pil_frame.convert("RGB")
            frame = cv2.cvtColor(np.array(processed_rgb), cv2.COLOR_RGB2BGR)
            
        out.write(frame)
        
    cap.release()
    out.release()

    # Объединяем обработанное видео без звука с аудиодорожкой из оригинального файла с помощью FFmpeg
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_silent_path,
            "-i", input_video_path,
            "-c:v", "libx264",
            "-c:a", "aac",
            "-map", "0:v:0",
            "-map", "1:a:0?",
            "-shortest",
            final_output_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        # Если вдруг ffmpeg выдаст ошибку, просто отдадим файл как есть
        if os.path.exists(temp_silent_path):
            os.replace(temp_silent_path, final_output_path)

    if os.path.exists(temp_silent_path):
        os.remove(temp_silent_path)


async def set_main_menu(bot: Bot):
    main_menu_commands = [
        BotCommand(command="inversion", description="Инвертировать цвета картинки"),
        BotCommand(command="setka", description="Наложить вашу сетку на фото/видео"),
    ]
    await bot.set_my_commands(main_menu_commands)


@dp.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Выберите команду в меню или пришлите фото/видео с подписью:\n"
        "• `/Inversion` — инверсия цветов (только фото)\n"
        "• `/setka` — наложение вашей сетки (фото или видео)",
        parse_mode="Markdown"
    )


@dp.message(Command("Inversion", "inversion"))
async def cmd_inversion(message: Message, state: FSMContext):
    await state.update_data(mode="inversion")
    await state.set_state(ModeState.waiting_for_media)
    await message.answer("Отправьте картинку для инверсии цветов.")


@dp.message(Command("setka"))
async def cmd_setka(message: Message, state: FSMContext):
    await state.update_data(mode="setka")
    await state.set_state(ModeState.waiting_for_media)
    await message.answer("Отправьте фото или видео для наложения вашей сетки.")


@dp.message(F.photo)
async def process_photo(message: Message, state: FSMContext):
    caption = (message.caption or "").strip().lower()
    user_data = await state.get_data()
    selected_mode = user_data.get("mode")

    mode = None
    if caption in ["/inversion", "inversion"]:
        mode = "inversion"
    elif caption in ["/setka", "setka"]:
        mode = "setka"
    elif selected_mode:
        mode = selected_mode

    if not mode:
        await message.answer("Пожалуйста, выберите команду `/Inversion` или `/setka` в меню.", parse_mode="Markdown")
        return

    photo_file = await bot.get_file(message.photo[-1].file_id)
    photo_bytes = await bot.download_file(photo_file.file_path)
    raw_data = photo_bytes.read()

    if mode == "inversion":
        result_bytes = invert_image(raw_data)
        input_file = BufferedInputFile(result_bytes, filename="inverted.jpg")
        await message.answer_photo(photo=input_file)
    else:
        result_bytes = add_grid_image_to_photo(raw_data)
        input_file = BufferedInputFile(result_bytes, filename="grid_photo.jpg")
        await message.answer_photo(photo=input_file)

    await state.clear()


@dp.message(F.video)
async def process_video(message: Message, state: FSMContext):
    caption = (message.caption or "").strip().lower()
    user_data = await state.get_data()
    selected_mode = user_data.get("mode")

    mode = None
    if caption in ["/setka", "setka"] or selected_mode == "setka":
        mode = "setka"

    if not mode:
        await message.answer("Для видео поддерживается только команда `/setka`.", parse_mode="Markdown")
        return

    await message.answer("⏳ Обрабатываю видео со звуком, подождите...")

    video_file = await bot.get_file(message.video.file_id)
    
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as input_tmp:
        input_path = input_tmp.name
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as output_tmp:
        output_path = output_tmp.name

    try:
        await bot.download_file(video_file.file_path, destination=input_path)
        await asyncio.to_thread(add_grid_to_video, input_path, output_path)

        video_input = FSInputFile(output_path, filename="grid_video.mp4")
        await message.answer_video(video=video_input)
    except Exception as e:
        await message.answer(f"Ошибка при обработке видео: {e}")
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)
            
    await state.clear()


async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


async def main():
    await set_main_menu(bot)
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
