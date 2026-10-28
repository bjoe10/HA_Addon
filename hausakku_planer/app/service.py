"""Add-on service: scheduler and the web UI backend."""
import asyncio, json, logging, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from aiohttp import web
import paths, prices, settings, views
import ha_client
from ha_client import connection

TZ=ZoneInfo('Europe/Berlin')
APP=Path(__file__).resolve().parent
MAIN_TIMES=((14,15),(20,15))   # daily full run
REPLAN_MINUTE=45               # quiet hourly replan
WEEKLY_TIME=(0,8,0)            # weekday (0 = Monday), hour, minute: weekly balance
log=logging.getLogger('hausakku')

def planner_args(kind,mode):
    """Command line of the planner for a run kind: 'main' or 'replan', by operating mode."""
    if kind=='weekly':return []
    if mode=='observe':return []                        # compute only, nothing is written to HA
    return ['--publish'] if kind=='main' else ['--replan']

def due_runs(now,last_check):
    """Run kinds due in (last_check, now], collapsed: one run now covers everything missed. Pure, for tests."""
    due=[]
    t=(last_check+timedelta(minutes=1)).replace(second=0,microsecond=0)
    while t<=now:
        if (t.weekday(),t.hour,t.minute)==WEEKLY_TIME:due.append('weekly')
        if (t.hour,t.minute) in MAIN_TIMES:due.append('main')
        elif t.minute==REPLAN_MINUTE:due.append('replan')
        t+=timedelta(minutes=1)
    return (['main'] if 'main' in due else ['replan'] if 'replan' in due else [])+(['weekly'] if 'weekly' in due else [])

def log_run(entry):
    paths.ensure()
    with (paths.STATE/'runs.jsonl').open('a') as f:f.write(json.dumps(entry,ensure_ascii=False)+'\n')
    lines=(paths.STATE/'runs.jsonl').read_text().splitlines()
    if len(lines)>500:(paths.STATE/'runs.jsonl').write_text('\n'.join(lines[-500:])+'\n')

def read_runs(limit=50):
    f=paths.STATE/'runs.jsonl'
    if not f.exists():return []
    return [json.loads(l) for l in f.read_text().splitlines()[-limit:]][::-1]

async def run_planner(kind,mode,trigger='zeit',command=None):
    """Run planner.py as its own process (keeps its lock and failure handling) and log the result."""
    missing=settings.current().missing('plan')
    started=datetime.now(TZ)
    if missing:
        entry={'time':started.isoformat(),'kind':kind,'trigger':trigger,'mode':mode,'ok':False,'skipped':True,
               'message':'Einrichtung unvollständig: '+', '.join(settings.label(r) for r in missing)}
        log_run(entry);return entry
    script='weekly_report.py' if kind=='weekly' else 'planner.py'
    cmd=command or [sys.executable,str(APP/script),*planner_args(kind,mode)]
    t0=time.monotonic()
    proc=await asyncio.create_subprocess_exec(*cmd,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,cwd=str(APP),env=os.environ.copy())
    out,err=await proc.communicate()
    full=out.decode(errors='replace')
    entry={'time':started.isoformat(),'kind':kind,'trigger':trigger,'mode':mode,'ok':proc.returncode==0,
           'seconds':round(time.monotonic()-t0,1),'stdout':full[-3000:],'stderr':err.decode(errors='replace')[-1500:]}
    log_run(entry)
    if mode!='observe' and not command:await publish_report({**entry,'stdout':full})
    return entry

def bridge_attributes(entry,previous):
    """Attributes of the report sensor: the latest output per run kind, merged into what is already there."""
    attrs=dict(previous)
    report=(entry.get('stdout') or '').strip()
    attrs[entry['kind']]={'time':entry['time'],'ok':entry['ok'],'report':report[:12000],'error':(entry.get('stderr') or '').strip()[-1500:]}
    return attrs

async def publish_report(entry):
    """Hand the run's output to Home Assistant as one sensor, so a summariser can read it without the add-on API."""
    if entry.get('skipped'):return
    f=paths.STATE/'bridge.json'
    previous=json.loads(f.read_text()) if f.exists() else {}
    attrs=bridge_attributes(entry,previous)
    f.write_text(json.dumps(attrs,ensure_ascii=False))
    try:
        async with connection() as ha:
            await ha.call('ha_set_state',entity_id=ha_client.report_sensor(),state=entry['time'],attributes=attrs)
    except Exception as exc:
        log.warning('Bericht-Sensor nicht geschrieben (%s)',type(exc).__name__)

class Scheduler:
    def __init__(self):self.lock=asyncio.Lock();self.running=None;self._tasks=set()

    def _claim(self,kind):
        """Mark a run as active right away, so status and a second request see it before the task starts."""
        if self.running or self.lock.locked():return False
        self.running={'kind':kind,'since':datetime.now(TZ).isoformat()}
        return True

    async def _execute(self,kind,trigger):
        async with self.lock:
            try:return await run_planner(kind,settings.operating_mode(),trigger)
            finally:self.running=None

    async def trigger(self,kind,trigger='zeit'):
        """Run and wait for the result (used by the scheduler loop)."""
        if not self._claim(kind):return {'ok':False,'message':'Ein Lauf ist bereits aktiv.'}
        return await self._execute(kind,trigger)

    def start(self,kind,trigger='manuell'):
        """Run in the background and return at once; False if a run is already active."""
        if not self._claim(kind):return False
        task=asyncio.create_task(self._execute(kind,trigger))
        self._tasks.add(task);task.add_done_callback(self._tasks.discard)
        return True

    async def loop(self):
        last=datetime.now(TZ)
        plan=paths.STATE/'plan.json'
        # A fresh install or restart should not wait up to an hour for the first plan.
        if not plan.exists() or time.time()-plan.stat().st_mtime>3600:
            await self.trigger('main','start')
        while True:
            await asyncio.sleep(20)
            now=datetime.now(TZ)
            for kind in due_runs(now,last):await self.trigger(kind)
            last=now

def plan_summary():
    f=paths.STATE/'plan.json'
    if not f.exists():return None
    p=json.loads(f.read_text())
    return {'created_at':p.get('created_at'),'valid_until':p.get('valid_until'),'target_soc':p.get('target_soc'),
            'mode':p.get('mode'),'publication':(p.get('publication') or {}).get('verified')}

WEB=APP/'web'
STATS_DAYS=28

def load_plan():
    f=paths.STATE/'plan.json'
    return json.loads(f.read_text()) if f.exists() else None

async def index(request):return web.FileResponse(WEB/'index.html')

async def status(request):
    cfg=settings.current()
    sched=request.app['scheduler']
    runs=read_runs(1)
    return web.json_response({'mode':settings.operating_mode(),
        'missing':[settings.label(r) for r in cfg.missing('plan')],
        'running':sched.running,'plan':plan_summary(),
        'last_run':{k:runs[0][k] for k in ('time','kind','ok','message') if k in runs[0]} if runs else None})

async def runs(request):return web.json_response(read_runs(int(request.query.get('limit','50'))))

async def run_now(request):
    """Start a run in the background. The UI polls /api/status; a run can take minutes on the first start."""
    if not request.app['scheduler'].start('main','manuell'):
        return web.json_response({'ok':False,'message':'Ein Lauf ist bereits aktiv.'},status=409)
    return web.json_response({'ok':True,'started':True},status=202)

async def plan(request):
    p=load_plan()
    return web.json_response({'plan':views.plan_view(p) if p else None})

async def get_settings(request):
    cfg=settings.current()
    roles=[{'role':r,'label':label,'need':need,'list':r in settings.LISTS} for r,(label,need) in settings.ROLES.items()]
    return web.json_response({'settings':{k:cfg.data[k] for k in ('entities','location','battery','tariff','prices','helper_prefix','adopt_legacy_helpers')},'roles':roles,
                              'helpers':cfg.helpers(),
                              'missing':cfg.missing('plan'),'missing_control':cfg.missing('control'),'mode':settings.operating_mode()})

async def put_settings(request):
    clean,errors=views.validate_settings(await request.json())
    if errors:return web.json_response({'ok':False,'errors':errors},status=400)
    clean['planner']=settings.current().data.get('planner',{})   # developer overrides are not edited here
    settings.save(clean)
    return web.json_response({'ok':True,'missing':settings.current().missing('plan')})

async def entities(request):
    role=request.query.get('role','')
    if role not in settings.ROLES and role!='price_entity':return web.json_response({'error':'unknown role'},status=400)
    try:
        async with connection() as ha:states=(await ha.call('ha_list_states'))['states']
    except Exception as exc:
        return web.json_response({'entities':[],'warning':'Home Assistant nicht erreichbar ('+type(exc).__name__+')'})
    return web.json_response({'entities':views.suggest(role,states,request.query.get('q',''))})

async def check_entity(ha,role,entity,now=None):
    """Does the entity exist, what unit does it have, and (for counters) is there enough statistics history?"""
    result={'entity':entity,'ok':False,'messages':[]}
    try:
        state=await ha.call('ha_get_state',entity_id=entity)
    except Exception:
        result['messages'].append('Entität nicht gefunden.');return result
    attrs=state.get('attributes') or {};unit=attrs.get('unit_of_measurement')
    result.update(state=state.get('state'),unit=unit,ok=True)
    if state.get('state') in ('unavailable','unknown'):
        result['ok']=False;result['messages'].append('Aktuell nicht verfügbar.')
    if role in views.COUNTER_ROLES|views.FORECAST_ROLES|{'battery_kwh'} and unit not in views.ENERGY_UNITS:
        result['ok']=False;result['messages'].append(f'Einheit {unit or "fehlt"}: erwartet kWh oder Wh.')
    if role in views.COUNTER_ROLES:
        now=now or datetime.now(TZ)
        rows=await ha.call('ha_get_history',source='statistics',entity_ids=entity,start_time=(now-timedelta(days=STATS_DAYS)).isoformat(),
                           end_time=now.isoformat(),period='day',statistic_types=['change'])
        days=len([r for e in rows['entities'] for r in e.get('statistics',[]) if r.get('change') is not None])
        result['history_days']=days
        if days==0:result['ok']=False;result['messages'].append('Keine Langzeitstatistik. Der Zähler braucht state_class total oder total_increasing.')
        elif days<STATS_DAYS-3:result['messages'].append(f'Erst {days} von {STATS_DAYS} Tagen Verlauf; der Plan wird mit Startwerten ungenauer.')
        else:result['messages'].append(f'{days} Tage Verlauf vorhanden.')
    return result

async def check(request):
    role=request.query.get('role','');entity=request.query.get('entity','')
    if role not in settings.ROLES or not views.ENTITY_RE.match(entity):return web.json_response({'error':'bad request'},status=400)
    try:
        async with connection() as ha:return web.json_response(await check_entity(ha,role,entity))
    except Exception as exc:
        return web.json_response({'entity':entity,'ok':False,'messages':['Home Assistant nicht erreichbar ('+type(exc).__name__+')']})

async def check_prices(request):
    """Fetch the configured price source once and report what the planner would see."""
    now=datetime.now(TZ);daystart=now.replace(hour=0,minute=0,second=0,microsecond=0)
    try:
        async with connection() as ha:
            rows,info=await prices.fetch(ha,daystart)
    except prices.PriceError as exc:
        return web.json_response({'ok':False,'message':str(exc)})
    except Exception as exc:
        return web.json_response({'ok':False,'message':'Abruf fehlgeschlagen ('+type(exc).__name__+')'})
    s=prices.summarize(rows,info,now)
    notes=[]
    if s['gaps']:notes.append(f"{s['gaps']} Lücke(n) in den Preisen; der Planer lehnt lückenhafte Preise ab.")
    if info.get('unit_known') is False:notes.append('Einheit des Sensors unbekannt, es wird EUR/kWh angenommen.')
    if s['now'] is None:notes.append('Für die aktuelle Viertelstunde liegt kein Preis vor.')
    return web.json_response({'ok':not s['gaps'] and s['now'] is not None,'summary':s,'notes':notes})

INGRESS_GATEWAY='172.30.32.2'

@web.middleware
async def ingress_only(request,handler):
    """In the add-on only the Supervisor's ingress gateway may talk to the service."""
    if os.environ.get('SUPERVISOR_TOKEN') and request.remote not in (INGRESS_GATEWAY,'127.0.0.1'):
        raise web.HTTPForbidden()
    return await handler(request)

def make_app():
    app=web.Application(middlewares=[ingress_only]);app['scheduler']=Scheduler()
    app.router.add_get('/',index);app.router.add_get('/api/status',status)
    app.router.add_get('/api/runs',runs);app.router.add_post('/api/run',run_now);app.router.add_get('/api/plan',plan)
    app.router.add_get('/api/settings',get_settings);app.router.add_put('/api/settings',put_settings)
    app.router.add_get('/api/entities',entities);app.router.add_get('/api/check',check);app.router.add_get('/api/prices/check',check_prices)
    async def start(app):app['task']=asyncio.create_task(app['scheduler'].loop())
    async def stop(app):app['task'].cancel()
    if os.environ.get('HAUSAKKU_NO_SCHEDULER')!='1':app.on_startup.append(start);app.on_cleanup.append(stop)
    return app

def main():
    logging.basicConfig(level=os.environ.get('HAUSAKKU_LOG_LEVEL','info').upper())
    paths.ensure()
    web.run_app(make_app(),host='0.0.0.0',port=8099)

if __name__=='__main__':main()
