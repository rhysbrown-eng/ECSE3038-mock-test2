from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Response, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import os
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError

import paho.mqtt.publish as publish

import secrets

load_dotenv()
client = MongoClient(os.getenv("MONGODB_URI"), tz_aware=True)
mqtt_name = os.getenv("MQTT_NAME")
db = client["mock-test-2"]

devices = db["devices"]
readings = db["readings"]
alarms = db["alarms"]

devices.create_index([("mac", ASCENDING)], unique=True)

MQTT_BROKER = "135.232.203.144"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
) # allows ui from laptop to access server. see tutorial 7 for details.

class Device(BaseModel):
    mac: str
    room: str

class Reading(BaseModel):
    mac: str
    temp: float = Field(ge=-40, le=80)

class Alarm(BaseModel):
    max_temp: float

@app.post("/devices", status_code=201)
def create_device(device: Device):
    new_device = device.model_dump()
    x_api_key = secrets.token_urlsafe(16)
    new_device["X-API-Key"] = x_api_key

    try:
        devices.insert_one(new_device)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail=f"Device with MAC {device.mac} already exists big bro.")

    new_device.pop("_id")

    return new_device

@app.post("/readings", status_code=201)
def create_reading(reading: Reading, x_api_key: str | None = Header(default=None)):
    new_reading = reading.model_dump()

    if not x_api_key:
        raise HTTPException(status_code=401, detail=f"You don't have any credentials big bro. give credentials")

    device = devices.find_one({"mac": reading.mac}) 

    if(device is None):
        raise HTTPException(status_code=404, detail=f"Device with MAC {device.mac} does not exist big bro.")

    if(device["X-API-Key"] != x_api_key):
        raise HTTPException(status_code=403, detail=f"That's not your credentials big bro.")

    new_reading["time"] = datetime.now(timezone.utc)
    readings.insert_one(new_reading)
    new_reading.pop("_id")
    return new_reading

@app.get("/readings")
def get_reading( mac: str | None = None,  since: str | None = None):
    query = {}

    if mac:
        query["mac"] = mac

    if since:
        try:
            since_datetime = datetime.fromisoformat(since)
            query["time"] = {"$gte": since_datetime}
        except ValueError:
            raise HTTPException(status_code = 400, detail="Invalid format for time used big bro. Please use ISO format.")

    found_readings = readings.find(query).sort("time", -1)
    results = []
    for reading in found_readings:
        reading.pop("_id", None)
        results.append(reading)
        
    return results

@app.put("/alarm/{mac}")
def put_alarm(mac: str, alarm: Alarm, response: Response):
    new_alarm =  alarm.model_dump()
    new_alarm["mac"] = mac

    inserted_alarm = alarms.replace_one({"mac": mac}, new_alarm, upsert=True)
    if inserted_alarm.upserted_id is not None:
        response.status_code = 201
    new_alarm.pop("_id", None)

    try:
        publish.single("ecse3038/" + mqtt_name + "/alarm/max", str(new_alarm["max_temp"]),
                       retain=True, hostname=MQTT_BROKER)
    except Exception as error:
        print("Could not publish the limit:", error)

    return new_alarm

@app.get("/devices")
def get_devices():
    cursor = devices.find({}, {"_id": 0, "X-API-Key": 0})
    return list(cursor)


    

