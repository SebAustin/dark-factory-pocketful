import json,sys,urllib.request
from datetime import datetime,timedelta,timezone
from playwright.sync_api import sync_playwright
B=sys.argv[1]
U=lambda i,h,b:{"id":i,"email":h+"@e.com","password":"correct horse","display_name":h,"handle":h,"balance":b}
exp=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
def reset(): urllib.request.urlopen(urllib.request.Request(B+"/_test/reset",data=json.dumps({"currency":"EUR","minor_units":2,"users":[U("u_ada","ada",10000),U("u_bob","bob",5000)],
  "authorizations":[{"id":"a_1","from_user_id":"u_bob","to_user_id":"u_ada","amount":500,"status":"open","expires_at":exp}]}).encode(),method="POST",headers={"Content-Type":"application/json"}))
T=lambda t:'[data-testid="%s"]'%t
JS="""(t)=>{const e=document.querySelector(`[data-testid="${t}"]`); if(!e) return 'missing'; const r=e.getBoundingClientRect(); const tb=document.querySelector('.tabbar'); const hd=document.querySelector('.app-header');
 const lim=tb&&getComputedStyle(tb).display!=='none'?tb.getBoundingClientRect().top:innerHeight; const top=hd?hd.getBoundingClientRect().bottom:0;
 return (r.bottom<=lim+0.5 && r.top>=top-0.5)?'ok':`HIDDEN top=${Math.round(r.top)} bottom=${Math.round(r.bottom)} bar=${Math.round(lim)} header=${Math.round(top)}`}"""
cases=[("/","pay",[("pay-handle","bob"),("pay-amount","999999")],"pay-error",None),
       ("/","pay-ok",[("pay-handle","bob"),("pay-amount","1")],"pay-success","pay-submit"),
       ("/","pay-unc",[("pay-handle","bob"),("pay-amount","2")],"pay-uncertain","pay-submit"),
       ("/","request",[("request-handle","zz"),("request-amount","1")],"request-error",None),
       ("/","authorize",[("authorize-handle","bob"),("authorize-amount","999999")],"authorize-error",None),
       ("/","authorize-ok",[("authorize-handle","bob"),("authorize-amount","1")],"authorize-success","authorize-submit"),
       ("/split","split",[("split-amount","10"),("split-handles","bob,nobody")],"split-error",None),
       ("/split","split-ok",[("split-amount","10"),("split-handles","bob")],"split-success","split-submit"),
       ("/authorizations","capture",[("authorization-capture-amount-a_1","99")],"authorization-error","authorization-capture-a_1"),
       ("/authorizations","capture-ok",[("authorization-capture-amount-a_1","1")],"authorization-captured","authorization-capture-a_1")]
bad=0;n=0
with sync_playwright() as p:
    b=p.chromium.launch()
    for w,hgt in ((360,640),(375,667),(390,844),(412,915),(430,932),(768,1024),(900,600),(999,700),(1280,800)):
        for route,name,steps,tid,btn in cases:
            reset(); pg=b.new_page(viewport={"width":w,"height":hgt})
            pg.goto(B+"/login"); pg.fill(T("login-email"),"ada@e.com"); pg.fill(T("login-password"),"correct horse"); pg.click(T("login-submit")); pg.wait_for_selector(T("wallet-available"))
            if route!="/": pg.goto(B+route); pg.wait_for_load_state("networkidle")
            if name=="pay-unc": pg.route("**/payments",lambda r:r.abort())
            for f,v in steps: pg.fill(T(f),v)
            sub=btn or (name.split("-")[0]+"-submit")
            if name=="capture" or name=="capture-ok": sub="authorization-capture-a_1"
            pg.click(T(sub)); pg.wait_for_selector(T(tid)); pg.wait_for_timeout(500)
            res=pg.evaluate(JS,tid); n+=1
            if res!='ok': bad+=1; print(w,hgt,name,res)
            pg.close()
    b.close()
print("checked",n,"hidden",bad)
