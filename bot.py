import io
import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile, BotCommand
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from PIL import Image, ImageOps, ImageDraw

TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()


class ModeState(StatesGroup):
    waiting_for_photo = State()


def invert_image(image_bytes: bytes) -> bytes:
    """Инвертирует цвета изображения."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")
        inverted_img = ImageOps.invert(img)
        output_buffer = io.BytesIO()
        inverted_img.save(output_buffer, format="JPEG")
        return output_buffer.getvalue()


def add_grid(image_bytes: bytes, rows: int = 30, cols: int = 30, line_width: int = 3) -> bytes:
    """Накладывает черную сетку 30x30 с утолщенными линиями (line_width=3)."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")
        
        draw = ImageDraw.Draw(img)
        width, height = img.size
        step_x = width / cols
        step_y = height / rows
        
        # Вертикальные линии
        for i in range(1, cols):
            x = int(i * step_x)
            draw.line([(x, 0), (x, height)], fill="black", width=line_width)
            
        # Горизонтальные линии
        for j in range(1, rows):
            y = int(j * step_y)
            draw.line([(0, y), (width, y)], fill="black", width=line_width)
            
        output_buffer = io.BytesIO()
        img.save(output_buffer, format="JPEG")
        return output_buffer.getvalue()


async def set_main_menu(bot: Bot):
    """Установка синей кнопки 'Меню' слева от поля ввода."""
    main_menu_commands = [
        BotCommand(command="inversion", description="Инвертировать цвета картинки"),
        BotCommand(command="setka", description="Наложить сетку 30x30"),
    ]
    await bot.set_my_commands(main_menu_commands)


@dp.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Выберите команду в меню или пришлите фото с подписью:\n"
        "• `/Inversion` — инверсия цветов\n"
        "• `/setka` — черная сетка 30x30",
        parse_mode="Markdown"
    )


@dp.message(Command("Inversion", "inversion"))
async def cmd_inversion(message: Message, state: FSMContext):
    await state.update_data(mode="inversion")
    await state.set_state(ModeState.waiting_for_photo)
    await message.answer("Отправьте картинку для инверсии цветов.")


@dp.message(Command("setka"))
async def cmd_setka(message: Message, state: FSMContext):
    await state.update_data(mode="setka")
    await state.set_state(ModeState.waiting_for_photo)
    await message.answer("Отправьте картинку для наложения сетки 30x30.")


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
        await message.answer(
            "Пожалуйста, сначала выберите команду `/Inversion` или `/setka` в меню, либо добавьте её в подпись к фото.",
            parse_mode="Markdown"
        )
        return

    photo_file = await bot.get_file(message.photo[-1].file_id)
    photo_bytes = await bot.download_file(photo_file.file_path)
    raw_data = photo_bytes.read()

    if mode == "inversion":
        result_bytes = invert_image(raw_data)
        file_name = "inverted.jpg"
    else:
        # line_width=3 делает линии хорошо видимыми и толстыми
        result_bytes = add_grid(raw_data, rows=30, cols=30, line_width=3)
        file_name = "grid_30x30.jpg"

    input_file = BufferedInputFile(result_bytes, filename=file_name)
    await message.answer_photo(photo=input_file)
    await state.clear()


# Мини веб-сервер для Keep-Alive на Render
async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
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
