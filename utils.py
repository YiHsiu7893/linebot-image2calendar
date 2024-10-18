import os
import requests
import json
import google.generativeai as genai


def create_form(form, form_service):
    form = form #{ "info": {"title": formName, "documentTitle": formName} }

    result = form_service.forms().create(body=form).execute()
    
    return result['formId']

def add_form(formId, form, form_service):
    add = form

    form_service.forms().batchUpdate(formId=formId, body=add).execute()


## 這部分先不會用到
def update_form(formId, form_service, item_id):
    update = {
        "requests": [
            {
                "updateFormInfo": {
                    "info": {
                        "description": (
                            "校運會預購表單"
                        )
                    },
                    "updateMask": "description",
                }
            },
            {
                "updateItem": {
                    "item": {
                        "questionItem": {
                            "question": {
                                "choiceQuestion": {
                                    "options": [
                                    {"value": "1"},
                                    {"value": "2"},
                                    {"value": "3"},
                                ],
                                }
                            }
                        }
                    },
                    "itemId": item_id
                }
            }
        ]
    }

    # Update the form with a description
    form_service.forms().batchUpdate(formId=formId, body=update).execute()


title_prompt = """
請把語音中提到的title提取出來。
title和documentTitle必須是一樣的內容。
輸出成 JSON 格式，絕對不能有其他多餘的格式，格式如下：
{ 
    "info": {
        "title": "餅乾團購表",
        "documentTitle": "餅乾團購表"
    }
}
"""

content_prompt = """
請把語音中的問題item提取出來。
其中，若item是簡答題，則question為textQuestion；若item為選擇題，則question為choiceQuestion並依序填入選項。
index由0依序編號。
輸出成 JSON 格式，絕對不能有其他多餘的格式，範例如下：
{
    "requests": [
        {
            "createItem": {
                "item":{
                    "title": "姓名",
                    "questionItem":{
                        "question":{
                            "required": True,
                            "textQuestion": {}
                        }
                    }
                },
                "location": {"index": 0}
            }
        },
        {
            "createItem": {
                "item": {
                    "title": "你要買多少餅乾?",
                    "questionItem": {
                        "question": {
                            "required": True,
                            "choiceQuestion":{
                                "type": "RADIO",
                                "options": [
                                    {"value": "0"},
                                    {"value": "1"}
                                ],
                                "shuffle": False
                            }
                        }
                    }
                },
                "location": {"index": 1}
            }
        }
    ]
}
"""

def make_form(audio_path, form_service, access_token):
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    if audio_path is not None:
        audio_file = genai.upload_file(path=audio_path)   
    else:
        return "None"

    model = genai.GenerativeModel("gemini-1.5-flash")

    title_response = model.generate_content([title_prompt, audio_file])
    title_json = json.loads(title_response.text)
    formId = create_form(title_json, form_service)

    content_response = model.generate_content([content_prompt, audio_file])
    content_json = json.loads(content_response.text)
    add_form(formId, content_json, form_service)


    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    url = f"https://forms.googleapis.com/v1/forms/{formId}"
    form_url = requests.get(url, headers=headers).json()["responderUri"]

    return form_url


def shorten_url_by_reurl_api(short_url):
    url = "https://api.reurl.cc/shorten"

    headers = {
        "Content-Type": "application/json",
        "reurl-api-key": os.getenv("REURL_API_KEY"),
    }

    response = requests.post(
        url,
        headers=headers,
        data=json.dumps(
            {
                "url": short_url,
            }
        ),
    )

    return response.json()["short_url"]
