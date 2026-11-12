#!/usr/bin/env python3
"""Refresh discovery catalogs, match explicit channel identities, decode and publish in user order."""
import ipaddress
import argparse, concurrent.futures as cf, csv, datetime as dt, hashlib, json, os, re, subprocess, sys, unicodedata
from pathlib import Path
from urllib.parse import urlparse
from build_playlist import SOURCES, parse_m3u, inspect_stream, safe, public_url
from hls_quality import session_rejection
from official import refresh as refresh_official
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'.cache'; REPORT=ROOT/'reports'
FEEDS={k:v for k,v in SOURCES.items() if k not in ('radio-browser','tundrak-radio','rakuten')}
FEEDS['free-italy']='https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_italy.m3u8'
FEEDS['free-fast']='https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_zz_vod_it.m3u8'
FEEDS['iptvsat']='https://raw.githubusercontent.com/domenicomarfe-crypto/CANALI-IPTV/main/IPTVSAT.m3u'
FEEDS['world']='https://iptv-org.github.io/iptv/index.m3u'

def now():return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def key(name):
    name=re.sub(r'\[[^]]*\]|\((?:576i|1080p|720p)\)','',name,flags=re.I)
    name=re.sub(r'\b(?:HD|SD|FHD|UHD|4K|HDR)\b','',name,flags=re.I)
    name=re.sub(r'^Pluto\s*TV\s*|\s*[–—-]\s*Pluto\s*TV$','',name,flags=re.I)
    name=unicodedata.normalize('NFKD',name).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9+]','',name)
def load_requests():return json.loads((ROOT/'config/channels.json').read_text())
def fetch(pair):
    name,url=pair; dest=CACHE/(name+'.m3u');temp=dest.with_suffix('.tmp')
    p=subprocess.run(['curl','-fLsS','--max-time','60','--max-filesize','30000000',url,'-o',str(temp)],capture_output=True,text=True)
    good=p.returncode==0 and '#EXTM3U' in temp.read_text(errors='replace')[:500]
    if good:temp.replace(dest)
    return {'source':name,'url':url,'ok':good,'checked_at':now(),'error':p.stderr[-300:] if not good else ''}
def catalog(refresh):
    CACHE.mkdir(exist_ok=True);REPORT.mkdir(exist_ok=True)
    if refresh:
        with cf.ThreadPoolExecutor(max_workers=5) as pool: states=list(pool.map(fetch,FEEDS.items()))
        (REPORT/'sources.json').write_text(json.dumps(states,indent=2))
        available={s['source'] for s in states if s['ok']}
    else:available={s for s in FEEDS if (CACHE/(s+'.m3u')).exists()}
    entries=[]
    if refresh:entries+=refresh_official(ROOT,load_requests())
    elif (CACHE/'official.json').exists():entries+=json.loads((CACHE/'official.json').read_text())
    for source in sorted(available):
        entries+=parse_m3u((CACHE/(source+'.m3u')).read_text(errors='replace'),source)
    previous=ROOT/'ARCKAD_TV.m3u'
    if previous.exists():entries+=parse_m3u(previous.read_text(),'previous-publication')
    extras=ROOT/'config/extra_streams.json'
    if extras.exists():entries+=json.loads(extras.read_text())
    # Same clear Mediaset origin, alternate manifest format; never touch DRM manifests or signatures.
    alternatives=[]
    for e in entries:
        parsed=urlparse(e['url'])
        if parsed.hostname and parsed.hostname.endswith('.cdn.mediaset.net') and parsed.path.endswith('-clr.isml/manifest.mpd') and not parsed.query:
            alternatives.append({**e,'url':e['url'].removesuffix('manifest.mpd')+'index.m3u8','derived_from':e['url']})
    return entries+alternatives

def match(rows,entries):
    index={}
    for e in entries:
        for k in {key(e['name']),key(e.get('declared',''))}:
            if k:index.setdefault(k,[]).append(e)
    matched=[]
    for row in rows:
        candidates=[]
        # Only explicit names/aliases; no fuzzy matches that can silently substitute channels.
        for name in [row['requested']]+row.get('aliases',[]): candidates+=index.get(key(name),[])
        ids=set(row.get('epg_ids',[]))
        if ids:candidates += [e for e in entries if re.sub(r'@(?:HD|SD|FHD|UHD|4K)$','',e.get('epg',''),flags=re.I).lower() in ids]
        if row.get('exclude'):candidates=[]
        unique={}
        for e in candidates:
            is_pluto=('pluto' in e['url'].lower() or '/plu-' in e['url'] or e['source'].startswith('pluto'))
            if 'pluto' in row['requested'].lower() and not is_pluto:continue
            if row['requested'].strip().lower()=='arte' and is_pluto:continue  # ARTE broadcaster is not Pluto TV Arte.
            if not public_url(e['url']) or session_rejection(e['url']):continue
            # Probe without custom authorization/referrer headers; only direct AVPlayer-compatible streams qualify.
            try:
                ipaddress.ip_address(urlparse(e['url']).hostname)
                continue
            except ValueError:pass
            if e['source']=='world' and not row.get('international') and '.it' not in e.get('epg','').lower():continue
            if row.get('exclude_url_patterns') and any(re.search(x,e['url'],re.I) for x in row['exclude_url_patterns']):continue
            unique.setdefault(e['url'],e)
        matched.append((row,list(unique.values())))
    return matched

def check(url,timeout):
    try:
        p=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--probe',url],capture_output=True,text=True,timeout=timeout)
        return json.loads(p.stdout) if p.returncode==0 else {'status':'failed','reason':p.stderr[-350:],'url':url,'checked_at':now()}
    except subprocess.TimeoutExpired:return {'status':'timeout','reason':'Tempo massimo di verifica superato','url':url,'checked_at':now()}
    except Exception as ex:return {'status':'failed','reason':str(ex),'url':url,'checked_at':now()}

def publish(matches,checks):
    rows=[];selected=[];seen_urls={};seen_ids={}
    for row,candidates in matches:
        good=[e for e in candidates if checks.get(e['url'],{}).get('status')=='verified' and checks[e['url']].get('has_video')]
        good.sort(key=lambda e:(checks[e['url']].get('height',0),e['url'].startswith('https'),e['source']=='fulgione'),reverse=True)
        report=dict(number=row['number'],requested=row['requested'],status='unavailable',candidates=len(candidates),note=row.get('note',''),checked_at=now())
        if good:
            e=good[0];r=checks[e['url']];identity=re.sub(r'@(?:hd|sd|fhd|uhd|4k)$','',e.get('epg','').lower())
            previous=seen_urls.get(e['url']) or (seen_ids.get(identity) if identity else None)
            if previous:
                report.update(status='duplicate',note=f'Stesso canale della posizione {previous}; non ripetuto nella playlist')
            else:
                seen_urls[e['url']]=row['number']
                if identity:seen_ids[identity]=row['number']
                report.update(status='verified',height=r.get('height',0),width=r.get('width',0),source=e['source'],url=e['url'],checked_at=r['checked_at'],matched=e['name'])
                selected.append((row,e,r))
        elif not candidates:report['note']=report['note'] or 'Nessun candidato pubblico compatibile identificato con certezza nelle sorgenti consultate'
        else:report['note']=report['note'] or 'Nessun candidato ha superato la decodifica audio/video da questa rete'
        if report['status']=='unavailable':
            failures=[{'source':e['source'],'status':checks.get(e['url'],{}).get('status','not_tested'),'reason':checks.get(e['url'],{}).get('reason','Verifica non disponibile')[-400:]} for e in candidates]
            report['failures']=failures
            report['reason']=' | '.join(dict.fromkeys(f['status']+': '+f['reason'].replace('\n',' ') for f in failures))[:1600]
            report['checked_at']=max((checks.get(e['url'],{}).get('checked_at','') for e in candidates),default='')
        rows.append(report)
    (REPORT/'channels.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    with (REPORT/'channels.csv').open('w',newline='') as f:
        fields=['number','requested','status','height','width','matched','source','candidates','checked_at','note','reason']
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    # Protect an existing publication against a runner/network outage. Always expose the attempted run in reports.
    previous=ROOT/'ARCKAD_TV.m3u';old_count=previous.read_text().count('#EXTINF:') if previous.exists() else 0
    old_numbers={int(n) for n in re.findall(r'tvg-chno="(\d+)"',previous.read_text())} if previous.exists() else set()
    new_numbers={row['number'] for row,_,_ in selected}
    missing_core=sorted((old_numbers & set(range(1,11)))-new_numbers)
    publish_ok=bool(selected) and not missing_core and (not old_count or len(selected)>=old_count*0.8)
    status={'checked_at':now(),'requested':len(rows),'verified':len(selected),'hd_or_better':sum(r.get('height',0)>=720 for _,_,r in selected),'unavailable':sum(r['status']=='unavailable' for r in rows),'duplicates':sum(r['status']=='duplicate' for r in rows),'published':publish_ok,'previous_channels':old_count,'missing_core_channels':missing_core,'test':'Campione audio/video FFmpeg; non garantisce disponibilità futura o su altre reti'}
    (ROOT/'stato.json').write_text(json.dumps(status,ensure_ascii=False,indent=2))
    if not publish_ok:print(json.dumps(status),flush=True);return False
    lines=['#EXTM3U x-tvg-url="https://iptv-epg.org/files/epg-it.xml"','# ARCKAD — ordine richiesto dall’utente — '+now()]
    for row,e,r in selected:
        label=re.sub(r'\s*\[SENZA URL\]|^\[\d+\]\s*','',row['requested'])
        label=re.sub(r'\b(?:HD|UHD|4K|HDR)\b','',label).strip()
        label=re.sub(r'\s+',' ',label)
        if key(row['requested'])==key('Rai 4K'):label='Rai 4K'
        elif r.get('height',0)>=2160:label+=' UHD'
        elif r.get('height',0)>=720:label+=' HD'
        group='ARCKAD • Ordine personale'
        lines += [f'#EXTINF:-1 tvg-id="{safe(e.get("epg",""))}" tvg-chno="{row["number"]}" tvg-name="{safe(label)}" tvg-logo="{safe(e.get("logo",""))}" group-title="{group}",{safe(label)}',e['url']]
    temp=previous.with_suffix('.tmp');temp.write_text('\n'.join(lines)+'\n');os.replace(temp,previous)
    print(json.dumps(status,ensure_ascii=False),flush=True);return True

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--refresh',action='store_true');ap.add_argument('--discover-only',action='store_true');ap.add_argument('--assemble-only',action='store_true');ap.add_argument('--resume',action='store_true');ap.add_argument('--retry-failed',action='store_true');ap.add_argument('--workers',type=int,default=10);ap.add_argument('--timeout',type=int,default=150);ap.add_argument('--probe');args=ap.parse_args()
    if args.probe:
        print(json.dumps(inspect_stream(args.probe,22)));return
    matches=match(load_requests(),catalog(args.refresh))
    (REPORT/'matches.json').write_text(json.dumps([dict(**r,candidates=c) for r,c in matches],ensure_ascii=False,indent=2))
    urls={e['url'] for _,entries in matches for e in entries}
    print(f'{len(matches)} richieste; {sum(bool(c) for _,c in matches)} con candidati; {len(urls)} URL distinti',flush=True)
    if args.discover_only:return
    checks={};journal=REPORT/'checks.jsonl'
    if (args.resume or args.assemble_only) and journal.exists():
        for line in journal.read_text().splitlines():
            r=json.loads(line)
            if (dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(r['checked_at'])).total_seconds()<7200 and (r['status']!='verified' or r.get('decoded_audio_frames',0)>=10):checks[r['url']]=r
    if args.retry_failed:checks={url:r for url,r in checks.items() if r['status']=='verified' or urlparse(url).path.lower().endswith('.mpd')}
    pending=sorted(urls-checks.keys())
    if args.assemble_only and pending:raise SystemExit('Mancano verifiche recenti: non pubblicato')
    with journal.open('a' if args.resume or args.assemble_only else 'w') as log,cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks={pool.submit(check,url,args.timeout):url for url in pending}
        for i,f in enumerate(cf.as_completed(tasks),1):
            r=f.result();checks[r['url']]=r;log.write(json.dumps(r)+'\n');log.flush()
            if i%25==0 or i==len(tasks):print(f'Test {i}/{len(tasks)}; verificati {sum(r["status"]=="verified" for r in checks.values())}',flush=True)
    if not publish(matches,checks):raise SystemExit(2)
if __name__=='__main__':main()
