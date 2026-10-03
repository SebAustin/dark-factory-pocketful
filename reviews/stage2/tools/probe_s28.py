import json,urllib.request,sys
from datetime import datetime,timezone
S1,S2=sys.argv[1],sys.argv[2]
def call(base,m,p,b=None,t=None,k=None):
    h={"Content-Type":"application/json"}
    if t:h["Authorization"]="Bearer "+t
    if k:h["Idempotency-Key"]=k
    r=urllib.request.Request(base+p,data=None if b is None else json.dumps(b).encode(),method=m,headers=h)
    try:
        with urllib.request.urlopen(r,timeout=15) as x: d=x.read(); return x.status,(json.loads(d) if d else None)
    except urllib.error.HTTPError as e: return e.code,json.loads(e.read() or b"null")
U=lambda i,h,b,e=None:{"id":i,"email":e or h+"@e.com","password":"correct horse","display_name":h,"handle":h,"balance":b}
login=lambda base,e:call(base,"POST","/auth/login",{"email":e,"password":"correct horse"})[1]["token"]
# stage-1 source
call(S1,"POST","/_test/reset",{"currency":"EUR","minor_units":2,"users":[U("u_ada","ada",1000),U("u_bob","bob",0),U("u_cy","cy",0)],
  "requests":[{"id":"rq_1","requester_id":"u_bob","payer_id":"u_ada","amount":100,"status":"pending"}]})
t_src=login(S1,"ada@e.com")
pay=call(S1,"POST","/requests/rq_1/pay",{},t_src,"rp")
e1=call(S1,"GET","/_test/export")[1]
# stage-2 destination with sessions
call(S2,"POST","/_test/reset",{"currency":"EUR","minor_units":2,"users":[U("u_ada","ada",5,"ADA@e.com"),U("u_bob","bob",0,"other@e.com"),U("u_cy","cyx",0,"cy@e.com"),U("u_zed","zed",0)]})
d={h:login(S2,e) for h,e in (("ada","ADA@e.com"),("bob","other@e.com"),("cy","cy@e.com"),("zed","zed@e.com"))}
print("stage-1 import",call(S2,"POST","/_test/import",e1)[0])
print("dest tokens: ada same id/email(case)/handle ->",call(S2,"GET","/me",t=d["ada"])[0],"| bob other email ->",call(S2,"GET","/me",t=d["bob"])[0],
      "| cy other handle ->",call(S2,"GET","/me",t=d["cy"])[0],"| zed absent ->",call(S2,"GET","/me",t=d["zed"])[0])
print("source token ->",call(S2,"GET","/me",t=t_src)[0])
r=call(S2,"POST","/requests/rq_1/pay",{},t_src,"rp"); print("pre-upgrade request pay replay ->",r[0], r[1]==pay[1])
# stage-2 format import stays pure replacement
e2=call(S2,"GET","/_test/export")[1]
late=login(S2,"bob@e.com")
print("stage-2 import",call(S2,"POST","/_test/import",e2)[0],"later dest token ->",call(S2,"GET","/me",t=late)[0],"exported ada token ->",call(S2,"GET","/me",t=d["ada"])[0])
# ttl range
base={"currency":"EUR","minor_units":2,"users":[U("u_ada","ada",1000),U("u_bob","bob",0)]}
lim=int((datetime(9999,12,31,23,59,59,tzinfo=timezone.utc)-datetime.now(timezone.utc)).total_seconds())
for ttl in (1,10**9+1,lim-3600,lim+3600,10**12,10**30,"1e9",0):
    st=call(S2,"POST","/_test/reset",dict(base,authorization_ttl_seconds=ttl))[0]
    extra=""
    if st==204:
        t=login(S2,"ada@e.com"); a=call(S2,"POST","/authorizations",{"to_handle":"bob","amount":1},t,"h"); extra=(a[0],a[1].get("expires_at"))
    print("ttl",str(ttl)[:14],"->",st,extra)
e=call(S2,"GET","/_test/export")[1]; e["state"]["settings"]["authorization_ttl_seconds"]=10**12
print("import ttl 1e12 ->",call(S2,"POST","/_test/import",e)[0])
