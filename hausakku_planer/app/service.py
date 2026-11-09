"""Add-on service: scheduler and the web UI backend."""
import asyncio, json, logging, math, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from aiohttp import web
import collector, dashboard_card, multiday, paths, prices, settings, shadow, views
import ha_client
from ha_client import connection

TZ=ZoneInfo('Europe/Berlin')
APP=Path(__file__).resolve().parent
MAIN_TIMES=((14,15),(20,15))   # daily full run
REPLAN_MINUTE=45               # quiet hourly replan
WEEKLY_TIME=(0,8,0)            # weekday (0 = Monday), hour, minute: weekly balance
# A run is stopped after this many seconds. Normal runs take one to three minutes; a hung run would otherwise
# hold the scheduler lock for good, and no later plan, replan or balance could start.
RUN_TIMEOUT={'main':900,'replan':900,'weekly':600}
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

async def run_process(cmd,timeout):
    """Run a command, collecting its output. Past `timeout` seconds it is killed; what it printed so far is kept.
    Returns (returncode or None when killed, stdout bytes, stderr bytes)."""
    # Unbuffered, so a stopped run keeps what it printed; a minute before the limit it writes where it waits (diagnostics.py).
    env={**os.environ,'PYTHONUNBUFFERED':'1','HAUSAKKU_DUMP_AFTER':str(max(timeout-60,timeout*.8))}
    proc=await asyncio.create_subprocess_exec(*cmd,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,cwd=str(APP),env=env)
    reads=[asyncio.ensure_future(proc.stdout.read()),asyncio.ensure_future(proc.stderr.read())]
    try:
        await asyncio.wait_for(proc.wait(),timeout)
        killed=False
    except asyncio.TimeoutError:
        proc.kill();await proc.wait();killed=True
    # After the process ends the pipes close; a leftover child holding them open must not block us again.
    done,pending=await asyncio.wait(reads,timeout=5)
    for task in pending:task.cancel()
    out,err=(t.result() if t in done and t.exception() is None else b'' for t in reads)
    return (None if killed else proc.returncode),out,err

async def run_planner(kind,mode,trigger='zeit',command=None,timeout=None):
    """Run planner.py as its own process (keeps its lock and failure handling) and log the result."""
    missing=settings.current().missing('plan')
    started=datetime.now(TZ)
    if missing:
        entry={'time':started.isoformat(),'kind':kind,'trigger':trigger,'mode':mode,'ok':False,'skipped':True,
               'message':'Einrichtung unvollständig: '+', '.join(settings.label(r) for r in missing)}
        log_run(entry);return entry
    script='weekly_report.py' if kind=='weekly' else 'planner.py'
    cmd=command or [sys.executable,str(APP/script),*planner_args(kind,mode)]
    limit=timeout or RUN_TIMEOUT.get(kind,900)
    t0=time.monotonic()
    code,out,err=await run_process(cmd,limit)
    full=out.decode(errors='replace');errors=err.decode(errors='replace')
    entry={'time':started.isoformat(),'kind':kind,'trigger':trigger,'mode':mode,'ok':code==0,
           'seconds':round(time.monotonic()-t0,1),'stdout':full[-3000:],'stderr':errors[-1500:]}
    if code is None:
        entry['message']=f'Zeitlimit von {round(limit/60)} min überschritten, Lauf abgebrochen.' if limit>=60 else f'Zeitlimit von {limit} s überschritten, Lauf abgebrochen.'
        entry['stderr']=(errors+'\n'+entry['message']).strip()[-8000:]     # room for the stack dump
        log.warning('Lauf %s nach %d s abgebrochen (Zeitlimit)',kind,limit)
    log_run(entry)
    if mode!='observe' and not command:await publish_report({**entry,'stdout':full})
    return entry

def soc_plan_attribute(plan):
    """The published plan's battery energy at each interval end, compact for a dashboard line.
    Only a verified publication counts: any other plan is not what the schedules in HA say."""
    if not plan or not (plan.get('publication') or {}).get('verified'):return None
    intervals=(plan.get('plan') or {}).get('intervals') or []
    if not intervals:return None
    start=datetime.fromisoformat(intervals[0]['start'])
    return {'created_at':plan.get('created_at'),'valid_until':plan.get('valid_until'),'start':intervals[0]['start'],
            'capacity_kwh':(plan.get('inputs') or {}).get('nominal_capacity_kwh'),'initial_kwh':round(intervals[0]['initial_kwh'],2),
            'minutes':[round((datetime.fromisoformat(i['end'])-start).total_seconds()/60) for i in intervals],
            'kwh':[round(i['terminal_kwh'],2) for i in intervals]}

def bridge_attributes(entry,previous,plan=None):
    """Attributes of the report sensor: the latest output per run kind, merged into what is already there,
    and the planned battery energy of the last verified publication."""
    attrs=dict(previous)
    report=(entry.get('stdout') or '').strip()
    attrs[entry['kind']]={'time':entry['time'],'ok':entry['ok'],'report':report[:12000],'error':(entry.get('stderr') or '').strip()[-1500:]}
    soc=soc_plan_attribute(plan)
    if soc:attrs['soc_plan']=soc
    return attrs

SHADOW_FILE='shadow.json'

def savings_summary():
    """The running savings of the control as last computed (see shadow.py); None before the first update."""
    try:return json.loads((paths.STATE/SHADOW_FILE).read_text()).get('summary')
    except (OSError,ValueError):return None

def savings_state(summary):
    """State and attributes of the savings sensor: total saving in EUR since counting started, plus this week."""
    attrs={'unit_of_measurement':'EUR','device_class':'monetary','state_class':'total','icon':'mdi:piggy-bank-outline',
           'friendly_name':'Hausakku Ersparnis',
           'note':'Nur Viertelstunden mit eingeschalteter Steuerung; Vergleich: Wechselrichter dauernd an, nie Netzladen.'}
    if not summary:return 'unknown',attrs
    attrs.update({k:v for k,v in summary.items() if k!='total_eur'})
    return summary['total_eur'],attrs

def load_config():
    """The planner's configuration, as planner.load_config (without importing the planner)."""
    path=paths.DATA/'config.json'
    return json.loads(path.read_text()) if path.exists() else settings.current().planner_config()

async def savings_rows(ha,cfg,config,start,end,prices_by_quarter):
    """Quarter-hour rows for the shadow from 5-minute statistics, the release switch's history and the price archive.
    Returns (rows, battery kWh at the end or None)."""
    iso=lambda t:datetime.fromtimestamp(t,TZ).isoformat()
    roles=collector.energy_map(cfg);evs=collector.vehicle_entities(cfg)
    stats=await ha.call('ha_get_history',source='statistics',entity_ids=list(roles.values())+evs,start_time=iso(start),
                        end_time=iso(end),period='5minute',statistic_types=['change'])
    data=collector.normalize_statistics(stats)
    meters={role:shadow.quarters(data.get(e,{}),start,end) for role,e in roles.items()}   # roles: grid, wr, charger, export, pv
    buckets=range(int(start),int(end),shadow.BUCKET)
    ev=collector.vehicle_energy(data.get(evs[0],{}),{e:data.get(e,{}) for e in evs[1:]}) if evs else {float(t):0. for t in buckets}
    meters['ev']=shadow.quarters(ev,start,end)
    kwh=cfg.entity('battery_kwh',required=False)
    entity=kwh or cfg.entity('battery_soc')
    b=await ha.call('ha_get_history',source='statistics',entity_ids=entity,start_time=iso(start),end_time=iso(end),
                    period='5minute',statistic_types=['mean'])
    factor=1. if kwh else float(config['capacity_kwh'])/100.
    means={}
    for e in b['entities']:
        scale=factor*(.001 if kwh and e.get('unit_of_measurement')=='Wh' else 1.)
        for r in e.get('statistics',[]):
            if r.get('mean') is not None:means[int(float(r['start'])/1000)]=float(r['mean'])*scale
    battery={q:means[q] for q in range(int(start),int(end),shadow.STEP) if q in means}
    measured=means[max(means)] if means else None
    perm='input_boolean.'+cfg.helpers()['permission']
    h=await ha.call('ha_get_history',entity_ids=perm,start_time=iso(start),end_time=iso(end),
                    minimal_response=True,significant_changes_only=False)
    states=[(datetime.fromisoformat(s['last_changed']).timestamp(),s.get('state')) for e in h['entities'] for s in e['states'] if s.get('last_changed')]
    active=shadow.active_quarters(states,start,end)
    return shadow.build_rows(start,end,meters,battery,active,prices_by_quarter),measured

async def update_savings(ha,now=None):
    """Advance the savings shadow to the last complete quarter-hour and keep its summary for the sensor and the UI."""
    cfg=settings.current();now_ts=(now or datetime.now(TZ)).timestamp()
    f=paths.STATE/SHADOW_FILE;state=shadow.load_state(f,now_ts)
    config=load_config()
    snap=paths.STATE/'snapshot.json'
    try:calibration=json.loads(snap.read_text()).get('battery_calibration') if snap.exists() else None
    except ValueError:calibration=None
    params=shadow.model_params(config,calibration)
    archive=multiday.read_prices(paths.STATE/'multiday_audit.sqlite',datetime.fromtimestamp(now_ts,TZ).isoformat())
    by_quarter={int(r['start']):float(r['price']) for r in archive}
    value=shadow.battery_value(config,by_quarter,params,now_ts)
    end=math.floor((now_ts-shadow.SETTLE)/shadow.STEP)*shadow.STEP
    shadow.skip_to(state,end-shadow.MAX_CATCHUP,value)
    if end>state['last_end']:
        rows,measured=await savings_rows(ha,cfg,config,state['last_end'],end,by_quarter)
        shadow.advance(state,rows,params,value)
        if measured is not None:state['end_kwh']=measured
    state['summary']=shadow.summary(state,value,state.get('end_kwh'))
    shadow.save_state(f,state)
    return state['summary']

async def publish_report(entry):
    """Hand the run's output to Home Assistant as one sensor, so a summariser can read it without the add-on API.
    The savings are brought up to date and written alongside, so both come back with the next run after a
    Home Assistant restart."""
    if entry.get('skipped'):return
    f=paths.STATE/'bridge.json'
    previous=json.loads(f.read_text()) if f.exists() else {}
    attrs=bridge_attributes(entry,previous,load_plan())
    f.write_text(json.dumps(attrs,ensure_ascii=False))
    try:
        async with connection() as ha:
            await ha.call('ha_set_state',entity_id=ha_client.report_sensor(),state=entry['time'],attributes=attrs)
            try:summary=await update_savings(ha)
            except Exception as exc:
                log.warning('Ersparnis nicht fortgeschrieben (%s)',type(exc).__name__);summary=savings_summary()
            state,extra=savings_state(summary)
            await ha.call('ha_set_state',entity_id=ha_client.savings_sensor(),state=state,attributes=extra)
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
        'running':sched.running,'plan':plan_summary(),'savings':savings_summary(),
        'last_run':{k:runs[0][k] for k in ('time','kind','ok','message') if k in runs[0]} if runs else None})

async def runs(request):return web.json_response(read_runs(int(request.query.get('limit','50'))))

async def run_now(request):
    """Start a run in the background. The UI polls /api/status; a run can take minutes on the first start."""
    kind=request.query.get('kind','main')
    if kind not in ('main','replan','weekly'):return web.json_response({'ok':False,'message':'Unbekannte Laufart.'},status=400)
    if not request.app['scheduler'].start(kind,'manuell'):
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
                              'missing':cfg.missing('plan'),'missing_control':cfg.missing('control'),'mode':settings.operating_mode(),
                              'publish':settings.operating_mode()=='publish','publish_saved':cfg.data.get('publish') is not None})

async def blueprint(request):
    cfg=settings.current()
    return web.json_response({'import_url':views.BLUEPRINT_IMPORT,'source_url':views.BLUEPRINT_URL,
                              'values':[{'label':l,'value':v} for l,v in views.blueprint_values(cfg)]})

async def control_setup(request):
    """Create the control automation from the blueprint (the UI asks for confirmation first). The release switch stays off."""
    cfg=settings.current()
    if settings.operating_mode()!='publish':
        return web.json_response({'ok':False,'message':'Zuerst „In Home Assistant veröffentlichen“ einschalten und speichern.'},status=409)
    inputs=views.blueprint_inputs(cfg)
    missing=[settings.label(r) for r,k in (('charger_switch','charger_switch'),('inverter_switch','inverter_switch'),('battery_soc','soc_sensor')) if not inputs.get(k)]
    if missing:return web.json_response({'ok':False,'message':'Es fehlen: '+', '.join(missing)+'.'},status=400)
    try:
        async with connection() as ha:
            owner='input_boolean.'+cfg.helpers()['owner']
            related=await ha.call('ha_related',entity_id=owner)      # an error here stops the setup: no check, no automation
            if related.get('automation'):
                return web.json_response({'ok':False,'message':'Es gibt schon eine Steuerung, die diese Helfer benutzt. Es wurde nichts angelegt.'},status=409)
            await ha.ensure_own_helpers()
            done=await ha.install_control((APP/'blueprint'/'steuerung.yaml').read_text(),views.BLUEPRINT_URL,inputs)
    except ha_client.ControlExists:
        return web.json_response({'ok':False,'message':'Die Automation „Hausakku-Planer Steuerung“ gibt es schon.'},status=409)
    except Exception as exc:
        log.warning('Steuerung einrichten fehlgeschlagen (%s)',type(exc).__name__)
        return web.json_response({'ok':False,'message':'Einrichten fehlgeschlagen ('+type(exc).__name__+'). Es wurde nichts eingeschaltet.'},status=500)
    return web.json_response({'ok':True,**done,'message':'Die Automation wurde angelegt. Die Freigabe ist aus, es wird nichts geschaltet.'})

async def card(request):
    """The dashboard card: installed, current with this add-on version and settings, and the Tibber home for the example."""
    cfg=settings.current()
    try:
        async with connection() as ha:
            resource=dashboard_card.find_card(await ha.lovelace_resources())
            try:device=dashboard_card.tibber_device((await ha.call('ha_entity_registry'))['entities'])
            except Exception:device=None
    except Exception as exc:
        return web.json_response({'installed':None,'warning':'Home Assistant nicht erreichbar ('+type(exc).__name__+')'})
    return web.json_response({'installed':resource is not None,'current':bool(resource) and resource.get('url')==dashboard_card.current_url(cfg),
                              'version':dashboard_card.installed_version(resource),'device_id':device})

async def card_setup(request):
    """Install the dashboard card as a Lovelace resource or bring it up to date (the UI asks first)."""
    if settings.operating_mode()!='publish':
        return web.json_response({'ok':False,'message':'Zuerst „In Home Assistant veröffentlichen“ einschalten und speichern.'},status=409)
    if not settings.current().entity('battery_soc',required=False):
        return web.json_response({'ok':False,'message':'Es fehlt: '+settings.label('battery_soc')+'.'},status=400)
    try:
        async with connection() as ha:done=await ha.install_card(dashboard_card.current_url())
    except Exception as exc:
        log.warning('Dashboard-Karte einrichten fehlgeschlagen (%s)',type(exc).__name__)
        return web.json_response({'ok':False,'message':'Einrichten fehlgeschlagen ('+type(exc).__name__+'). Die Dashboard-Ressourcen dürfen nicht im YAML-Modus sein.'},status=500)
    text={'created':'Die Karte ist als Dashboard-Ressource angelegt.','updated':'Die Karte ist aktualisiert.','unchanged':'Die Karte ist schon aktuell.'}[done['action']]
    return web.json_response({'ok':True,**done,'message':text+' Danach die Dashboard-Seite neu laden.'})

async def refresh_card():
    """Keep an installed card in step with this add-on version and its settings. Never installs it by itself."""
    if settings.operating_mode()!='publish' or not settings.current().entity('battery_soc',required=False):return
    try:
        async with connection() as ha:done=await ha.install_card(dashboard_card.current_url(),adopt_only=True)
        if done['action']=='updated':log.info('Dashboard-Karte aktualisiert')
    except Exception as exc:
        log.warning('Dashboard-Karte nicht aktualisiert (%s)',type(exc).__name__)

BACKGROUND=set()
def background(coro):
    task=asyncio.create_task(coro);BACKGROUND.add(task);task.add_done_callback(BACKGROUND.discard)

async def put_settings(request):
    data=await request.json()
    data.setdefault('adopt_legacy_helpers',settings.current().data.get('adopt_legacy_helpers',False))   # not editable in the UI
    data.setdefault('publish',settings.current().data.get('publish'))
    clean,errors=views.validate_settings(data)
    if errors:return web.json_response({'ok':False,'errors':errors},status=400)
    clean['planner']=settings.current().data.get('planner',{})   # developer overrides are not edited here
    settings.save(clean)
    background(refresh_card())     # the card carries the helper names and battery entities
    return web.json_response({'ok':True,'missing':settings.current().missing('plan')})

async def entities(request):
    role=request.query.get('role','')
    if role not in settings.ROLES and role!='price_entity':return web.json_response({'error':'unknown role'},status=400)
    try:
        async with connection() as ha:states=(await ha.call('ha_list_states'))['states']
    except Exception as exc:
        return web.json_response({'entities':[],'warning':'Home Assistant nicht erreichbar ('+type(exc).__name__+')'})
    return web.json_response({'entities':views.suggest(role,states,request.query.get('q',''))})

async def setup(request):
    """The setup checklist. The two Home Assistant questions (is a control automation using the marker, is it released) may stay open."""
    cfg=settings.current();plan=load_plan();found=released=None;config_api=None
    try:
        names=cfg.helpers()
        async with connection() as ha:
            related=await ha.call('ha_related',entity_id='input_boolean.'+names['owner'])
            found=bool(related.get('automation'))
            try:config_api=True;await ha.call('ha_control_automation')
            except Exception:config_api=False
            try:released=(await ha.call('ha_get_state',entity_id='input_boolean.'+names['permission'])).get('state')=='on'
            except Exception:released=False
    except Exception:pass
    steps=views.setup_steps(cfg.missing('plan'),plan,settings.operating_mode(),found,released)
    return web.json_response({'steps':[{'id':i,'label':l,'done':d,'go':g} for i,l,d,g in steps],'complete':all(d for _,_,d,_ in steps),
                              'automation_known':found is not None,'config_api':config_api})

async def autofill(request):
    """Proposals for empty entity roles from the Energy dashboard, device siblings and names. Nothing is saved."""
    try:
        async with connection() as ha:
            states=(await ha.call('ha_list_states'))['states']
            notes=[]
            try:registry=(await ha.call('ha_entity_registry'))['entities']
            except Exception:registry=[];notes.append('Die Geräteliste war nicht lesbar, Zähler an den Schaltern werden nicht gesucht.')
            try:prefs=(await ha.call('ha_manage_energy_prefs',mode='get')).get('config') or {}
            except Exception:prefs=None;notes.append('Das Energie-Dashboard war nicht lesbar.')
    except Exception as exc:
        return web.json_response({'proposals':{},'warning':'Home Assistant nicht erreichbar ('+type(exc).__name__+')'})
    return web.json_response({'proposals':views.autofill(states,registry,prefs,settings.current().data['entities']),'notes':notes,
                              'sources':{'registry':len(registry),'energy_dashboard':len(views.energy_dashboard_roles(prefs))}})

async def estimates(request):
    """Battery capacity and charger power estimated from the recorded statistics. Nothing is saved."""
    cfg=settings.current();now=datetime.now(TZ);start=(now-timedelta(days=28)).isoformat()
    out={};notes=[]
    try:
        async with connection() as ha:
            async def hourly(entity,kind):
                r=await ha.call('ha_get_history',source='statistics',entity_ids=entity,start_time=start,end_time=now.isoformat(),
                                period='hour',statistic_types=[kind],limit=1000)
                rows={float(x['start'])/1000:x.get(kind) for e in r['entities'] for x in e.get('statistics',[]) if x.get(kind) is not None}
                return rows,(r['entities'][0].get('unit_of_measurement') if r['entities'] else None)
            for role,key,pct in (('charger_energy','charge_kw',.9),):   # the inverter's output is limited by the house load, so it says nothing about its maximum
                entity=cfg.entity(role,required=False)
                if not entity:notes.append('Für '+settings.label(role)+' ist noch nichts eingetragen.');continue
                values,unit=await hourly(entity,'change')
                factor=.001 if unit=='Wh' else 1.     # kWh per hour is kW
                est=views.estimate_power([v*factor for v in values.values()],percentile=pct)
                if est is None:notes.append('Zu wenige Betriebsstunden für '+settings.label(role)+'.')
                else:out[key]=est
            kwh,soc=cfg.entity('battery_kwh',required=False),cfg.entity('battery_soc',required=False)
            if kwh and soc:
                (a,_),(b,_)=await hourly(kwh,'mean'),await hourly(soc,'mean')
                est=views.estimate_capacity([(a[t],b[t]) for t in a if t in b])
                if est is None:notes.append('Zu wenige Messwerte für die Kapazität.')
                else:out['capacity_kwh']=est
            else:notes.append('Für die Kapazität werden Akku-Inhalt (kWh) und Ladestand gebraucht.')
    except Exception as exc:
        return web.json_response({'estimates':{},'notes':['Abruf fehlgeschlagen ('+type(exc).__name__+').']})
    return web.json_response({'estimates':out,'notes':notes})

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
    app.router.add_get('/api/blueprint',blueprint);app.router.add_post('/api/control/setup',control_setup);app.router.add_get('/api/card',card);app.router.add_post('/api/card/setup',card_setup);app.router.add_get('/api/autofill',autofill);app.router.add_get('/api/setup',setup);app.router.add_get('/api/estimates',estimates)
    app.router.add_get('/api/settings',get_settings);app.router.add_put('/api/settings',put_settings)
    app.router.add_get('/api/entities',entities);app.router.add_get('/api/check',check);app.router.add_get('/api/prices/check',check_prices)
    async def start(app):
        app['task']=asyncio.create_task(app['scheduler'].loop())
        background(refresh_card())     # an add-on update brings a new card
    async def stop(app):app['task'].cancel()
    if os.environ.get('HAUSAKKU_NO_SCHEDULER')!='1':app.on_startup.append(start);app.on_cleanup.append(stop)
    return app

def main():
    logging.basicConfig(level=os.environ.get('HAUSAKKU_LOG_LEVEL','info').upper())
    paths.ensure()
    settings.migrate_publish()
    web.run_app(make_app(),host='0.0.0.0',port=8099)

if __name__=='__main__':main()
