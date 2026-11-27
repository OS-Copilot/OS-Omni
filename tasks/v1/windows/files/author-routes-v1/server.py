"""Offline author route planner; synthetic map, persisted route history."""
import json,os
from pathlib import Path
from flask import Flask,request,jsonify
app=Flask(__name__);state=Path(os.environ['AUTHOR_ROUTE_STATE'])
PLACES=['Current location','Mountain View Transit Center','Stanford University','Googleplex','Meta Headquarters']
HTML='''<!doctype html><title>Author Route Planner</title><style>body{font:20px Arial;margin:40px;background:#eef3f8}label{display:block;margin:20px}select,input,button{font-size:22px;padding:12px}main{display:flex;gap:50px}svg{background:white;border:2px solid #456}li{margin:10px}</style><h1>Author Route Planner</h1><p>Offline benchmark map. Plan routes in order; history is retained.</p><main><form id=f><label>Origin <select id=origin></select></label><label>Destination <select id=destination></select></label><label>Mode <select id=mode><option>Driving</option><option>Walking</option></select></label><label>Departure <input id=departure value="Leave now"></label><button>Generate route</button></form><section><svg width=600 height=350><circle cx=80 cy=90 r=12 fill=blue/><circle cx=270 cy=60 r=12 fill=green/><circle cx=500 cy=110 r=12 fill=orange/><circle cx=200 cy=260 r=12 fill=purple/><circle cx=470 cy=270 r=12 fill=red/><path d="M80 90L270 60L500 110L470 270L200 260Z" fill=none stroke=#999 stroke-width=3/><text x=40 y=140>Transit</text><text x=200 y=40>Stanford</text><text x=420 y=80>Googleplex</text><text x=400 y=310>Meta</text></svg><h2 id=current>No route generated</h2></section></main><h2>Route history</h2><ol id=history></ol><script>const places=PLACES;for(const id of ['origin','destination'])for(const p of places)document.getElementById(id).add(new Option(p,p));async function refresh(){const s=await(await fetch('/state')).json();document.getElementById("history").innerHTML='';for(const r of s.routes){const li=document.createElement('li');li.textContent=`${r.origin} → ${r.destination}, ${r.mode}, ${r.departure}`;document.getElementById('history').append(li)}if(s.routes.length){const r=s.routes.at(-1);current.textContent=`${r.mode}: ${r.origin} → ${r.destination} (${r.departure})`}}f.onsubmit=async e=>{e.preventDefault();await fetch('/route',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(['origin','destination','mode','departure'].map(k=>[k,document.getElementById(k).value])))});refresh()};refresh()</script>'''
@app.get('/')
def index():return HTML.replace('PLACES',json.dumps(PLACES))
@app.get('/state')
def get_state():return jsonify(json.loads(state.read_text()) if state.exists() else {'routes':[]})
@app.post('/route')
def route():
 r=request.get_json();assert r['origin'] in PLACES and r['destination'] in PLACES and r['mode'] in ['Driving','Walking']
 s=json.loads(state.read_text()) if state.exists() else {'routes':[]};s['routes'].append({k:r[k] for k in ['origin','destination','mode','departure']});state.write_text(json.dumps(s));return jsonify(ok=True)
if __name__=='__main__':app.run(host='127.0.0.1',port=4388)
