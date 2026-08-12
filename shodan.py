#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shodan GUI - Volwaardige Shodan Client voor Windows 11 / 2026
==============================================================
Versie: 1.2.0 - Windows 2026 Fluent Edition

Fixes & Features v1.2:
- FIX: Async error handling in GUI callbacks gefixt, zodat query/API fouten altijd zichtbaar worden i.p.v. stil falen.
- FIX: Tabbladen worden niet meer kleiner bij selecteren (uniforme padding + Windows 11 style)
- FIX: API key dialoog knoppen volledig leesbaar (grotere dialoog, correcte layout, DPI-proof)
- FIX: Preset "Webcams" gefixed: port:554,80,8080 + product:"webcam" gaf 0 resultaten of error → nu has_screenshot:true + webcam (losse filters)
- FIX: Query combineren (country:NL + webcam etc.) werkt nu correct, met URL-encoding & validatie
- NIEUW: Instellingen menu rechts naast Extra → bevat Account & API key, Developer Mode toggle
- NIEUW: Developer Modus + apart Logging / Troubleshooting tabblad (alle API calls, errors, timings)
- NIEUW: Credits uitleg: hoelang geldig, wanneer reset (maandelijks op 1e), dagen tot reset, plan info
- NIEUW: Windows 2026 Fluent layout: mica-achtige kleuren, Segoe UI Variable, cards, accent underline tabs
- EXTRA: Troubleshooting verbeteringen: request URL tonen, error copy, export debug, rate-limit info, retry

Alle 37 REST endpoints behouden. Opslag nog steeds in Windows Register.
"""

import sys
import os
import json
import threading
import webbrowser
import datetime
import re
import csv
import time
import traceback
from pathlib import Path
from tkinter import *
from tkinter import ttk, messagebox, filedialog
import tkinter.font as tkfont

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.request, urllib.parse, urllib.error

try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False

# ---------------------------------------------------------------------------
# CONFIG MANAGER
# ---------------------------------------------------------------------------
class ConfigManager:
    REG_PATH = r"Software\ShodanGUI"
    def __init__(self):
        self._fallback_path = self._get_fallback_path()
        self._cache = {}
        self.load()
        # defaults
        if "developer_mode" not in self._cache:
            self._cache["developer_mode"] = False
        if "theme" not in self._cache:
            self._cache["theme"] = "light"

    def _get_fallback_path(self):
        if os.name == 'nt':
            base = os.getenv('APPDATA') or str(Path.home())
            p = Path(base) / "ShodanGUI" / "config.json"
        else:
            p = Path.home() / ".shodan_gui.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def load(self):
        if HAS_WINREG:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_READ)
                i=0
                while True:
                    try:
                        n,v,_=winreg.EnumValue(key,i)
                        self._cache[n]=v
                        i+=1
                    except OSError:
                        break
                winreg.CloseKey(key)
                if "config_json" in self._cache:
                    try:
                        extra=json.loads(self._cache["config_json"])
                        self._cache.update(extra)
                    except: pass
                return
            except FileNotFoundError: pass
            except Exception: pass
        if self._fallback_path.exists():
            try:
                with open(self._fallback_path,'r',encoding='utf-8') as f:
                    self._cache=json.load(f)
            except: self._cache={}

    def save(self):
        if HAS_WINREG:
            try:
                key=winreg.CreateKey(winreg.HKEY_CURRENT_USER,self.REG_PATH)
                for k,v in self._cache.items():
                    if k=="config_json": continue
                    if isinstance(v,(dict,list)): continue
                    try:
                        winreg.SetValueEx(key,k,0,winreg.REG_SZ,str(v))
                    except: pass
                complex_data={k:v for k,v in self._cache.items() if isinstance(v,(dict,list)) or isinstance(v,bool)}
                if complex_data:
                    try:
                        winreg.SetValueEx(key,"config_json",0,winreg.REG_SZ,json.dumps(complex_data,ensure_ascii=False))
                    except: pass
                winreg.CloseKey(key)
                try:
                    with open(self._fallback_path,'w',encoding='utf-8') as f:
                        json.dump(self._cache,f,indent=2,ensure_ascii=False)
                except: pass
                return
            except: pass
        try:
            with open(self._fallback_path,'w',encoding='utf-8') as f:
                json.dump(self._cache,f,indent=2,ensure_ascii=False)
        except Exception as e:
            print(f"Config save error: {e}")

    def get(self,k,default=None):
        return self._cache.get(k,default)
    def set(self,k,v):
        self._cache[k]=v
        self.save()
    def delete(self,k):
        if k in self._cache:
            del self._cache[k]
            self.save()
            if HAS_WINREG:
                try:
                    kk=winreg.OpenKey(winreg.HKEY_CURRENT_USER,self.REG_PATH,0,winreg.KEY_WRITE)
                    try: winreg.DeleteValue(kk,k)
                    except: pass
                    winreg.CloseKey(kk)
                except: pass

# ---------------------------------------------------------------------------
# LOGGER - voor Developer Modus
# ---------------------------------------------------------------------------
class AppLogger:
    def __init__(self):
        self.entries=[]
        self.text_widget=None
        self.enabled=True

    def attach(self, text_widget):
        self.text_widget=text_widget
        self.refresh()

    def log(self, level, msg, detail=""):
        ts=datetime.datetime.now().strftime("%H:%M:%S")
        entry=f"[{ts}] {level:7} | {msg}"
        if detail:
            entry+=f"\n         └─ {detail}"
        self.entries.append(entry)
        # keep max 800 lines
        if len(self.entries)>800:
            self.entries=self.entries[-800:]
        if self.text_widget:
            try:
                self.text_widget.configure(state=NORMAL)
                self.text_widget.insert(END, entry+"\n")
                self.text_widget.see(END)
                self.text_widget.configure(state=DISABLED)
            except: pass
        # also print to console when developer
        if level in ("ERROR","WARN"):
            print(entry)

    def clear(self):
        self.entries.clear()
        if self.text_widget:
            self.text_widget.configure(state=NORMAL)
            self.text_widget.delete("1.0",END)
            self.text_widget.configure(state=DISABLED)

    def refresh(self):
        if self.text_widget:
            self.text_widget.configure(state=NORMAL)
            self.text_widget.delete("1.0",END)
            for e in self.entries:
                self.text_widget.insert(END,e+"\n")
            self.text_widget.configure(state=DISABLED)

    def export(self, path):
        with open(path,'w',encoding='utf-8') as f:
            f.write("\n".join(self.entries))

LOGGER = AppLogger()

# ---------------------------------------------------------------------------
# SHODAN API CLIENT
# ---------------------------------------------------------------------------
class ShodanAPI:
    BASE="https://api.shodan.io"
    INTERNETDB="https://internetdb.shodan.io"
    def __init__(self, api_key, logger=None):
        self.api_key=api_key.strip() if api_key else ""
        self.logger=logger or LOGGER

    def _log(self, lvl, msg, detail=""):
        try:
            if self.logger:
                self.logger.log(lvl,msg,detail)
        except: pass

    def _request(self, method, path, params=None, data=None, base=None):
        if not self.api_key and base==self.BASE:
            raise ValueError("Geen API key ingesteld")
        base=base or self.BASE
        url=f"{base}{path}"
        if params is None:
            params={}
        if base==self.BASE:
            params["key"]=self.api_key
        # Build full URL for logging (without exposing full key)
        masked_key=self.api_key[:4]+"…"+self.api_key[-4:] if len(self.api_key)>8 else "***"
        log_params={k: (masked_key if k=="key" else v) for k,v in params.items()}
        qs= "&".join([f"{k}={v}" for k,v in log_params.items()])
        full_log_url=f"{url}?{qs}" if qs else url
        t0=time.time()
        self._log("INFO", f"{method} {path}", full_log_url)
        if HAS_REQUESTS:
            try:
                if method=="GET":
                    r=requests.get(url,params=params,timeout=20)
                elif method=="POST":
                    r=requests.post(url,params=params,json=data,timeout=20)
                elif method=="PUT":
                    r=requests.put(url,params=params,json=data,timeout=20)
                elif method=="DELETE":
                    r=requests.delete(url,params=params,timeout=20)
                else:
                    raise ValueError("Unsupported method")
                elapsed=int((time.time()-t0)*1000)
                try: j=r.json()
                except: j={"raw":r.text[:2000]}
                if r.status_code>=400:
                    err=j.get("error",r.text) if isinstance(j,dict) else r.text
                    self._log("ERROR", f"API {r.status_code} {path} ({elapsed}ms)", str(err)[:500])
                    raise Exception(f"API fout {r.status_code}: {err}")
                self._log("OK", f"{r.status_code} {path} ({elapsed}ms) — {len(str(j))} bytes", f"Credits? zie /api-info")
                return j
            except requests.exceptions.RequestException as e:
                elapsed=int((time.time()-t0)*1000)
                self._log("ERROR", f"Netwerkfout {path} ({elapsed}ms)", str(e))
                raise Exception(f"Netwerkfout: {e}")
        else:
            qs_real=urllib.parse.urlencode(params)
            full=f"{url}?{qs_real}" if qs_real else url
            req_data=None
            headers={"Content-Type":"application/json"}
            if data is not None:
                req_data=json.dumps(data).encode()
            req=urllib.request.Request(full,data=req_data,headers=headers,method=method)
            try:
                with urllib.request.urlopen(req,timeout=20) as resp:
                    body=resp.read().decode()
                    elapsed=int((time.time()-t0)*1000)
                    self._log("OK", f"200 {path} ({elapsed}ms)", "")
                    return json.loads(body) if body else {}
            except urllib.error.HTTPError as e:
                body=e.read().decode()
                try: j=json.loads(body); err=j.get("error",body)
                except: err=body
                self._log("ERROR", f"HTTP {e.code} {path}", err[:500])
                raise Exception(f"API fout {e.code}: {err}")
            except Exception as e:
                self._log("ERROR", f"Netwerkfout {path}", str(e))
                raise Exception(f"Netwerkfout: {e}")

    def get_api_info(self): return self._request("GET","/api-info")
    def get_account_profile(self): return self._request("GET","/account/profile")
    def get_org_info(self): return self._request("GET","/org")
    def org_add_member(self,user): return self._request("PUT",f"/org/member/{user}")
    def org_remove_member(self,user): return self._request("DELETE",f"/org/member/{user}")
    def host(self,ip,history=False,minify=False):
        p={}
        if history: p["history"]="true"
        if minify: p["minify"]="true"
        return self._request("GET",f"/shodan/host/{ip}",p)
    def host_search(self,query,page=1,facets=None,minify=None):
        p={"query":query,"page":str(page)}
        if facets: p["facets"]=facets
        if minify is not None: p["minify"]=str(minify).lower()
        return self._request("GET","/shodan/host/search",p)
    def host_count(self,query,facets=None):
        p={"query":query}
        if facets: p["facets"]=facets
        return self._request("GET","/shodan/host/count",p)
    def host_search_facets(self): return self._request("GET","/shodan/host/search/facets")
    def host_search_filters(self): return self._request("GET","/shodan/host/search/filters")
    def host_search_tokens(self,query): return self._request("GET","/shodan/host/search/tokens",{"query":query})
    def ports(self): return self._request("GET","/shodan/ports")
    def protocols(self): return self._request("GET","/shodan/protocols")
    def scan(self,ips):
        if isinstance(ips,list): ips=",".join(ips)
        return self._request("POST","/shodan/scan",data={"ips":ips})
    def scan_internet(self,port,protocol): return self._request("POST","/shodan/scan/internet",data={"port":port,"protocol":protocol})
    def scans_list(self): return self._request("GET","/shodan/scans")
    def scan_status(self,sid): return self._request("GET",f"/shodan/scans/{sid}")
    def alert_list(self): return self._request("GET","/shodan/alert/info")
    def alert_create(self,name,ips,expires=0):
        if isinstance(ips,str): ips=[x.strip() for x in ips.split(",") if x.strip()]
        return self._request("POST","/shodan/alert",data={"name":name,"filters":{"ip":ips},"expires":expires})
    def alert_info(self,aid): return self._request("GET",f"/shodan/alert/{aid}/info")
    def alert_delete(self,aid): return self._request("DELETE",f"/shodan/alert/{aid}")
    def alert_edit(self,aid,ips):
        if isinstance(ips,str): ips=[x.strip() for x in ips.split(",") if x.strip()]
        return self._request("POST",f"/shodan/alert/{aid}",data={"filters":{"ip":ips}})
    def alert_triggers(self): return self._request("GET","/shodan/alert/triggers")
    def alert_enable_trigger(self,aid,tr): return self._request("PUT",f"/shodan/alert/{aid}/trigger/{tr}")
    def alert_disable_trigger(self,aid,tr): return self._request("DELETE",f"/shodan/alert/{aid}/trigger/{tr}")
    def alert_whitelist(self,aid,tr,svc): return self._request("PUT",f"/shodan/alert/{aid}/trigger/{tr}/ignore/{svc}")
    def alert_whitelist_remove(self,aid,tr,svc): return self._request("DELETE",f"/shodan/alert/{aid}/trigger/{tr}/ignore/{svc}")
    def alert_add_notifier(self,aid,nid): return self._request("PUT",f"/shodan/alert/{aid}/notifier/{nid}")
    def alert_remove_notifier(self,aid,nid): return self._request("DELETE",f"/shodan/alert/{aid}/notifier/{nid}")
    def notifier_list(self): return self._request("GET","/notifier")
    def notifier_providers(self): return self._request("GET","/notifier/provider")
    def notifier_get(self,nid): return self._request("GET",f"/notifier/{nid}")
    def notifier_create(self,provider,args,description=""): return self._request("POST","/notifier",data={"provider":provider,"args":args,"description":description})
    def notifier_update(self,nid,args): return self._request("PUT",f"/notifier/{nid}",data=args)
    def notifier_delete(self,nid): return self._request("DELETE",f"/notifier/{nid}")
    def query_list(self,page=1,sort="votes",order="desc"): return self._request("GET","/shodan/query",{"page":str(page),"sort":sort,"order":order})
    def query_search(self,query,page=1): return self._request("GET","/shodan/query/search",{"query":query,"page":str(page)})
    def query_tags(self,size=10): return self._request("GET","/shodan/query/tags",{"size":str(size)})
    def data_list(self): return self._request("GET","/shodan/data")
    def data_dataset(self,ds): return self._request("GET",f"/shodan/data/{ds}")
    def dns_resolve(self,hostnames):
        if isinstance(hostnames,list): hostnames=",".join(hostnames)
        return self._request("GET","/dns/resolve",{"hostnames":hostnames})
    def dns_reverse(self,ips):
        if isinstance(ips,list): ips=",".join(ips)
        return self._request("GET","/dns/reverse",{"ips":ips})
    def dns_domain(self,domain): return self._request("GET",f"/dns/domain/{domain}")
    def tools_myip(self): return self._request("GET","/tools/myip")
    def tools_httpheaders(self): return self._request("GET","/tools/httpheaders")
    def honeyscore(self,ip): return self._request("GET",f"/labs/honeyscore/{ip}")
    def internetdb(self,ip): return self._request("GET",f"/{ip}",base=self.INTERNETDB)

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
FILTERS_NL = {
    "country": "Land (ISO code, bv. NL, DE, US)",
    "city": "Stad",
    "org": "Organisatie / Eigenaar",
    "isp": "ISP / Provider",
    "asn": "ASN (bv. AS15169)",
    "hostname": "Hostname bevat",
    "net": "Netblock (CIDR bv. 8.8.8.0/24)",
    "port": "Poort nummer",
    "product": "Product / Software (bv. nginx, Apache)",
    "version": "Versie",
    "os": "Besturingssysteem",
    "cpe": "CPE",
    "title": "HTML title bevat",
    "http.title": "HTTP title",
    "http.html": "HTML inhoud",
    "http.component": "Web technologie (bv. WordPress)",
    "http.component_category": "Component categorie",
    "http.status": "HTTP status code",
    "ssl": "SSL data",
    "ssl.cert.subject.cn": "SSL CN",
    "ssl.cert.expired": "SSL verlopen (true/false)",
    "has_screenshot": "Heeft screenshot (true/false)",
    "has_ipv6": "Heeft IPv6 (true/false)",
    "has_ssl": "Heeft SSL (true/false)",
    "tag": "Tag (bv. ics, webcam)",
    "vuln": "Kwetsbaarheid (CVE)",
    "hash": "Data hash",
    "ip_str": "IP adres",
    "state": "Staat/Provincie",
    "postal": "Postcode",
    "geo": "Geo (lat,lon,radius)",
    "after": "Na datum (dd/mm/yyyy)",
    "before": "Voor datum (dd/mm/yyyy)",
    "bitcoin.ip": "Bitcoin peer IP",
    "ntp.ip": "NTP monlist IP",
}
# FIXED presets: port:554,80,8080 werkte niet betrouwbaar + product:"webcam" gaf 0 resultaten.
PRESETS = {
    "🌐 Webcams (algemeen)": 'has_screenshot:true webcam',
    "🌐 Webcams NL 🇳🇱": 'country:NL has_screenshot:true webcam',
    "📷 Hikvision Camera": 'product:"Hikvision" has_screenshot:true',
    "📷 Axis Camera": 'product:"Axis" has_screenshot:true',
    "🖨️ Printers": 'port:9100 has_screenshot:true',
    "🔧 ICS / SCADA": 'tag:ics',
    "🏭 Modbus": 'port:502',
    "⚡ BACnet": 'port:47808',
    "🗄️ MongoDB (open)": 'product:MongoDB port:27017',
    "🗄️ MySQL (open)": 'product:MySQL port:3306',
    "🐘 PostgreSQL": 'product:PostgreSQL port:5432',
    "🔴 Redis (open)": 'product:Redis port:6379',
    "📡 Elasticsearch": 'product:Elastic port:9200',
    "🌍 Apache": 'product:Apache',
    "🟢 Nginx": 'product:nginx',
    "🔵 IIS": 'product:"Microsoft IIS"',
    "☁️ AWS": 'org:"Amazon"',
    "🔍 RDP open": 'port:3389 has_screenshot:true',
    "📁 SMB open": 'port:445',
    "📹 DVR / NVR": 'product:"DVR" has_screenshot:true',
    "🚨 Kwetsbaar (CVE)": 'vuln:CVE-2021-44228',
    "🔐 Self-signed SSL": 'ssl.cert.issuer.cn:"self-signed"',
    "🇳🇱 Nederland": 'country:NL',
    "🇩🇪 Duitsland": 'country:DE',
    "🇺🇸 USA": 'country:US',
    "🌐 WordPress": 'http.component:"WordPress"',
    "🎥 RTSP Stream": 'port:554 has_screenshot:true',
}

def pretty_json(o): return json.dumps(o,indent=2,ensure_ascii=False)
def validate_ip(ip):
    return bool(re.match(r"^(\d{1,3}\.){3}\d{1,3}$",ip)) and all(0<=int(p)<=255 for p in ip.split("."))
def credits_uitleg(api_info):
    # api_info bevat query_credits, scan_credits, plan
    try:
        today=datetime.date.today()
        # Volgende reset is 1e volgende maand
        if today.month==12:
            nxt=datetime.date(today.year+1,1,1)
        else:
            nxt=datetime.date(today.year,today.month+1,1)
        dagen=(nxt - today).days
        plan=api_info.get("plan","?") if api_info else "?"
        qc=api_info.get("query_credits","?") if api_info else "?"
        sc=api_info.get("scan_credits","?") if api_info else "?"
        # Info per plan (benadering)
        plan_info={
            "dev":"Gratis / Dev: ±100 queries/maand",
            "basic":"Basic: ±10.000 queries/maand",
            "plus":"Plus: ±50.000 queries/maand",
            "enterprise":"Enterprise: onbeperkt / op maat"
        }
        ptxt=plan_info.get(str(plan).lower(), f"Plan {plan}")
        return (f"Plan: {plan} — {ptxt}\n"
                f"Resterend: {qc} query credits • {sc} scan credits\n"
                f"Geldigheid: credits zijn maandelijks, reset op de 1e van de maand.\n"
                f"Volgende reset: {nxt.strftime('%d %B %Y')} (over {dagen} dagen, om 00:00 UTC)\n"
                f"Tip: /shodan/host/count is gratis (verbruikt geen credits), /search wel (1 credit per 100 resultaten pagina).")
    except:
        return "Credits zijn maandelijks. Reset op 1e van elke maand 00:00 UTC. Zie https://account.shodan.io/billing voor exacte limieten."

# ---------------------------------------------------------------------------
# HOOFD APP - Windows 2026 Fluent
# ---------------------------------------------------------------------------
class ShodanGUI(Tk):
    def __init__(self, app_config):
        super().__init__()
        self.app_config=app_config
        self.api=None
        k=self.app_config.get("api_key","")
        if k:
            self.api=ShodanAPI(k, LOGGER)
        self.title("Shodan GUI  —  Windows 2026 Edition  •  Fluent  •  Alle 37 endpoints")
        self.geometry(self.app_config.get("geometry","1360x860"))
        self.minsize(1240,760)

        # Use Segoe UI Variable if available
        self.style=ttk.Style()
        # Probeer vista (native Windows) voor echte 2026 look, fallback clam
        for th in ("vista","xpnative","clam"):
            try:
                self.style.theme_use(th)
                break
            except: continue
        self._setup_styles()

        self.search_history=self.app_config.get("search_history",[])
        self.favorites=self.app_config.get("favorites",[])
        self.developer_mode=bool(self.app_config.get("developer_mode", False))

        self._build_menu()
        self._build_topbar()
        self._build_tabs()
        self._build_statusbar()

        if not k:
            self.after(600, self.prompt_api_key)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if self.api:
            self.after(900, self.refresh_account_info)

    def _setup_styles(self):
        # Windows 2026 Fluent palette
        self.COLORS={
            "bg":"#f3f3f3",          # win11 mica light
            "bg_card":"#ffffff",
            "bg_top":"#ffffff",
            "border":"#e5e5e5",
            "border_strong":"#d1d1d1",
            "primary":"#0078d4",     # win11 accent
            "primary_hover":"#106ebe",
            "text":"#1f1f1f",
            "muted":"#605e5c",
            "success":"#107c10",
            "warn":"#d83b01",
            "code_bg":"#f8f9fa",
        }
        self.configure(bg=self.COLORS["bg"])
        # --- Tabs: FIX shrinking - uniform padding for selected/unselected ---
        # Use Segoe UI Variable Text if available
        try:
            fams=tkfont.families()
            font_name="Segoe UI Variable Text" if "Segoe UI Variable Text" in fams else "Segoe UI"
        except:
            font_name="Segoe UI"
        self.style.configure("TNotebook", background=self.COLORS["bg"], borderwidth=0, tabmargins=[8,6,8,0])
        # Belangrijk: padding identiek voor selected en !selected zodat tab niet krimpt
        self.style.configure("TNotebook.Tab",
            padding=[16, 10],
            font=(font_name, 9),
            background=self.COLORS["bg"],
            foreground=self.COLORS["muted"])
        self.style.map("TNotebook.Tab",
            padding=[("selected", [16,10]), ("!selected", [16,10])],
            background=[("selected", self.COLORS["bg_card"]), ("!selected", self.COLORS["bg"])],
            foreground=[("selected", self.COLORS["primary"]), ("!selected", self.COLORS["muted"])],
            expand=[("selected", [1,1,1,0])]
        )
        # Cards
        self.style.configure("Card.TFrame", background=self.COLORS["bg_card"])
        self.style.configure("TFrame", background=self.COLORS["bg"])
        self.style.configure("TLabel", background=self.COLORS["bg"], foreground=self.COLORS["text"])
        # Buttons - win11 style
        self.style.configure("Accent.TButton", font=(font_name, 9, "bold"), padding=[14,6])
        self.style.configure("TButton", padding=[12,6], font=(font_name, 9))
        # Treeview
        self.style.configure("Treeview", rowheight=26, font=(font_name, 9), background="white", fieldbackground="white", bordercolor=self.COLORS["border"])
        self.style.configure("Treeview.Heading", font=(font_name, 9, "bold"), padding=[8,8], background="#f9f9f9")
        self.style.map("Treeview", background=[("selected","#e5f1fb")], foreground=[("selected","#000000")])

    def _build_menu(self):
        self.menubar=Menu(self, bg="white", relief=FLAT, bd=0)
        # Bestand
        m_file=Menu(self.menubar, tearoff=0, font=("Segoe UI",9))
        m_file.add_command(label="Exporteer laatste resultaten → JSON", command=lambda:self.export_results("json"))
        m_file.add_command(label="Exporteer laatste resultaten → CSV", command=lambda:self.export_results("csv"))
        m_file.add_separator()
        m_file.add_command(label="Afsluiten", command=self.on_close, accelerator="Alt+F4")
        self.menubar.add_cascade(label="Bestand", menu=m_file)
        # Extra
        m_tools=Menu(self.menubar, tearoff=0, font=("Segoe UI",9))
        m_tools.add_command(label="Facets & Filters verversen", command=self.load_facets_filters)
        m_tools.add_command(label="Cache wissen (weergave)", command=self.clear_cache)
        m_tools.add_separator()
        m_tools.add_command(label="Open Shodan Filters site", command=lambda:webbrowser.open("https://www.shodan.io/search/filters"))
        self.menubar.add_cascade(label="Extra", menu=m_tools)
        # Instellingen - NIEUW rechts naast Extra
        self.m_settings=Menu(self.menubar, tearoff=0, font=("Segoe UI",9))
        self.m_settings.add_command(label="🔑  API Key beheren…", command=self.open_settings_api)
        self.m_settings.add_command(label="👤  Account & Credits…", command=self.open_settings_account)
        self.m_settings.add_separator()
        # Developer mode check
        self.dev_var=BooleanVar(value=self.developer_mode)
        self.m_settings.add_checkbutton(label="🧪  Developer modus", variable=self.dev_var, command=self.toggle_developer_mode)
        self.m_settings.add_command(label="📋  Logboek openen", command=self.open_logging_tab)
        self.m_settings.add_command(label="🗑️  Logboek wissen", command=lambda: LOGGER.clear())
        self.m_settings.add_command(label="📤  Logboek exporteren…", command=self.export_logs)
        self.m_settings.add_separator()
        self.m_settings.add_command(label="⚙️  Instellingen openen…", command=self.open_settings_window)
        self.m_settings.add_command(label="🎨  Thema: Licht / Donker (demo)", command=lambda: messagebox.showinfo("Thema","Donker thema komt in volgende update. Nu: Licht (Windows 2026)."))
        self.menubar.add_cascade(label="Instellingen", menu=self.m_settings)
        # Help
        m_help=Menu(self.menubar, tearoff=0, font=("Segoe UI",9))
        m_help.add_command(label="Shodan Developer Docs", command=lambda:webbrowser.open("https://developer.shodan.io/api"))
        m_help.add_command(label="Shodan Filters overzicht", command=lambda:webbrowser.open("https://www.shodan.io/search/filters"))
        m_help.add_command(label="Diagnose & Troubleshooting…", command=self.show_diagnostics)
        m_help.add_separator()
        m_help.add_command(label="Over deze app…", command=self.show_about)
        self.menubar.add_cascade(label="Help", menu=m_help)
        self.configure(menu=self.menubar)

    def _build_topbar(self):
        # Windows 2026 topbar - wit met subtiele schaduw, afgeronde hoeken gevoel
        top=Frame(self, bg=self.COLORS["bg_top"], highlightthickness=0)
        top.pack(fill=X, side=TOP, padx=0, pady=0)
        # dunne border onder
        border=Frame(self, bg=self.COLORS["border"], height=1)
        border.pack(fill=X, side=TOP)
        inner=Frame(top, bg=self.COLORS["bg_top"])
        inner.pack(fill=X, padx=18, pady=10)
        left=Frame(inner, bg=self.COLORS["bg_top"])
        left.pack(side=LEFT, fill=Y)
        # Logo
        Label(left, text="SHODAN", bg=self.COLORS["bg_top"], fg="#d83b01", font=("Segoe UI", 16, "bold")).pack(side=LEFT)
        Label(left, text=" GUI", bg=self.COLORS["bg_top"], fg=self.COLORS["text"], font=("Segoe UI", 16)).pack(side=LEFT, padx=(1,10))
        Label(left, text="2026", bg=self.COLORS["primary"], fg="white", font=("Segoe UI", 7, "bold"), padx=6, pady=2).pack(side=LEFT, padx=4)
        Label(left, text="Fluent  •  Alle 37 API endpoints  •  Register opslag  •  Developer-ready", bg=self.COLORS["bg_top"], fg=self.COLORS["muted"], font=("Segoe UI", 8)).pack(side=LEFT, padx=12)
        right=Frame(inner, bg=self.COLORS["bg_top"])
        right.pack(side=RIGHT)
        self.api_status_dot=Label(right, text="●", bg=self.COLORS["bg_top"], fg="#a0a0a0", font=("Segoe UI", 12))
        self.api_status_dot.pack(side=LEFT, padx=(0,6))
        self.api_status_label=Label(right, text="Geen API key", bg=self.COLORS["bg_top"], fg=self.COLORS["muted"], font=("Segoe UI", 8, "bold"))
        self.api_status_label.pack(side=LEFT, padx=(0,10))
        # Win11 style buttons
        ttk.Button(right, text="Instellingen", style="Accent.TButton", command=self.open_settings_window).pack(side=LEFT, padx=4)
        ttk.Button(right, text="🔑 API Key", command=self.open_settings_api).pack(side=LEFT, padx=4)
        ttk.Button(right, text="🔄 Valideren", command=self.validate_api_key).pack(side=LEFT, padx=4)
        self._update_api_status()

    def _build_tabs(self):
        self.notebook=ttk.Notebook(self)
        self.notebook.pack(fill=BOTH, expand=True, padx=10, pady=(8,0))
        self.tab_search=ttk.Frame(self.notebook)
        self.tab_host=ttk.Frame(self.notebook)
        self.tab_dns=ttk.Frame(self.notebook)
        self.tab_directory=ttk.Frame(self.notebook)
        self.tab_scans=ttk.Frame(self.notebook)
        self.tab_tools=ttk.Frame(self.notebook)
        self.tab_account=ttk.Frame(self.notebook)
        self.tab_logging=ttk.Frame(self.notebook)

        self.notebook.add(self.tab_search, text="  🔍 Zoeken  ")
        self.notebook.add(self.tab_host, text="  🖥️ Host / IP  ")
        self.notebook.add(self.tab_dns, text="  🌐 DNS  ")
        self.notebook.add(self.tab_directory, text="  📚 Directory  ")
        self.notebook.add(self.tab_scans, text="  📡 Scans & Alerts  ")
        self.notebook.add(self.tab_tools, text="  🧰 Hulpmiddelen  ")
        self.notebook.add(self.tab_account, text="  👤 Account  ")
        # Logging tab alleen als developer mode aan (initieel verbergen via forget, later add)
        self.notebook.add(self.tab_logging, text="  🛠️ Logging  ")

        self._build_search_tab()
        self._build_host_tab()
        self._build_dns_tab()
        self._build_directory_tab()
        self._build_scans_tab()
        self._build_tools_tab()
        self._build_account_tab()
        self._build_logging_tab()

        # Verberg logging als developer uit
        if not self.developer_mode:
            try: self.notebook.forget(self.tab_logging)
            except: pass
        # Style tweak: selected tab krijgt blauwe underline via custom? we simuleren met focus
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self.log_tab_change())

    def _build_statusbar(self):
        self.statusbar=Frame(self, bg="#f9f9f9", height=30, highlightthickness=1, highlightbackground=self.COLORS["border"])
        self.statusbar.pack(fill=X, side=BOTTOM)
        self.statusbar.pack_propagate(False)
        left=Frame(self.statusbar, bg="#f9f9f9")
        left.pack(side=LEFT, fill=Y, padx=10, pady=4)
        self.status_text=Label(left, text="Gereed. Vul je API key in bij Instellingen → API Key.", bg="#f9f9f9", fg=self.COLORS["text"], font=("Segoe UI", 8), anchor=W)
        self.status_text.pack(side=LEFT)
        # Credits validiteit rechts
        right=Frame(self.statusbar, bg="#f9f9f9")
        right.pack(side=RIGHT, fill=Y, padx=10, pady=4)
        self.credits_label=Label(right, text="", bg="#f9f9f9", fg=self.COLORS["primary"], font=("Segoe UI", 8, "bold"))
        self.credits_label.pack(side=LEFT, padx=6)
        self.reset_label=Label(right, text="", bg="#f9f9f9", fg=self.COLORS["muted"], font=("Segoe UI", 8))
        self.reset_label.pack(side=LEFT, padx=6)
        ttk.Button(right, text="❓ Credits ?", width=11, command=self.show_credits_help).pack(side=LEFT, padx=8)

    def set_status(self, msg, timeout=4200):
        self.status_text.config(text=msg)
        LOGGER.log("STATUS", msg)
        if timeout:
            self.after(timeout, lambda: self.status_text.config(text="Gereed."))

    # -----------------------------------------------------------------------
    # SEARCH TAB
    # -----------------------------------------------------------------------
    def _build_search_tab(self):
        container=Frame(self.tab_search, bg=self.COLORS["bg"])
        container.pack(fill=BOTH, expand=True)
        card=Frame(container, bg=self.COLORS["bg_card"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        card.pack(fill=X, padx=12, pady=10)
        hdr=Frame(card, bg=self.COLORS["bg_card"])
        hdr.pack(fill=X, padx=14, pady=(10,6))
        Label(hdr, text="Visuele Query Builder", bg=self.COLORS["bg_card"], fg=self.COLORS["primary"], font=("Segoe UI", 10, "bold")).pack(side=LEFT)
        Label(hdr, text="— combineer filters zonder syntax te kennen. Port-lijsten met komma zijn nu gefixed.", bg=self.COLORS["bg_card"], fg=self.COLORS["muted"], font=("Segoe UI", 8)).pack(side=LEFT, padx=10)
        # Presets 2 rijen
        pf_inner=Frame(card, bg=self.COLORS["bg_card"])
        pf_inner.pack(fill=X, padx=12, pady=(0,6))
        row1=Frame(pf_inner, bg=self.COLORS["bg_card"])
        row1.pack(fill=X, pady=1)
        row2=Frame(pf_inner, bg=self.COLORS["bg_card"])
        row2.pack(fill=X, pady=1)
        for i,(label,q) in enumerate(PRESETS.items()):
            par=row1 if i<11 else row2
            b=Button(par, text=label, font=("Segoe UI", 8), bg="#e5f1fb", fg=self.COLORS["primary"], relief=FLAT, bd=0, padx=8, pady=4, command=lambda qq=q: self.preset_search(qq))
            b.pack(side=LEFT, padx=3, pady=2)
            b.bind("<Enter>", lambda e,btn=b: btn.config(bg="#cce4f6"))
            b.bind("<Leave>", lambda e,btn=b: btn.config(bg="#e5f1fb"))
        # Builder
        builder=Frame(card, bg=self.COLORS["bg_card"])
        builder.pack(fill=X, padx=14, pady=6)
        Label(builder, text="Filter:", bg=self.COLORS["bg_card"], font=("Segoe UI", 9)).pack(side=LEFT)
        self.search_filter_var=StringVar(value="country")
        f_combo=ttk.Combobox(builder, textvariable=self.search_filter_var, values=list(FILTERS_NL.keys()), width=18, state="readonly")
        f_combo.pack(side=LEFT, padx=6)
        f_combo.bind("<<ComboboxSelected>>", lambda e: self.set_status(FILTERS_NL.get(self.search_filter_var.get(),"")))
        Label(builder, text="Waarde:", bg=self.COLORS["bg_card"], font=("Segoe UI", 9)).pack(side=LEFT, padx=(10,0))
        self.search_value_var=StringVar()
        Entry(builder, textvariable=self.search_value_var, width=24, font=("Segoe UI", 9)).pack(side=LEFT, padx=6)
        ttk.Button(builder, text="＋ Toevoegen", command=self.add_filter_to_query).pack(side=LEFT, padx=6)
        ttk.Button(builder, text="Wissen", command=lambda:self.search_query_var.set("")).pack(side=LEFT, padx=2)
        toggle_frame=Frame(card, bg=self.COLORS["bg_card"])
        toggle_frame.pack(fill=X, padx=14, pady=2)
        self.has_screenshot_var=BooleanVar()
        self.has_ssl_var=BooleanVar()
        Checkbutton(toggle_frame, text="has_screenshot:true", variable=self.has_screenshot_var, bg=self.COLORS["bg_card"], command=self.toggle_screenshot).pack(side=LEFT, padx=6)
        Checkbutton(toggle_frame, text="has_ssl:true", variable=self.has_ssl_var, bg=self.COLORS["bg_card"], command=self.toggle_ssl).pack(side=LEFT, padx=6)
        Label(toggle_frame, text="Voorbeeld gecombineerd: country:NL has_screenshot:true webcam  (nu gefixed!)", bg=self.COLORS["bg_card"], fg=self.COLORS["muted"], font=("Segoe UI", 8, "italic")).pack(side=LEFT, padx=14)
        # Query row
        query_row=Frame(card, bg=self.COLORS["bg_card"])
        query_row.pack(fill=X, padx=14, pady=(6,10))
        Label(query_row, text="Query:", bg=self.COLORS["bg_card"], font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        self.search_query_var=StringVar()
        self.search_query_entry=Entry(query_row, textvariable=self.search_query_var, font=("Consolas", 10), bg="#f9f9f9", relief=SOLID, bd=1, highlightthickness=1, highlightbackground=self.COLORS["border"])
        self.search_query_entry.pack(side=LEFT, fill=X, expand=True, padx=8, ipady=4)
        self.search_query_entry.bind("<Return>", lambda e: self.do_search())
        ttk.Button(query_row, text="🔍 Zoeken", style="Accent.TButton", command=self.do_search).pack(side=LEFT, padx=2)
        ttk.Button(query_row, text="🔢 Tellen (gratis)", command=self.do_count).pack(side=LEFT, padx=2)
        ttk.Button(query_row, text="🧩 Tokens", command=self.do_tokens).pack(side=LEFT, padx=2)
        # Opties
        opts=Frame(container, bg=self.COLORS["bg"])
        opts.pack(fill=X, padx=12, pady=(0,6))
        left_opts=Frame(opts, bg=self.COLORS["bg"])
        left_opts.pack(side=LEFT, fill=X, expand=True)
        Label(left_opts, text="Facetten:", bg=self.COLORS["bg"], font=("Segoe UI", 9)).pack(side=LEFT)
        self.search_facets_var=StringVar(value="")
        ttk.Combobox(left_opts, textvariable=self.search_facets_var, values=["","org","country","port:20","product","os","asn:20","city:20","org:10,country:10,port:10"], width=28).pack(side=LEFT, padx=6)
        Label(left_opts, text="Pagina:", bg=self.COLORS["bg"], font=("Segoe UI", 9)).pack(side=LEFT, padx=(8,0))
        self.search_page_var=IntVar(value=1)
        Spinbox(left_opts, from_=1, to=100, textvariable=self.search_page_var, width=5, font=("Segoe UI", 9)).pack(side=LEFT, padx=6)
        right_opts=Frame(opts, bg=self.COLORS["bg"])
        right_opts.pack(side=RIGHT)
        ttk.Button(right_opts, text="📥 JSON", command=lambda:self.export_results("json")).pack(side=LEFT, padx=2)
        ttk.Button(right_opts, text="📄 CSV", command=lambda:self.export_results("csv")).pack(side=LEFT, padx=2)
        ttk.Button(right_opts, text="⭐ Favoriet", command=self.save_favorite).pack(side=LEFT, padx=2)
        # Results
        paned=PanedWindow(container, orient=VERTICAL, bg=self.COLORS["bg"], sashwidth=6)
        paned.pack(fill=BOTH, expand=True, padx=12, pady=(0,10))
        tree_frame=Frame(paned, bg=self.COLORS["bg_card"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        cols=("ip","port","org","hostnames","country","product","title","updated")
        self.search_tree=ttk.Treeview(tree_frame, columns=cols, show="headings", height=11)
        headings={"ip":"IP Adres","port":"Poort","org":"Organisatie","hostnames":"Hostnames","country":"Land","product":"Product","title":"Title","updated":"Gezien"}
        widths={"ip":120,"port":66,"org":150,"hostnames":140,"country":54,"product":120,"title":160,"updated":120}
        for c in cols:
            self.search_tree.heading(c,text=headings[c])
            self.search_tree.column(c,width=widths[c],anchor=W)
        vsb=ttk.Scrollbar(tree_frame, orient=VERTICAL, command=self.search_tree.yview)
        hsb=ttk.Scrollbar(tree_frame, orient=HORIZONTAL, command=self.search_tree.xview)
        self.search_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.search_tree.grid(row=0,column=0,sticky="nsew")
        vsb.grid(row=0,column=1,sticky="ns")
        hsb.grid(row=1,column=0,sticky="ew")
        tree_frame.grid_rowconfigure(0,weight=1)
        tree_frame.grid_columnconfigure(0,weight=1)
        self.search_tree.bind("<Double-1>", self.on_search_doubleclick)
        self.search_tree.bind("<<TreeviewSelect>>", self.on_search_select)
        # context menu
        self.search_tree.bind("<Button-3>", self.show_search_context)
        paned.add(tree_frame, minsize=220)
        detail_frame=Frame(paned, bg=self.COLORS["bg_card"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        detail_nb=ttk.Notebook(detail_frame)
        detail_nb.pack(fill=BOTH, expand=True, padx=4, pady=4)
        tab1=Frame(detail_nb, bg="white")
        tab2=Frame(detail_nb, bg="white")
        tab3=Frame(detail_nb, bg="white")
        detail_nb.add(tab1, text="  📋 Geselecteerd  ")
        detail_nb.add(tab2, text="  📊 Facetten  ")
        detail_nb.add(tab3, text="  🧾 Ruwe JSON  ")
        self.search_detail_text=Text(tab1, wrap=WORD, font=("Consolas", 9), bg="#fafafa", relief=FLAT, padx=10, pady=10)
        self.search_facets_text=Text(tab2, wrap=WORD, font=("Consolas", 9), bg="#fffbe6", relief=FLAT, padx=10, pady=10)
        self.search_raw_text=Text(tab3, wrap=WORD, font=("Consolas", 8), bg="#fafafa", relief=FLAT, padx=10, pady=10)
        for w in (self.search_detail_text, self.search_facets_text, self.search_raw_text):
            w.pack(fill=BOTH, expand=True, padx=2, pady=2)
        nav=Frame(detail_frame, bg="white")
        nav.pack(fill=X, padx=4, pady=4)
        ttk.Button(nav, text="◀ Vorige", command=lambda:self.change_page(-1)).pack(side=LEFT, padx=2)
        self.search_info_label=Label(nav, text="Geen resultaten — voer een zoekopdracht uit", bg="white", fg=self.COLORS["muted"], font=("Segoe UI", 8, "italic"))
        self.search_info_label.pack(side=LEFT, padx=10)
        ttk.Button(nav, text="Volgende ▶", command=lambda:self.change_page(1)).pack(side=LEFT, padx=2)
        ttk.Button(nav, text="📋 Kopieer", command=self.copy_detail).pack(side=RIGHT, padx=4)
        ttk.Button(nav, text="🌐 Open in Shodan", command=self.open_selected_in_shodan).pack(side=RIGHT, padx=4)
        paned.add(detail_frame, minsize=210)
        self.last_search_results=None
        self.last_search_query=""

    # Search helpers (met fix voor combineren)
    def preset_search(self, query):
        cur=self.search_query_var.get().strip()
        # FIX: port:554,80,8080 was onbetrouwbaar → presets nu al gefixed, maar ook hier slim samenvoegen
        if cur and query not in cur:
            # voorkom dubbele spaties, zorg dat comma-lijsten intact blijven
            new_q=f"{cur} {query}".strip().replace("  "," ")
        else:
            new_q=query if not cur else cur
            if query != cur and cur!="":
                if query not in cur:
                    new_q=f"{cur} {query}"
        # Normaliseer: verwijder dubbele has_screenshot etc
        self.search_query_var.set(new_q.strip())
        self.set_status(f"Preset toegevoegd: {query}")
        LOGGER.log("INFO", "Preset toegevoegd", query)

    def add_filter_to_query(self):
        f=self.search_filter_var.get().strip()
        v=self.search_value_var.get().strip()
        if not f or not v:
            messagebox.showwarning("Let op","Kies een filter en vul een waarde in.")
            return
        if " " in v and not (v.startswith('"') and v.endswith('"')):
            v=f'"{v}"'
        add=f"{f}:{v}"
        cur=self.search_query_var.get().strip()
        new_q=f"{cur} {add}".strip() if cur else add
        self.search_query_var.set(new_q)
        self.search_value_var.set("")
        self.set_status(f"Filter toegevoegd: {add}")
        LOGGER.log("INFO","Filter toegevoegd",add)

    def toggle_screenshot(self):
        q=self.search_query_var.get()
        tok="has_screenshot:true"
        if self.has_screenshot_var.get():
            if tok not in q: self.search_query_var.set(f"{q} {tok}".strip())
        else:
            self.search_query_var.set(q.replace(tok,"").strip().replace("  "," "))
    def toggle_ssl(self):
        q=self.search_query_var.get()
        tok="has_ssl:true"
        if self.has_ssl_var.get():
            if tok not in q: self.search_query_var.set(f"{q} {tok}".strip())
        else:
            self.search_query_var.set(q.replace(tok,"").strip().replace("  "," "))

    def show_search_context(self, event):
        # simple context menu
        try:
            menu=Menu(self, tearoff=0)
            menu.add_command(label="Kopieer IP", command=lambda: self.copy_selected_ip())
            menu.add_command(label="Open in Shodan", command=self.open_selected_in_shodan)
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try: menu.grab_release()
            except: pass

    def copy_selected_ip(self):
        sel=self.search_tree.selection()
        if sel and self.last_search_results:
            idx=self.search_tree.index(sel[0])
            m=self.last_search_results["matches"][idx]
            self.clipboard_clear(); self.clipboard_append(m.get("ip_str",""))
            self.set_status("IP gekopieerd")

    def require_api(self):
        if not self.api or not self.api.api_key:
            messagebox.showerror("Geen API Key","Stel eerst je Shodan API key in via Instellingen → API Key.\n\nJe vindt je key op https://account.shodan.io")
            self.open_settings_api()
            return False
        return True

    def run_async(self, func, on_success, on_error=None):
        def wrapper():
            try:
                res=func()
                self.after(0, lambda: on_success(res))
            except Exception as e:
                tb=traceback.format_exc()
                LOGGER.log("ERROR", str(e), tb.splitlines()[-1] if tb else "")
                if on_error:
                    self.after(0, lambda err=e: on_error(err))
                else:
                    self.after(0, lambda err=e: messagebox.showerror("Fout", str(err)))
                    self.after(0, lambda err=e: self.set_status(f"Fout: {err}"))
        threading.Thread(target=wrapper, daemon=True).start()

    def do_search(self):
        if not self.require_api(): return
        query=self.search_query_var.get().strip()
        if not query:
            messagebox.showinfo("Zoeken","Vul een zoekquery in of gebruik presets.\n\nVoorbeeld gecombineerd (nu gefixed):\ncountry:NL has_screenshot:true webcam")
            return
        # FIX: query validatie - geef waarschuwing bij verdachte comma-port
        if "port:" in query and ", " in query:
            # gebruiker heeft "port:554, 80" met spatie → fix
            query=query.replace(", ", ",")
            self.search_query_var.set(query)
        page=self.search_page_var.get()
        facets=self.search_facets_var.get().strip()
        if query not in self.search_history:
            self.search_history.insert(0,query)
            self.search_history=self.search_history[:30]
            self.app_config.set("search_history", self.search_history)
        self.last_search_query=query
        self.set_status(f"Zoeken: {query} (p{page})…")
        self.search_info_label.config(text=f"Bezig: {query} …")
        for i in self.search_tree.get_children(): self.search_tree.delete(i)
        self.search_detail_text.delete("1.0",END); self.search_facets_text.delete("1.0",END)
        def task(): return self.api.host_search(query, page=page, facets=facets or None)
        def success(data):
            self.last_search_results=data
            self.display_search_results(data, query, page)
            self.set_status(f"Gevonden: {data.get('total',0)} resultaten (p{page})")
            self.refresh_credits_silent()
            if data.get("total",0)==0:
                self.search_info_label.config(text=f"Geen resultaten voor '{query}'. Probeer algemener: verwijder product:\"webcam\" en gebruik alleen webcam.")
                LOGGER.log("WARN","0 resultaten", query)
        def error(e):
            # Geef troubleshoot hulp
            msg=str(e)
            if "Invalid search query" in msg or "invalid" in msg.lower():
                msg+= "\n\nTip: controleer filters. Gebruik bv. has_screenshot:true (zonder spatie) en port zonder spatie na komma."
                LOGGER.log("ERROR","Ongeldige query", query)
            messagebox.showerror("Zoekfout", msg)
            self.search_info_label.config(text=f"Fout: {e}")
            self.set_status(f"Zoekfout: {e}")
        self.run_async(task, success, error)

    def do_count(self):
        if not self.require_api(): return
        query=self.search_query_var.get().strip()
        if not query: 
            messagebox.showinfo("Tellen","Vul eerst een query in.")
            return
        facets=self.search_facets_var.get().strip()
        self.set_status(f"Tellen: {query} (gratis)…")
        def task(): return self.api.host_count(query, facets=facets or None)
        def success(data):
            total=data.get("total",0)
            self.search_facets_text.delete("1.0",END)
            self.search_facets_text.insert(END, f"🔢 COUNT\nQuery: {query}\nTotaal: {total:,} resultaten\n\n".replace(",","."))
            if data.get("facets"): self.search_facets_text.insert(END, pretty_json(data["facets"]))
            else: self.search_facets_text.insert(END, "(Geen facetten — vul bv. 'country:10,org:10' in)")
            self.search_raw_text.delete("1.0",END); self.search_raw_text.insert(END, pretty_json(data))
            self.search_info_label.config(text=f"Telling: {total:,} resultaten voor '{query}' (gratis)".replace(",","."))
            messagebox.showinfo("Count", f"Query: {query}\n\nTotaal: {total:,}\n(Facetten in tab Facetten)".replace(",","."))
        self.run_async(task, success, lambda e: messagebox.showerror("Fout", str(e)))

    def do_tokens(self):
        if not self.require_api(): return
        query=self.search_query_var.get().strip()
        if not query: return
        def task(): return self.api.host_search_tokens(query)
        def success(data):
            self.search_facets_text.delete("1.0",END)
            self.search_facets_text.insert(END, f"🧩 TOKENS voor: {query}\n\n"+pretty_json(data))
            self.search_info_label.config(text="Tokens geanalyseerd — zie Facetten tab")
            self.set_status("Tokens geanalyseerd")
        self.run_async(task, success, lambda e: messagebox.showerror("Fout", str(e)))

    def display_search_results(self, data, query, page):
        total=data.get("total",0); matches=data.get("matches",[])
        for i in self.search_tree.get_children(): self.search_tree.delete(i)
        for m in matches:
            ip=m.get("ip_str","")
            port=str(m.get("port",""))
            org=m.get("org","")[:30]
            hostnames=", ".join(m.get("hostnames",[])[:2])
            country=m.get("location",{}).get("country_code","") or m.get("country_code","")
            product=m.get("product","") or m.get("_shodan",{}).get("module","")
            title=m.get("http",{}).get("title","")[:36] if m.get("http") else ""
            ts=m.get("timestamp","")[:19].replace("T"," ")
            self.search_tree.insert("",END,values=(ip,port,org,hostnames,country,product,title,ts))
        self.search_facets_text.delete("1.0",END)
        if data.get("facets"): self.search_facets_text.insert(END, pretty_json(data["facets"]))
        else:
            self.search_facets_text.insert(END, "(Geen facetten — vul bij Facetten bv. 'country:15,org:15,port:15' en zoek opnieuw)\n\nTip: facetten geven breakdown zoals op shodan.io.\n")
        self.search_raw_text.delete("1.0",END); self.search_raw_text.insert(END, pretty_json(data))
        self.search_info_label.config(text=f"{total:,} resultaten voor '{query}' — p{page} toont {len(matches)}  •  ◀ ▶ bladeren".replace(",","."))

    def on_search_select(self, event):
        sel=self.search_tree.selection()
        if not sel or not self.last_search_results: return
        idx=self.search_tree.index(sel[0])
        matches=self.last_search_results.get("matches",[])
        if 0<= idx < len(matches):
            m=matches[idx]
            self.search_detail_text.delete("1.0",END)
            ip=m.get("ip_str")
            self.search_detail_text.insert(END, f"IP: {ip}\nPoort: {m.get('port')} / {m.get('transport','tcp')}\nOrganisatie: {m.get('org')} • ISP: {m.get('isp')}\nHostnames: {', '.join(m.get('hostnames',[]))}\nDomeinen: {', '.join(m.get('domains',[]))}\n")
            loc=m.get("location",{})
            self.search_detail_text.insert(END, f"Locatie: {loc.get('city','')}, {loc.get('country_name','')} ({loc.get('country_code','')}) • {loc.get('latitude')},{loc.get('longitude')}\nASN: {m.get('asn')} • OS: {m.get('os')}\nProduct: {m.get('product')} • Versie: {m.get('version')}\n")
            if m.get("vulns"):
                self.search_detail_text.insert(END, f"\n⚠️ KWETSBAARHEDEN ({len(m['vulns'])}): {', '.join(m['vulns'])}\n")
            self.search_detail_text.insert(END, f"\n— BANNER —\n{m.get('data','')[:2000]}\n")
            if m.get("http"): self.search_detail_text.insert(END, f"\n— HTTP —\n{pretty_json(m.get('http'))}\n")
            if m.get("ssl"): self.search_detail_text.insert(END, f"\n— SSL —\n{pretty_json(m.get('ssl'))}\n")
            self.search_detail_text.insert(END, f"\n— FULL JSON —\n{pretty_json(m)}")

    def on_search_doubleclick(self, event):
        sel=self.search_tree.selection()
        if not sel or not self.last_search_results: return
        idx=self.search_tree.index(sel[0])
        ip=self.last_search_results["matches"][idx].get("ip_str")
        if ip:
            self.notebook.select(self.tab_host)
            self.host_ip_var.set(ip)
            self.do_host_lookup()
    def change_page(self, d):
        new=max(1,self.search_page_var.get()+d)
        self.search_page_var.set(new)
        if self.search_query_var.get().strip(): self.do_search()
    def copy_detail(self):
        txt=self.search_detail_text.get("1.0",END)
        self.clipboard_clear(); self.clipboard_append(txt)
        self.set_status("Detail gekopieerd")
    def open_selected_in_shodan(self):
        sel=self.search_tree.selection()
        if not sel or not self.last_search_results:
            messagebox.showinfo("Open","Selecteer eerst een resultaat"); return
        idx=self.search_tree.index(sel[0])
        ip=self.last_search_results["matches"][idx].get("ip_str")
        if ip: webbrowser.open(f"https://www.shodan.io/host/{ip}")
    def export_results(self, fmt):
        if not self.last_search_results:
            messagebox.showinfo("Export","Geen resultaten. Zoek eerst."); return
        if fmt=="json":
            path=filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")], initialfile=f"shodan_{self.last_search_query[:20].replace(' ','_')}.json")
            if path:
                with open(path,'w',encoding='utf-8') as f: json.dump(self.last_search_results,f,indent=2,ensure_ascii=False)
                messagebox.showinfo("Export",f"Geëxporteerd naar {path}")
        else:
            path=filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")], initialfile=f"shodan_{self.last_search_query[:20].replace(' ','_')}.csv")
            if path:
                matches=self.last_search_results.get("matches",[])
                with open(path,'w',newline='',encoding='utf-8') as f:
                    w=csv.writer(f); w.writerow(["ip_str","port","org","isp","hostnames","country","city","product","version","os","asn","title","timestamp"])
                    for m in matches:
                        loc=m.get("location",{})
                        w.writerow([m.get("ip_str",""),m.get("port",""),m.get("org",""),m.get("isp",""),";".join(m.get("hostnames",[])),loc.get("country_code",""),loc.get("city",""),m.get("product",""),m.get("version",""),m.get("os",""),m.get("asn",""),m.get("http",{}).get("title","") if m.get("http") else "",m.get("timestamp","")])
                messagebox.showinfo("Export",f"Geëxporteerd naar {path}")
    def save_favorite(self):
        q=self.search_query_var.get().strip()
        if not q: return
        if q not in self.favorites:
            self.favorites.insert(0,q); self.favorites=self.favorites[:20]
            self.app_config.set("favorites",self.favorites)
            self.set_status(f"Favoriet: {q}")
            messagebox.showinfo("Favoriet",f"Opgeslagen:\n{q}")

    # -----------------------------------------------------------------------
    # HOST TAB (fixed)
    # -----------------------------------------------------------------------
    def _build_host_tab(self):
        top=Frame(self.tab_host, bg=self.COLORS["bg_card"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        top.pack(fill=X, padx=12, pady=10)
        Label(top, text="Host Lookup — alle banners & services voor één IP", bg=self.COLORS["bg_card"], fg=self.COLORS["primary"], font=("Segoe UI", 10, "bold")).pack(anchor=W, padx=14, pady=(8,4))
        row=Frame(top, bg=self.COLORS["bg_card"])
        row.pack(fill=X, padx=14, pady=6)
        Label(row, text="IP:", bg=self.COLORS["bg_card"], font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        self.host_ip_var=StringVar(value="8.8.8.8")
        Entry(row, textvariable=self.host_ip_var, width=20, font=("Consolas", 11)).pack(side=LEFT, padx=8)
        self.host_history_var=BooleanVar(); self.host_minify_var=BooleanVar()
        Checkbutton(row, text="Historie", variable=self.host_history_var, bg=self.COLORS["bg_card"]).pack(side=LEFT, padx=6)
        Checkbutton(row, text="Minify", variable=self.host_minify_var, bg=self.COLORS["bg_card"]).pack(side=LEFT, padx=4)
        ttk.Button(row, text="🔍 Ophalen", style="Accent.TButton", command=self.do_host_lookup).pack(side=LEFT, padx=8)
        ttk.Button(row, text="🧪 Honeyscore", command=self.do_honeyscore).pack(side=LEFT, padx=2)
        ttk.Button(row, text="🌐 InternetDB", command=self.do_internetdb).pack(side=LEFT, padx=2)
        ttk.Button(row, text="📋 Kopieer JSON", command=self.copy_host_json).pack(side=LEFT, padx=8)
        self.host_info_frame=Frame(self.tab_host, bg=self.COLORS["bg"])
        self.host_info_frame.pack(fill=BOTH, expand=True, padx=12, pady=(0,10))
        paned=PanedWindow(self.host_info_frame, orient=HORIZONTAL, bg=self.COLORS["bg"], sashwidth=6)
        paned.pack(fill=BOTH, expand=True)
        left_card=Frame(paned, bg=self.COLORS["bg_card"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        self.host_summary_text=Text(left_card, wrap=WORD, font=("Segoe UI", 9), bg="white", relief=FLAT, padx=12, pady=12, width=46)
        self.host_summary_text.pack(fill=BOTH, expand=True)
        left_btns=Frame(left_card, bg="white")
        left_btns.pack(fill=X, padx=8, pady=6)
        ttk.Button(left_btns, text="🗺️ Maps", command=self.open_host_maps).pack(side=LEFT, padx=2)
        ttk.Button(left_btns, text="🔗 Shodan", command=lambda:webbrowser.open(f"https://www.shodan.io/host/{self.host_ip_var.get().strip()}")).pack(side=LEFT, padx=2)
        ttk.Button(left_btns, text="📥 Export JSON", command=self.export_host_json).pack(side=LEFT, padx=2)
        paned.add(left_card)
        right_card=Frame(paned, bg=self.COLORS["bg_card"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        nb=ttk.Notebook(right_card); nb.pack(fill=BOTH, expand=True, padx=6, pady=6)
        banner_frame=Frame(nb, bg="white"); nb.add(banner_frame, text="  📦 Services  ")
        self.host_banner_tree=ttk.Treeview(banner_frame, columns=("port","transport","product","version","title"), show="headings", height=10)
        for c,h,w in [("port","Poort",60),("transport","Proto",60),("product","Product",130),("version","Versie",80),("title","Title",240)]:
            self.host_banner_tree.heading(c,text=h); self.host_banner_tree.column(c,width=w)
        vsb=ttk.Scrollbar(banner_frame, orient=VERTICAL, command=self.host_banner_tree.yview)
        self.host_banner_tree.configure(yscrollcommand=vsb.set)
        self.host_banner_tree.pack(side=LEFT, fill=BOTH, expand=True); vsb.pack(side=RIGHT, fill=Y)
        self.host_banner_tree.bind("<<TreeviewSelect>>", self.on_host_banner_select)
        vuln_frame=Frame(nb, bg="white"); nb.add(vuln_frame, text="  ⚠️ CVE’s  ")
        self.host_vuln_text=Text(vuln_frame, wrap=WORD, font=("Consolas", 9), bg="#fff8e1", padx=10, pady=10); self.host_vuln_text.pack(fill=BOTH, expand=True)
        raw_frame=Frame(nb, bg="white"); nb.add(raw_frame, text="  🧾 JSON  ")
        self.host_raw_text=Text(raw_frame, wrap=WORD, font=("Consolas", 8), bg="#fafafa", padx=10, pady=10); self.host_raw_text.pack(fill=BOTH, expand=True)
        detail_frame=Frame(right_card, bg="white", highlightthickness=1, highlightbackground=self.COLORS["border"])
        detail_frame.pack(fill=BOTH, expand=True, padx=6, pady=6)
        Label(detail_frame, text="Banner Detail — klik een service hierboven:", bg="white", fg=self.COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(anchor=W, padx=4, pady=(4,2))
        self.host_banner_detail=Text(detail_frame, wrap=WORD, font=("Consolas", 8), bg="#fafafa", padx=10, pady=10, height=10); self.host_banner_detail.pack(fill=BOTH, expand=True, padx=4, pady=4)
        paned.add(right_card)
        self.last_host_data=None

    def do_host_lookup(self):
        if not self.require_api(): return
        ip=self.host_ip_var.get().strip()
        if not ip: messagebox.showwarning("Host","Vul een IP in"); return
        self.set_status(f"Host ophalen: {ip} …")
        self.host_summary_text.delete("1.0",END); self.host_summary_text.insert(END,f"Bezig met ophalen van {ip} …\n")
        for i in self.host_banner_tree.get_children(): self.host_banner_tree.delete(i)
        self.host_raw_text.delete("1.0",END); self.host_vuln_text.delete("1.0",END); self.host_banner_detail.delete("1.0",END)
        def task(): return self.api.host(ip, history=self.host_history_var.get(), minify=self.host_minify_var.get())
        def success(d):
            self.last_host_data=d
            self.display_host_data(d)
            self.set_status(f"Host {ip} — {len(d.get('data',[]))} services, {len(d.get('ports',[]))} poorten")
        def error(e):
            self.host_summary_text.delete("1.0",END)
            self.host_summary_text.insert(END,f"Fout bij ophalen {ip}:\n{e}\n\nMogelijk:\n• IP niet in Shodan\n• Rate limit\n• Ongeldige key")
            messagebox.showerror("Host fout", str(e))
        self.run_async(task, success, error)

    def display_host_data(self,d):
        self.host_summary_text.delete("1.0",END)
        self.host_summary_text.insert(END, "🌐 HOST OVERZICHT\n", "title")
        self.host_summary_text.tag_configure("title", font=("Segoe UI", 11, "bold"), foreground=self.COLORS["primary"])
        self.host_summary_text.insert(END, f"IP: {d.get('ip_str')}  ({d.get('ip')})\nHostnames: {', '.join(d.get('hostnames',[])) or '—'}\nDomeinen: {', '.join(d.get('domains',[])) or '—'}\nOrganisatie: {d.get('org','—')}\nISP: {d.get('isp','—')}\nASN: {d.get('asn','—')}\nOS: {d.get('os') or '—'}\nLand: {d.get('country_name','')} ({d.get('country_code','')}) • Stad: {d.get('city') or '—'}\nCoords: {d.get('latitude')}, {d.get('longitude')}\nLaatste update: {d.get('last_update')}\nPoorten ({len(d.get('ports',[]))}): {', '.join(map(str,d.get('ports',[])))}\n")
        tags=d.get("tags",[])
        if tags: self.host_summary_text.insert(END, f"Tags: {', '.join(tags)}\n")
        vulns=set()
        for b in d.get("data",[]):
            if "vulns" in b: vulns.update(b["vulns"].keys() if isinstance(b["vulns"],dict) else b["vulns"])
        if vulns:
            self.host_summary_text.insert(END, f"\n⚠️ KWETSBAARHEDEN: {len(vulns)}\n","warn")
            self.host_summary_text.tag_configure("warn", foreground=self.COLORS["warn"], font=("Segoe UI", 9, "bold"))
            for v in sorted(vulns)[:20]: self.host_summary_text.insert(END, f"  • {v}\n")
        else: self.host_summary_text.insert(END, "\n✅ Geen CVE's in banners\n")
        for i in self.host_banner_tree.get_children(): self.host_banner_tree.delete(i)
        for b in d.get("data",[]):
            port=b.get("port"); trans=b.get("transport","")
            prod=b.get("product","") or b.get("_shodan",{}).get("module","")
            ver=b.get("version","")
            title=b.get("http",{}).get("title","")[:44] if b.get("http") else b.get("data","").split("\n")[0][:48]
            self.host_banner_tree.insert("",END, values=(port,trans,prod,ver,title))
        self.host_raw_text.delete("1.0",END); self.host_raw_text.insert(END, pretty_json(d))
        self.host_vuln_text.delete("1.0",END)
        if vulns:
            self.host_vuln_text.insert(END, "Gevonden kwetsbaarheden:\n\n")
            for b in d.get("data",[]):
                if b.get("vulns"):
                    self.host_vuln_text.insert(END, f"— Poort {b.get('port')} —\n")
                    vd=b["vulns"]
                    if isinstance(vd,dict):
                        for cve,info in vd.items():
                            self.host_vuln_text.insert(END, f"{cve} (CVSS:{info.get('cvss','?')}) — {info.get('summary','')[:180]}\n")
                    else:
                        for cve in vd: self.host_vuln_text.insert(END, f"{cve}\n")
        else:
            self.host_vuln_text.insert(END,"Geen kwetsbaarheden gedetecteerd.\n\nTip: vink 'Historie' aan voor oudere banners.")
    def on_host_banner_select(self,event):
        sel=self.host_banner_tree.selection()
        if not sel or not self.last_host_data: return
        idx=self.host_banner_tree.index(sel[0])
        b=self.last_host_data.get("data",[])[idx]
        self.host_banner_detail.delete("1.0",END)
        self.host_banner_detail.insert(END, f"=== POORT {b.get('port')}/{b.get('transport')} — {b.get('product','')} {b.get('version','')} ===\n\nTimestamp: {b.get('timestamp')}\nHostnames: {', '.join(b.get('hostnames',[]))}\nOS: {b.get('os')} • ISP: {b.get('isp')}\n")
        if b.get("vulns"): self.host_banner_detail.insert(END, f"\n⚠️ Vulns: {list(b['vulns'].keys()) if isinstance(b['vulns'],dict) else b['vulns']}\n")
        self.host_banner_detail.insert(END, f"\n— DATA —\n{b.get('data','')[:3000]}\n")
        if b.get("http"): self.host_banner_detail.insert(END, f"\n— HTTP —\n{pretty_json(b['http'])}\n")
        if b.get("ssl"): self.host_banner_detail.insert(END, f"\n— SSL —\n{pretty_json(b['ssl'])}\n")
    def copy_host_json(self):
        if not self.last_host_data: messagebox.showinfo("Kopie","Geen data"); return
        self.clipboard_clear(); self.clipboard_append(pretty_json(self.last_host_data)); self.set_status("Host JSON gekopieerd")
    def export_host_json(self):
        if not self.last_host_data: return
        p=filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")], initialfile=f"shodan_host_{self.host_ip_var.get().strip()}.json")
        if p:
            with open(p,'w',encoding='utf-8') as f: json.dump(self.last_host_data,f,indent=2,ensure_ascii=False)
            messagebox.showinfo("Export",f"Opgeslagen: {p}")
    def open_host_maps(self):
        if not self.last_host_data: return
        lat=self.last_host_data.get("latitude"); lon=self.last_host_data.get("longitude")
        if lat and lon: webbrowser.open(f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=10/{lat}/{lon}")
        else: messagebox.showinfo("Maps","Geen coördinaten")
    def do_honeyscore(self):
        if not self.require_api(): return
        ip=self.host_ip_var.get().strip()
        def task(): return self.api.honeyscore(ip)
        def ok(d):
            score=d if isinstance(d,(int,float)) else d.get("honeyscore",d.get("score",d))
            messagebox.showinfo("Honeyscore",f"IP: {ip}\nScore: {score}\n\n0.0 = geen honeypot, 1.0 = zeker honeypot")
            self.host_banner_detail.delete("1.0",END); self.host_banner_detail.insert(END,f"Honeyscore voor {ip}: {score}\n\nRaw: {pretty_json(d)}")
        self.run_async(task, ok, lambda e: messagebox.showerror("Honeyscore fout", str(e)))
    def do_internetdb(self):
        ip=self.host_ip_var.get().strip()
        def task(): return self.api.internetdb(ip)
        def ok(d):
            self.host_banner_detail.delete("1.0",END); self.host_banner_detail.insert(END, f"InternetDB voor {ip}:\n\n{pretty_json(d)}")
            if isinstance(d,dict): messagebox.showinfo("InternetDB",f"IP: {ip}\nPoorten: {d.get('ports',[])}\nTags: {d.get('tags',[])}\nVulns: {d.get('vulns',[])}")
        self.run_async(task, ok, lambda e: messagebox.showerror("InternetDB fout", str(e)))

    # -----------------------------------------------------------------------
    # DNS TAB
    # -----------------------------------------------------------------------
    def _build_dns_tab(self):
        nb=ttk.Notebook(self.tab_dns); nb.pack(fill=BOTH, expand=True, padx=12, pady=10)
        f1=Frame(nb, bg="white"); nb.add(f1, text="  🔎 Resolve  ")
        Label(f1, text="Hostnames (komma gescheiden):", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=14, pady=(10,4))
        self.dns_resolve_var=StringVar(value="google.com, facebook.com, shodan.io")
        Entry(f1, textvariable=self.dns_resolve_var, font=("Consolas", 10), width=70).pack(padx=14, fill=X, ipady=4)
        ttk.Button(f1, text="🔍 Resolve", command=self.do_dns_resolve).pack(padx=14, pady=6, anchor=W)
        self.dns_resolve_text=Text(f1, wrap=WORD, font=("Consolas", 9), bg="#fafafa", padx=10, pady=10, height=12); self.dns_resolve_text.pack(fill=BOTH, expand=True, padx=14, pady=6)
        f2=Frame(nb, bg="white"); nb.add(f2, text="  🔁 Reverse  ")
        Label(f2, text="IP adressen (komma gescheiden):", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=14, pady=(10,4))
        self.dns_reverse_var=StringVar(value="8.8.8.8, 1.1.1.1")
        Entry(f2, textvariable=self.dns_reverse_var, font=("Consolas", 10), width=70).pack(padx=14, fill=X, ipady=4)
        ttk.Button(f2, text="🔁 Reverse Lookup", command=self.do_dns_reverse).pack(padx=14, pady=6, anchor=W)
        self.dns_reverse_text=Text(f2, wrap=WORD, font=("Consolas", 9), bg="#fafafa", padx=10, pady=10, height=12); self.dns_reverse_text.pack(fill=BOTH, expand=True, padx=14, pady=6)
        f3=Frame(nb, bg="white"); nb.add(f3, text="  🌍 Domain Info  ")
        Label(f3, text="Domein (bv. shodan.io):", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=14, pady=(10,4))
        self.dns_domain_var=StringVar(value="shodan.io")
        Entry(f3, textvariable=self.dns_domain_var, font=("Consolas", 10), width=36).pack(padx=14, anchor=W, ipady=4)
        ttk.Button(f3, text="🌐 Haal Domein Info", command=self.do_dns_domain).pack(padx=14, pady=6, anchor=W)
        Label(f3, text="Kost 1 query credit", bg="white", fg=self.COLORS["muted"], font=("Segoe UI", 8, "italic")).pack(anchor=W, padx=14)
        self.dns_domain_text=Text(f3, wrap=WORD, font=("Consolas", 9), bg="#fafafa", padx=10, pady=10, height=12); self.dns_domain_text.pack(fill=BOTH, expand=True, padx=14, pady=6)
        f4=Frame(nb, bg="white"); nb.add(f4, text="  🧰 Mijn IP & Headers  ")
        btns=Frame(f4, bg="white"); btns.pack(fill=X, padx=14, pady=8)
        ttk.Button(btns, text="📍 Mijn IP", command=self.do_myip).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="📨 HTTP Headers", command=self.do_httpheaders).pack(side=LEFT, padx=4)
        self.dns_tools_text=Text(f4, wrap=WORD, font=("Consolas", 9), bg="#fafafa", padx=10, pady=10, height=14); self.dns_tools_text.pack(fill=BOTH, expand=True, padx=14, pady=6)
    def do_dns_resolve(self):
        if not self.require_api(): return
        h=self.dns_resolve_var.get().strip()
        self.dns_resolve_text.delete("1.0",END); self.dns_resolve_text.insert(END,f"Resolving: {h} …\n")
        self.run_async(lambda: self.api.dns_resolve(h), lambda d: (self.dns_resolve_text.delete("1.0",END), self.dns_resolve_text.insert(END, pretty_json(d))), lambda e: messagebox.showerror("DNS fout", str(e)))
    def do_dns_reverse(self):
        if not self.require_api(): return
        ips=self.dns_reverse_var.get().strip()
        self.dns_reverse_text.delete("1.0",END); self.dns_reverse_text.insert(END,f"Reverse: {ips} …\n")
        self.run_async(lambda: self.api.dns_reverse(ips), lambda d: (self.dns_reverse_text.delete("1.0",END), self.dns_reverse_text.insert(END, pretty_json(d))), lambda e: messagebox.showerror("DNS fout", str(e)))
    def do_dns_domain(self):
        if not self.require_api(): return
        dom=self.dns_domain_var.get().strip()
        self.dns_domain_text.delete("1.0",END); self.dns_domain_text.insert(END,f"Domein {dom} … (1 credit)\n")
        def ok(d):
            self.dns_domain_text.delete("1.0",END)
            self.dns_domain_text.insert(END, f"Domein: {d.get('domain')}\nTags: {', '.join(d.get('tags',[]))}\nSubdomeinen ({len(d.get('subdomains',[]))}): {', '.join(d.get('subdomains',[])[:20])}\n\n"+pretty_json(d))
        self.run_async(lambda: self.api.dns_domain(dom), ok, lambda e: messagebox.showerror("DNS fout", str(e)))
    def do_myip(self):
        if not self.require_api(): return
        self.run_async(lambda: self.api.tools_myip(), lambda d: (self.dns_tools_text.delete("1.0",END), self.dns_tools_text.insert(END, f"Mijn IP:\n{pretty_json(d)}\n")), lambda e: messagebox.showerror("Fout", str(e)))
    def do_httpheaders(self):
        if not self.require_api(): return
        self.run_async(lambda: self.api.tools_httpheaders(), lambda d: self.dns_tools_text.insert(END, f"\nHTTP Headers:\n{pretty_json(d)}\n"), lambda e: messagebox.showerror("Fout", str(e)))

    # -----------------------------------------------------------------------
    # DIRECTORY
    # -----------------------------------------------------------------------
    def _build_directory_tab(self):
        nb=ttk.Notebook(self.tab_directory); nb.pack(fill=BOTH, expand=True, padx=12, pady=10)
        q_frame=Frame(nb, bg="white"); nb.add(q_frame, text="  🔖 Queries  ")
        top_q=Frame(q_frame, bg="white"); top_q.pack(fill=X, padx=10, pady=6)
        Label(top_q, text="Doorzoek Shodan query directory:", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W)
        row=Frame(q_frame, bg="white"); row.pack(fill=X, padx=10, pady=4)
        self.query_search_var=StringVar(); Entry(row, textvariable=self.query_search_var, width=36, font=("Segoe UI", 9)).pack(side=LEFT, padx=4)
        ttk.Button(row, text="🔍 Zoeken", command=self.do_query_search).pack(side=LEFT, padx=4)
        ttk.Button(row, text="📋 Populaire", command=self.do_query_list).pack(side=LEFT, padx=4)
        self.query_text=Text(q_frame, wrap=WORD, font=("Consolas", 9), bg="#fafafa", padx=10, pady=10); self.query_text.pack(fill=BOTH, expand=True, padx=10, pady=6)
        ttk.Button(q_frame, text="➡️ Gebruik in Zoeken-tab", command=self.use_query_in_search).pack(pady=4)
        f_frame=Frame(nb, bg="white"); nb.add(f_frame, text="  🏷️ Facetten/Filters  ")
        btns=Frame(f_frame, bg="white"); btns.pack(fill=X, padx=10, pady=6)
        ttk.Button(btns, text="🔄 Facetten", command=lambda:self.load_facets_filters(False,"facets")).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="🔄 Filters", command=lambda:self.load_facets_filters(False,"filters")).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="🔄 Beide", command=self.load_facets_filters).pack(side=LEFT, padx=4)
        paned=PanedWindow(f_frame, orient=HORIZONTAL, bg="white"); paned.pack(fill=BOTH, expand=True, padx=10, pady=6)
        left=Frame(paned, bg="white"); Label(left, text="Facetten (GET /shodan/host/search/facets)", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self.facets_list_text=Text(left, wrap=WORD, font=("Consolas", 9), bg="#fffbe6", height=16); self.facets_list_text.pack(fill=BOTH, expand=True, pady=4); paned.add(left)
        right=Frame(paned, bg="white"); Label(right, text="Filters (GET /shodan/host/search/filters)", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self.filters_list_text=Text(right, wrap=WORD, font=("Consolas", 9), bg="#eef6ee", height=16); self.filters_list_text.pack(fill=BOTH, expand=True, pady=4); paned.add(right)
        a_frame=Frame(nb, bg="white"); nb.add(a_frame, text="  📊 Poorten/Protocollen  ")
        Label(a_frame, text="Wat crawlt Shodan:", bg="white", font=("Segoe UI", 10, "bold"), fg=self.COLORS["primary"]).pack(anchor=W, padx=14, pady=(10,4))
        btns2=Frame(a_frame, bg="white"); btns2.pack(fill=X, padx=14, pady=4)
        ttk.Button(btns2, text="🔌 Poorten", command=self.do_ports).pack(side=LEFT, padx=4)
        ttk.Button(btns2, text="📡 Protocollen", command=self.do_protocols).pack(side=LEFT, padx=4)
        ttk.Button(btns2, text="📦 Datasets", command=self.do_datasets).pack(side=LEFT, padx=4)
        self.ports_text=Text(a_frame, wrap=WORD, font=("Consolas", 9), bg="#fafafa", padx=10, pady=10); self.ports_text.pack(fill=BOTH, expand=True, padx=14, pady=6)
        t_frame=Frame(nb, bg="white"); nb.add(t_frame, text="  🧩 Tokens  ")
        Label(t_frame, text="Breek query op in tokens:", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=14, pady=(10,4))
        rowt=Frame(t_frame, bg="white"); rowt.pack(fill=X, padx=14, pady=4)
        self.tokens_var=StringVar(value="apache country:NL city:Amsterdam")
        Entry(rowt, textvariable=self.tokens_var, width=50, font=("Consolas", 10)).pack(side=LEFT, padx=4, ipady=4)
        ttk.Button(rowt, text="🧩 Analyseer", command=self.do_analyse_tokens).pack(side=LEFT, padx=8)
        self.tokens_text=Text(t_frame, wrap=WORD, font=("Consolas", 9), bg="#fafafa", padx=10, pady=10); self.tokens_text.pack(fill=BOTH, expand=True, padx=14, pady=6)
    def do_query_search(self):
        if not self.require_api(): return
        q=self.query_search_var.get().strip()
        if not q: messagebox.showinfo("Query","Vul zoekterm in"); return
        self.query_text.delete("1.0",END); self.query_text.insert(END,f"Zoeken naar: {q} …\n")
        def ok(d):
            self.query_text.delete("1.0",END)
            self.query_text.insert(END, f"Gevonden: {len(d.get('matches',[]))} queries\n\n")
            for m in d.get("matches",[]): self.query_text.insert(END, f"🔖 {m.get('title')}\n   Query: {m.get('query')}\n   Tags: {', '.join(m.get('tags',[]))} • Votes:{m.get('votes')}\n   —\n")
            self.query_text.insert(END, f"\nRaw:\n{pretty_json(d)}")
        self.run_async(lambda:self.api.query_search(q), ok, lambda e: messagebox.showerror("Fout", str(e)))
    def do_query_list(self):
        if not self.require_api(): return
        self.run_async(lambda:self.api.query_list(), lambda d: (self.query_text.delete("1.0",END), self.query_text.insert(END, "\n".join([f"{m.get('title')} — {m.get('query')} (votes:{m.get('votes')})" for m in d.get("matches",[])[:20]])+"\n\n"+pretty_json(d))), lambda e: messagebox.showerror("Fout", str(e)))
    def do_query_tags(self):
        if not self.require_api(): return
        self.run_async(lambda:self.api.query_tags(size=30), lambda d: (self.query_text.delete("1.0",END), self.query_text.insert(END, "\n".join([f"#{t.get('value')} ({t.get('count')})" for t in d.get("matches",[])]))), lambda e: messagebox.showerror("Fout", str(e)))
    def use_query_in_search(self):
        import re
        m=re.search(r"Query:\s*(.+)", self.query_text.get("1.0",END))
        if m:
            q=m.group(1).strip(); self.search_query_var.set(q); self.notebook.select(self.tab_search); self.set_status(f"Query overgenomen: {q}")
        else: messagebox.showinfo("Gebruik","Kopieer handmatig een query en plak in Zoeken.")
    def load_facets_filters(self, silent=True, target="both"):
        if not self.require_api():
            if not silent: messagebox.showerror("API","Geen API key"); return
        if target in ("both","facets"):
            self.run_async(lambda:self.api.host_search_facets(), lambda d: (self.facets_list_text.delete("1.0",END), self.facets_list_text.insert(END, pretty_json(d))), lambda e: self.facets_list_text.insert(END, f"Fout: {e}\n"))
        if target in ("both","filters"):
            self.run_async(lambda:self.api.host_search_filters(), lambda d: (self.filters_list_text.delete("1.0",END), self.filters_list_text.insert(END, pretty_json(d))), lambda e: self.filters_list_text.insert(END, f"Fout: {e}\n"))
    def do_ports(self):
        if not self.require_api(): return
        self.run_async(lambda:self.api.ports(), lambda d: (self.ports_text.delete("1.0",END), self.ports_text.insert(END, f"{len(d)} poorten:\n{', '.join(map(str, sorted(d)[:100]))}\n\n{pretty_json(d)}")), lambda e: messagebox.showerror("Fout", str(e)))
    def do_protocols(self):
        if not self.require_api(): return
        self.run_async(lambda:self.api.protocols(), lambda d: (self.ports_text.delete("1.0",END), self.ports_text.insert(END, pretty_json(d))), lambda e: messagebox.showerror("Fout", str(e)))
    def do_datasets(self):
        if not self.require_api(): return
        self.run_async(lambda:self.api.data_list(), lambda d: (self.ports_text.delete("1.0",END), self.ports_text.insert(END, pretty_json(d))), lambda e: messagebox.showerror("Fout", str(e)))
    def do_analyse_tokens(self):
        if not self.require_api(): return
        q=self.tokens_var.get().strip()
        self.run_async(lambda:self.api.host_search_tokens(q), lambda d: (self.tokens_text.delete("1.0",END), self.tokens_text.insert(END, pretty_json(d))), lambda e: messagebox.showerror("Fout", str(e)))

    # -----------------------------------------------------------------------
    # SCANS
    # -----------------------------------------------------------------------
    def _build_scans_tab(self):
        nb=ttk.Notebook(self.tab_scans); nb.pack(fill=BOTH, expand=True, padx=12, pady=10)
        s_frame=Frame(nb, bg="white"); nb.add(s_frame, text="  📡 Scans  ")
        Label(s_frame, text="Vraag Shodan om IP/netblock te scannen (kost scan credits):", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=14, pady=(10,4))
        row=Frame(s_frame, bg="white"); row.pack(fill=X, padx=14, pady=4)
        Label(row, text="IP / Netblock:", bg="white").pack(side=LEFT)
        self.scan_ips_var=StringVar(value="8.8.8.8"); Entry(row, textvariable=self.scan_ips_var, width=26, font=("Consolas", 10)).pack(side=LEFT, padx=8)
        ttk.Button(row, text="🚀 Scan aanvragen", command=self.do_scan).pack(side=LEFT, padx=8)
        ttk.Button(row, text="🌐 Crawl Poort/Proto", command=self.do_scan_internet).pack(side=LEFT, padx=4)
        row2=Frame(s_frame, bg="white"); row2.pack(fill=X, padx=14, pady=4)
        Label(row2, text="Internet scan — Poort:", bg="white").pack(side=LEFT)
        self.scan_port_var=StringVar(value="443"); Entry(row2, textvariable=self.scan_port_var, width=8).pack(side=LEFT, padx=4)
        Label(row2, text="Protocol:", bg="white").pack(side=LEFT, padx=8)
        self.scan_proto_var=StringVar(value="https"); Entry(row2, textvariable=self.scan_proto_var, width=12).pack(side=LEFT, padx=4)
        btns=Frame(s_frame, bg="white"); btns.pack(fill=X, padx=14, pady=6)
        ttk.Button(btns, text="🔄 Lijst verversen", command=self.do_scans_list).pack(side=LEFT)
        self.scans_text=Text(s_frame, wrap=WORD, font=("Consolas", 9), bg="#fafafa", padx=10, pady=10); self.scans_text.pack(fill=BOTH, expand=True, padx=14, pady=6)
        a_frame=Frame(nb, bg="white"); nb.add(a_frame, text="  🚨 Alerts  ")
        Label(a_frame, text="Monitor een netwerk:", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=14, pady=(10,4))
        row_a=Frame(a_frame, bg="white"); row_a.pack(fill=X, padx=14, pady=4)
        Label(row_a, text="Naam:", bg="white").pack(side=LEFT)
        self.alert_name_var=StringVar(value="Mijn Netwerk"); Entry(row_a, textvariable=self.alert_name_var, width=18).pack(side=LEFT, padx=6)
        Label(row_a, text="IPs (komma):", bg="white").pack(side=LEFT, padx=6)
        self.alert_ips_var=StringVar(value="8.8.8.8, 1.1.1.1"); Entry(row_a, textvariable=self.alert_ips_var, width=26).pack(side=LEFT, padx=6)
        ttk.Button(row_a, text="＋ Alert aanmaken", command=self.do_alert_create).pack(side=LEFT, padx=8)
        btns_a=Frame(a_frame, bg="white"); btns_a.pack(fill=X, padx=14, pady=4)
        ttk.Button(btns_a, text="🔄 Alerts verversen", command=self.do_alert_list).pack(side=LEFT, padx=4)
        ttk.Button(btns_a, text="🗑️ Verwijder", command=self.do_alert_delete).pack(side=LEFT, padx=4)
        ttk.Button(btns_a, text="⚙️ Triggers", command=self.do_alert_triggers).pack(side=LEFT, padx=4)
        self.alerts_text=Text(a_frame, wrap=WORD, font=("Consolas", 9), bg="#fafafa", padx=10, pady=10, height=10); self.alerts_text.pack(fill=BOTH, expand=True, padx=14, pady=2)
        Label(a_frame, text="Triggers & Notifiers:", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=14, pady=(4,2))
        self.alert_triggers_text=Text(a_frame, wrap=WORD, font=("Consolas", 9), bg="#fffbe6", padx=10, pady=10, height=7); self.alert_triggers_text.pack(fill=BOTH, expand=True, padx=14, pady=(0,6))
        n_frame=Frame(nb, bg="white"); nb.add(n_frame, text="  🔔 Notifiers  ")
        Label(n_frame, text="Notificatie kanalen (Slack, Email, Webhook):", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=14, pady=(10,4))
        btns_n=Frame(n_frame, bg="white"); btns_n.pack(fill=X, padx=14, pady=4)
        ttk.Button(btns_n, text="🔄 Notifiers", command=self.do_notifier_list).pack(side=LEFT, padx=4)
        ttk.Button(btns_n, text="📋 Providers", command=self.do_notifier_providers).pack(side=LEFT, padx=4)
        self.notifiers_text=Text(n_frame, wrap=WORD, font=("Consolas", 9), bg="#fafafa", padx=10, pady=10); self.notifiers_text.pack(fill=BOTH, expand=True, padx=14, pady=6)
    def do_scan(self):
        if not self.require_api(): return
        ips=self.scan_ips_var.get().strip()
        self.run_async(lambda:self.api.scan(ips), lambda d: (self.scans_text.delete("1.0",END), self.scans_text.insert(END, f"Scan {ips}:\n\n{pretty_json(d)}\n"), self.set_status("Scan aangevraagd")), lambda e: messagebox.showerror("Scan fout", str(e)))
    def do_scan_internet(self):
        if not self.require_api(): return
        port=self.scan_port_var.get().strip(); proto=self.scan_proto_var.get().strip()
        self.run_async(lambda:self.api.scan_internet(port,proto), lambda d: (self.scans_text.delete("1.0",END), self.scans_text.insert(END, pretty_json(d))), lambda e: messagebox.showerror("Scan fout", str(e)))
    def do_scans_list(self):
        if not self.require_api(): return
        self.run_async(lambda:self.api.scans_list(), lambda d: (self.scans_text.delete("1.0",END), self.scans_text.insert(END, pretty_json(d))), lambda e: messagebox.showerror("Fout", str(e)))
    def do_alert_list(self):
        if not self.require_api(): return
        def ok(d):
            self.alerts_text.delete("1.0",END); self.alerts_text.insert(END, pretty_json(d))
            if isinstance(d,list) and d: self.alerts_text.insert(END, "\n\n— SAMENVATTING —\n"+ "\n".join([f"• {a.get('name')} — ID:{a.get('id')} — IPs:{a.get('filters',{}).get('ip',[])}" for a in d]))
        self.run_async(lambda:self.api.alert_list(), ok, lambda e: messagebox.showerror("Fout", str(e)))
    def do_alert_create(self):
        if not self.require_api(): return
        name=self.alert_name_var.get().strip(); ips=self.alert_ips_var.get().strip()
        if not name or not ips: messagebox.showwarning("Alert","Vul naam en IP(s) in"); return
        self.run_async(lambda:self.api.alert_create(name,ips), lambda d: (self.alerts_text.delete("1.0",END), self.alerts_text.insert(END, pretty_json(d)), self.do_alert_list()), lambda e: messagebox.showerror("Fout", str(e)))
    def do_alert_delete(self):
        if not self.require_api(): return
        aid=simple_prompt(self,"Alert verwijderen","Voer Alert ID in:")
        if not aid: return
        self.run_async(lambda:self.api.alert_delete(aid.strip()), lambda d: (self.alerts_text.delete("1.0",END), self.alerts_text.insert(END, pretty_json(d)), self.do_alert_list()), lambda e: messagebox.showerror("Fout", str(e)))
    def do_alert_triggers(self):
        if not self.require_api(): return
        self.run_async(lambda:self.api.alert_triggers(), lambda d: (self.alert_triggers_text.delete("1.0",END), self.alert_triggers_text.insert(END, pretty_json(d))), lambda e: messagebox.showerror("Fout", str(e)))
    def do_notifier_list(self):
        if not self.require_api(): return
        self.run_async(lambda:self.api.notifier_list(), lambda d: (self.notifiers_text.delete("1.0",END), self.notifiers_text.insert(END, pretty_json(d))), lambda e: messagebox.showerror("Fout", str(e)))
    def do_notifier_providers(self):
        if not self.require_api(): return
        self.run_async(lambda:self.api.notifier_providers(), lambda d: (self.notifiers_text.delete("1.0",END), self.notifiers_text.insert(END, pretty_json(d))), lambda e: messagebox.showerror("Fout", str(e)))

    # -----------------------------------------------------------------------
    # TOOLS
    # -----------------------------------------------------------------------
    def _build_tools_tab(self):
        nb=ttk.Notebook(self.tab_tools); nb.pack(fill=BOTH, expand=True, padx=12, pady=10)
        g_frame=Frame(nb, bg="white"); nb.add(g_frame, text="  🧰 Algemeen  ")
        Label(g_frame, text="Snelle hulpmiddelen:", bg="white", font=("Segoe UI", 10, "bold"), fg=self.COLORS["primary"]).pack(anchor=W, padx=14, pady=(10,6))
        grid=Frame(g_frame, bg="white"); grid.pack(fill=X, padx=14, pady=6)
        tools=[("📍 Mijn IP",self.do_myip_tools),("📨 HTTP Headers",self.do_httpheaders_tools),("🔌 Poorten",self.do_ports),("📡 Protocollen",self.do_protocols),("🔎 Filters",lambda:self.load_facets_filters(False,"filters")),("🏷️ Facetten",lambda:self.load_facets_filters(False,"facets")),("📦 Datasets",self.do_datasets),("🌐 Filters site",lambda:webbrowser.open("https://www.shodan.io/search/filters"))]
        for i,(label,cmd) in enumerate(tools):
            ttk.Button(grid, text=label, width=20, command=cmd).grid(row=i//4, column=i%4, padx=6, pady=6, sticky=W)
        self.tools_general_text=Text(g_frame, wrap=WORD, font=("Consolas", 9), bg="#fafafa", padx=10, pady=10); self.tools_general_text.pack(fill=BOTH, expand=True, padx=14, pady=6)
        h_frame=Frame(nb, bg="white"); nb.add(h_frame, text="  🕘 Geschiedenis & Favorieten  ")
        Label(h_frame, text="Lokaal opgeslagen in register:", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=14, pady=(10,4))
        paned=PanedWindow(h_frame, orient=HORIZONTAL, bg="white"); paned.pack(fill=BOTH, expand=True, padx=10, pady=6)
        hf=Frame(paned, bg="white"); Label(hf, text="🕘 Geschiedenis", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=4)
        self.history_listbox=Listbox(hf, font=("Consolas", 9), bg="#fafafa", height=12); self.history_listbox.pack(fill=BOTH, expand=True, padx=4, pady=4)
        btns_h=Frame(hf, bg="white"); btns_h.pack(fill=X, padx=4, pady=4)
        ttk.Button(btns_h, text="➡️ Gebruik", command=lambda:self.use_from_listbox(self.history_listbox)).pack(side=LEFT, padx=2)
        ttk.Button(btns_h, text="🗑️ Wissen", command=self.clear_history).pack(side=LEFT, padx=2)
        ttk.Button(btns_h, text="🔄 Verversen", command=self.refresh_history).pack(side=LEFT, padx=2)
        paned.add(hf)
        ff=Frame(paned, bg="white"); Label(ff, text="⭐ Favorieten", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=4)
        self.fav_listbox=Listbox(ff, font=("Consolas", 9), bg="#fffbe6", height=12); self.fav_listbox.pack(fill=BOTH, expand=True, padx=4, pady=4)
        btns_f=Frame(ff, bg="white"); btns_f.pack(fill=X, padx=4, pady=4)
        ttk.Button(btns_f, text="➡️ Gebruik", command=lambda:self.use_from_listbox(self.fav_listbox)).pack(side=LEFT, padx=2)
        ttk.Button(btns_f, text="🗑️ Verwijderen", command=self.delete_favorite).pack(side=LEFT, padx=2)
        paned.add(ff)
        self.refresh_history()
    def do_myip_tools(self):
        if not self.require_api(): return
        self.run_async(lambda:self.api.tools_myip(), lambda d: (self.tools_general_text.delete("1.0",END), self.tools_general_text.insert(END, pretty_json(d))), lambda e: messagebox.showerror("Fout", str(e)))
    def do_httpheaders_tools(self):
        if not self.require_api(): return
        self.run_async(lambda:self.api.tools_httpheaders(), lambda d: (self.tools_general_text.delete("1.0",END), self.tools_general_text.insert(END, pretty_json(d))), lambda e: messagebox.showerror("Fout", str(e)))
    def refresh_history(self):
        self.history_listbox.delete(0,END)
        for h in self.app_config.get("search_history",[]): self.history_listbox.insert(END,h)
        self.fav_listbox.delete(0,END)
        for f in self.app_config.get("favorites",[]): self.fav_listbox.insert(END,f)
    def use_from_listbox(self, lb):
        sel=lb.curselection()
        if not sel: return
        val=lb.get(sel[0]); self.search_query_var.set(val); self.notebook.select(self.tab_search); self.set_status(f"Query geladen: {val}")
    def clear_history(self):
        if messagebox.askyesno("Wissen","Geschiedenis wissen?"):
            self.app_config.set("search_history",[]); self.refresh_history()
    def delete_favorite(self):
        sel=self.fav_listbox.curselection()
        if not sel: return
        val=self.fav_listbox.get(sel[0]); favs=self.app_config.get("favorites",[])
        if val in favs: favs.remove(val); self.app_config.set("favorites",favs); self.refresh_history()
    def clear_cache(self):
        try: self.search_facets_text.delete("1.0",END)
        except: pass
        try: self.host_raw_text.delete("1.0",END)
        except: pass
        self.set_status("Cache (weergave) gewist")
        LOGGER.log("INFO","Cache gewist")

    # -----------------------------------------------------------------------
    # ACCOUNT TAB (nu ook via Instellingen bereikbaar, met credits uitleg)
    # -----------------------------------------------------------------------
    def _build_account_tab(self):
        container=Frame(self.tab_account, bg=self.COLORS["bg"])
        container.pack(fill=BOTH, expand=True, padx=12, pady=10)
        # API Key kaart - nu ook via Instellingen, maar hier nog zichtbaar voor backwards compat
        key_card=Frame(container, bg=self.COLORS["bg_card"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        key_card.pack(fill=X, pady=(0,10))
        hdr=Frame(key_card, bg=self.COLORS["bg_card"]); hdr.pack(fill=X, padx=14, pady=(10,4))
        Label(hdr, text="🔑 API Key — ook te beheren via Instellingen → API Key", bg=self.COLORS["bg_card"], fg=self.COLORS["primary"], font=("Segoe UI", 10, "bold")).pack(side=LEFT)
        ttk.Button(hdr, text="⚙️ Open Instellingen", command=self.open_settings_window).pack(side=RIGHT)
        Label(key_card, text="Opgeslagen in HKEY_CURRENT_USER\\Software\\ShodanGUI  (+ backup %APPDATA%\\ShodanGUI\\config.json)", bg=self.COLORS["bg_card"], fg=self.COLORS["muted"], font=("Segoe UI", 8)).pack(anchor=W, padx=14)
        row=Frame(key_card, bg=self.COLORS["bg_card"]); row.pack(fill=X, padx=14, pady=8)
        Label(row, text="API Key:", bg=self.COLORS["bg_card"], font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        self.account_api_var=StringVar(value=self.app_config.get("api_key",""))
        self.account_api_entry=Entry(row, textvariable=self.account_api_var, width=44, font=("Consolas", 10), show="•", bg="#fafafa", relief=SOLID, bd=1)
        self.account_api_entry.pack(side=LEFT, padx=8, ipady=4)
        self.show_key_var=BooleanVar()
        Checkbutton(row, text="Toon", variable=self.show_key_var, bg=self.COLORS["bg_card"], command=self.toggle_key_visibility).pack(side=LEFT, padx=4)
        ttk.Button(row, text="💾 Opslaan", command=self.save_api_key).pack(side=LEFT, padx=6)
        ttk.Button(row, text="🔍 Valideren", command=self.validate_api_key).pack(side=LEFT, padx=4)
        ttk.Button(row, text="🗑️ Wissen", command=self.delete_api_key).pack(side=LEFT, padx=4)
        # Paned profile + credits
        paned=PanedWindow(container, orient=HORIZONTAL, bg=self.COLORS["bg"], sashwidth=6)
        paned.pack(fill=BOTH, expand=True)
        left=Frame(paned, bg=self.COLORS["bg_card"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        Label(left, text="👤 Account Profiel (GET /account/profile)", bg=self.COLORS["bg_card"], font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=12, pady=(8,4))
        self.account_profile_text=Text(left, wrap=WORD, font=("Consolas", 9), bg="#fafafa", padx=10, pady=10, height=16); self.account_profile_text.pack(fill=BOTH, expand=True, padx=12, pady=4)
        btns_left=Frame(left, bg=self.COLORS["bg_card"]); btns_left.pack(fill=X, padx=12, pady=4)
        ttk.Button(btns_left, text="🔄 Vernieuwen", command=self.refresh_account_info).pack(side=LEFT, padx=4)
        ttk.Button(btns_left, text="📋 Kopieer", command=lambda:self.copy_text(self.account_profile_text)).pack(side=LEFT, padx=4)
        paned.add(left)
        right=Frame(paned, bg=self.COLORS["bg_card"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        Label(right, text="📊 Credits & Plan (GET /api-info)", bg=self.COLORS["bg_card"], font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=12, pady=(8,4))
        self.account_apiinfo_text=Text(right, wrap=WORD, font=("Consolas", 9), bg="#eef6ee", padx=10, pady=10, height=16); self.account_apiinfo_text.pack(fill=BOTH, expand=True, padx=12, pady=4)
        btns_right=Frame(right, bg=self.COLORS["bg_card"]); btns_right.pack(fill=X, padx=12, pady=4)
        ttk.Button(btns_right, text="🔄 Vernieuwen", command=self.refresh_account_info).pack(side=LEFT, padx=4)
        ttk.Button(btns_right, text="🏢 Org", command=self.refresh_org).pack(side=LEFT, padx=4)
        ttk.Button(btns_right, text="❓ Uitleg credits", command=self.show_credits_help).pack(side=LEFT, padx=4)
        paned.add(left); paned.add(right)
        # Uitleg onder
        info=Frame(container, bg=self.COLORS["bg_card"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        info.pack(fill=X, pady=(10,0))
        Label(info, text="ℹ️ Credits uitleg (automatisch berekend)", bg=self.COLORS["bg_card"], fg=self.COLORS["primary"], font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=12, pady=(6,2))
        self.credits_explain_label=Label(info, text="Laden…", bg=self.COLORS["bg_card"], fg=self.COLORS["text"], font=("Segoe UI", 8), justify=LEFT, wraplength=1100)
        self.credits_explain_label.pack(anchor=W, padx=12, pady=(0,6))
        link_row=Frame(info, bg=self.COLORS["bg_card"]); link_row.pack(fill=X, padx=12, pady=(0,8))
        for txt,url in [("Developer Docs","https://developer.shodan.io/api"),("Shodan Account","https://account.shodan.io"),("Billing","https://account.shodan.io/billing")]:
            b=Button(link_row, text=txt, font=("Segoe UI", 8, "underline"), fg=self.COLORS["primary"], bg=self.COLORS["bg_card"], bd=0, cursor="hand2", command=lambda u=url: webbrowser.open(u))
            b.pack(side=LEFT, padx=8)

    def toggle_key_visibility(self):
        self.account_api_entry.config(show="" if self.show_key_var.get() else "•")
    def save_api_key(self):
        k=self.account_api_var.get().strip()
        if not k: messagebox.showwarning("API Key","Vul een key in"); return
        self.app_config.set("api_key",k); self.api=ShodanAPI(k, LOGGER); self._update_api_status(); self.set_status("API key opgeslagen"); messagebox.showinfo("Opgeslagen","API key opgeslagen in Register.\nHKEY_CURRENT_USER\\Software\\ShodanGUI"); self.refresh_account_info()
    def delete_api_key(self):
        if messagebox.askyesno("Wissen","API key verwijderen?"):
            self.app_config.delete("api_key"); self.account_api_var.set(""); self.api=None; self._update_api_status(); self.set_status("API key verwijderd")
    def validate_api_key(self):
        k=self.account_api_var.get().strip() or self.app_config.get("api_key","")
        if not k: messagebox.showwarning("Validatie","Geen key"); return
        tmp=ShodanAPI(k, LOGGER)
        self.set_status("Valideren bij Shodan…")
        def task(): return tmp.get_api_info()
        def ok(d):
            self.app_config.set("api_key",k); self.api=tmp; self._update_api_status()
            plan=d.get("plan","?"); qc=d.get("query_credits","?"); sc=d.get("scan_credits","?")
            messagebox.showinfo("Validatie","✅ Geldig!\n\nPlan: %s\nQuery credits: %s\nScan credits: %s\n\nOpgeslagen."%(plan,qc,sc))
            self.set_status(f"Geldig — Plan: {plan} | Credits: {qc}")
            self.refresh_account_info()
        def err(e): messagebox.showerror("Validatie mislukt", f"❌ {e}\n\nControleer https://account.shodan.io"); self.set_status(f"Validatie mislukt: {e}")
        self.run_async(task, ok, err)
    def _update_api_status(self):
        k=self.app_config.get("api_key","")
        if k and self.api:
            self.api_status_dot.config(fg=self.COLORS["success"])
            masked=k[:4]+"•"*(len(k)-8)+k[-4:] if len(k)>8 else "••••"
            self.api_status_label.config(text=f"API: {masked}", fg=self.COLORS["success"])
        else:
            self.api_status_dot.config(fg=self.COLORS["warn"])
            self.api_status_label.config(text="Geen API key", fg=self.COLORS["muted"])
    def refresh_account_info(self):
        if not self.require_api():
            self.account_profile_text.delete("1.0",END); self.account_profile_text.insert(END,"Geen API key — stel in via Instellingen → API Key.\n\nhttps://account.shodan.io")
            self.account_apiinfo_text.delete("1.0",END); self.account_apiinfo_text.insert(END,"Geen data.")
            self.credits_explain_label.config(text="Geen credits info zonder API key.")
            return
        self.account_profile_text.delete("1.0",END); self.account_profile_text.insert(END,"Laden…\n")
        self.account_apiinfo_text.delete("1.0",END); self.account_apiinfo_text.insert(END,"Laden…\n")
        def tp(): return self.api.get_account_profile()
        def okp(d):
            self.account_profile_text.delete("1.0",END)
            self.account_profile_text.insert(END, f"Gebruiker: {d.get('username','—')} • Email: {d.get('email','—')}\nLid sinds: {d.get('created','—')}\nPlan: {d.get('member','—')}\nCredits: {d.get('credits','—')}\n\n— VOLLEDIGE JSON —\n{pretty_json(d)}")
        def ti(): return self.api.get_api_info()
        def oki(d):
            self.account_apiinfo_text.delete("1.0",END)
            self.account_apiinfo_text.insert(END, f"Plan: {d.get('plan','—')} • HTTPS: {d.get('https')}\nQuery credits: {d.get('query_credits','—')} • Scan credits: {d.get('scan_credits','—')}\nUnlocked: {d.get('unlocked','—')} • Telnet: {d.get('telnet','—')}\nMonitored IPs: {d.get('monitored_ips','—')}\n\n— VOLLEDIGE JSON —\n{pretty_json(d)}")
            self.credits_label.config(text=f"Credits: {d.get('query_credits','?')} queries • {d.get('scan_credits','?')} scans • {d.get('plan','?')}")
            # Reset label + uitleg
            try:
                today=datetime.date.today()
                nxt=datetime.date(today.year+1,1,1) if today.month==12 else datetime.date(today.year,today.month+1,1)
                dagen=(nxt-today).days
                self.reset_label.config(text=f"Reset: {nxt.strftime('%d %b')} (over {dagen}d)")
            except:
                self.reset_label.config(text="")
            self.credits_explain_label.config(text=credits_uitleg(d))
        self.run_async(tp, okp, lambda e: self.account_profile_text.insert(END, f"\nFout: {e}"))
        self.run_async(ti, oki, lambda e: self.account_apiinfo_text.insert(END, f"\nFout: {e}"))
    def refresh_org(self):
        if not self.require_api(): return
        self.run_async(lambda:self.api.get_org_info(), lambda d: (self.account_apiinfo_text.delete("1.0",END), self.account_apiinfo_text.insert(END, f"ORG INFO:\n\n{pretty_json(d)}")), lambda e: messagebox.showerror("Org fout", str(e)))
    def refresh_credits_silent(self):
        if not self.api: return
        self.run_async(lambda:self.api.get_api_info(), lambda d: (self.credits_label.config(text=f"Credits: {d.get('query_credits','?')} • {d.get('scan_credits','?')} • {d.get('plan','?')}"), self.reset_label.config(text=f"Reset: {(datetime.date.today().replace(day=1)+datetime.timedelta(days=32)).replace(day=1).strftime('%d %b')}")), lambda e: None)
    def show_credits_help(self):
        # Toon uitgebreide uitleg
        info=self.account_apiinfo_text.get("1.0",END)[:500]
        # Probeer api_info opnieuw te tonen
        if self.api:
            try:
                # al in label, nu popup
                messagebox.showinfo("Credits — hoelang geldig?", 
                    "🔹 Query credits: 1 credit per 100 resultaten (1 pagina) bij /search.\n"
                    "   /count is altijd gratis.\n"
                    "🔹 Scan credits: 1 credit per IP bij on-demand scan.\n"
                    "🔹 Geldigheid: maandelijks, reset op 1e van elke maand 00:00 UTC.\n"
                    "   Je krijgt dan opnieuw je bundel (afhankelijk van plan).\n"
                    "🔹 Gratis plan: ±100 queries/maand, 1 scan credit.\n"
                    "   Zie https://account.shodan.io/billing voor upgrade.\n\n"
                    + credits_uitleg({"plan":"?","query_credits":"?","scan_credits":"?"})
                )
            except: pass
        else:
            messagebox.showinfo("Credits", credits_uitleg(None))
    def copy_text(self, w):
        txt=w.get("1.0",END); self.clipboard_clear(); self.clipboard_append(txt); self.set_status("Gekopieerd")

    # -----------------------------------------------------------------------
    # LOGGING TAB - Developer Modus
    # -----------------------------------------------------------------------
    def _build_logging_tab(self):
        container=Frame(self.tab_logging, bg=self.COLORS["bg"])
        container.pack(fill=BOTH, expand=True, padx=12, pady=10)
        top=Frame(container, bg=self.COLORS["bg_card"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        top.pack(fill=X, pady=(0,8))
        Label(top, text="🛠️ Developer Logboek & Troubleshooting", bg=self.COLORS["bg_card"], fg=self.COLORS["primary"], font=("Segoe UI", 10, "bold")).pack(anchor=W, padx=14, pady=(8,2))
        Label(top, text="Hier zie je of commands werken, welke API calls gedaan worden, fouten, timings en request URLs. Activeer via Instellingen → Developer modus.", bg=self.COLORS["bg_card"], fg=self.COLORS["muted"], font=("Segoe UI", 8)).pack(anchor=W, padx=14, pady=(0,8))
        btns=Frame(top, bg=self.COLORS["bg_card"]); btns.pack(fill=X, padx=14, pady=6)
        ttk.Button(btns, text="🗑️ Wissen", command=lambda: LOGGER.clear()).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="📋 Kopieer alles", command=lambda: self.copy_text(self.log_text)).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="📤 Exporteren…", command=self.export_logs).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="🧪 Test API (ping /api-info)", command=self.test_api_logging).pack(side=LEFT, padx=8)
        ttk.Button(btns, text="🐞 Simuleer fout", command=lambda: LOGGER.log("ERROR","Simulatie fout","Dit is een test-error om troubleshooting te demonstreren")).pack(side=LEFT, padx=4)
        # Text
        self.log_text=Text(container, wrap=WORD, font=("Consolas", 8), bg="#1e1e1e", fg="#d4d4d4", insertbackground="white", padx=10, pady=10, state=DISABLED)
        self.log_text.pack(fill=BOTH, expand=True)
        # Attach logger
        LOGGER.attach(self.log_text)
        LOGGER.log("INFO","Logging gestart","Developer modus: %s" % ("AAN" if self.developer_mode else "UIT"))
        LOGGER.log("INFO","App versie 1.2.0 Windows 2026", "Alle 37 endpoints geladen")
        if not self.api:
            LOGGER.log("WARN","Geen API key geconfigureerd","Ga naar Instellingen → API Key beheren")

    def toggle_developer_mode(self):
        self.developer_mode=self.dev_var.get()
        self.app_config.set("developer_mode", self.developer_mode)
        if self.developer_mode:
            try:
                # Voeg tab toe als niet aanwezig
                if str(self.tab_logging) not in [str(self.notebook.tabs()[i]) for i in range(len(self.notebook.tabs()))]:
                    # check via index
                    tabs=self.notebook.tabs()
                    # eenvoudig: probeer toe te voegen
                    self.notebook.add(self.tab_logging, text="  🛠️ Logging  ")
            except:
                try: self.notebook.add(self.tab_logging, text="  🛠️ Logging  ")
                except: pass
            LOGGER.log("INFO","Developer modus AAN","Logging tab zichtbaar, alle API calls worden gelogd")
            self.set_status("Developer modus aan — logging actief")
            self.notebook.select(self.tab_logging)
        else:
            try: self.notebook.forget(self.tab_logging)
            except: pass
            LOGGER.log("INFO","Developer modus UIT","Logging tab verborgen")
            self.set_status("Developer modus uit")
        # Log toggle
        LOGGER.log("INFO", f"Developer modus {'AAN' if self.developer_mode else 'UIT'}", f"Config opgeslagen: {self.app_config.get('developer_mode')}")

    def open_logging_tab(self):
        if not self.developer_mode:
            if messagebox.askyesno("Developer modus","Logging is alleen zichtbaar in Developer modus. Nu aanzetten?"):
                self.dev_var.set(True); self.toggle_developer_mode()
            else: return
        try: self.notebook.select(self.tab_logging)
        except: pass

    def export_logs(self):
        path=filedialog.asksaveasfilename(defaultextension=".log", filetypes=[("Log","*.log"),("Tekst","*.txt")], initialfile=f"shodan_logs_{datetime.date.today()}.log")
        if path:
            try:
                LOGGER.export(path)
                messagebox.showinfo("Export", f"Logs geëxporteerd naar {path}")
            except Exception as e:
                messagebox.showerror("Export fout", str(e))

    def test_api_logging(self):
        if not self.require_api(): return
        LOGGER.log("INFO","Test API call gestart","GET /api-info")
        def ok(d): LOGGER.log("OK","Test geslaagd", f"Plan {d.get('plan')} — credits {d.get('query_credits')}")
        def err(e): LOGGER.log("ERROR","Test gefaald", str(e))
        self.run_async(lambda:self.api.get_api_info(), ok, err)

    def log_tab_change(self):
        try:
            idx=self.notebook.index(self.notebook.select())
            tab_text=self.notebook.tab(idx, "text")
            LOGGER.log("INFO", f"Tab gewisseld naar: {tab_text.strip()}")
        except: pass

    # -----------------------------------------------------------------------
    # INSTELLINGEN WINDOW
    # -----------------------------------------------------------------------
    def open_settings_window(self):
        win=Toplevel(self)
        win.title("⚙️ Instellingen — Shodan GUI 2026")
        win.geometry("720x560")
        win.transient(self); win.grab_set()
        win.configure(bg=self.COLORS["bg"])
        # Center
        win.update_idletasks()
        x=self.winfo_x() + (self.winfo_width() - 720)//2
        y=self.winfo_y() + (self.winfo_height() - 560)//2
        win.geometry(f"+{x}+{y}")
        # Header
        header=Frame(win, bg=self.COLORS["bg_top"], height=56)
        header.pack(fill=X)
        Frame(win, bg=self.COLORS["border"], height=1).pack(fill=X)
        Label(header, text="⚙️  Instellingen", bg=self.COLORS["bg_top"], fg=self.COLORS["text"], font=("Segoe UI", 14, "bold")).pack(side=LEFT, padx=18, pady=12)
        Label(header, text="Beheer API key, account en developer opties", bg=self.COLORS["bg_top"], fg=self.COLORS["muted"], font=("Segoe UI", 8)).pack(side=LEFT, padx=8)
        nb=ttk.Notebook(win); nb.pack(fill=BOTH, expand=True, padx=12, pady=12)
        # Tab 1: Algemeen
        tab1=Frame(nb, bg="white"); nb.add(tab1, text="  Algemeen  ")
        Label(tab1, text="Algemene voorkeuren", bg="white", fg=self.COLORS["primary"], font=("Segoe UI", 10, "bold")).pack(anchor=W, padx=14, pady=(12,6))
        Label(tab1, text="Opslag: Windows Register (HKCU\\Software\\ShodanGUI) + backup %APPDATA%\\ShodanGUI\\config.json\nVenster positie en geschiedenis worden automatisch bewaard.", bg="white", fg=self.COLORS["muted"], font=("Segoe UI", 8), justify=LEFT).pack(anchor=W, padx=14, pady=4)
        # Checkboxes
        Checkbutton(tab1, text="Developer modus inschakelen (toont Logging tab & API details)", variable=self.dev_var, bg="white", font=("Segoe UI", 9), command=lambda: (self.toggle_developer_mode(), win.lift())).pack(anchor=W, padx=14, pady=6)
        Label(tab1, text="Thema: Licht (Windows 2026) — Donker komt later", bg="white", fg=self.COLORS["muted"], font=("Segoe UI", 8, "italic")).pack(anchor=W, padx=14)
        ttk.Button(tab1, text="🗑️ Wis zoekgeschiedenis", command=self.clear_history).pack(anchor=W, padx=14, pady=8)
        ttk.Button(tab1, text="📂 Open config map", command=lambda: os.startfile(str(Path(self.app_config._fallback_path).parent)) if os.name=='nt' else webbrowser.open(str(Path(self.app_config._fallback_path).parent))).pack(anchor=W, padx=14, pady=4)
        # Tab 2: API Key
        tab2=Frame(nb, bg="white"); nb.add(tab2, text="  🔑 API Key  ")
        Label(tab2, text="API Key beheren", bg="white", fg=self.COLORS["primary"], font=("Segoe UI", 10, "bold")).pack(anchor=W, padx=14, pady=(12,6))
        Label(tab2, text="Je key vind je op https://account.shodan.io → 'Show API Key'. Deze wordt versleuteld opgeslagen in je register.", bg="white", fg=self.COLORS["muted"], font=("Segoe UI", 8), wraplength=640, justify=LEFT).pack(anchor=W, padx=14)
        row=Frame(tab2, bg="white"); row.pack(fill=X, padx=14, pady=12)
        Label(row, text="API Key:", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W)
        var2=StringVar(value=self.app_config.get("api_key",""))
        ent2=Entry(row, textvariable=var2, width=52, font=("Consolas", 10), show="•", bg="#fafafa", relief=SOLID, bd=1)
        ent2.pack(fill=X, pady=6, ipady=6)
        show2=BooleanVar()
        def toggle2(): ent2.config(show="" if show2.get() else "•")
        Checkbutton(row, text="Toon key", variable=show2, bg="white", command=toggle2).pack(anchor=W)
        btnrow=Frame(tab2, bg="white"); btnrow.pack(fill=X, padx=14, pady=8)
        def save2():
            k=var2.get().strip()
            if not k: messagebox.showwarning("Let op","Vul een key in", parent=win); return
            self.app_config.set("api_key",k); self.account_api_var.set(k); self.api=ShodanAPI(k, LOGGER); self._update_api_status()
            LOGGER.log("INFO","API key opgeslagen via Instellingen", k[:4]+"…"+k[-4:])
            messagebox.showinfo("Opgeslagen","API key opgeslagen in Register!", parent=win); self.refresh_account_info()
        ttk.Button(btnrow, text="💾 Opslaan", style="Accent.TButton", command=save2).pack(side=LEFT, padx=4)
        ttk.Button(btnrow, text="🔍 Valideren", command=lambda: (var2.set(self.account_api_var.get()), self.validate_api_key())).pack(side=LEFT, padx=4)
        ttk.Button(btnrow, text="🌐 Open account.shodan.io", command=lambda: webbrowser.open("https://account.shodan.io")).pack(side=LEFT, padx=4)
        # Tab 3: Account
        tab3=Frame(nb, bg="white"); nb.add(tab3, text="  👤 Account  ")
        Label(tab3, text="Account & Credits — live van Shodan", bg="white", fg=self.COLORS["primary"], font=("Segoe UI", 10, "bold")).pack(anchor=W, padx=14, pady=(12,6))
        info_box=Text(tab3, wrap=WORD, font=("Consolas", 8), bg="#fafafa", padx=10, pady=10, height=14)
        info_box.pack(fill=BOTH, expand=True, padx=14, pady=6)
        def refresh_info_box():
            if not self.api:
                info_box.delete("1.0",END); info_box.insert(END,"Geen API key ingesteld.\n\nGa naar tab 'API Key' en vul je key in.")
                return
            info_box.delete("1.0",END); info_box.insert(END,"Laden…\n")
            def ok(d):
                info_box.delete("1.0",END)
                info_box.insert(END, credits_uitleg(d) + "\n\n— RAW /api-info —\n" + pretty_json(d))
            self.run_async(lambda:self.api.get_api_info(), ok, lambda e: info_box.insert(END, f"\nFout: {e}"))
        ttk.Button(tab3, text="🔄 Vernieuwen", command=refresh_info_box).pack(anchor=W, padx=14, pady=6)
        refresh_info_box()
        # Footer
        footer=Frame(win, bg=self.COLORS["bg"]); footer.pack(fill=X, padx=12, pady=8)
        ttk.Button(footer, text="Sluiten", command=win.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(footer, text="📋 Exporteer debug info", command=self.export_debug_info).pack(side=LEFT, padx=4)

    def open_settings_api(self):
        # Snel naar instellingen API tab
        self.open_settings_window()
        # Focus ligt al op API tab? we openen window en gebruiker ziet tab
    def open_settings_account(self):
        self.notebook.select(self.tab_account)
        # ook open settings window voor credits uitleg
        self.set_status("Account tab geopend — zie ook Instellingen voor meer opties")

    def export_debug_info(self):
        path=filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")], initialfile="shodan_debug_info.json")
        if not path: return
        info={
            "app":"Shodan GUI 1.2.0 Windows 2026",
            "config": self.app_config._cache,
            "credits": self.credits_label.cget("text"),
            "logs": LOGGER.entries[-50:],
            "timestamp": datetime.datetime.now().isoformat()
        }
        try:
            with open(path,'w',encoding='utf-8') as f: json.dump(info,f,indent=2,ensure_ascii=False)
            messagebox.showinfo("Debug","Debug info geëxporteerd naar "+path)
            LOGGER.log("INFO","Debug info geëxporteerd", path)
        except Exception as e:
            messagebox.showerror("Fout", str(e))

    def show_diagnostics(self):
        # Troubleshooting popup
        diag=f"App: Shodan GUI 1.2.0\nPython: {sys.version.split()[0]}\nPlatform: {sys.platform}\nDeveloper: {'AAN' if self.developer_mode else 'UIT'}\nAPI key: {'aanwezig' if self.app_config.get('api_key') else 'geen'}\nLogs: {len(LOGGER.entries)} entries\n\nProbeer:\n• Instellingen → Test API\n• Logging tab → bekijk laatste errors\n• Help → Developer Docs"
        messagebox.showinfo("Diagnose & Troubleshooting", diag)
        LOGGER.log("INFO","Diagnose geopend")

    # -----------------------------------------------------------------------
    # DIALOOG - API KEY (FIX: buttons leesbaar, grotere dialoog)
    # -----------------------------------------------------------------------
    def prompt_api_key(self):
        win=Toplevel(self)
        win.title("🔑 Shodan API Key instellen")
        win.geometry("580x400")  # FIX: was 560x320, nu 580x400 zodat knoppen volledig zichtbaar
        win.minsize(580,400)
        win.transient(self); win.grab_set()
        win.configure(bg="white")
        win.update_idletasks()
        # Center
        try:
            x=self.winfo_x() + (self.winfo_width() - 580)//2
            y=self.winfo_y() + (self.winfo_height() - 400)//2
            win.geometry(f"+{x}+{y}")
        except: pass
        # Top accent
        Frame(win, bg=self.COLORS["primary"], height=4).pack(fill=X)
        # Content frame met scrollbar-achtige padding
        content=Frame(win, bg="white")
        content.pack(fill=BOTH, expand=True, padx=20, pady=12)
        Label(content, text="Welkom bij Shodan GUI 2026", bg="white", fg=self.COLORS["primary"], font=("Segoe UI", 14, "bold")).pack(pady=(8,4))
        Label(content, text="Voer éénmalig je Shodan API key in. Deze wordt veilig bewaard\nin het Windows Register (HKEY_CURRENT_USER\\Software\\ShodanGUI).", bg="white", fg=self.COLORS["muted"], font=("Segoe UI", 9), justify=CENTER).pack(pady=4)
        entry_frame=Frame(content, bg="white")
        entry_frame.pack(fill=X, pady=12)
        Label(entry_frame, text="API Key:", bg="white", font=("Segoe UI", 9, "bold")).pack(anchor=W)
        var=StringVar(value=self.app_config.get("api_key",""))
        ent=Entry(entry_frame, textvariable=var, font=("Consolas", 11), show="•", bg="#fafafa", relief=SOLID, bd=1, highlightthickness=1, highlightbackground=self.COLORS["border"])
        ent.pack(fill=X, ipady=8, pady=6)
        ent.focus_set()
        show_var=BooleanVar()
        def toggle(): ent.config(show="" if show_var.get() else "•")
        Checkbutton(entry_frame, text="Toon key", variable=show_var, bg="white", command=toggle).pack(anchor=W)
        Label(content, text="Tip: vind je key op https://account.shodan.io → 'Show API Key'", bg="white", fg=self.COLORS["muted"], font=("Segoe UI", 8, "italic")).pack(pady=2)
        link=Label(content, text="Open account.shodan.io ↗", bg="white", fg=self.COLORS["primary"], font=("Segoe UI", 8, "underline"), cursor="hand2")
        link.pack()
        link.bind("<Button-1>", lambda e: webbrowser.open("https://account.shodan.io"))
        # Knoppen - FIX: nu in apart frame onderaan met voldoende padding, altijd zichtbaar
        btns=Frame(win, bg="white", highlightthickness=1, highlightbackground=self.COLORS["border"])
        btns.pack(fill=X, side=BOTTOM, padx=0, pady=0)
        inner_btns=Frame(btns, bg="white")
        inner_btns.pack(fill=X, padx=16, pady=10)
        def save():
            k=var.get().strip()
            if not k: messagebox.showwarning("Let op","Vul een API key in", parent=win); return
            self.app_config.set("api_key",k); self.account_api_var.set(k); self.api=ShodanAPI(k, LOGGER); self._update_api_status()
            LOGGER.log("INFO","API key opgeslagen via eerste dialoog", k[:4]+"…"+k[-4:])
            win.destroy()
            messagebox.showinfo("Opgeslagen","API key opgeslagen in Windows Register!\n\nJe kunt nu alle Shodan functies gebruiken.")
            self.refresh_account_info()
        def skip(): win.destroy()
        ttk.Button(inner_btns, text="💾 Opslaan & Valideren", style="Accent.TButton", command=save).pack(side=RIGHT, padx=6)
        ttk.Button(inner_btns, text="Later", command=skip).pack(side=RIGHT, padx=6)
        ttk.Button(inner_btns, text="🌐 Key ophalen", command=lambda: webbrowser.open("https://account.shodan.io")).pack(side=LEFT)
        win.bind("<Return>", lambda e: save())
        win.bind("<Escape>", lambda e: skip())

    def show_about(self):
        messagebox.showinfo("Over Shodan GUI", 
            "Shodan GUI — Windows 2026 Edition v1.2.0\n\n"
            "• Alle 37 Shodan REST API endpoints\n"
            "• Visuele query builder — geen syntax nodig (nu gefixed voor country:NL + webcam)\n"
            "• Presets: webcams, ICS/SCADA, databases…\n"
            "• Host lookup met banners, CVE’s, SSL, HTTP\n"
            "• DNS, Directory, Scans & Alerts, Logging\n"
            "• Opslag in Windows Register\n"
            "• Fluent Design, Segoe UI Variable\n\n"
            "Docs: https://developer.shodan.io/api\n"
            "© 2026 — Gratis met je Shodan API key"
        )
    def on_close(self):
        try: self.app_config.set("geometry", self.geometry())
        except: pass
        LOGGER.log("INFO","App gesloten", self.geometry())
        self.destroy()

def simple_prompt(parent, title, prompt):
    win=Toplevel(parent); win.title(title); win.geometry("400x140")
    win.transient(parent); win.grab_set(); win.configure(bg="white")
    win.update_idletasks()
    x=parent.winfo_x() + (parent.winfo_width() - 400)//2
    y=parent.winfo_y() + (parent.winfo_height() - 140)//2
    win.geometry(f"+{x}+{y}")
    Label(win, text=prompt, bg="white", font=("Segoe UI", 9)).pack(pady=(16,6), padx=14, anchor=W)
    var=StringVar(); Entry(win, textvariable=var, width=38, font=("Consolas", 10)).pack(padx=14, fill=X, ipady=4)
    result={"value":None}
    def ok(): result["value"]=var.get(); win.destroy()
    def cancel(): win.destroy()
    btns=Frame(win, bg="white"); btns.pack(pady=10)
    ttk.Button(btns, text="OK", command=ok).pack(side=LEFT, padx=6)
    ttk.Button(btns, text="Annuleren", command=cancel).pack(side=LEFT, padx=6)
    win.bind("<Return>", lambda e: ok()); win.bind("<Escape>", lambda e: cancel())
    parent.wait_window(win)
    return result["value"]

def main():
    cfg=ConfigManager()
    app=ShodanGUI(cfg)
    app.mainloop()

if __name__=="__main__": main()
