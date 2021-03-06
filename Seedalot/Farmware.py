import os
import json
import requests
import datetime
import ast
import sys

#timezone
tz=0
# long date representation to date object
def l2d(long_s): return datetime.datetime.strptime(long_s, "%Y-%m-%dT%H:%M:%S.%fZ")
def s2d(short_s): return datetime.datetime.strptime(short_s, "%Y-%m-%d")
# date object to long date representation
def d2l(date): return date.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
def d2s(date): return date.strftime("%Y-%m-%d")
def l2u(date): return date-datetime.timedelta(hours=tz)
def u2l(date): return date+datetime.timedelta(hours=tz)
def today_utc(): return datetime.datetime.utcnow()
def today_local(): return today_utc()+datetime.timedelta(hours=tz)


class Farmware(object):
    # ------------------------------------------------------------------------------------------------------------------
    def __init__(self,app_name):
        self._points=None
        self._sequences=None
        self._tools=None
        self.args = {}
        self.debug=False
        self.local = False
        self.app_name=app_name
        self.api_url = 'https://my.farmbot.io/api/'
        try:
            self.headers = {'Authorization': 'Bearer ' + os.environ['API_TOKEN'], 'content-type': "application/json"}
        except :
            print("API_TOKEN is not set, you gonna have a bad time")
            sys.exit(1)

    # ------------------------------------------------------------------------------------------------------------------
    def load_config(self):
        try:
            global tz
            self.device = self.get('device')
            tz = self.device['tz_offset_hrs']
        except Exception as e:
            self.log(e,'error')

    # ------------------------------------------------------------------------------------------------------------------
    # loads config parameters
    def get_arg(self, name, default):
        prefix = self.app_name.lower().replace('-', '_')
        if type(default)!=tuple:
            self.args[name] = type(default)(os.environ.get(prefix + '_'+name, default))
        else:
            self.args[name] = ast.literal_eval(os.environ.get(prefix + '_' + name, str(default)))

        if name=='action':
            if self.args[name]!='real':
                if self.args[name] == 'local': self.local = True
                self.debug = True
                self.log("TEST MODE, NO sequences or movement will be run, plants will NOT be updated",'warn')
        return self.args[name]


    # ------------------------------------------------------------------------------------------------------------------
    def log(self, message, message_type='info'):

        try:
            if not self.local:
                log_message = '[{}] {}'.format(self.app_name, message)
                node = {'kind': 'send_message', 'args': {'message': log_message, 'message_type': message_type}}
                response = requests.post(os.environ['FARMWARE_URL'] + 'api/v1/celery_script', data=json.dumps(node),headers=self.headers)
                response.raise_for_status()
                message = log_message
        except: pass

        print(message)

    # ------------------------------------------------------------------------------------------------------------------
    def sync(self):
        if not self.debug:
            node = {'kind': 'sync', 'args': {}}
            response = requests.post(os.environ['FARMWARE_URL'] + 'api/v1/celery_script', data=json.dumps(node),headers=self.headers)
            response.raise_for_status()

    # ------------------------------------------------------------------------------------------------------------------
    def get(self, enpoint):
        response = requests.get(self.api_url + enpoint, headers=self.headers)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------------------------------------------------------
    def delete(self, enpoint):
        if not self.debug:
            response = requests.delete(self.api_url + enpoint, headers=self.headers)
            response.raise_for_status()
            return
    # ------------------------------------------------------------------------------------------------------------------
    def post(self, enpoint, data):
        if not self.debug:
            response = requests.post(self.api_url + enpoint, headers=self.headers, data=json.dumps(data))
            response.raise_for_status()
            return response.json()

    # ------------------------------------------------------------------------------------------------------------------
    def put(self, enpoint, data):
        if not self.debug:
            response = requests.put(self.api_url + enpoint, headers=self.headers, data=json.dumps(data))
            response.raise_for_status()
            return response.json()

    # ------------------------------------------------------------------------------------------------------------------
    def patch(self, enpoint, data):
        if not self.debug:
            response = requests.patch(self.api_url + enpoint, headers=self.headers, data=json.dumps(data))
            response.raise_for_status()
            return response.json()

    # ------------------------------------------------------------------------------------------------------------------
    def execute_sequence(self, sequence, message=''):
        if sequence != None:
            if message != None:
                self.log('{}Executing sequence: {}({})'.format(message, sequence['name'].upper(), sequence['id']))
            if not self.debug:
                node = {'kind': 'execute', 'args': {'sequence_id': sequence['id']}}
                response = requests.post(os.environ['FARMWARE_URL'] + 'api/v1/celery_script', data=json.dumps(node),
                                         headers=self.headers)
                response.raise_for_status()

    # ------------------------------------------------------------------------------------------------------------------
    def move_absolute(self, location, offset={'x': 0, 'y': 0, 'z': 0}, message=''):

        if message!=None:
            self.log('{}Moving absolute: {} {}'.format(message, str(location), "" if offset=={'y': 0, 'x': 0, 'z': 0} else str(offset)))

        node = {'kind': 'move_absolute', 'args':
            {
                'location': {'kind': 'coordinate', 'args': location},
                'offset': {'kind': 'coordinate', 'args': offset},
                'speed': 300
            }
                }

        if not self.debug:
            response = requests.post(os.environ['FARMWARE_URL'] + 'api/v1/celery_script', data=json.dumps(node),
                                     headers=self.headers)
            response.raise_for_status()

    # ------------------------------------------------------------------------------------------------------------------
    def points(self):
        if self._points!=None: return self._points
        self._points=self.get('points')
        return self._points

    # ------------------------------------------------------------------------------------------------------------------
    def plant_age(self, p):

        if p['pointer_type'].lower()!= 'plant': return 0
        if p['plant_stage'] != 'planted': return 0
        if p['planted_at'] == None: return 0
        return (today_utc() - l2d(p['planted_at'])).days + 1

    # ------------------------------------------------------------------------------------------------------------------
    def sequences(self):
        if self._sequences != None: return self._sequences
        self._sequences = self.get('sequences')
        return self._sequences

    # ------------------------------------------------------------------------------------------------------------------
    def tools(self):
        if self._tools != None: return self._tools
        self._tools = self.get('tools')
        return self._tools

    # ------------------------------------------------------------------------------------------------------------------
    def lookup_openfarm(self, plant):
        response = requests.get(
            'https://openfarm.cc/api/v1/crops?include=pictures&filter={}'.format(plant['openfarm_slug']), headers=self.headers)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------------------------------------------------------
    def load_weather(self):

        self.weather = {}
        today = (datetime.datetime.utcnow()+ datetime.timedelta(hours=tz)).strftime('%Y-%m-%d')

        try:
            weather_station = None
            try:
                watering_tool = next(x for x in self.tools() if 'water' in x['name'].lower())
                weather_station = next(x for x in self.points() if x['pointer_type'] == 'ToolSlot'
                                       and x['tool_id'] == watering_tool['id'])
            except Exception as e:
                self.log("No watering tool detected (I save weather into the watering tool meta)")

            self.weather = ast.literal_eval(weather_station['meta']['current_weather'])
            if not isinstance(self.weather, dict): raise ValueError
            # leave only last 7 days
            if 'rain_3' in self.weather.keys(): del self.weather['rain_3']
            self.weather = {k: v for (k, v) in self.weather.items() if
                            datetime.date.today() - s2d(k).date() < datetime.timedelta(days=7)}

        except:  pass

    # ------------------------------------------------------------------------------------------------------------------
    def save_weather(self):

        weather_station = None
        try:
            if 'rain_3' in self.weather.keys(): del self.weather['rain_3']
            watering_tool = next(x for x in self.tools() if 'water' in x['name'].lower())
            weather_station = next(x for x in self.points() if x['pointer_type'] == 'ToolSlot'
                                   and x['tool_id'] == watering_tool['id'])
            weather_station['meta']['current_weather'] = str(self.weather)
            self.post('points/{}'.format(weather_station['id']), weather_station)
        except:
            raise ValueError("No watering tool detected (I save weather into the watering tool meta)")

