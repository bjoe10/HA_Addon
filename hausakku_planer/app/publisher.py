"""Publish only own helpers, invalidate before writing and verify before commit.
Raw schedules must NEVER be wired without expiry/date guards.
"""
from datetime import datetime
from ha_client import connection
import settings
from collector import body
DAYS=('monday','tuesday','wednesday','thursday','friday','saturday','sunday')

def seconds(t):
    parts=t.split(':');v=int(parts[0])*3600+int(parts[1])*60+(float(parts[2]) if len(parts)>2 else 0)
    return 86400. if abs(v-86400)<.001 else v

def normalize_week(week):
    return {d:[{'from':seconds(x['from']),'to':seconds(x['to']),'data':x.get('data',{})} for x in week.get(d,[])] for d in DAYS}

def validate_schedule_pair(charge,serve):
    for week in (charge,serve):
        if set(week)!=set(DAYS):raise ValueError('All seven weekdays must be explicit')
        for day,windows in week.items():
            end=-1
            for w in windows:
                start,finish=seconds(w['from']),seconds(w['to'])
                if not 0<=start<finish<=86400 or start<end:raise ValueError('Invalid or overlapping schedule window')
                date=w.get('data',{}).get('plan_date')
                if not date or DAYS[datetime.fromisoformat(date).weekday()]!=day:raise ValueError('Date-bound schedule required')
                end=finish
    for d in DAYS:
        for a in charge[d]:
            for b in serve[d]:
                if max(seconds(a['from']),seconds(b['from']))<min(seconds(a['to']),seconds(b['to'])):
                    raise ValueError('Charge and serve overlap')

async def expire(ha):
    EXPIRY='input_datetime.'+settings.current().helpers()['expiry']
    await ha.call('ha_call_service',domain='input_datetime',service='set_datetime',entity_id=EXPIRY,data={'datetime':'2000-01-01 00:00:00'},wait=False)
    state=body(await ha.call('ha_get_state',entity_id=EXPIRY))
    if state.get('state')!='2000-01-01 00:00:00':raise RuntimeError('Failed to invalidate old plan')

async def publish(charge,serve,valid_until,target_soc,status):
    validate_schedule_pair(charge,serve)
    names=settings.current().helpers()
    EXPIRY='input_datetime.'+names['expiry'];TARGET='input_number.'+names['target'];STATUS='input_text.'+names['status']
    async with connection() as ha:
        await ha.ensure_own_helpers()
        await expire(ha)
        for helper,week in [(names['charge'],charge),(names['serve'],serve)]:
            await ha.call('ha_config_set_helper',helper_type='schedule',helper_id=helper,action='update',config=week)
        listed=await ha.call('ha_config_list_helpers',helper_type='schedule',limit=500)
        if listed.get('has_more'):raise RuntimeError('Schedule readback truncated')
        lookup={h['id']:h for h in listed['helpers']}
        for helper,expected in [(names['charge'],charge),(names['serve'],serve)]:
            if helper not in lookup or normalize_week(lookup[helper])!=normalize_week(expected):
                raise RuntimeError('Schedule readback mismatch: '+helper)
        await ha.call('ha_call_service',domain='input_number',service='set_value',entity_id=TARGET,data={'value':int(target_soc)},wait=False)
        await ha.call('ha_call_service',domain='input_text',service='set_value',entity_id=STATUS,data={'value':status[:255]},wait=False)
        state=body(await ha.call('ha_get_state',entity_id=[TARGET,STATUS]))['states']
        if float(state[TARGET]['state'])!=int(target_soc) or state[STATUS]['state']!=status[:255]:
            raise RuntimeError('Plan metadata readback mismatch')
        until=valid_until.strftime('%Y-%m-%d %H:%M:%S')
        await ha.call('ha_call_service',domain='input_datetime',service='set_datetime',entity_id=EXPIRY,data={'datetime':until},wait=False)
        state=body(await ha.call('ha_get_state',entity_id=EXPIRY))
        if state['state']!=until:raise RuntimeError('Plan expiry readback mismatch')
        return {'verified':True,'valid_until':valid_until.isoformat(),'helpers':['schedule.'+names['charge'],'schedule.'+names['serve']]}


async def publish_ev_window(week):
    """Write the vehicle window to the user's display helper and read it back. Nothing reacts to it."""
    EV_HELPER=settings.current().entity('ev_window_helper')
    if set(week)!=set(DAYS):raise ValueError('All seven weekdays must be explicit')
    for windows in week.values():
        end=-1
        for w in windows:
            a,b=seconds(w['from']),seconds(w['to'])
            if not 0<=a<b<=86400 or a<end:raise ValueError('Invalid or overlapping EV window')
            end=b
    async with connection() as ha:
        await ha.call('ha_config_set_helper',helper_type='schedule',helper_id=EV_HELPER,action='update',config=week)
        listed=await ha.call('ha_config_list_helpers',helper_type='schedule',limit=500)
        if listed.get('has_more'):raise RuntimeError('Schedule readback truncated')
        lookup={h['id']:h for h in listed['helpers']}
        if EV_HELPER not in lookup or normalize_week(lookup[EV_HELPER])!=normalize_week(week):
            raise RuntimeError('EV window readback mismatch')
        return {'verified':True,'helper':'schedule.'+EV_HELPER}
