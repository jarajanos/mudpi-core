import time
import datetime
import json
import redis
import threading
import sys
import RPi.GPIO as GPIO
from enum import Enum
sys.path.append('..')

import variables

#r = redis.Redis(host='127.0.0.1', port=6379)
GPIO.setmode(GPIO.BCM)

class MotorState(Enum):
  STOPPED = 0
  OPEN = 1
  CLOSING = 2
  CLOSED = 3
  OPENING = 4

MOTOR_STATE_STRING = ['STOPPED', 'OPEN', 'CLOSING', 'CLOSED', 'OPENING']


class MotorWorker():
	def __init__(self, config, main_thread_running, system_ready, motor_available, motor_active):
		#self.config = {**config, **self.config}
		self.config = config
		self.config['pwm_pin'] = int(self.config['pwm_pin']) #parse possbile strings to avoid errors
    self.config['pwm_power'] = min(max(int(self.config['pwm_power']), 0), 100) if self.config['pwm_power'] is not None else 100
    self.config['cw_pin'] = int(self.config['cw_pin']) #parse possbile strings to avoid errors
    self.config['ccw_pin'] = int(self.config['ccw_pin']) #parse possbile strings to avoid errors
    self.config['max_move_time'] = int(self.config['max_move_time']) if self.config['max_move_time'] is not None else 0 #parse possbile strings to avoid errors

		#Events
		self.main_thread_running = main_thread_running
		self.system_ready = system_ready
		self.motor_available = motor_available
		self.motor_active = motor_active

		#Dynamic Properties based on config
		self.state = MotorState.CLOSED
		self.control_topic = self.config['control_topic'].replace(" ", "/").lower() if self.config['control_topic'] is not None else 'mudpi/relay/'
    self.state_topic = self.config['state_topic'].replace(" ", "/").lower() if self.config['state_topic'] is not None else self.control_topic + 'state/'
    self.pwm = None

		#Pubsub Listeners
		self.pubsub = variables.r.pubsub()
		self.pubsub.subscribe(**{self.control_topic: self.handleMessage})

		self.init()
		return

	def init(self):
		GPIO.setup(self.config['cw_pin'], GPIO.OUT)
    GPIO.setup(self.config['ccw_pin'], GPIO.OUT)
		GPIO.setup(self.config['pwm_pin'], GPIO.OUT)
    self.pwm = GPIO.PWM(self.control_topic['pwm_pin'], 8000)
    #Close the relay by default, we use the pin state we determined based on the config at init
		GPIO.output(self.config['cw_pin'], GPIO.LOW)
    GPIO.output(self.config['ccw_pin'], GPIO.LOW)
		time.sleep(0.1)

		#Feature to restore relay state in case of crash  or unexpected shutdown. This will check for last state stored in redis and set relay accordingly
		if(self.config.get('restore_last_known_state', None) is not None and self.config.get('restore_last_known_state', False) is True):
			if(variables.r.get(self.config['key']+'_state')):
				self.open = True
				variables.LOGGER.info("Restoring motor {key}".format(**self.config))
				print('Restoring motor \033[1;36m{key} On\033[0;0m'.format(**self.config))


		variables.LOGGER("Motor Worker {key} ready".format(**self.config))
		print('Motor Worker {key}...\t\t\t\033[1;32m Ready\033[0;0m'.format(**self.config))
		return

	def run(self): 
		t = threading.Thread(target=self.work, args=())
		t.start()
		variables.LOGGER.info('Motor Worker {key} running'.format(**self.config))
		print('Motor Worker {key}...\t\t\t\033[1;32m Running\033[0;0m'.format(**self.config))
		return t

	def decodeMessageData(self, message):
		if isinstance(message, dict):
			#print('Dict Found')
			return message
		elif isinstance(message.decode('utf-8'), str):
			try:
				temp = json.loads(message.decode('utf-8'))
				#print('Json Found')
				return temp
			except:
				#print('Json Error. Str Found')
				return {'event':'Unknown', 'data':message}
		else:
			#print('Failed to detect type')
			return {'event':'Unknown', 'data':message}

	def handleMessage(self, message):
		data = message['data']
		if data is not None:
			decoded_message = self.decodeMessageData(data)
			try:
				if decoded_message['event'] == 'Switch':
          data = decoded_message.get('data', None)
					if data != None and (data == MotorState.OPEN) or int(data) == int(MotorState.OPEN)) and self.state != MotorState.OPEN:
						self.motor_active.set()
					elif data != None and (data == MotorState.CLOSED) or int(data) == int(MotorState.CLOSED)) and self.state != MotorState.CLOSED:
						self.motor_active.clear()
          else:
            variables.LOGGER.warning('Switch Motor {0}: unknown data'.format(self.config['key']))
            return
          variables.LOGGER.info('Switch Motor {0} to state {1}'.format(self.config['key'], data))
					print('Switch Motor \033[1;36m{0}\033[0;0m state to \033[1;36m{1}\033[0;0m'.format(self.config['key'], data))
				elif decoded_message['event'] == 'Toggle':
					if self.motor_active.is_set():
            self.motor_active.clear()
            state = 'Off'
          else:
            self.motor_active.set()
            state = 'On'
          variables.LOGGER.info('Toggle Motor {0} to {1}'.format(config['key'], state))
					print('Toggle Motor \033[1;36m{0} to {1} \033[0;0m'.format(self.config['key'], state))
        elif decoded_message['event'] == 'Stop':
          data = decoded_message.get('data', None)
          if data.lower() != variables.LOW_CURRENT:
            self.state = MotorState.STOPPED
          self.motor_active.clear()
          variables.LOGGER.info('Stop Motor {0}'.format(self.config['key']))
          print(variables.RED_BACK + 'Stop Motor {0}'.format(self.config['key']) + '\033[0;0m')
			except:
				variables.LOGGER.error('Error Decoding message for Motor {key}'.format(**self.config))
				print('Error Decoding Message for Motor {0}'.format(self.config['key']))

	def elapsedTime(self):
		self.time_elapsed = time.perf_counter() - self.time_start
		return self.time_elapsed

	def resetElapsedTime(self):
		self.time_start = time.perf_counter()
		pass
	
	def turnOn(self):
		#Turn on relay if its available
		if self.motor_available.is_set():
			if self.state == MotorState.OPEN:
        self.pwm.start(self.config['pwm_power'])
				GPIO.output(self.config['ccw_pin'], GPIO.HIGH)
        self.state = MotorState.CLOSING
      elif self.state == MotorState.CLOSED:
        self.pwm.start(self.config['pwm_power'])
				GPIO.output(self.config['cw_pin'], GPIO.HIGH)
        self.state = MotorState.OPENING
      else:
        if self.config['max_move_time'] != 0 and self.elapsedTime > self.config['max_move_time']:
          self.motor_active.clear()
        return

      message = {'event':'StateChanged', 'data': MOTOR_STATE_STRING[int(self.state)]}
      variables.r.set(self.config['key']+'_state', int(self.state))
      variables.r.publish(self.state_topic, json.dumps(message))
      self.resetElapsedTime()	
      variables.LOGGER.debug("Motor {key} turned ON".format(**self.config))

	def turnOff(self):
		#Turn off volkeye to flip off relay
		if self.motor_available.is_set():
			if self.state == MotorState.STOPPED:
        self.pwm.stop()
        GPIO.output(self.config['ccw_pin'], GPIO.LOW)
        GPIO.output(self.config['cw_pin'], GPIO.LOW)
			elif self.state == MotorState.CLOSING:
        self.pwm.stop()
        GPIO.output(self.config['ccw_pin'], GPIO.LOW)
        self.state = MotorState.CLOSED
      elif self.state == MotorState.OPENING:
        self.pwm.stop()
        GPIO.output(self.config['cw_pin'], GPIO.LOW)
        self.state = MotorState.OPEN
      else:
        return

      message = {'event':'StateChanged', 'data': MOTOR_STATE_STRING[int(self.state)]}
      variables.r.set(self.config['key']+'_state', int(self.state))
      variables.r.publish(self.topic, json.dumps(message))
      self.resetElapsedTime()
      variables.LOGGER.debug("Motor {key} turned OFF".format(**self.config))

	def work(self):
		self.resetElapsedTime()
		while self.main_thread_running.is_set():
			if self.system_ready.is_set():
				try:
					self.pubsub.get_message()
					if self.motor_available.is_set() and self.motor_active.is_set():
            self.turnOn()
            time.sleep(0.1)
					else:
						self.turnOff()
						time.sleep(1)
				except:
					variables.LOGGER.error("Unexpected error in Motor worker {key}".format(**self.config))
					print("Motor Worker \033[1;36m{key}\033[0;0m \t\033[1;31m Unexpected Error\033[0;0m".format(**self.config))

			else:
				#System not ready relay should be off
				self.turnOff()
				time.sleep(1)
				self.resetElapsedTime()
				
			time.sleep(0.1)


		#This is only ran after the main thread is shut down
		#Close the pubsub connection
		self.pubsub.close()
		variables.LOGGER.info("Motor Worker {key} shutting down".format(**self.config))
		print("Motor Worker {key} Shutting Down...\t\033[1;32m Complete\033[0;0m".format(**self.config))
