import json,sys,urllib.request
from playwright.sync_api import sync_playwright
B=sys.argv[1]
U=lambda i,h,b:{"id":i,"email":h+"@e.com","password":"correct horse","display_name":h,"handle":h,"balance":b}
def reset(): urllib.request.urlopen(urllib.request.Request(B+"/_test/reset",data=json.dumps({"currency":"EUR","minor_units":2,"users":[U("u_ada","ada",100),U("u_bob","bob",0)],
  "requests":[{"id":"rq_1","requester_id":"u_bob","payer_id":"u_ada","amount":99999,"status":"pending"}]}).encode(),method="POST",headers={"Content-Type":"application/json"}))
T=lambda t:'[data-testid="%s"]'%t
JS="""(t)=>{const e=document.querySelector(`[data-testid="${t}"]`); if(!e) return null; const r=e.getBoundingClientRect(); const tb=document.querySelector('.tabbar');
 const tbr=tb&&getComputedStyle(tb).display!=='none'?tb.getBoundingClientRect():null; const top=tbr?tbr.top:innerHeight;
 return {top:Math.round(r.top),bottom:Math.round(r.bottom),visible_limit:Math.round(top),hidden_px:Math.max(0,Math.round(r.bottom-top)),fully_hidden:r.top>=top}}"""
with sync_playwright() as p:
    b=p.chromium.launch()
    for w,hgt in ((375,667),(390,844),(768,1024),(1280,800)):
        for form,steps,tid in (("pay",[("pay-handle","bob"),("pay-amount","500")],"pay-error"),("request",[("request-handle","zz"),("request-amount","1")],"request-error"),("authorize",[("authorize-handle","bob"),("authorize-amount","500")],"authorize-error")):
            reset(); pg=b.new_page(viewport={"width":w,"height":hgt})
            pg.goto(B+"/login"); pg.fill(T("login-email"),"ada@e.com"); pg.fill(T("login-password"),"correct horse"); pg.click(T("login-submit")); pg.wait_for_selector(T("wallet-available"))
            for f,v in steps: pg.fill(T(f),v)
            pg.click(T(form+"-submit")); pg.wait_for_selector(T(tid)); pg.wait_for_timeout(400)
            print(w,form,pg.evaluate(JS,tid)); pg.close()
        reset(); pg=b.new_page(viewport={"width":w,"height":hgt})
        pg.goto(B+"/login"); pg.fill(T("login-email"),"ada@e.com"); pg.fill(T("login-password"),"correct horse"); pg.click(T("login-submit")); pg.wait_for_selector(T("wallet-available"))
        pg.goto(B+"/requests"); pg.click(T("request-pay-rq_1")); pg.wait_for_selector(T("request-error")); pg.wait_for_timeout(400)
        print(w,"request-row pay",pg.evaluate(JS,"request-error")); pg.close()
    b.close()
