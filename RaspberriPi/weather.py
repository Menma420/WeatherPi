import time
import json
import socket
from paho.mqtt import client as mqtt
import Adafruit_DHT

# -------------------------
# Sensor setup
# -------------------------
DHT_SENSOR = Adafruit_DHT.DHT11
DHT_PIN = 4  # GPIO4 (Pin 7)

# -------------------------
# MQTT setup
# -------------------------
BROKER_HOST = "10.147.255.200"
BROKER_PORT = 1883
DEVICE_ID = socket.gethostname()
MYKEY = "VUSAN"

client = mqtt.Client(protocol=mqtt.MQTTv5)
client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
client.loop_start()

client.publish(f"devices/{DEVICE_ID}/status", "online", qos=1, retain=True)

# -------------------------
# Functions
# -------------------------


def encrypt(num, key):
    number_str = str(num)
    key_str = str(key)
    
    encrypted = []
    for i, ch in enumerate(number_str):
        encrypted_val = ord(ch) ^ ord(key_str[i % len(key_str)])
        encrypted.append(str(encrypted_val))
    
    return "-".join(encrypted)



def read_dht():
    """Read DHT11 sensor"""
    humidity, temperature = Adafruit_DHT.read_retry(DHT_SENSOR, DHT_PIN)
    if humidity is not None and temperature is not None:
        print(f"Temp = {temperature:.1f}°C | Humidity = {humidity:.1f}%")
        return {"temperature": encrypt(temperature, MYKEY), "humidity": encrypt(humidity, MYKEY)}
    else:
        print("Failed to retrieve data from DHT sensor")
        return None
	

def send_to_mqtt(data):
    """Publish DHT data to MQTT"""
    payload = {
        "ts": int(time.time() * 1000),
        "value": data,
        "status": 200,
        "device": DEVICE_ID
    }
    topic = f"sensors/{DEVICE_ID}/dht11"
    client.publish(topic, json.dumps(payload), qos=1, retain=False)
'''
def send_to_mqtt(data):
    """Publish temperature and humidity to separate MQTT topics"""
    
    timestamp = int(time.time() * 1000)

    # Temperature topic
    temp_payload = {
        "ts": timestamp,
        "value": data["temperature"],
        "status": 200,
        "device": DEVICE_ID
    }
    temp_topic = f"sensors/{DEVICE_ID}/temperature"
    client.publish(temp_topic, json.dumps(temp_payload), qos=1, retain=False)

    # Humidity topic
    hum_payload = {
        "ts": timestamp,
        "value": data["humidity"],
        "status": 200,
        "device": DEVICE_ID
    }
    hum_topic = f"sensors/{DEVICE_ID}/humidity"
    client.publish(hum_topic, json.dumps(hum_payload), qos=1, retain=False)
'''
# -------------------------
# Main loop
# -------------------------
try:
    while True:
        dht_data = read_dht()
        if dht_data:
            send_to_mqtt(dht_data)
        time.sleep(2)

except KeyboardInterrupt:
    print("Exiting...")
finally:
    client.loop_stop()
    client.disconnect()
