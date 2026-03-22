import os

from dotenv import load_dotenv
from fastapi import FastAPI
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

load_dotenv()

mongo_uri = os.environ["MONGO_URI"]
mongo_client = MongoClient(mongo_uri)
db = mongo_client.get_default_database()

app = FastAPI()


@app.get("/health")
def health():
    """Verifica o status da aplicação e da conexão com o MongoDB.

    Returns:
        Um dicionário com o status geral da aplicação, o estado
        da conexão, o nome do banco acessado, as coleções disponíveis
        e informações do servidor.
    """
    try:
        server_info = mongo_client.server_info()
        collections = db.list_collection_names()
        db_status = "connected"
    except ConnectionFailure:
        server_info = None
        collections = []
        db_status = "disconnected"

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "database": {
            "connection": db_status,
            "name": db.name,
            "collections": collections,
        },
        "server": {
            "version": server_info.get("version") if server_info else None,
        },
    }
