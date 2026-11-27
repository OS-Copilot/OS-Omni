"""Recovered OpenDriver API contract from the installed debug APK.

Local replacement, not the original backend. All mutations are persisted and
logged; GET requests never manufacture the task's expected final outcomes.
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import json, threading, uuid, datetime, urllib.parse, re, sys

ROOT = Path(__file__).parent
sys.path.insert(0,str(ROOT.parent))
LOCK = threading.RLock()
SCENARIO = 'empty_workflow'
STATE_FILE = ROOT/'opendriver-backend-state.json'
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def ident(prefix): return prefix+'-'+uuid.uuid4().hex[:12]
def user(name,email,role):
    return dict(id=ident('user'),name=name,email=email,phone='',role=role,isVerified=True)
def profile(u):
    return dict(id=ident('driver'),userId=u['id'],user=u,licenseNumber='D-2048',vehicleMake='Toyota',vehicleModel='Camry',vehicleYear='2022',licensePlate='DRV-204',vehicleColor='Blue',verificationStatus='approved',driverStatus='offline',currentLatitude=37.4477,currentLongitude=-122.1619,averageRating=5,totalTrips=0,documents=[],documentSummary={})
def fresh():
    users=[user('Dana Driver','dash@example.com','driver'),user('Jordan Driver','jordan.driver26@example.com','driver'),user('Lucas Lin','lucas@example.com','rider'),user('Lin Rider','rider@example.com','rider')]
    state = dict(users=users,profiles={u['id']:profile(u) for u in users if u['role']=='driver'},tokens={},selectedUserId=users[0]['id'],rides=[],documents=[],tickets=[dict(id='ticket-payments',userId=users[0]['id'],category='Payments',message='Payment question',status='open',createdAt=now(),updatedAt=now(),replies=[])],payments=[dict(id='card-default',type='card',brand='Visa',last4='4242',label='Visa 4242',isDefault=False),dict(id='credits',type='wallet',brand='OpenDriver',last4='',label='OpenDriver credits',isDefault=True)],savedPlaces=[],coupons=[dict(id='safe10',code='SAFE10',title='Safety discount',discountPercent=10)],refunds=[],invoices=[],payouts=[],events=[])
    if SCENARIO == 'rider_full_service':
        rider=users[-1]
        rider['name']='Avery'
        for status in ('completed','scheduled'):
            state['rides'].append(dict(id='baseline-'+status,status=status,riderId=rider['id'],rider=rider,pickupAddress='Stanford University',pickupLatitude=37.4275,pickupLongitude=-122.1697,destinationAddress='University Avenue, Palo Alto, CA',destinationLatitude=37.4477,destinationLongitude=-122.1619,createdAt='2026-06-24T10:00:00Z',scheduledFor='2026-06-26T10:00:00' if status=='scheduled' else '',estimatedFare=16,finalFare=16 if status=='completed' else None,messages=[],timeline=[],waypoints=[]))
        for category in ('Payments','rider issue'):
            state['tickets'].append(dict(id=ident('baseline-ticket'),userId=rider['id'],category=category,message='Seed support record',status='open',createdAt=now(),updatedAt=now(),replies=[]))
    if SCENARIO == 'driver_workspace_support':
        state['rides'].append(dict(id='baseline-incoming-request',status='requested',riderId=users[-1]['id'],rider=users[-1],pickupAddress='University Avenue, Palo Alto, CA',pickupLatitude=37.4477,pickupLongitude=-122.1619,destinationAddress='Stanford University',destinationLatitude=37.4275,destinationLongitude=-122.1697,messages=[],timeline=[],estimatedFare=15))
    return state
STATE = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else fresh()
def persist(): STATE_FILE.write_text(json.dumps(STATE,indent=2),encoding='utf-8')
def place(label,lat,lon): return dict(id=label.lower().replace(' ','-'),cityId='sf_bay',address=label,latitude=lat,longitude=lon)
LOCATIONS=[place('University Avenue, Palo Alto, CA',37.4477,-122.1619),place('San Francisco International Airport',37.6213,-122.3790),place('Stanford University',37.4275,-122.1697),place('Mountain View Transit Center',37.3947,-122.076),place('Meta Headquarters',37.4848,-122.1484),place('San Jose International Airport',37.3639,-121.9289),place('Union Square, San Francisco',37.7879,-122.4075),place('Mission Dolores Park, San Francisco, CA',37.7596,-122.4269),place('San Jose Diridon Station',37.3297,-121.902)]
CITY=dict(id='sf_bay',name='San Francisco Bay Area',region='California',centerLatitude=37.4477,centerLongitude=-122.1619,radiusKm=100,currencyCode='USD',currencySymbol='$',currencyDecimals=2,locations=LOCATIONS)
def dispatch(method,path,body,token):
    global STATE, SCENARIO
    uid=STATE['tokens'].get(token,STATE['selectedUserId'])
    u=next((u for u in STATE['users'] if u['id']==uid),STATE['users'][0])
    p=STATE['profiles'].get(uid)
    if path=='/health': return {'status':'ready','replacement_backend':True}
    if path=='/route/driving': return {'points':[],'routingAvailable':False,'source':'No original road graph; APK uses its explicit geometric fallback'}
    if path=='/dev/reset' and method=='POST': STATE=fresh();return {'reset':True}
    if path=='/dev/scenario' and method=='POST':
        SCENARIO=body.get('scenario','empty_workflow');STATE=fresh();return {'scenario':SCENARIO,'reconstructed':True}
    if path=='/config/bootstrap': return {'serviceCities':[CITY],'locations':{x['id']:x for x in LOCATIONS}}
    if path in ('/auth/login','/auth/register') and method=='POST':
        email=body.get('email','');role=body.get('role','rider')
        found=next((x for x in STATE['users'] if x['email']==email and x['role']==role),None)
        if found is None:
            if path.endswith('/login'): raise ValueError('Unknown seeded account; use registration for a new account')
            found=user(body.get('name',''),email,role);STATE['users'].append(found)
            if role=='driver': STATE['profiles'][found['id']]=profile(found)
        key=uuid.uuid4().hex;STATE['tokens'][key]=found['id'];STATE['selectedUserId']=found['id']
        return {'token':key,'user':found,'driverProfile':STATE['profiles'].get(found['id'])}
    if path=='/auth/logout': STATE['tokens'].pop(token,None);return {'loggedOut':True}
    if path=='/users/me':
        if method=='PATCH': u.update({k:body[k] for k in ('name','phone') if k in body})
        return {'user':u,'driverProfile':p}
    if path=='/driver/profile':
        if method=='PATCH':
            if p is None: raise ValueError('Driver account required')
            p.update(body)
        return {'driverProfile':p}
    if path=='/driver/status':
        if p is None: raise ValueError('Driver account required')
        p['driverStatus']=body['driverStatus'];return {'driverProfile':p}
    if path=='/driver/documents':
        if method=='POST': STATE['documents'].append(dict(id=ident('document'),driverId=p['id'],userId=uid,status='pending',createdAt=now(),**body))
        docs=[x for x in STATE['documents'] if x['userId']==uid]
        return {'documents':docs,'documentSummary':{'total':len(docs)},'driverProfile':p}
    if path=='/driver/payouts':
        if method=='POST': STATE['payouts'].append(dict(id=ident('payout'),userId=uid,status='pending',createdAt=now(),**body))
        return {'payouts':[x for x in STATE['payouts'] if x['userId']==uid]}
    if path=='/driver/earnings': return {'earnings':{'today':0,'total':0,'availablePayout':0,'tripEarnings':0},'rides':[x for x in STATE['rides'] if x['status']=='completed']}
    if path=='/driver/incoming-ride' and method=='POST':
        r=dict(id=ident('ride'),status='requested',pickupAddress=LOCATIONS[0]['address'],pickupLatitude=37.4477,pickupLongitude=-122.1619,destinationAddress='Stanford University',destinationLatitude=37.4275,destinationLongitude=-122.1697,rider=next(x for x in STATE['users'] if x['role']=='rider'),messages=[],timeline=[],estimatedFare=15)
        STATE['rides'].append(r);return {'ride':r,'rides':[r]}
    if path=='/driver/incoming-rides': return {'rides':[x for x in STATE['rides'] if x['status']=='requested']}
    if path in ('/driver/active-ride','/rides/active'):
        # Incoming requests must remain in the Driver offer list until accepted.
        # Rider polling still includes its unaccepted request.
        statuses = ('accepted','arriving','arrived','in_progress') if path == '/driver/active-ride' else ('accepted','arriving','arrived','in_progress','requested')
        return {'ride':next((x for x in reversed(STATE['rides']) if x['status'] in statuses and not x.get('scheduledFor')),None)}
    if path=='/rides/scheduled': return {'rides':[x for x in STATE['rides'] if x.get('scheduledFor') and x['status']!='cancelled']}
    if path=='/rides/history': return {'rides':[x for x in STATE['rides'] if x['status'] in ('completed','cancelled')]}
    if path in ('/rides/estimate','/rides/request'):
        tier=body.get('rideTier','standard')
        tier_title={'standard':'RideX','plus':'RideXL','xl':'RideXL','comfort':'Comfort'}.get(tier,tier.title())
        fare=dict(baseFare=3,distanceFare=10,timeFare=2,serviceFee=1,surgeMultiplier=1,estimatedTotal=16,currencyCode='USD',currencySymbol='$',currencyDecimals=2,rideTier=tier,rideTierTitle=tier_title,promoCode=body.get('promoCode',''))
        if path.endswith('/estimate'): return {'fareBreakdown':fare,'rideOptions':[dict(id=k,title=title,estimatedTotal=v,currencySymbol='$',currencyCode='USD') for k,title,v in [('standard','RideX',16),('comfort','Comfort',20),('plus','RideXL',25)]]}
        payment_label=next((x['label'] for x in STATE['payments'] if x['id']==body.get('paymentMethod')),'')
        r=dict(id=ident('ride'),status='scheduled' if body.get('scheduledFor') else 'requested',riderId=uid,rider=u,messages=[],timeline=[],createdAt=now(),estimatedFare=16,fareBreakdown=fare,rideTierTitle=tier_title,paymentMethodLabel=payment_label,**body);STATE['rides'].append(r);return {'ride':r}
    parts=path.strip('/').split('/')
    if 'rides' in parts and len(parts)>=3:
        i=parts.index('rides');rid=parts[i+1];action=parts[i+2]
        r=next((x for x in STATE['rides'] if x['id']==rid),None)
        if r is None: raise ValueError('Unknown ride')
        if action in ('accept','reject','cancel','confirm-boarding','status'):
            r['status']=body.get('status',{'accept':'accepted','reject':'rejected','cancel':'cancelled','confirm-boarding':'in_progress'}.get(action,r['status']))
            r['timeline'].append(dict(status=r['status'],at=now(),label=r['status']))
            if p:
                r['driver']=u
                r['driverProfile']=p
        elif action=='messages': r['messages'].append(dict(id=ident('msg'),rideId=rid,senderId=uid,senderRole=u['role'],senderName=u['name'],body=body.get('message',''),createdAt=now()))
        elif action=='rating': r['rating']=body
        elif action=='waypoints': r['waypoints']=body.get('waypoints',[])
        return {'ride':r,'messages':r['messages']}
    if path=='/support/tickets':
        if method=='POST':
            t=dict(id=ident('ticket'),userId=uid,category=body.get('category','rider issue'),message=body.get('message',''),rideId=body.get('rideId',''),status='open',createdAt=now(),updatedAt=now(),replies=[]);STATE['tickets'].append(t)
            return {'ticket':t}
        return {'tickets':[x for x in STATE['tickets'] if x['userId']==uid]}
    if path.startswith('/support/tickets/') and path.endswith('/replies'):
        t=next(x for x in STATE['tickets'] if x['id']==parts[2]);t['replies'].append(dict(id=ident('reply'),ticketId=t['id'],userId=uid,userName=u['name'],role=u['role'],message=body.get('message',''),createdAt=now()));return {'ticket':t}
    collections={'/payments/methods':('payments','paymentMethods'),'/rider/saved-places':('savedPlaces','savedPlaces'),'/rider/coupons':('coupons','coupons'),'/payments/refunds':('refunds','refunds'),'/invoices':('invoices','invoices')}
    if path in collections:
        key,envelope=collections[path]
        if method=='POST': STATE[key].append(dict(id=ident(key),userId=uid,**body))
        return {envelope:STATE[key]}
    if path=='/payments/history': return {'payments':[]}
    for prefix,key,envelope in [('/payments/methods/','payments','paymentMethods'),('/rider/saved-places/','savedPlaces','savedPlaces')]:
        if path.startswith(prefix):
            item_id=path[len(prefix):].split('/')[0]
            if method=='DELETE': STATE[key]=[x for x in STATE[key] if x['id']!=item_id]
            elif path.endswith('/default') and method=='PATCH':
                for item in STATE[key]: item['isDefault']=item['id']==item_id
            return {envelope:STATE[key]}
    if path=='/notifications': return {'notifications':[]}
    if path=='/promos/validate':
        valid=body.get('code','').upper()=='SAFE10'
        return {'valid':valid,'coupon':{'code':'SAFE10','title':'Safety discount','discountPercent':10} if valid else None}
    raise KeyError('Unimplemented endpoint: '+method+' '+path)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_OPTIONS(self): self.send_response(204);self.headers_out();self.end_headers()
    def headers_out(self):
        self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Headers','Content-Type,Authorization');self.send_header('Access-Control-Allow-Methods','GET,POST,PATCH,DELETE,OPTIONS')
    def handle_request(self):
        path=urllib.parse.urlparse(self.path).path
        tile_match=re.fullmatch(r'/map/tiles/(\d+)/(\d+)/(\d+)(?:@2x)?\.png',path)
        if self.command=='GET' and tile_match:
            from local_eval.driver_map import render_tile
            zoom,x,y=map(int,tile_match.groups())
            if not (0<=zoom<=22 and 0<=x<2**zoom and 0<=y<2**zoom):
                self.send_error(400,'Invalid map tile coordinates');return
            encoded=render_tile(zoom,x,y,LOCATIONS)
            self.send_response(200);self.headers_out();self.send_header('Content-Type','image/png');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded);return
        body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or b'{}')
        token=self.headers.get('Authorization','').removeprefix('Bearer ')
        with LOCK:
            try:
                data=dispatch(self.command,path,body,token);code=200;response={'success':True,'data':data}
                if self.command!='GET': STATE['events'].append(dict(method=self.command,path=path,body=body,at=now()));persist()
            except (ValueError,KeyError,StopIteration) as e: code=400;response={'success':False,'error':{'code':'REQUEST_FAILED','message':str(e)}}
            with (ROOT/'opendriver-http.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps(dict(method=self.command,path=path,status=code,at=now()))+'\n')
        encoded=json.dumps(response).encode();self.send_response(code);self.headers_out();self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
    do_GET=do_POST=do_PATCH=do_DELETE=handle_request

if __name__=='__main__':
    persist();print('OpenDriver replacement backend: http://127.0.0.1:4321',flush=True)
    ThreadingHTTPServer(('127.0.0.1',4321),Handler).serve_forever()
