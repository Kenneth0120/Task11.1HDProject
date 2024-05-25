import RPi.GPIO as GPIO
import time
import requests
import threading
import subprocess
import os
import speech_recognition as sr
from twilio.rest import Client
from pydub import AudioSegment
from pydub.playback import play
from io import BytesIO
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from datetime import datetime
from bluepy import btle


# Global variable to store the motion detection status
global_motion_detected = False
global_lock_system = False
global_deactivate_system = True

# Setup GPIO for PIR sensor
sensorPin = 18
GPIO.setmode(GPIO.BCM)
GPIO.setup(sensorPin, GPIO.IN)

# Initialize camera
picam2 = Picamera2()
video_config = picam2.create_video_configuration(main={"format": "YUV420", "size": (1920, 1080)})
picam2.configure(video_config)

# Initialize the recognizer
r = sr.Recognizer()

# Bluetooth Delegate for Handling Notifications
class MyDelegate(btle.DefaultDelegate):
    def __init__(self):
        super().__init__()

    def handleNotification(self, cHandle, data):
        try:
            systemActivated, potentialBreakIn = map(int, data.decode().split(','))
            handle_data(systemActivated, potentialBreakIn)
        except ValueError as e:
            print("Error processing the data:", e)
            
def handle_data(systemActivated, potentialBreakIn):
    global global_lock_system
    global global_deactivate_system
    
    if systemActivated == 0:
        global_lock_system = True
        global_deactivate_system = False
    if systemActivated == 1:
        global_lock_system = False
        global_deactivate_system = True
    if potentialBreakIn == 1:
        handle_motion_detected()
    print("systemActivated status: ", systemActivated)
    print("potentialBreakIn status: ", potentialBreakIn)

def maintain_bluetooth_connection():
    global global_motion_detected
    global global_lock_system
    global global_deactivate_system
    device_address = "d4:d4:da:4f:34:e6"
    service_uuid = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
    char_uuid_tx = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
    char_uuid_rx = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
    
    while True:
        try:
            p = btle.Peripheral(device_address)
            p.setDelegate(MyDelegate())
            svc = p.getServiceByUUID(service_uuid)
            ch_tx = svc.getCharacteristics(char_uuid_tx)[0]
            ch_rx = svc.getCharacteristics(char_uuid_rx)[0]
            setup_data = b"\x01\00"
            p.writeCharacteristic(ch_rx.valHandle+1, setup_data, withResponse=True)
            
            while True:
                potentialBreakIn = 0
                if p.waitForNotifications(1.0):
                    continue
                # Example command to send data to Arduino
                data_string = f"{int(global_motion_detected)},{int(global_lock_system)},{int(global_deactivate_system)}"
                dString = bytes(data_string, 'utf-8')
                ch_tx.write(dString, True)
                print(f"Sent to Arduino: {data_string}")
                global_motion_detected = False
                time.sleep(2)  # Adjust based on your needs
        except btle.BTLEException as e:
            print("Bluetooth connection error:", e)
            time.sleep(1)  # Reconnect after a delay


def convert_to_mp4(input_file, output_file):
    """Converts an H.264 video file to MP4 using ffmpeg."""
    cmd = [
        'ffmpeg',
        '-framerate', '30',
        '-i', input_file,
        '-c', 'copy',
        '-f', 'mp4',
        '-y',  # Overwrite without asking
        output_file
    ]
    subprocess.run(cmd, check=True)

def play_audio_from_url(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            audio_segment = AudioSegment.from_file(BytesIO(response.content), format="m4a")
            play(audio_segment)
        else:
            print(f"Failed to download audio: Status code {response.status_code}")
    except Exception as e:
        print(f"Error playing audio: {e}")


def record_video(duration=10):
    """Records a video for a specified duration and saves it as MP4."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    h264_path = f'/home/kenneth/Kenneth/Project/video/{timestamp}.h264'
    mp4_path = f'/home/kenneth/Kenneth/Project/video/{timestamp}.mp4'
    
    picam2.start_preview()
    time.sleep(2)  # Camera warm-up time
    picam2.start_recording(H264Encoder(10000000), h264_path)
    print(f"Recording started... File: {h264_path}")
    time.sleep(duration)
    picam2.stop_recording()
    picam2.stop_preview()
    print(f"Recording stopped, video saved as '{h264_path}'")
    
    # Convert the H.264 video to MP4
    print("Converting to MP4...")
    convert_to_mp4(h264_path, mp4_path)
    print(f"Conversion complete, MP4 saved as '{mp4_path}'")

def handle_motion_detected():
    global global_motion_detected
    audio_url = 'https://github.com/Kenneth0120/Task11.2HDProject/blob/main/voice/Warning.m4a?raw=true'
    audio_thread = threading.Thread(target=play_audio_from_url, args=(audio_url,))
    video_thread = threading.Thread(target=record_video, args=(10,))
    audio_thread.start()
    video_thread.start()
    audio_thread.join()
    video_thread.join()
    # Sending SMS and making a call
    sms()
    call()
    
    global_motion_detected = True
    print("Audio and video response to motion detected completed.")

# Function to continuously monitor the PIR sensor
def monitor_motion():
    global global_motion_detected
    global global_lock_system
    
    motion_detected_time = None
    last_state = False

    while True:
        current_motion = GPIO.input(sensorPin)
        if current_motion:
            if last_state == False:
                #print("Motion Detected!")
                last_state = True
            if motion_detected_time is None:
                motion_detected_time = time.time()
            
            # If motion is detected for more than 6 seconds
            if time.time() - motion_detected_time > 6 and global_lock_system:
                global_motion_detected = True
                handle_motion_detected()
                motion_detected_time = None  # Reset the motion detection timer
                motionValue = False
            
        else:
            if last_state == True:
                #print("No Motion!")
                last_state = False
            motion_detected_time = None  # Reset the motion detection timer
        
        time.sleep(0.1)

def system_active(command):
    global global_lock_system
    global global_deactivate_system
    
    if "lock system" in command:
        global_lock_system = True
        global_deactivate_system = False
        
    if "deactivate system" in command:
        global_deactivate_system = True
        global_lock_system = False
    
# Function to continuously listen and recognize speech
def recognize_speech():
    failed_attempts = 0
    active = False
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source)
        print("System ready. Say 'Hey Jarvis' to activate.")
        while True:
            try:
                audio = r.listen(source, timeout=1, phrase_time_limit=5)
                text = r.recognize_google(audio).lower()
                print("Recognized: " + text)

                if "hey jarvis" in text and not active:
                    active = True
                    failed_attempts = 0
                    time.sleep(1)
                    play_audio_from_url('https://github.com/Kenneth0120/Task7.2DAudioProcessing/blob/main/Voice/Hi_I_am_Jarvis.m4a?raw=true')
                    print("Hi, I am Jarvis. What can I help you?")

                elif active:
                    if any(cmd in text for cmd in ["lock system"]):
                        system_active(text)
                        failed_attempts = 0  # Reset on successful command
                        time.sleep(1)
                        play_audio_from_url('https://github.com/Kenneth0120/Task11.2HDProject/blob/main/voice/Locking_System.m4a?raw=true')
                        print("Command executed: " + text)
                        print("Ok, no problem. Locking the system")
                    elif any(cmd in text for cmd in ["deactivate system"]):
                        system_active(text)
                        failed_attempts = 0  # Reset on successful command
                        time.sleep(1)
                        play_audio_from_url('https://github.com/Kenneth0120/Task11.2HDProject/blob/main/voice/Sys_Deactivating.m4a?raw=true')
                        print("Command executed: " + text)
                        print("Ok, no problem. Deactivating the system")
                    else:
                        print("Command not recognized. Please try again.")
                        failed_attempts += 1
                        if failed_attempts >= 10:
                            active = False
                            print("Deactivating after 10 failed commands. Say 'Hey Jarvis' to reactivate.")
            except sr.UnknownValueError:
                print("Could not understand audio, try again.")
                if active:
                    failed_attempts += 1
                    if failed_attempts >= 10:
                        active = False
                        print("Deactivating after 10 failed commands. Say 'Hey Jarvis' to reactivate.")
            except sr.RequestError as e:
                print("Could not request results from Google Speech Recognition service; {0}".format(e))
            except sr.WaitTimeoutError:
                print("No speech detected, try speaking again.")

def sms():
    try:
        account_sid = 'AC8a6254b7879731364be2125214426424'
        auth_token = 'da00e123bf00b13d02855b4d57f40b6c'
        client = Client(account_sid, auth_token)

        message = client.messages.create(
          from_='+17602308857',
          body='Warning! Your home may have a potential break-in. In case of emergency, please call 000. ',
          to='+610423426651'
        )
        print(f"SMS sent: {message.sid}")
    except Exception as e:
        print(f"Failed to send SMS: {e}")

def call():
    try:
        # Set the environment variables directly for testing
        os.environ['TWILIO_ACCOUNT_SID'] = 'AC8a6254b7879731364be2125214426424'
        os.environ['TWILIO_AUTH_TOKEN'] = 'da00e123bf00b13d02855b4d57f40b6c'

        account_sid = os.environ['TWILIO_ACCOUNT_SID']
        auth_token = os.environ['TWILIO_AUTH_TOKEN']
        client = Client(account_sid, auth_token)

        call = client.calls.create(
            url='https://handler.twilio.com/twiml/EH05497edd6c164e1988aece1c424f9348',
            to='+610423426651',
            from_='+17602308857'
        )
        print(f"Call initiated: {call.sid}")
    except Exception as e:
        print(f"Failed to initiate call: {e}")

try:
    bt_thread = threading.Thread(target=maintain_bluetooth_connection)
    bt_thread.start()
    motion_thread = threading.Thread(target=monitor_motion)
    motion_thread.start()
    speech_thread = threading.Thread(target=recognize_speech)
    speech_thread.start()

    # Wait for all threads to finish
    bt_thread.join()
    motion_thread.join()
    speech_thread.join()
    
except KeyboardInterrupt:
    print("Program exited.")
finally:
    GPIO.cleanup()
    
