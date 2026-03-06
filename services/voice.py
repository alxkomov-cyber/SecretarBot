import os
from groq import Groq
import config

client = Groq(api_key=config.GROQ_API_KEY)

async def transcribe_voice(update, context):
    """Скачивает и расшифровывает голосовое сообщение"""
    try:
        file_id = update.message.voice.file_id
        new_file = await context.bot.get_file(file_id)
        ogg_file_path = f"voice_{file_id}.ogg"
        await new_file.download_to_drive(ogg_file_path)

        with open(ogg_file_path, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(ogg_file_path, file.read()),
                model="whisper-large-v3",
                response_format="json",
                language="ru"
            )
        
        # Удаляем файл после обработки
        if os.path.exists(ogg_file_path):
            os.remove(ogg_file_path)
            
        return transcription.text
    except Exception as e:
        print(f"Voice Error: {e}")
        return None