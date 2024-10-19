import logging
import os
import sys
from pydub import AudioSegment
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import requests
from urllib.parse import urlencode
from fastapi import FastAPI, HTTPException, Request
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ReplyMessageRequest,
    TextMessage,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
)
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, AudioMessageContent
import google.generativeai as genai
import uvicorn
from utils import *


# 初始化日誌
logging.basicConfig(level=os.getenv("LOG", "WARNING"))
logger = logging.getLogger(__file__)


# 讀取 LINE 和 OAuth2 參數
channel_secret = os.getenv("LINE_CHANNEL_SECRET")
channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
client_id = os.getenv("CLIENT_ID")
client_secret = os.getenv("CLIENT_SECRET")
redirect_uri = os.getenv("REDIRECT_URI")
gemini_key = os.getenv("GEMINI_API_KEY")

if not all([channel_secret, channel_access_token, client_id, client_secret, redirect_uri, gemini_key]):
    logger.error("環境變數缺失。請檢查配置。")
    sys.exit(1)


# 初始化 FastAPI 和 LINE Bot
app = FastAPI()
configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)


# 設定 OAuth 2.0 參數
scope = 'https://www.googleapis.com/auth/forms.body https://www.googleapis.com/auth/drive'
auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode({'client_id': client_id, 'redirect_uri': redirect_uri, 'scope': scope, 'response_type': 'code'})}"


# 初始化 Gemini Pro API
genai.configure(api_key=gemini_key)


# 儲存授權碼與權杖
authorization_code = None
access_token = None

def exchange_code_for_token(code: str):
    """交換授權碼換取存取權杖"""
    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    }
    response = requests.post(token_url, data=payload)

    return response.json()


@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    authorization_code = request.query_params.get("code")
    #return {"message": f"授權成功，授權碼: {authorization_code}"}
    token_response = exchange_code_for_token(authorization_code)
    access_token = token_response.get('access_token')

    creds = Credentials(
    token=access_token,
    token_uri='https://oauth2.googleapis.com/token',
    client_id=client_id,
    client_secret=client_secret
    )

    # 使用憑證初始化 form_service 物件
    global form_service
    form_service = build(
        "forms", "v1",
        credentials=creds,
        static_discovery=False
    )


# 啟動 FastAPI 應用程式
@app.post("/webhooks/line")
async def handle_callback(request: Request):
    signature = request.headers["X-Line-Signature"]

    # get request body as text
    body = await request.body()
    body = body.decode()

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

# LINE Bot 事件處理
@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio_message(event):
    #檢查是否已授權
    if not access_token:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    replyToken=event.reply_token, messages=[TextMessage(text=f"請點擊以下連結進行授權：{auth_url}")]
                )
            )
        authorization_code = requests.get('http://localhost:8080/get_token')
        access_token = exchange_code_for_token(authorization_code.text)['access_token']

        creds = Credentials(
            token=access_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=client_id,
            client_secret=client_secret
            )

        # 使用憑證初始化 form_service 物件
        form_service = build(
            "forms", "v1",
            credentials=creds,
            static_discovery=False
        )
            
    # 下載語音訊息檔案
    audio_message_id = event.message.id

    with ApiClient(configuration) as api_client:
        line_bot_blob_api = MessagingApiBlob(api_client)
        audio_content = line_bot_blob_api.get_message_content(audio_message_id)
    
    m4a_path = f"/tmp/{audio_message_id}.m4a"   
    with open(m4a_path, "wb") as f:
        f.write(audio_content)
        
    # 將 M4A 轉成 MP3
    mp3_path = f"/tmp/{audio_message_id}.mp3"
    audio = AudioSegment.from_file(m4a_path, format="m4a")
    audio.export(mp3_path, format="mp3")

    # 發送語音檔案給 Gemini API，回傳表單連結
    form_url = make_form(mp3_path, form_service, access_token)
    reply_msg = shorten_url_by_reurl_api(form_url)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=event.reply_token, messages=[TextMessage(text=reply_msg)]
            )
        )
    return "OK"



if __name__ == "__main__":
    port = int(os.environ.get("PORT", default=8080))
    debug = True if os.environ.get("API_ENV", default="develop") == "develop" else False
    logging.info("Application will start...")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=debug)
