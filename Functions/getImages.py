import base64
import html
import json

import flask
import functions_framework
import vertexai
from vertexai.preview.vision_models import ImageGenerationModel
from vertexai.generative_models import GenerativeModel, Part, FinishReason
import vertexai.preview.generative_models as generative_models

MAX_IMAGE_COUNT = 5
VERTEX_MAX_IMAGE_COUNT = 4
PROJECT_ID = "imagenio"
LOCATION = "us-central1"

vertexai.init(project=PROJECT_ID, location=LOCATION)

image_model = ImageGenerationModel.from_pretrained("imagegeneration@006")

caption_model = GenerativeModel("gemini-1.5-pro-preview-0409")

caption_generation_config = {
    "max_output_tokens": 8192,
    "temperature": 1,
    "top_p": 0.95,
}

safety_settings = {
    generative_models.HarmCategory.HARM_CATEGORY_HATE_SPEECH: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    generative_models.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    generative_models.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    generative_models.HarmCategory.HARM_CATEGORY_HARASSMENT: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
}

@functions_framework.http
def get_image(request):
    http_origin = request.environ.get('HTTP_ORIGIN', 'no origin')
    if request.method == "OPTIONS":
        # Allows GET requests from any origin with the Content-Type
        # header and caches preflight response for an 3600s
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)
    
    request_json = request.get_json(silent=True)
    request_args = request.args

    default_image_prompt = 'a picture of a cute cat jumping'
    default_description_prompt = 'decribe the image'
    default_image_count = 1
    image_prompt = (request_json or request_args).get('image_prompt', default_image_prompt)
    input_prompt = (request_json or request_args).get('desc_prompt', default_description_prompt)
    text_prompt =  f"""Do this for each image separately: "{html.escape(input_prompt)}". We will call the result of it as the information about an image. Give each image a title. Return the result as a list of objects in json format; each object will correspond one image and the fields for the object will be "title" for the title and "info" for the information."""
    image_count = int((request_json or request_args).get('image_count', default_image_count))

    if image_count > MAX_IMAGE_COUNT:
        return ("Invalid image_count. Maximum image count is 5.", 406)

    images = get_images_with_count(image_prompt, image_count)
    image_strings = []
    caption_input = []
    for img in images:
        temp_bytes = img._image_bytes
        image_strings.append(base64.b64encode(temp_bytes).decode("ascii"))
        temp_image=Part.from_data(
                mime_type="image/png",
                data=temp_bytes)
        caption_input.append(temp_image)
    captions = caption_model.generate_content(
        caption_input + [text_prompt],
        generation_config=caption_generation_config,
        safety_settings=safety_settings,
    )
    captions_list = make_captions(captions)
    
    resp_images_dict = []
    for img, cap in zip(image_strings, captions_list):
        resp_images_dict.append({"image": img, "caption": cap["description"], "title": cap["title"]})
    resp = flask.jsonify(resp_images_dict)
    resp.headers.set("Access-Control-Allow-Origin", "*")
    return resp


def get_images_with_count(image_prompt, image_count):
    current_image_count = 0
    images = []
    while current_image_count < image_count:
        remaining_image_count = image_count - current_image_count
        allowed_image_count = min(VERTEX_MAX_IMAGE_COUNT, remaining_image_count)
        temp_images = image_model.generate_images(
            prompt=image_prompt,
            # Optional parameters
            number_of_images=allowed_image_count,
            language="en",
            # You can't use a seed value and watermark at the same time.
            # add_watermark=False,
            # seed=100,
            aspect_ratio="1:1",
            safety_filter_level="block_some",
            person_generation="allow_adult",
        )
        images.extend(temp_images)
        current_image_count = len(images)
        print(f'Images generated so far: {current_image_count}')
    return images


def make_captions(captions):
    captions_text = captions.text
    # Sometimes the result is returned with a json field specifier
    if captions_text.startswith("```json"):
        captions_text = captions_text[7:-4]
    captions_list = json.loads(captions_text)
    final_captions = []
    for caption in captions_list:
        title = caption["title"]
        desc = caption["info"]
        final_captions.append({"title": title, "description": desc})
    return final_captions
