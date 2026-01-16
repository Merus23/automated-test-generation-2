from flask import Flask, blueprints

# import the model manager 
from model_manager import ModelManager
models = blueprints.Blueprint('models', __name__)

app = Flask(__name__)


@models.route("/", methods=["GET"])
def get_models():
    return ModelManager().list_hf_models()

app.register_blueprint(models, url_prefix="/models")
