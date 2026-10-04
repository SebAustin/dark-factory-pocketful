import json,sys,urllib.request,uuid
from datetime import datetime,timedelta,timezone
B=sys.argv[1]
def call(m,p,b=None,t=None,k=None):
    h={"Content-Type":"application/json"}
    if t:h["Authorization"]="Bearer "+t
    if k:h["Idempotency-Key"]=k
    r=urllib.request.Request(B+p,data=None if b is None else json.dumps(b).encode(),method=m,headers=h)
    try:
        with urllib.request.urlopen(r,timeout=15) as x: d=x.read(); return x.status,(json.loads(d) if d else None)
    except urllib.error.HTTPError as e: return e.code,json.loads(e.read() or b"null")
c=lambda r:(r[0],(r[1] or {}).get("error",{}).get("code")) if r[0]>=400 else r[0]
U=lambda i,h,b:{"id":i,"email":h+"@e.com","password":"correct horse","display_name":h,"handle":h,"balance":b}
K=lambda:uuid.uuid4().hex; ago=lambda s:(datetime.now(timezone.utc)-timedelta(seconds=s)).isoformat()
call("POST","/_test/reset",{"currency":"EUR","minor_units":2,"settlement_operator_ids":["u_op"],"users":[U("u_a","a",1000),U("u_b","b",0),U("u_op","op",0)]})
T={h:call("POST","/auth/login",{"email":h+"@e.com","password":"correct horse"})[1]["token"] for h in ("a","b","op")}
p1=call("POST","/payments",{"to_handle":"b","amount":400},T["a"],K())[1]   # b 400
p2=call("POST","/payments",{"to_handle":"a","amount":300},T["b"],K())[1]   # b 100, a 900
it=lambda p,amt,rev=1,eff=None:{"payment_id":p["payment_id"],"expected_revision":rev,"amount":amt,"effective_at":eff or ago(0.5),"reason":"b","extra":1}
B_=lambda items,t="op",k=None:call("POST","/correction-batches",{"corrections":items,"unknown":True},T[t],k or K())
print("non-operator 403:",c(B_([it(p1,1)],"a")),"no token:",c(call("POST","/correction-batches",{"corrections":[]},None,K())),"no key:",c(call("POST","/correction-batches",{"corrections":[it(p1,1)]},T["op"])))
# combined affordability: reducing p1 to 0 debits b 400 (b has 100) -> alone insufficient; with p2 to 0 (credits b 300) still short 0?  b: 100 -400 +300 = 0 -> ok together
print("alone (p1->0):",c(B_([it(p1,0)])))
st,snap=call("GET","/statement?limit=200",t=T["b"]); feed0=call("GET","/activity",t=T["a"])[1]
k=K(); r=B_([it(p1,0),it(p2,0)],k=k); print("together:",c(r))
print("replay 200 identical:",B_([it(p1,0),it(p2,0)],k=k)==(200,r[1]) if False else "n/a (effective_at regenerated)")
print("snapshot unchanged:",call("GET","/statement?snapshot=%s&limit=200"%snap["snapshot"],t=T["b"])[1]["entries"]==snap["entries"], "activity unchanged:",call("GET","/activity",t=T["a"])[1]==feed0)
revs=call("GET","/payments/%s/revisions"%p1["payment_id"],t=T["a"])[1]["revisions"]; print("revision exposes batch id:",revs[-1].get("correction_batch_id")==r[1]["correction_batch_id"], "single rev1 batch id null:", revs[0].get("correction_batch_id","MISSING") is None)
print("balances:",[call("GET","/me",t=T[h])[1]["total"] for h in ("a","b")])
# precedence: item error later in input vs settlement incompleteness earlier
