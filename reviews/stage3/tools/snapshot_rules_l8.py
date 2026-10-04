import json,sys,urllib.request
from datetime import datetime,timedelta,timezone
B=sys.argv[1]
def call(m,p,b=None,t=None,k=None,raw=None):
    h={"Content-Type":"application/json"}
    if t:h["Authorization"]="Bearer "+t
    if k:h["Idempotency-Key"]=k
    r=urllib.request.Request(B+p,data=raw if raw is not None else (None if b is None else json.dumps(b).encode()),method=m,headers=h)
    try:
        with urllib.request.urlopen(r,timeout=30) as x: d=x.read(); return x.status,(json.loads(d) if d else None)
    except urllib.error.HTTPError as e: return e.code,json.loads(e.read() or b"null")
U=lambda i,h,b:{"id":i,"email":h+"@e.com","password":"correct horse","display_name":h,"handle":h,"balance":b}
call("POST","/_test/reset",{"currency":"EUR","minor_units":2,"users":[U("u_a","a",5000),U("u_b","b",5000)]})
T={h:call("POST","/auth/login",{"email":h+"@e.com","password":"correct horse"})[1]["token"] for h in "ab"}
ps=[call("POST","/payments",{"to_handle":"b","amount":10+i},T["a"],"p%d"%i)[1] for i in range(12)]
mid=ps[6]["created_at"]
s,full=call("GET","/statement?limit=200&to="+urllib.request.quote(mid,safe=""),t=T["a"]); snap=full["snapshot"]
page=lambda: call("GET","/statement?snapshot=%s&limit=200"%snap,t=T["a"])
# backdated correction that moves a later payment into the window, and one that changes an in-window amount
early=(datetime.fromisoformat(ps[0]["created_at"])-timedelta(seconds=1)).isoformat()
print("corr move-in", call("POST","/payments/%s/corrections"%ps[10]["payment_id"],{"expected_revision":1,"amount":5,"effective_at":early,"reason":"move in"},T["a"],"c1")[0],
      "corr change", call("POST","/payments/%s/corrections"%ps[2]["payment_id"],{"expected_revision":1,"amount":0,"effective_at":ps[2]["created_at"],"reason":"zero"},T["a"],"c2")[0])
print("snapshot unchanged after backdated corrections:", page()[1]==full)
fresh=call("GET","/statement?limit=200&to="+urllib.request.quote(mid,safe=""),t=T["a"])[1]
print("fresh read differs (moved-in entry, zero delta):", len(fresh["entries"])==len(full["entries"])+1, any(e["delta"]==0 for e in fresh["entries"]))
e=call("GET","/_test/export")[1]; print("snapshots not in export:", "snapshots" not in e["state"] or not e["state"]["snapshots"], "size", len(json.dumps(e)))
print("import (no reset) ->", call("POST","/_test/import",e)[0])
call("POST","/payments",{"to_handle":"b","amount":1},T["a"],"after-import")
print("pre-import token pages identically after import + new payment:", page()[1]==full)
call("POST","/_test/reset",{"currency":"EUR","minor_units":2,"users":[U("u_z","z",1)]}); print("import after reset", call("POST","/_test/import",e)[0])
print("token after reset (+import) -> 404:", page()[0])
