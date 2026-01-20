from flask import Flask, blueprints, request

# import the model manager 
from model_manager import ModelManager
models = blueprints.Blueprint('models', __name__)

app = Flask(__name__)


@models.route("/", methods=["GET"])
def get_models():
    try:
        return ModelManager().list_hf_models()
    except ValueError as e:
        return {"status": "error", "message": str(e)}, 400
    
@models.route("/download/<model_name>", methods=["POST"])
def download_model(model_name):
    try:
        model_path = ModelManager().download_model(model_name)
        return {"status": "success", "model_path": str(model_path)}
    except ValueError as e:
        return {"status": "error", "message": str(e)}, 400
    

@models.route("/run", methods=["POST"])
def run_modal():

    request_data = request.get_json()
    model_name = request_data.get("model_name")
    prompt = request_data.get("prompt")
    
    if not model_name or not prompt:
        return {"status": "error", "message": "model_name and prompt are required."}, 400

    try:
        output = ModelManager().run_model(model_name, prompt)
        return {"status": "success", "output": output}
    except ValueError as e:
        return {"status": "error", "message": str(e)}, 400
    

app.register_blueprint(models, url_prefix="/models")
