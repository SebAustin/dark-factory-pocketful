import json,sys,time,urllib.request
from datetime import datetime,timedelta,timezone
from decimal import Decimal
B=sys.argv[1]
def call(m,p,b=None,t=None,k=None):
    h={"Content-Type":"application/json"}
    if t:h["Authorization"]="Bearer "+t
    if k:h["Idempotency-Key"]=k
    r=urllib.request.Request(B+p,data=None if b is None else json.dumps(b).encode(),method=m,headers=h)
    try:
        with urllib.request.urlopen(r,timeout=15) as x: d=x.read(); return x.status,(json.loads(d) if d else None)
    except urllib.error.HTTPError as e: return e.code,json.loads(e.read() or b"null")
U=lambda i,h,b:{"id":i,"email":h+"@e.com","password":"correct horse","display_name":h,"handle":h,"balance":b}
ts=lambda s,off="+00:00": (datetime.now(timezone(timedelta(hours=int(off[:3])))) + timedelta(seconds=s)).isoformat()
P=lambda i,f,t,a,ca=None: dict({"id":i,"from_user_id":f,"to_user_id":t,"amount":a},**({"created_at":ca} if ca else {}))
key=lambda s: datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
fx={"currency":"EUR","minor_units":2,"users":[U("u_a","a",1000),U("u_b","b",500),U("u_op","op",0)],"settlement_operator_ids":["u_op"],
    "payments":[P("p_old","u_a","u_b",300,ts(-7200,"+05:30")),P("p_mid","u_b","u_a",100,ts(-3600,"-04:00")),P("p_now","u_a","u_b",50)]}
t0=time.time()
print("reset",call("POST","/_test/reset",fx)[0])
T={h:call("POST","/auth/login",{"email":h+"@e.com","password":"correct horse"})[1]["token"] for h in ("a","b","op")}
print("balances kept",[call("GET","/me",t=T[h])[1]["balance"] for h in ("a","b")])
ex=call("GET","/_test/export")[1]["state"]
pn=ex["payments"]["p_now"]; print("omitted created_at ~ reset time:", abs(key(pn["created_at"])-t0)<5, pn["created_at"])
print("rev1 of p_old:",ex["payments"]["p_old"].get("revisions"))
c=[call("POST","/payments",{"to_handle":"b","amount":1},T["a"],"k%d"%i)[1]["created_at"] for i in range(5)]
print("api created_at:",c[0], "µs digits", len(c[0].split(".")[1].split("+")[0]) if "." in c[0] else 0, "strictly increasing", all(key(x)<key(y) for x,y in zip(c,c[1:])), "after seeded", key(c[0])>key(pn["created_at"]))
st=call("POST","/settlements",{"transfers":[{"from_handle":"a","to_handle":"op","amount":5},{"from_handle":"op","to_handle":"b","amount":5}]},T["op"],"st")[1]
ex=call("GET","/_test/export")[1]["state"]
mem=[ex["payments"][m["payment_id"]]["revisions"][0] for m in st["payments"]]
print("settlement members rev1 = committed_at:", all(r["effective_at"]==r["recorded_at"]==st["committed_at"] for r in mem))
before=call("GET","/_test/export")[1]
bad={"future created_at":dict(fx,payments=[P("p_f","u_a","u_b",1,ts(3600))]),
     "negative opening (a sends more than it ends with + ...)":dict(fx,users=[U("u_a","a",0),U("u_b","b",1500),U("u_op","op",0)],payments=[P("p_x","u_b","u_a",10,ts(-100)),P("p_y","u_a","u_b",20,ts(-50))])}
for n,f in bad.items(): print(n,call("POST","/_test/reset",f)[0], "unchanged",call("GET","/_test/export")[1]==before)
# holds closed_at
fx2={"currency":"EUR","minor_units":2,"users":[U("u_a","a",1000),U("u_b","b",0)],"authorization_ttl_seconds":2}
call("POST","/_test/reset",fx2); T={h:call("POST","/auth/login",{"email":h+"@e.com","password":"correct horse"})[1]["token"] for h in ("a","b")}
A=lambda k:call("POST","/authorizations",{"to_handle":"b","amount":100},T["a"],k)[1]
a1,a2,a3,a4=A("1"),A("2"),A("3"),A("4")
print("open closed_at:",a1.get("closed_at","MISSING"))
cp=call("POST","/authorizations/%s/capture"%a1["authorization_id"],{"amount":40},T["b"],"c")[1]
nf=call("POST","/authorizations/%s/capture"%a2["authorization_id"],{"amount":40,"final":False},T["b"],"c2")[1]
v=call("POST","/authorizations/%s/void"%a3["authorization_id"],None,T["a"])[1]
time.sleep(3)
L={x["authorization_id"]:x for x in call("GET","/authorizations",t=T["a"])[1]["authorizations"]}
print("captured closed_at == capture created_at:", L[a1["authorization_id"]]["closed_at"]==cp["created_at"])
print("voided closed_at set:", v.get("closed_at") is not None, "expired closed_at == expires_at:", L[a4["authorization_id"]]["closed_at"]==L[a4["authorization_id"]]["expires_at"], L[a4["authorization_id"]]["status"])
print("nonfinal then expired: status",L[a2["authorization_id"]]["status"],"closed_at==expires_at",L[a2["authorization_id"]]["closed_at"]==L[a2["authorization_id"]]["expires_at"], "held now", call("GET","/me",t=T["a"])[1]["held"])
