"""Native Home Assistant client (REST + WebSocket through the Supervisor proxy).

Replaces the former MCP client. The tool names and result shapes the collectors and the
publisher already use are kept (`call('ha_get_state', ...)`), so the planner core did not
have to change; each tool is implemented on the plain HA API.

Safety, unchanged in spirit: a write allowlist. The client can only write the add-on's own
helpers and never switches hardware. In operating mode `observe` no write is allowed at all.
"""
import json, os
from contextlib import asynccontextmanager
import aiohttp
import settings

SUPERVISOR_URL='http://supervisor/core'
def own():
    """Object ids of the helpers the add-on owns (from the helper prefix). Created on first publish if missing."""
    return set(settings.current().helpers().values())
READ={'ha_get_state','ha_list_states','ha_get_history','ha_config_list_helpers','ha_eval_template','ha_list_services'}

class WritesDisabled(RuntimeError):
    pass

def ev_helper():
    return settings.current().entity('ev_window_helper',required=False)

def _require_writes(mode=None):
    if (mode or settings.operating_mode())=='observe':
        raise WritesDisabled('Betriebsstufe "Beobachten": es wird nichts in Home Assistant geschrieben')

def check_call(name,args,mode=None):
    """Raise unless this call is allowed. `mode` defaults to the add-on's operating mode."""
    weather=settings.current().entity('weather',required=False)
    if name in READ: return
    if name=='ha_manage_energy_prefs' and args=={'mode':'get'}: return
    if name=='ha_call_service':
        pair=(args.get('domain'),args.get('service'))
        entity=args.get('entity_id','')
        # Read-only services that return data.
        if pair==('tibber','get_prices'): return
        if pair==('weather','get_forecasts') and weather and entity==weather and args.get('data')=={'type':'hourly'}: return
        if pair in {('input_datetime','set_datetime'),('input_text','set_value'),('input_number','set_value')} and entity.split('.')[-1] in own():
            _require_writes(mode);return
        raise ValueError('Hardware/service writes prohibited by planner client')
    if name=='ha_config_set_helper':
        helper=args.get('helper_id','').split('.')[-1]
        if (helper in own() or (ev_helper() and helper==ev_helper())) and args.get('action')=='update':
            _require_writes(mode);return
    raise ValueError('Tool or helper outside planner scope')

class Transport:
    """Thin aiohttp wrapper: REST calls and one WebSocket session with auth and request ids."""
    def __init__(self,base=None,token=None):
        self.base=(base or os.environ.get('HA_URL') or SUPERVISOR_URL).rstrip('/')
        self.token=token or os.environ.get('SUPERVISOR_TOKEN') or os.environ.get('HA_TOKEN')
        if not self.token:raise RuntimeError('Kein Zugriffstoken (SUPERVISOR_TOKEN) vorhanden')
        self.http=None;self.ws=None;self._id=0

    async def open(self):
        self.http=aiohttp.ClientSession(headers={'Authorization':'Bearer '+self.token},timeout=aiohttp.ClientTimeout(total=120))
        return self

    async def close(self):
        if self.ws is not None:await self.ws.close()
        if self.http is not None:await self.http.close()

    async def rest(self,method,path,json_body=None,params=None):
        async with self.http.request(method,self.base+'/api'+path,json=json_body,params=params) as r:
            if r.status==404:return None
            if r.status>=400:raise RuntimeError(f'Home Assistant REST {method} {path.split("?")[0]}: HTTP {r.status}')
            text=await r.text()
            return json.loads(text) if text and 'json' in r.headers.get('Content-Type','') else text

    async def _ws_connect(self):
        url=self.base.replace('http','ws',1)+'/websocket'
        self.ws=await self.http.ws_connect(url,max_msg_size=0)
        msg=await self.ws.receive_json()
        if msg.get('type')!='auth_required':raise RuntimeError('WebSocket handshake failed')
        await self.ws.send_json({'type':'auth','access_token':self.token})
        msg=await self.ws.receive_json()
        if msg.get('type')!='auth_ok':raise RuntimeError('WebSocket authentication failed')

    async def command(self,**payload):
        if self.ws is None:await self._ws_connect()
        self._id+=1;mid=self._id
        await self.ws.send_json({'id':mid,**payload})
        while True:
            msg=await self.ws.receive_json()
            if msg.get('id')!=mid:continue
            if not msg.get('success',False):
                # The error body may echo request details; report the code only.
                raise RuntimeError('Home Assistant WebSocket command failed: '+str(msg.get('error',{}).get('code','unknown')))
            return msg.get('result')

def _iso(value):
    return value if isinstance(value,str) else value.isoformat()

def _as_list(value):
    return [value] if isinstance(value,str) else list(value or [])

WEEK=('monday','tuesday','wednesday','thursday','friday','saturday','sunday')

class HA:
    """Tool-style facade over a Transport. `call(name, **args)` returns MCP-shaped dicts."""
    def __init__(self,transport,mode=None):
        self.t=transport;self.mode=mode

    async def call(self,name,**args):
        check_call(name,args,self.mode)
        handler=getattr(self,'_'+name,None)
        if handler is None:raise ValueError('Tool not implemented: '+name)
        return await handler(**args)

    # --- reads -------------------------------------------------------------
    async def _ha_get_state(self,entity_id):
        if isinstance(entity_id,str):
            state=await self.t.rest('GET','/states/'+entity_id)
            if state is None:raise RuntimeError('Entität nicht gefunden: '+entity_id)
            return state
        states={};missing=[]
        for entity in entity_id:
            state=await self.t.rest('GET','/states/'+entity)
            if state is None:missing.append(entity)
            else:states[entity]=state
        return {'states':states,'error_count':len(missing),'errors':missing}

    async def _ha_list_states(self):
        return {'states':await self.t.rest('GET','/states') or []}

    async def _ha_get_history(self,entity_ids,start_time,end_time,source='history',period='hour',statistic_types=None,
                              limit=None,minimal_response=True,significant_changes_only=True):
        ids=_as_list(entity_ids)
        if source=='statistics':
            rows=await self.t.command(type='recorder/statistics_during_period',start_time=_iso(start_time),end_time=_iso(end_time),
                                      statistic_ids=ids,period=period,types=list(statistic_types or ['change']))
            meta=await self.t.command(type='recorder/get_statistics_metadata',statistic_ids=ids)
            units={m['statistic_id']:(m.get('statistics_unit_of_measurement') or m.get('unit_of_measurement')) for m in meta or []}
            # The WebSocket API answers in one piece, so nothing is ever truncated.
            return {'entities':[{'entity_id':e,'unit_of_measurement':units.get(e),'has_more':False,
                                 'statistics':(rows or {}).get(e,[])} for e in ids]}
        params={'filter_entity_id':','.join(ids),'end_time':_iso(end_time),
                'significant_changes_only':'1' if significant_changes_only else '0'}
        if minimal_response:params['minimal_response']='1'
        groups=await self.t.rest('GET','/history/period/'+_iso(start_time),params=params) or []
        return {'entities':[{'entity_id':g[0].get('entity_id'),'has_more':False,'states':g} for g in groups if g]}

    async def _ha_config_list_helpers(self,helper_type,limit=None):
        if helper_type!='schedule':raise ValueError('Only schedule helpers can be listed')
        return {'helpers':await self.t.command(type='schedule/list') or [],'has_more':False}

    async def _ha_eval_template(self,template):
        return {'result':await self.t.rest('POST','/template',{'template':template})}

    async def _ha_manage_energy_prefs(self,mode):
        return {'config':await self.t.command(type='energy/get_prefs') or {}}

    # --- writes (own helpers only; check_call has already vetted the target) ---
    async def _ha_call_service(self,domain,service,entity_id=None,data=None,return_response=False,wait=True):
        body=dict(data or {})
        if entity_id:body['entity_id']=entity_id
        result=await self.t.rest('POST',f'/services/{domain}/{service}',body,params={'return_response':'1'} if return_response else None)
        if return_response:
            return result if isinstance(result,dict) else {'service_response':{}}
        return {'success':True}

    async def _ha_config_set_helper(self,helper_type,helper_id,action,config,**_ignored):
        if helper_type!='schedule':raise ValueError('Only schedule helpers can be written')
        name=helper_id.split('.')[-1]
        week={k:v for k,v in config.items() if k in WEEK}
        existing=await self.t.command(type='schedule/list') or []
        if any(i['id']==name for i in existing):
            await self.t.command(type='schedule/update',schedule_id=name,name=name,**week)
        else:
            await self.t.command(type='schedule/create',name=name,**week)
        return {'success':True}

    async def ensure_own_helpers(self):
        """Create the planner's own input helpers if missing (publish stage and above)."""
        _require_writes(self.mode)
        names=settings.current().helpers()
        spec={
         'input_datetime':{'name':names['expiry'],'has_date':True,'has_time':True},
         'input_text':{'name':names['status'],'max':255},
         'input_number':{'name':names['target'],'min':0,'max':100,'step':1,'mode':'box','unit_of_measurement':'%'},
        }
        created=[]
        for kind,fields in spec.items():
            existing=await self.t.command(type=kind+'/list') or []
            if not any(i.get('id')==fields['name'] for i in existing):
                await self.t.command(type=kind+'/create',**fields);created.append(kind+'.'+fields['name'])
        return created

@asynccontextmanager
async def connection():
    t=await Transport().open()
    try:
        yield HA(t)
    finally:
        await t.close()
