import time
import datetime 
import paho.mqtt.client as mqtt
import json
import redis
import threading
import sys
sys.path.append('..')

import variables


class MqttWorker:
  def __init__(self, config, main_thread_running, system_ready):
    self.config = config

    # Events
    self.main_thread_running = main_thread_running
    self.system_ready = system_ready

    # Config properties
    self.topic_publish = self.config['pub_topic'].replace(" ", "/").lower() if self.config['pub_topic'] is not None else 'mudpi/control'
    self.topic_subscribe = self.config['sub_topic'].replace(" ", "/").lower() if self.config['sub_topic'] is not None else 'mudpi/public/*'
    self.broker = self.config['broker'] if self.config['broker'] is not None else '127.0.0.1'
    self.port = self.config['port'] if self.config['port'] is not None else '1883'
    self.name = self.config['name'] if self.config['name'] is not None else 'MudPi'
    self.mqtt_topic_publish = self.config['mqtt_pub_topic'] if self.config['mqtt_pub_topic'] is not None else 'data'
    self.mqtt_topic_subscribe = self.config['mqtt_sub_topic'] if self.config['mqtt_sub_topic'] is not None else 'control'
    self.username = self.config['username'] if self.config['username'] is not None else ''
    self.password = self.config['password'] if self.config['password'] is not None else ''

    if self.mqtt_topic_publish[-1] != '/':
      self.mqtt_topic_publish += '/'

    if self.topic_publish[-1] != '/':
      self.topic_publish += '/'

    # Pubsub Listeners
		self.pubsub = variables.r.pubsub()
		self.pubsub.psubscribe(**{self.topic_subscribe: self.handlePublish})

		self.init()

  def init(self):
    self.client = mqtt.Client(self.name)
    self.client.username_pw_set(self.username, self.password)
    self.client.on_message = self.handleSubscribe
    self.client.connect(self.broker, self.port, keepalive=60)
    self.client.subsribe(self.mqtt_topic_subscribe, 0)

  def run(self):
    t = threading.Thread(target=self.work, args=())
    t.start()
    print('MQTT Worker...\t\t\t\033[1;32m Running\033[0;0m')
    return t

  def handlePublish(self, message):
    topic = self.mqtt_topic_publish + message['channel'][len(self.topic_subscribe) - 1:]
    self.client.publish(topic, payload=message['data'])
    print('MQTT Worker...\t\t\t\033[1;32m Publishing message \"' + message['data'] + '\" on MQTT topic \"' + topic + '\033[0;0m')
  
  def handleSubscribe(client, userdata, message):
    topic = self.topic_publish + message.topic[len(self.mqtt_topic_subscribe):]
    self.pubsub.publish(topic, message.payload)
    print('MQTT Worker...\t\t\t\033[1;32m Publishing message \"' + message.payload + '\" on Redis topic \"' + topic + '\033[0;0m')

	def elapsedTime(self):
		self.time_elapsed = time.perf_counter() - self.time_start
		return self.time_elapsed

	def resetElapsedTime(self):
		self.time_start = time.perf_counter()

  def work(self):
    self.resetElapsedTime();

    while self.main_thread_running.is_set():
      if self.system_ready.is_set():
        try:
          self.pubsub.get_message()
          self.client.loop(timeout=0.5)
        except:
          print("MQTT Worker \t\033[1;31m Unexpected Error\033[0;0m")
      
      else:
          self.resetElapsedTime()
      
      time.sleep(0.1)

    self.pubsub.close()
    print("MQTT Worker Shutting Down...\t\033[1;32m Complete\033[0;0m")
    