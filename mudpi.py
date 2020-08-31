import RPi.GPIO as GPIO
import threading
import datetime
import socket
import time
import json
import sys
import traceback
import logging
import paho.mqtt.client as m_client
sys.path.append('..')
from action import Action
from config_load import loadConfigJson
from server.mudpi_server import MudpiServer
from workers.lcd_worker import LCDWorker
from workers.relay_worker import RelayWorker
from workers.camera_worker import CameraWorker
from workers.trigger_worker import TriggerWorker
from workers.pi_sensor_worker import PiSensorWorker
from workers.pi_control_worker import PiControlWorker
from workers.mqtt_worker import MqttWorker
try:
	# Does this prevent the need to install the module if you dont use it?
	from workers.arduino_worker import ArduinoWorker
	NANPY_ENABLED = True
except ImportError:
	NANPY_ENABLED = False
try:
	# Does this prevent the need to install the module if you dont use it?
	from workers.adc_worker import ADCMCP3008Worker
	MCP_ENABLED = True
except ImportError:
	MCP_ENABLED = False

import variables

# __  __           _ _____ _ 
#|  \/  |         | |  __ (_)
#| \  / |_   _  __| | |__) | 
#| |\/| | | | |/ _` |  ___/ |
#| |  | | |_| | (_| | |   | |
#|_|  |_|\__,_|\__,_|_|   |_|
# https://mudpi.app

CONFIGS = {}
PROGRAM_RUNNING = True

print(chr(27) + "[2J")
variables.LOGGER.info('MudPi started')
print('Loading MudPi Configs...\r', end="", flush=True)

#load the configuration
try:
	CONFIGS = loadConfigJson()
except Exception e:
	variables.LOGGER.error("Config file NOT loaded: " + traceback.format_exc())
	print("Error loading config file: ")
	traceback.print_exc() 
	return

#Waiting for redis and services to be running
time.sleep(5) 
print('Loading MudPi Configs...\t\033[1;32m Complete\033[0;0m')
time.sleep(1)

#Clear the console if its open for debugging                           
print(chr(27) + "[2J")
#Print a display logo for startup
print("\033[1;32m")
print(' __  __           _ _____ _ ')
print('|  \/  |         | |  __ (_)')
print('| \  / |_   _  __| | |__) | ')
print('| |\/| | | | |/ _` |  ___/ | ')
print('| |  | | |_| | (_| | |   | | ')
print('|_|  |_|\__,_|\__,_|_|   |_| ')
print('_________________________________________________')
print('')
print('Eric Davisson @theDavisson')
print('Version: ', CONFIGS.get('version', '0.8.10'))
print('\033[0;0m')

if CONFIGS['debug'] is True:
	variables.LOGGER.debug('Debug mode enabled')
	print('\033[1;33mDEBUG MODE ENABLED\033[0;0m')
	print("Loaded Config\n--------------------")
	for index, config in CONFIGS.items():
		if config != '':
			print('%s: %s' % (index, config))
	time.sleep(10)

try:
	variables.LOGGER.info("Initializing garden control")
	print('Initializing Garden Control \r', end="", flush=True)
	GPIO.setwarnings(False)
	GPIO.setmode(GPIO.BCM)
	GPIO.cleanup()
	#Pause for GPIO to finish
	time.sleep(0.1)
	print('Initializing Garden Control...\t\t\033[1;32m Complete\033[0;0m')
	variables.LOGGER.info("Preparing threads for workers")
	print('Preparing Threads for Workers\r', end="", flush=True)

	threads = []
	actions = {}
	relays = {}
	relay_index = 0
	variables.lcd_message = {'line_1': 'Mudpi Control', 'line_2': 'Is Now Running'}

	new_messages_waiting = threading.Event() #Event to signal LCD to pull new messages
	main_thread_running = threading.Event() #Event to signal workers to close
	system_ready = threading.Event() #Event to tell workers to begin working
	camera_available = threading.Event() #Event to signal if camera can be used
	main_thread_running.set() #Main event to tell workers to run/shutdown

	pubsub = variables.r.pubsub()
	pubsub.psubscribe(CONFIGS['central_topic'] if 'central_topic' in CONFIGS else 'mudpi/control/central/')

	time.sleep(0.1)
	print('Preparing Threads for Workers...\t\033[1;32m Complete\033[0;0m')

	#l = LCDWorker(new_messages_waiting,main_thread_running,system_ready)
	#print('Loading LCD Worker')
	#l = l.run()
	#threads.append(l)

	# Worker for Camera
	try:
		c = CameraWorker(CONFIGS['camera'], main_thread_running, system_ready, camera_available)
		variables.LOGGER.info("Loading Pi Camera Worker")
		print('Loading Pi Camera Worker...')
		c = c.run()
		threads.append(c)
		camera_available.set()
	except KeyError:
		variables.LOGGER.warning('No Camera Found to Load')
		print('No Camera Found to Load')

	# Workers for pi (Sensors, Controls, Relays)
	try:
		for worker in CONFIGS['workers']:
			# Create worker for worker
			if worker['type'] == "sensor":
				pw = PiSensorWorker(worker, main_thread_running, system_ready)
				variables.LOGGER.info('Loading Pi Sensor Worker')
				print('Loading Pi Sensor Worker...')
			elif worker['type'] == "control":
				pw = PiControlWorker(worker, main_thread_running, system_ready)
				variables.LOGGER.info('Loading Pi Control Worker')
				print('Loading Pi Control Worker...')
			elif worker['type'] == "relay":
				# Add Relay Worker Here for Better Config Control
				variables.LOGGER.info('Loading Pi Relay Worker...')
				print('Loading Pi Relay Worker...')
			else:
				raise Exception("Unknown Worker Type: " + worker['type'])
			pw = pw.run()
			if pw is not None:
				threads.append(pw)
	except KeyError:
		variables.LOGGER.warning('No Pi Workers Found to Load or Invalid Type: ' + traceback.format_exc())
		print('No Pi Workers Found to Load or Invalid Type')
		traceback.print_exc()


	# Worker for relays attached to pi
	try:
		for relay in CONFIGS['relays']:
			variables.LOGGER.info("Loading Pi Relays")
			print("Loading Pi Relays...")
			#Create a threading event for each relay to check status
			relayState = {
				"available": threading.Event(), #Event to allow relay to activate
				"active": threading.Event() #Event to signal relay to open/close
			}
			#Store the relays under the key or index if no key is found, this way we can reference the right relays
			relays = {}
			group = relay.get("group", "common") 
			if group not in relays:
				relays[group] = {}
			relayEvents[group][relay.get("key", relay_index)] = relayState
			#Create sensor worker for a relay
			r = RelayWorker(relay, main_thread_running, system_ready, relayState['available'], relayState['active'])
			r = r.run()
			#Make the relays available, this event is toggled off elsewhere if we need to disable relays
			relayState['available'].set()
			relay_index +=1
			if r is not None:
				threads.append(r)
	except KeyError:
		variables.LOGGER.warning('No Relays Found to Load: ' + traceback.format_exc())
		print('No Relays Found to Load')
		traceback.print_exc()

	# Worker for nodes attached to pi via serial or wifi[esp8266]
	# Supported nodes: arduinos, esp8266, ADC-MCP3xxx, probably others
	try:
		for node in CONFIGS['nodes']:
			# Create worker for node
			if node['type'] == "arduino":
				if NANPY_ENABLED:
					t = ArduinoWorker(node, main_thread_running, system_ready)
				else:
					variables.LOGGER.error("Error Loading Nanpy library")
					print('Error Loading Nanpy library. Did you pip3 install -r requirements.txt?')
			elif node['type'] == "ADC-MCP3008":
				if MCP_ENABLED:
					t = ADCMCP3008Worker(node, main_thread_running, system_ready)
				else:
					variables.LOGGER.error('Error Loading MCP3xxx library')
					print('Error Loading MCP3xxx library. Did you pip3 install -r requirements.txt;?')
			else:
				raise Exception("Unknown Node Type: " + node['type'])
			t = t.run()
			if t is not None:
				threads.append(t)
	except KeyError as e:
		variables.LOGGER.warning('Invalid or no Nodes found to Load: ' + traceback.format_exc())
		print('Invalid or no Nodes found to Load')
		traceback.print_exc()


	# Load in Actions
	try:
		for action in CONFIGS["actions"]:
			a = Action(action)
			a.init_action()
			actions[a.key] = a
	except KeyError:
		variables.LOGGER.warning('No Actions Found to Load: ' + traceback.format_exc())
		print('No Actions Found to Load')
		traceback.print_exc()

	# Worker for Triggers
	try:
		t = TriggerWorker(CONFIGS['triggers'], main_thread_running, system_ready, actions)
		variables.LOGGER.info("Loading Triggers")
		print('Loading Triggers...')
		t = t.run()
		threads.append(t)
	except KeyError:
		variables.LOGGER.warning('No Triggers Found to Load: ' + traceback.format_exc())
		print('No Triggers Found to Load')
		traceback.print_exc()

	# Worker for MQTT
	try:
		variables.LOGGER.info("Loading MQTT worker")
		print('Loading MQTT worker...')
		m = MqttWorker(CONFIGS['mqtt'][0], main_thread_running, system_ready)
		m = m.run()
		threads.append(m)
	except KeyError:
		variables.LOGGER.warning("No MQTT worker settings found: " + traceback.format_exc())
		print('No MQTT worker settings')
		traceback.print_exc()

	#Decided not to build server worker (this is replaced with nodejs, expressjs)
	#Maybe use this for internal communication across devices if using wireless
	def server_worker():
		server.listen()
	variables.LOGGER.info("Starting web server")
	print('MudPi Server...\t\t\t\t\033[1;33m Starting\033[0;0m', end='\r', flush=True)
	time.sleep(1)
	server = MudpiServer(main_thread_running, CONFIGS['server']['host'], CONFIGS['server']['port'])
	s = threading.Thread(target=server_worker)
	threads.append(s)
	s.start()


	time.sleep(.5)
	variables.LOGGER.info("MudPi server ready")
	print('MudPi Garden Control...\t\t\t\033[1;32m Online\033[0;0m')
	print('_________________________________________________')
	system_ready.set() #Workers will not process until system is ready
	variables.r.set('started_at', str(datetime.datetime.now())) #Store current time to track uptime
	system_message = {'event':'SystemStarted', 'data':1}
	variables.r.publish('mudpi', json.dumps(system_message))
	

	#Hold the program here until its time to graceful shutdown
	#This is our pump cycle check, Using redis to determine if pump should activate
	while PROGRAM_RUNNING:
		# Main program loop
		# add logging or other system operations here...
		message = pubsub.get_message()
		if message:
			if message['data'][:4] == 'dis_':
				group = message['data'][4:]
				relay['available'].clear() for relay in relays[group] if group in relays
			elif message['data'][:4] == 'ena_':
				group = message['data'][4:]
				relay['available'].set() for relay in relays[group] if group in relays
				
		time.sleep(0.1)

except KeyboardInterrupt:
	PROGRAM_RUNNING = False
finally:
	variables.LOGGER.info("MudPi shutting down")
	print('MudPi Shutting Down...')
	#Perform any cleanup tasks here...

	#load a client on the server to clear it from waiting
	# sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	#sock.connect((CONFIGS['SERVER_HOST'], int(CONFIGS['SERVER_PORT'])))
	server.sock.shutdown(socket.SHUT_RDWR)
	# time.sleep(1)
	# sock.close()
	
	#Clear main running event to signal threads to close
	main_thread_running.clear()

	#Shutdown the camera loop
	camera_available.clear()

	#Join all our threads for shutdown
	for thread in threads:
		thread.join()

	print("MudPi Shutting Down...\t\t\t\033[1;32m Complete\033[0;0m")
	variables.LOGGER.info("MudPi was shut down successfully")
	print("Mudpi is Now...\t\t\t\t\033[1;31m Offline\033[0;0m")
	
