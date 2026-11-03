"""Analyze saved native browser screenshots and preserve a compact review reel."""
from pathlib import Path
import json,numpy as np
from PIL import Image,ImageDraw
import generate_idle as idle
HERE=Path(__file__).resolve().parent
p=HERE/'qa';cap=p/'native-capture'
timing=json.loads((cap/'timing.json').read_text())
files=[cap/(str(t['index']).zfill(4)+'.png') for t in timing]
rows=[]
for t,f in zip(timing,files):
    arr=np.asarray(Image.open(f).convert('RGB'));eye=arr[289:311,156:211].astype(int)
    blue=int(((eye[...,2]-eye[...,0]>10)&(eye[...,1]>90)&(eye[...,0]<140)).sum())
    rows.append({'index':t['index'],'ms':t['elapsedMs'],'face_blue_pixels':blue})
(p/'native-screen-samples.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
raw_count=len(rows)
valid=[(r,f) for r,f in zip(rows,files) if Image.open(f).size==(708,934)]
rows=[r for r,f in valid];file_map={r['index']:f for r,f in valid};files=[f for r,f in valid]
# Validate actual displayed feet, not just generated frame arrays.
base=np.asarray(Image.open(files[0]).convert('RGB')).astype(int)
foot_max=[0,0];face_changes=[0,0];last=[None,None];groups=[];active=False
for r,f in zip(rows,files):
 a=np.asarray(Image.open(f).convert('RGB')).astype(int)
 for j,(x0,x1) in enumerate(((25,344),(365,684))):
  foot_max[j]=max(foot_max[j],int(abs(a[750:845,x0:x1]-base[750:845,x0:x1]).max()))
  eye=a[289:311,x0+130:x0+188]
  if last[j] is not None and not np.array_equal(eye,last[j]):face_changes[j]+=1
  last[j]=eye
 closed=r['face_blue_pixels']<80
 if closed and not active:groups.append({'startMs':r['ms'],'endMs':r['ms'],'index':r['index']})
 elif closed:groups[-1]['endMs']=r['ms']
 active=closed
for name,r in [('closed',min(rows,key=lambda r:r['face_blue_pixels'])),('open',max(rows,key=lambda r:r['face_blue_pixels'])),('end',rows[-1])]:
 Image.open(file_map[r['index']]).save(p/('browser-native-'+name+'.png'))
assert foot_max==[0,0],foot_max
assert len(groups)>=6 and min(face_changes)>20
# Representative 10fps screen recording; raw timestamps remain in JSON.
review=[]
for ms in range(0,19000,100):
 r=min(rows,key=lambda r:abs(r['ms']-ms))
 review.append(Image.open(file_map[r['index']]).convert('RGB').resize((354,467),Image.Resampling.LANCZOS))
review[0].save(p/'native-three-loops-review.webp',save_all=True,append_images=review[1:],duration=100,loop=0,lossless=True,method=4,minimize_size=True)
# Each of the six visible closed-eye events is shown with surrounding frames.
sheet=Image.new('RGB',(7*240,6*120),'#e6ebf2');draw=ImageDraw.Draw(sheet)
full_events=[e for e in groups if e['endMs']-e['startMs']>=80]
for row,event in enumerate(full_events[:6]):
 for col,offset in enumerate((-120,-70,-20,50,100,150,220)):
  r=min(rows,key=lambda r:abs(r['ms']-(event['startMs']+offset)))
  screen=Image.open(file_map[r['index']]);face=screen.crop((150,281,214,322)).resize((210,92),Image.Resampling.NEAREST)
  x=col*240;y=row*120;sheet.paste(face,(x+12,y+23));draw.text((x+12,y+3),f'blink {row+1} / {r["ms"]/1000:.2f}s',fill='#24324a')
sheet.save(p/'native-six-blinks.png')
report={'method':'Actual browser native IMG screenshots, not canvas and not generated frames','screenSamples':raw_count,'consistentViewportSamples':len(rows),'excludedViewportReflowSamples':raw_count-len(rows),'firstSampleMs':rows[0]['ms'],'lastSampleMs':rows[-1]['ms'],'observedSpanMs':rows[-1]['ms']-rows[0]['ms'],'gif_and_webp_opened':True,'visible_closed_eye_events':groups,'complete_closed_eye_events':len(full_events),'initial_partial_blink':groups[0]['startMs']==rows[0]['ms'],'foot_max_display_pixel_change':{'webp':foot_max[0],'gif':foot_max[1]},'face_change_events':{'webp':face_changes[0],'gif':face_changes[1]},'review_reel':'10 fps half-size resampling of screen captures, not the production animation','sha256':{n:idle.sha256(HERE/n) for n in ['portrait-idle.webp','portrait-idle.gif']}}
(p/'native-playback-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
