import asyncio
import os
import logging
import pdfplumber
import pandas as pd
import tempfile
import matplotlib.pyplot as plt
from aiogram import Bot, Dispatcher, html, types, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram import F
from aiogram.types import Message, FSInputFile
from fastapi import FastAPI
import uvicorn

# Get bot token from environment variables
TOKEN = os.getenv("TOKEN")

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()

# Temporary storage directory
TEMP_DIR = tempfile.gettempdir()

@router.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await message.answer(f"Hello, {html.bold(message.from_user.full_name)}! Send me a PDF file, and I'll generate a report with a chart for you!")

@router.message(F.document)
async def handle_document(message: Message):
    document = message.document
    if not document.file_name.endswith('.pdf'):
        await message.answer("Please send a valid PDF file.")
        return

    file_path = os.path.join(TEMP_DIR, document.file_name)
    file_info = await bot.get_file(document.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    
    with open(file_path, "wb") as f:
        f.write(downloaded_file.read())
    
    try:
        report_text, chart_path = process_pdf(file_path)

        await message.answer(f"Here is your generated report:\n\n{report_text}")

        chart_file = FSInputFile(chart_path)
        await message.answer_photo(chart_file, caption="Here is the attendance chart.")

    except Exception as e:
        await message.answer(f"Error processing PDF: {str(e)}")
    finally:
        os.remove(file_path)
        if os.path.exists(chart_path):
            os.remove(chart_path)

def process_pdf(pdf_path):
    tables = []
    headers = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            extracted_tables = page.extract_tables()
            for table in extracted_tables:
                df = pd.DataFrame(table)
                df.columns = df.iloc[0]
                df = df[1:].reset_index(drop=True)

                if headers is None:
                    headers = df.columns
                else:
                    df = df[df.columns[df.columns != headers[0]]]

                tables.append(df)

    if not tables:
        raise ValueError("No tables found in the PDF.")

    result_df = pd.concat(tables, ignore_index=True)
    result_df.columns = headers
    result_df = result_df.iloc[:, [1, -1]]
    result_df.iloc[:, -1] = result_df.iloc[:, -1].replace({'P': 1, 'A': 0})
    grouped_df = result_df.groupby(result_df.columns[0]).agg({
        result_df.columns[1]: ['sum', 'count']
    })
    grouped_df.columns = ['Sum Present', 'Count Lecture']
    grouped_df['Percentage'] = (grouped_df['Sum Present'] / grouped_df['Count Lecture']) * 100

    report_text = "\n".join(
        [
            f"Course: {index}\n"
            f"✅ Present: {row['Sum Present']}\n"
            f"❌ Absent: {row['Count Lecture'] - row['Sum Present']}\n"
            f"📊 Total: {row['Count Lecture']}\n"
            f"📈 Percentage: {row['Percentage']:.2f}%\n"
            for index, row in grouped_df.iterrows()
        ]
    )

    chart_path = os.path.join(TEMP_DIR, "attendance_chart.png")
    generate_chart(grouped_df, chart_path)

    return report_text, chart_path

def generate_chart(grouped_df, chart_path):
    plt.figure(figsize=(10, 6))  # Increased figure size for better spacing
    courses = grouped_df.index
    percentages = grouped_df['Percentage']

    bars = plt.bar(courses, percentages, color='blue', alpha=0.7, width=0.5)  # Adjusted bar width

    # Adding labels on top of bars
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2, height + 2, f'{height:.2f}%', ha='center', va='bottom', fontsize=10, fontweight='bold')

    plt.xlabel("Course", fontsize=12, fontweight='bold', labelpad=10)
    plt.ylabel("Attendance Percentage", fontsize=12, fontweight='bold', labelpad=10)
    plt.title("Attendance Report", fontsize=14, fontweight='bold', pad=15)
    
    plt.xticks(rotation=30, ha="right", fontsize=10)  # Rotate x-axis labels for better readability
    plt.yticks(fontsize=10)
    
    plt.ylim(0, 110)  # Set a little higher than 100% for better spacing
    plt.grid(axis="y", linestyle="--", alpha=0.5)  # Add a light grid for better readability

    # Add padding to the plot
    plt.subplots_adjust(left=0.1, right=0.95, top=0.9, bottom=0.25)

    plt.tight_layout()
    plt.savefig(chart_path)
    plt.close()

# FastAPI Web Server to keep Render service active
app = FastAPI()

@app.get("/")
def home():
    return {"status": "Bot is running"}

def start_webserver():
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

if __name__ == "__main__":
    import threading
    threading.Thread(target=start_webserver).start()  # Start the web server
    asyncio.run(main())  # Start the bot
