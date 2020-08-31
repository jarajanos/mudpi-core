import time
import json
import redis
import sys
import traceback
from .trigger import Trigger
try:
	import pycron
	CRON_ENABLED = True
except ImportError:
	CRON_ENABLED = False
sys.path.append('..')
import variables

class TimeTrigger(Trigger):

	def __init__(self, main_thread_running, system_ready, name='TimeTrigger',key=None, trigger_active=None, actions=[], schedule=None, group=None):
		super().__init__(main_thread_running, system_ready, name=name, key=key, trigger_active=trigger_active, actions=actions, trigger_interval=60, group=group)
		self.schedule = schedule
		return

	def init_trigger(self):
		#Initialize the trigger here (i.e. set listeners or create cron jobs)
		pass

	def check(self):
		while self.main_thread_running.is_set():
			if self.system_ready.is_set():
				super().check()
				try:
					if CRON_ENABLED:
						if pycron.is_now(self.schedule):
							self.trigger_active.set()
							super().trigger()
						else:
							self.trigger_active.clear()
					else:
						variables.LOGGER.error("Pycron not found while setting up time trigger")
						print("Error pycron not found.")
				except:
					variables.LOGGER.error("Error evaluating time trigger schedule: " + traceback.format_exc())
					print("Error evaluating time trigger schedule.")
				time.sleep(self.trigger_interval)
			else:
				time.sleep(2)
		return

	def shutdown(self):
		return