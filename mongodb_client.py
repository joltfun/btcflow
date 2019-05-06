# MongoDB client loader

import os
import motor.motor_asyncio

def load_from_env_variables():
    MONGODB_HOST = os.getenv("MONGODB_HOST", "127.0.0.1")
    MONGODB_PORT = int(os.getenv("MONGODB_PORT", "27017"))
    MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "txdb")

    client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_HOST, MONGODB_PORT)
    db = client[MONGODB_DATABASE]

    return db
