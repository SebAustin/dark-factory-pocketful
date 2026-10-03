import sys
from playwright.sync_api import sync_playwright
B=sys.argv[1]
with sync_playwright() as p:
    b=p.chromium.launch()
    for w in [int(x) for x in (sys.argv[2] if len(sys.argv)>2 else "375,390,768,1024,1280,1440").split(",")]:
        pg=b.new_page(viewport={"width":w,"height":900})
        pg.goto(B+"/login"); pg.fill('[data-testid=login-email]',"ada@example.com"); pg.fill('[data-testid=login-password]',"correct horse"); pg.click('[data-testid=login-submit]'); pg.wait_for_selector('[data-testid=wallet-available]')
        m=pg.evaluate("""()=>{const r=t=>document.querySelector(`[data-testid=${t}]`).getBoundingClientRect();
          const h=r('current-handle'),u=r('current-user'),l=r('logout-button');
          const chip=document.querySelector('[data-chip=balance]'); const c=chip?chip.getBoundingClientRect():null;
          const nav=[...document.querySelectorAll('.nav-main a')].map(a=>a.getBoundingClientRect());
          const lastNav=nav.length?nav[nav.length-1]:null;
          return {handle_right:Math.round(h.right),user_right:Math.round(u.right),logout_left:Math.round(l.left),
            overlap_handle_logout:Math.round(Math.max(h.right,u.right)-l.left),
            nav_chip_overlap: (lastNav&&c)? Math.round(lastNav.right-c.left):null,
            chip_user_overlap: c? Math.round(c.right-Math.min(h.left,u.left)):null}}""")
        print(w,m); pg.close()
    b.close()
