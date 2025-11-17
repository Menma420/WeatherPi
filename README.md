# 🌦️ WeatherPi
**An IoT-powered Weather Monitoring System using Raspberry Pi, MQTT, and Flask.**

WeatherPi is a distributed weather station platform where:
- A **Raspberry Pi node** reads sensor data (temperature, humidity, etc.), pre-processes it, and publishes via **MQTT**.
- A **WebHost server** subscribes to those topics, processes data in real time, stores user credentials remotely, and displays live graphs and sensor updates in a Flask-based web dashboard.

---

## 🏗️ Project Structure

```

WeatherPi/
├── RaspberriPi/
│   ├── weather.py          # Publishes sensor data to MQTT broker
│   └──requirements.txt    # paho-mqtt, gpiozero, etc.
└── WebHost/
    ├── app.py              # Flask web dashboard and MQTT subscriber
    └── requirements.txt  

````

---

## ⚙️ Components Overview

| Component | Role | Runs on |
|------------|-------|----------|
| **Raspberry Pi Node** | Reads sensor data (e.g., DHT11) and publishes JSON over MQTT | Raspberry Pi |
| **MQTT Broker** | Message hub for data exchange between Pi and server with multiple topic | WebHost / separate server |
| **Flask WebHost** | Subscribes to sensor data, provides live dashboard, user login/signup | Host / Laptop |
| **Remote SQL API** | Simple remote DB endpoint for user auth | Render / Cloud |

---



## 🧠 Tech Stack

| Category | Technology                            |
| -------- | ------------------------------------- |
| Hardware | Raspberry Pi + DHT11 Sensor |
| Protocol | MQTT (via `paho-mqtt`)                |
| Backend  | Flask (Python 3)                      |
| Frontend | Chart.js + SSE (Server-Sent Events)   |
| Database | Remote SQLite API (REST)              |
| Broker   | Mosquitto                             |
| Language | Python 3.9+                           |

---






## 📊 Dashboard Features

✅ Real-time Temperature / Humidity / Pressure charts
✅ Live raw JSON stream viewer
✅ User Sign up / Login / Logout
✅ Auto-creation of user table in SQL API
✅ Sensor value decyprtion
✅ Time sanity check for sensor timestamps
✅ Secure session management

---

## 💡 Future Enhancements

* 🌍 Multi-device dashboard view
* 📦 SQLite/InfluxDB data persistence
* 📈 Daily reports & CSV export
* 🔔 Threshold alerts (Telegram / Email)
* 🌐 Interactive map for multi-station setup
* 🔒 Token-based API access

---
##Screenshots
<img width="616" height="615" alt="image" src="https://github.com/user-attachments/assets/7ff232c3-b803-4af0-ab78-88af1e4d227c" />

<img width="1238" height="512" alt="image" src="https://github.com/user-attachments/assets/c889a7d6-86dc-482f-ad88-462610ce9efd" />

## 🧑‍💻 Authors

* **Nishant Narjinary with Uttkarsh Malviya & Sahul Kumar** – Project Developer
* **WeatherPi Team** – IoT & Web System Integration

---

## 📜 License

This project is released under the **MIT License** — free for personal and educational use.

---


> “Measure. Connect. Predict.” — *WeatherPi 2025*

