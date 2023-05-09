from flask import Flask, render_template, request
from flask_socketio import SocketIO
from threading import Lock
from datetime import datetime
import serial
import pymysql
import atexit
import time

"""
Background Thread
"""
thread = None
thread_lock = Lock()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'meow'
socketio = SocketIO(app, cors_allowed_origins='*')

# Assuming user has not recently triggered the actuators, if value is above this, actuators will be enabled, else they will be disabled
threshold = 30

ser = serial.Serial('/dev/cu.usbmodem101', 9600)

dbConn = pymysql.connect(host="localhost", user="pi", password="password", db="smoke_db")

# current state of the actuators. 0 = off, 1 = on
actuator_data = {
    'buzzer': 0,
    'fan': 0
}

# number of seconds user's actions will be preserved before system will automatically re-trigger actuators based on sensor values
timeout = 5

# time when the user triggered an action through the UI
prevTime = 0


def get_current_datetime():
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")

"""
Gets values and send it to our clients
"""
def background_thread():
    while True:
        sensor_value, push_button_value = get_value()

        query = "INSERT INTO smoke_log (smoke, detected_datetime) VALUES ('%s', '%s')" % (sensor_value, get_current_datetime())
        with dbConn.cursor() as cursor:
            cursor.execute(query)
        dbConn.commit()

        select_query = "SELECT * FROM `smoke_log` ORDER BY detected_datetime DESC, smoke_id DESC LIMIT 1"
        with dbConn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(select_query)
            result = cursor.fetchone()

            if time.time() - prevTime > timeout:
                if result['smoke'] > threshold or push_button_value == '1':
                    turn_buzzer_on()
                    turn_fan_on()
                else:
                    turn_buzzer_off()
                    turn_fan_off()
                socketio.emit('updateActuatorData', actuator_data)

            socketio.emit('updateSensorData', {'value': result['smoke'], "date": str(result['detected_datetime']), 'push_button': push_button_value})
            socketio.sleep(0.2)


@app.route('/')
def index():
    return render_template('index.html', threshold=threshold, actuators=actuator_data)



@socketio.on('connect')
def connect():
    global thread
    print('Client connected')

    global thread
    with thread_lock:
        if thread is None:
            thread = socketio.start_background_task(background_thread)


@socketio.on('disconnect')
def disconnect():
    print('Client disconnected',  request.sid)

@app.route('/<actuator>/<value>')
def trigger_actuator(actuator, value):
    global prevTime
    prevTime = time.time()

    if actuator == 'buzzer':
        if value == 'on':
            turn_buzzer_on()
        elif value == 'off':
            turn_buzzer_off()
    elif actuator == 'fan':
        if value == 'on':
            turn_fan_on()
        elif value == 'off':
            turn_fan_off()

    return render_template('index.html', threshold=threshold, actuators=actuator_data)

# updates threshold value
@socketio.on('thresholdChange')
def threshold_change(value):
    print(value)
    global threshold
    threshold = int(value)

def get_value():
    return ser.readline().decode('utf-8').strip().split(',')

def write_value(value):
    ser.write(value)

# frees up resources before program exits
@atexit.register
def goodbye():
    print("You are now leaving the Python file")
    dbConn.close()

def turn_buzzer_off():
    actuator_data['buzzer'] = 0
    write_value(b'1')

def turn_buzzer_on():
    actuator_data['buzzer'] = 1
    write_value(b'2')

def turn_fan_off():
    actuator_data['fan'] = 0
    write_value(b'3')

def turn_fan_on():
    actuator_data['fan'] = 1
    write_value(b'4')

if __name__ == '__main__':
    socketio.run(app)
